from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from zipfile import BadZipFile, ZipFile, is_zipfile

import requests

WYZIE_DEFAULT_BASE_URL = "https://sub.wyzie.io"
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
EPISODE_TOKEN_PATTERN = re.compile(r"\bs(?P<season>\d{1,2})e(?P<episode>\d{1,3})\b", re.I)


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
    season: int | None = None
    episode: int | None = None
    episode_title: str = ""
    provider: str = "default"


def _language_codes(value: str) -> list[str]:
    requested = [part.strip().upper() for part in value.split(",")]
    usable = [code for code in requested if code in SUPPORTED_LANGUAGES]
    return list(dict.fromkeys(usable)) or ["AR", "EN"]


def _clean_label(value: Any, fallback: str) -> str:
    label = re.sub(r"\s+", " ", str(value or "")).strip()
    return (label or fallback)[:180]


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _episode_identity(*values: Any) -> tuple[int | None, int | None]:
    for value in values:
        match = EPISODE_TOKEN_PATTERN.search(str(value or ""))
        if match:
            return int(match.group("season")), int(match.group("episode"))
    return None, None


def _normalize_words(value: Any) -> list[str]:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
    return [word for word in text.split() if word]


def _title_matches_name(name: Any, episode_title: str = "") -> bool:
    words = [word for word in _normalize_words(episode_title) if len(word) > 1]
    if not words:
        return False
    haystack = set(_normalize_words(name))
    return all(word in haystack for word in words)


def _episode_matches_name(
    name: Any,
    *,
    season: int | None,
    episode: int | None,
    episode_title: str = "",
) -> bool:
    if not season or not episode:
        return _title_matches_name(name, episode_title)
    text = str(name or "")
    season_value = str(season).zfill(2)
    episode_value = str(episode).zfill(2)
    patterns = (
        rf"(^|[^a-z0-9])s0*{season}e0*{episode}([^a-z0-9]|$)",
        rf"(^|[^a-z0-9]){season_value}x{episode_value}([^a-z0-9]|$)",
        rf"(^|[^a-z0-9])0*{season}x0*{episode}([^a-z0-9]|$)",
        rf"season[ ._-]*0*{season}.*episode[ ._-]*0*{episode}",
    )
    return any(re.search(pattern, text, re.I) for pattern in patterns) or _title_matches_name(
        name,
        episode_title,
    )


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


