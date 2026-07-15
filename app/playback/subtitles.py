from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile, is_zipfile

import requests

SUBDL_SEARCH_URL = "https://api.subdl.com/api/v2/subtitles/search"
SUBDL_DOWNLOAD_BASE = "https://dl.subdl.com"
MAX_SEARCH_BYTES = 1_000_000
MAX_SUBTITLE_BYTES = 5_000_000
SUPPORTED_LANGUAGES = {"AR": "Arabic", "EN": "English"}
SUPPORTED_FORMATS = {"srt", "vtt"}
RAW_SUBTITLE_PATH_PATTERN = re.compile(r"^/subtitle/[A-Za-z0-9_-]{4,80}/[A-Za-z0-9._-]{4,160}$")
ARCHIVE_PATH_PATTERN = re.compile(r"^/subtitle/[A-Za-z0-9_-]{4,160}\.zip$")
TIMING_PATTERN = re.compile(
    r"^(\d{1,2}:\d{2}:\d{2})[,.](\d{3})(\s+-->\s+)"
    r"(\d{1,2}:\d{2}:\d{2})[,.](\d{3})(.*)$"
)


class SubtitleProviderError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SubtitleCandidate:
    language: str
    language_name: str
    label: str
    path: str
    file_format: str
    member_name: str
    hearing_impaired: bool


def _language_codes(value: str) -> list[str]:
    requested = [part.strip().upper() for part in value.split(",")]
    usable = [code for code in requested if code in SUPPORTED_LANGUAGES]
    return list(dict.fromkeys(usable)) or ["AR", "EN"]


def _clean_label(value: Any, fallback: str) -> str:
    label = re.sub(r"\s+", " ", str(value or "")).strip()
    return (label or fallback)[:180]


def _safe_subtitle_path(value: Any) -> str:
    parsed = urlsplit(str(value or ""))
    if (
        parsed.scheme
        or parsed.netloc
        or not (
            RAW_SUBTITLE_PATH_PATTERN.fullmatch(parsed.path)
            or ARCHIVE_PATH_PATTERN.fullmatch(parsed.path)
        )
    ):
        raise SubtitleProviderError("SubDL returned an invalid subtitle path.")
    return parsed.path