def _safe_remote_subtitle_url(value: Any) -> str:
    parsed = urlsplit(str(value or "").strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise SubtitleProviderError("The subtitle provider returned an invalid download URL.")
    hostname = parsed.hostname.casefold()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        raise SubtitleProviderError("The subtitle provider returned an invalid download URL.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        raise SubtitleProviderError("The subtitle provider returned an invalid download URL.")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _response_message(response: requests.Response, fallback: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        return fallback
    if isinstance(payload, dict):
        for key in ("message", "error", "detail"):
            value = payload.get(key)
            if value:
                return str(value)
    return fallback


def _download_payload(
    session: requests.Session,
    url: str,
    *,
    timeout: tuple[int, int],
    provider_name: str,
    headers: dict[str, str] | None = None,
) -> bytes:
    try:
        response = session.get(
            url,
            headers=headers
            or {
                "Accept": "text/plain, text/vtt, application/octet-stream",
                "User-Agent": "DragonV2/0.11 subtitle-client",
            },
            timeout=timeout,
            stream=True,
            allow_redirects=True,
        )
        if response.status_code in {401, 402, 403, 429}:
            default_message = (
                f"{provider_name} subtitle download is temporarily unavailable. "
                "Cached subtitles will keep working."
            )
            raise SubtitleProviderError(_response_message(response, default_message))
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
        return b"".join(chunks)
    except SubtitleProviderError:
        raise
    except requests.RequestException as exc:
        raise SubtitleProviderError(
            f"{provider_name} subtitle download is unavailable."
        ) from exc


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


class WyzieSubtitleProvider:
    name = "wyzie"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = WYZIE_DEFAULT_BASE_URL,
        session: requests.Session | None = None,
        timeout: tuple[int, int] = (5, 25),
    ) -> None:
        if not api_key.strip():
            raise ValueError("A Wyzie API key is required.")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout
        self._payload_cache: dict[str, bytes] = {}

    def search(
        self,
        movie: dict[str, Any],
        *,
        languages: str = "ar,en",
        season: int | None = None,
        episode: int | None = None,
        episode_title: str = "",
    ) -> list[SubtitleCandidate]:
        language_codes = _language_codes(languages)
        external_ids = movie.get("external_ids") or {}
        imdb_id = str(external_ids.get("imdb_id") or "").strip()
        tmdb_id = str(external_ids.get("tmdb_id") or "").strip()
        media_id = imdb_id if re.fullmatch(r"tt\d{5,12}", imdb_id) else tmdb_id
        if not media_id:
            raise SubtitleProviderError("Wyzie needs a TMDB or IMDb id before searching.")

        params: dict[str, Any] = {
            "id": media_id,
            "language": ",".join(code.lower() for code in language_codes),
            "format": "srt,vtt",
            "key": self.api_key,
        }
        if movie.get("media_type") == "tv" and season and episode:
            params["season"] = int(season)
            params["episode"] = int(episode)

        try:
            response = self.session.get(
                f"{self.base_url}/search",
                params=params,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "DragonV2/0.11 subtitle-client",
                },
                timeout=self.timeout,
            )
            if response.status_code in {401, 402, 403, 429}:
                raise SubtitleProviderError(
                    _response_message(
                        response,
                        "Wyzie subtitle search is temporarily unavailable.",
                    )
                )
            response.raise_for_status()
            if len(response.content) > MAX_SEARCH_BYTES:
                raise SubtitleProviderError("Wyzie returned an oversized search response.")
            data = response.json()
        except SubtitleProviderError:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise SubtitleProviderError("Wyzie subtitle search is unavailable.") from exc

        if not isinstance(data, list):
            raise SubtitleProviderError("Wyzie returned an invalid search response.")

        candidates: list[SubtitleCandidate] = []
        seen_urls: set[str] = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            language = str(item.get("language") or "").upper()
            if language not in language_codes:
                continue
            file_format = str(item.get("format") or "").lower().lstrip(".")
            if file_format not in SUPPORTED_FORMATS:
                continue
            try:
                subtitle_url = _safe_remote_subtitle_url(item.get("url"))
            except SubtitleProviderError:
                continue
            if subtitle_url in seen_urls:
                continue

            file_name = str(item.get("fileName") or "").strip()
            release_name = str(item.get("release") or "").strip()
            matched_release = str(item.get("matchedRelease") or "").strip()
            episode_hints = [value for value in (file_name, release_name, matched_release) if value]
            if (
                movie.get("media_type") == "tv"
                and season
                and episode
                and episode_hints
                and not any(
                    _episode_matches_name(
                        value,
                        season=season,
                        episode=episode,
                        episode_title=episode_title,
                    )
                    for value in episode_hints
                )
            ):
                continue

            seen_urls.add(subtitle_url)
            label = _clean_label(
                release_name or matched_release or file_name or item.get("media"),
                "Subtitle",
            )
            candidates.append(
                SubtitleCandidate(
                    language=language.lower(),
                    language_name=_clean_label(item.get("display"), SUPPORTED_LANGUAGES[language]),
                    label=label,
                    path=subtitle_url,
                    file_format=file_format,
                    member_name=file_name,
                    hearing_impaired=bool(item.get("isHearingImpaired", False)),
                    season=season,
                    episode=episode,
                    episode_title=episode_title,
                    provider=self.name,
                )
            )

        language_rank = {code.lower(): index for index, code in enumerate(language_codes)}
        candidates.sort(
            key=lambda item: (
                language_rank.get(item.language, len(language_rank)),
                item.hearing_impaired,
                not _episode_matches_name(
                    item.member_name or item.label,
                    season=season,
                    episode=episode,
                    episode_title=episode_title,
                ),
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

    def download(
        self,
        path: str,
        *,
        file_format: str,
        member_name: str = "",
        season: int | None = None,
        episode: int | None = None,
        episode_title: str = "",
    ) -> bytes:
        del member_name, season, episode, episode_title
        safe_url = _safe_remote_subtitle_url(path)
        normalized_format = file_format.lower().lstrip(".")
        if normalized_format not in SUPPORTED_FORMATS:
            raise SubtitleProviderError("The subtitle format is not supported.")
        payload = self._payload_cache.get(safe_url)
        if payload is None:
            payload = _download_payload(
                self.session,
                safe_url,
                timeout=self.timeout,
                provider_name="Wyzie",
            )
            if len(self._payload_cache) >= 24:
                self._payload_cache.pop(next(iter(self._payload_cache)))
            self._payload_cache[safe_url] = payload
        return to_webvtt(payload, normalized_format)


class SubdlSubtitleProvider:
    name = "subdl"

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
        self._payload_cache: dict[str, bytes] = {}

    def search(
        self,
        movie: dict[str, Any],
        *,
        languages: str = "ar,en",
        season: int | None = None,
        episode: int | None = None,
        episode_title: str = "",
    ) -> list[SubtitleCandidate]:
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
        if movie.get("media_type") == "tv":
            if season:
                params["season"] = int(season)
            # Keep the provider search season-wide. SubDL's exact episode filter often
            # hides full-season packs; Dragon filters/extracts the requested episode
            # locally after the archive is downloaded.

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
                file_season = _positive_int(file_item.get("season"))
                file_episode = _positive_int(file_item.get("episode"))
                if file_season is None or file_episode is None:
                    inferred_season, inferred_episode = _episode_identity(
                        file_item.get("name"),
                        file_item.get("release_name"),
                    )
                    file_season = file_season or inferred_season
                    file_episode = file_episode or inferred_episode
                if season and file_season and file_season != season:
                    continue
                if episode and file_episode and file_episode != episode:
                    continue
                if (
                    season
                    and episode
                    and not file_season
                    and not file_episode
                    and episode_title
                    and not _episode_matches_name(
                        " ".join(
                            str(value or "")
                            for value in (
                                file_item.get("name"),
                                file_item.get("release_name"),
                            )
                        ),
                        season=season,
                        episode=episode,
                        episode_title=episode_title,
                    )
                ):
                    continue
                file_format = str(file_item.get("format") or "").lower().lstrip(".")
                if file_format not in SUPPORTED_FORMATS:
                    continue
                language = str(file_item.get("language") or subtitle.get("language") or "").upper()
                if language not in language_codes:
                    continue
                member_name = str(file_item.get("name") or "").strip()
                try:
                    file_path = _safe_subtitle_path(file_item.get("url"))
                except SubtitleProviderError:
                    file_path = archive_path
                dedupe_key = (
                    f"{file_path}:{member_name.casefold()}"
                    if file_path.endswith(".zip")
                    else file_path
                )
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
                        path=file_path,
                        file_format=file_format,
                        member_name=member_name if file_path.endswith(".zip") else "",
                        hearing_impaired=bool(file_item.get("hi", subtitle.get("hi", False))),
                        season=file_season,
                        episode=file_episode,
                        episode_title=episode_title,
                        provider=self.name,
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
                    season=season,
                    episode=episode,
                    episode_title=episode_title,
                    provider=self.name,
                )
            )

        language_rank = {code.lower(): index for index, code in enumerate(language_codes)}
        candidates.sort(
            key=lambda item: (
                language_rank.get(item.language, len(language_rank)),
                item.path.endswith(".zip"),
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

    def download(
        self,
        path: str,
        *,
        file_format: str,
        member_name: str = "",
        season: int | None = None,
        episode: int | None = None,
        episode_title: str = "",
    ) -> bytes:
        safe_path = _safe_subtitle_path(path)
        if file_format.lower() not in {*SUPPORTED_FORMATS, "auto"}:
            raise SubtitleProviderError("The subtitle format is not supported.")
        payload = self._payload_cache.get(safe_path)
        if payload is None:
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
                if getattr(response, "status_code", 200) == 429:
                    message = "SubDL daily download limit reached. Try again later; cached subtitles will keep working."
                    try:
                        payload = response.json()
                        message = str(payload.get("message") or message)
                    except (AttributeError, ValueError):
                        pass
                    raise SubtitleProviderError(message)
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
            except SubtitleProviderError:
                raise
            except requests.RequestException as exc:
                raise SubtitleProviderError("SubDL subtitle download is unavailable.") from exc
            payload = b"".join(chunks)
            if len(self._payload_cache) >= 16:
                self._payload_cache.pop(next(iter(self._payload_cache)))
            self._payload_cache[safe_path] = payload
        if not safe_path.endswith(".zip"):
            return to_webvtt(payload, file_format)
        return _archive_to_webvtt(
            payload,
            member_name=member_name,
            season=season,
            episode=episode,
            episode_title=episode_title,
        )


def _archive_to_webvtt(
    payload: bytes,
    *,
    member_name: str,
    season: int | None = None,
    episode: int | None = None,
    episode_title: str = "",
) -> bytes:
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
                matched_member = next(
                    (
                        info
                        for info in safe_infos
                        if info.filename.replace("\\", "/").casefold() == wanted
                        or PurePosixPath(info.filename).name.casefold()
                        == PurePosixPath(member_name).name.casefold()
                    ),
                    None,
                )
                if matched_member is not None:
                    if season and episode and not _episode_matches_name(
                        matched_member.filename,
                        season=season,
                        episode=episode,
                        episode_title=episode_title,
                    ):
                        chosen = None
                    else:
                        chosen = matched_member
            if chosen is None and season and episode:
                exact_infos = [
                    info
                    for info in safe_infos
                    if _episode_matches_name(
                        info.filename,
                        season=season,
                        episode=episode,
                        episode_title=episode_title,
                    )
                ]
                if not exact_infos:
                    raise SubtitleProviderError(
                        "The subtitle archive does not contain the requested episode."
                    )
                chosen = max(exact_infos, key=lambda info: info.file_size)
            chosen = chosen or max(safe_infos, key=lambda info: info.file_size)
            file_format = PurePosixPath(chosen.filename).suffix.lower().lstrip(".")
            subtitle_payload = archive.read(chosen)
    except BadZipFile as exc:
        raise SubtitleProviderError("SubDL returned an invalid subtitle archive.") from exc
    return to_webvtt(subtitle_payload, file_format)


class FallbackSubtitleProvider:
    name = "auto"

    def __init__(self, providers: list[Any]) -> None:
        self.providers = providers

    def search(
        self,
        movie: dict[str, Any],
        *,
        languages: str = "ar,en",
        season: int | None = None,
        episode: int | None = None,
        episode_title: str = "",
    ) -> list[SubtitleCandidate]:
        messages: list[str] = []
        for provider in self.providers:
            try:
                candidates = provider.search(
                    movie,
                    languages=languages,
                    season=season,
                    episode=episode,
                    episode_title=episode_title,
                )
            except SubtitleProviderError as exc:
                messages.append(str(exc))
                continue
            if candidates:
                return candidates
        if messages:
            raise SubtitleProviderError(messages[0])
        return []


def build_subtitle_providers(config: dict[str, Any]) -> list[Any]:
    providers: dict[str, Any] = {}
    if str(config.get("DRAGON_WYZIE_API_KEY") or "").strip():
        providers["wyzie"] = WyzieSubtitleProvider(
            str(config["DRAGON_WYZIE_API_KEY"]),
            base_url=str(config.get("DRAGON_WYZIE_BASE_URL") or WYZIE_DEFAULT_BASE_URL),
        )
    if str(config.get("DRAGON_SUBDL_API_KEY") or "").strip():
        providers["subdl"] = SubdlSubtitleProvider(str(config["DRAGON_SUBDL_API_KEY"]))

    preferred = str(config.get("DRAGON_SUBTITLE_PROVIDER") or "auto").strip().lower()
    order = (
        ["wyzie", "subdl"]
        if preferred in {"auto", "wyzie"}
        else ["subdl", "wyzie"]
    )
    return [providers[name] for name in order if name in providers]