def _decode_subtitle(payload: bytes) -> str:
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return payload.decode("utf-16")
        except UnicodeDecodeError:
            pass
    for encoding in ("utf-8-sig", "cp1256", "iso-8859-6", "cp1252"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SubtitleProviderError("The subtitle text encoding is not supported.")


def to_webvtt(payload: bytes, file_format: str) -> bytes:
    text = _decode_subtitle(payload).replace("\r\n", "\n").replace("\r", "\n").strip()
    if "-->" not in text:
        raise SubtitleProviderError("The downloaded file does not contain subtitle cues.")
    if file_format.lower() == "vtt":
        body = text if text.startswith("WEBVTT") else f"WEBVTT\n\n{text}"
        return f"{body.rstrip()}\n".encode()

    converted: list[str] = []
    for line in text.split("\n"):
        match = TIMING_PATTERN.match(line.strip())
        if match:
            line = (
                f"{match.group(1)}.{match.group(2)}{match.group(3)}"
                f"{match.group(4)}.{match.group(5)}{match.group(6)}"
            )
        converted.append(line)
    return f"WEBVTT\n\n{'\n'.join(converted).rstrip()}\n".encode()


class SubdlSubtitleProvider:
    def __init__(
        self,
        api_key: str,
        *,
        session: requests.Session | None = None,
        timeout: tuple[int, int] = (5, 25),
    ) -> None:
        if not api_key.strip():
            raise ValueError("A SubDL API key is required.")
        self.api_key = api_key.strip()
        self.session = session or requests.Session()
        self.timeout = timeout

    def search(self, movie: dict[str, Any], *, languages: str = "ar,en") -> list[SubtitleCandidate]:
        language_codes = _language_codes(languages)
        params: dict[str, Any] = {
            "languages": ",".join(code.lower() for code in language_codes),
            "unpack": 1,
            "subs_per_page": 30,
        }
        external_ids = movie.get("external_ids") or {}
        imdb_id = str(external_ids.get("imdb_id") or "").strip()
        tmdb_id = str(external_ids.get("tmdb_id") or "").strip()
        if re.fullmatch(r"tt\d{5,12}", imdb_id):
            params["imdb_id"] = imdb_id
        elif tmdb_id.isdigit():
            params.update(
                tmdb_id=tmdb_id,
                type="tv" if movie.get("media_type") == "tv" else "movie",
            )
        else:
            params["film_name"] = str(movie.get("title") or "")[:300]
            if movie.get("year"):
                params["year"] = int(movie["year"])

        try:
            response = self.session.get(
                SUBDL_SEARCH_URL,
                params=params,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                    "User-Agent": "DragonV2/0.11 subtitle-client",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            if len(response.content) > MAX_SEARCH_BYTES:
                raise SubtitleProviderError("SubDL returned an oversized search response.")
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise SubtitleProviderError("SubDL subtitle search is unavailable.") from exc

        candidates: list[SubtitleCandidate] = []
        seen_paths: set[str] = set()
        for subtitle in data.get("subtitles") or []:
            if not isinstance(subtitle, dict):
                continue
            try:
                archive_path = _safe_subtitle_path(subtitle.get("url"))
            except SubtitleProviderError:
                continue
            unpack_files = subtitle.get("unpack_files") or []
            supported_files = []
            for file_item in unpack_files:
                if not isinstance(file_item, dict):
                    continue
                file_format = str(file_item.get("format") or "").lower().lstrip(".")
                if file_format not in SUPPORTED_FORMATS:
                    continue
                language = str(file_item.get("language") or subtitle.get("language") or "").upper()
                if language not in language_codes:
                    continue
                member_name = str(file_item.get("name") or "").strip()
                dedupe_key = f"{archive_path}:{member_name.casefold()}"
                if not member_name or dedupe_key in seen_paths:
                    continue
                seen_paths.add(dedupe_key)
                label = _clean_label(
                    file_item.get("release_name") or subtitle.get("release_name"),
                    _clean_label(file_item.get("name"), "Subtitle"),
                )
                candidates.append(
                    SubtitleCandidate(
                        language=language.lower(),
                        language_name=SUPPORTED_LANGUAGES[language],
                        label=label,
                        path=archive_path,
                        file_format=file_format,
                        member_name=member_name,
                        hearing_impaired=bool(file_item.get("hi", subtitle.get("hi", False))),
                    )
                )
                supported_files.append(file_item)
            if supported_files:
                continue
            language = str(subtitle.get("language") or "").upper()
            if language not in language_codes or archive_path in seen_paths:
                continue
            seen_paths.add(archive_path)
            candidates.append(
                SubtitleCandidate(
                    language=language.lower(),
                    language_name=SUPPORTED_LANGUAGES[language],
                    label=_clean_label(subtitle.get("release_name"), "Subtitle"),
                    path=archive_path,
                    file_format="auto",
                    member_name="",
                    hearing_impaired=bool(subtitle.get("hi", False)),
                )
            )

        language_rank = {code.lower(): index for index, code in enumerate(language_codes)}
        candidates.sort(
            key=lambda item: (
                language_rank.get(item.language, len(language_rank)),
                item.hearing_impaired,
                item.label.casefold(),
            )
        )
        per_language: dict[str, int] = {}
        selected: list[SubtitleCandidate] = []
        for candidate in candidates:
            count = per_language.get(candidate.language, 0)
            if count >= 6:
                continue
            per_language[candidate.language] = count + 1
            selected.append(candidate)
        return selected

    def download(self, path: str, *, file_format: str, member_name: str = "") -> bytes:
        safe_path = _safe_subtitle_path(path)
        if file_format.lower() not in {*SUPPORTED_FORMATS, "auto"}:
            raise SubtitleProviderError("The subtitle format is not supported.")
        try:
            response = self.session.get(
                f"{SUBDL_DOWNLOAD_BASE}{safe_path}",
                headers={
                    "Accept": "text/plain, text/vtt, application/octet-stream",
                    "X-API-Key": self.api_key,
                    "User-Agent": "DragonV2/0.11 subtitle-client",
                },
                timeout=self.timeout,
                stream=True,
                allow_redirects=False,
            )
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_SUBTITLE_BYTES:
                    raise SubtitleProviderError("The subtitle file is too large.")
                chunks.append(chunk)
        except requests.RequestException as exc:
            raise SubtitleProviderError("SubDL subtitle download is unavailable.") from exc
        payload = b"".join(chunks)
        if not safe_path.endswith(".zip"):
            return to_webvtt(payload, file_format)
        return _archive_to_webvtt(payload, member_name=member_name)


def _archive_to_webvtt(payload: bytes, *, member_name: str) -> bytes:
    stream = BytesIO(payload)
    if not is_zipfile(stream):
        raise SubtitleProviderError("SubDL returned an invalid subtitle archive.")
    stream.seek(0)
    try:
        with ZipFile(stream) as archive:
            infos = archive.infolist()
            if len(infos) > 100 or sum(info.file_size for info in infos) > MAX_SUBTITLE_BYTES:
                raise SubtitleProviderError("The subtitle archive is too large.")
            safe_infos = []
            for info in infos:
                name = info.filename.replace("\\", "/")
                path = PurePosixPath(name)
                if info.is_dir() or path.is_absolute() or ".." in path.parts:
                    continue
                if info.flag_bits & 0x1 or info.file_size > MAX_SUBTITLE_BYTES:
                    continue
                if path.suffix.lower().lstrip(".") not in SUPPORTED_FORMATS:
                    continue
                safe_infos.append(info)
            if not safe_infos:
                raise SubtitleProviderError("The archive has no supported subtitle file.")
            chosen = None
            if member_name:
                wanted = member_name.replace("\\", "/").casefold()
                chosen = next(
                    (
                        info
                        for info in safe_infos
                        if info.filename.replace("\\", "/").casefold() == wanted
                        or PurePosixPath(info.filename).name.casefold()
                        == PurePosixPath(member_name).name.casefold()
                    ),
                    None,
                )
            chosen = chosen or max(safe_infos, key=lambda info: info.file_size)
            file_format = PurePosixPath(chosen.filename).suffix.lower().lstrip(".")
            subtitle_payload = archive.read(chosen)
    except BadZipFile as exc:
        raise SubtitleProviderError("SubDL returned an invalid subtitle archive.") from exc
    return to_webvtt(subtitle_payload, file_format)
