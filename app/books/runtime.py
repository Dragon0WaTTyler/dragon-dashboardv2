from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree

from app.books.models import AudiobookAsset, AudiobookEdition, Book, TextAsset
from app.extensions import db
from app.history.services import HistoryService
from app.shared.time import utc_iso

AUDIO_MIMETYPES = {
    "M4B": "audio/mp4",
    "MP3": "audio/mpeg",
    "AAC": "audio/aac",
}
TEXT_MIMETYPES = {
    "KFX": "application/octet-stream",
    "AZW3": "application/vnd.amazon.ebook",
    "EPUB": "application/epub+zip",
    "PDF": "application/pdf",
}
LISTENING_PROGRESS_KEY = "listening_progress"
TEXT_READING_PROGRESS_KEY = "text_reading_progress"


@dataclass(frozen=True, slots=True)
class EpubChapter:
    index: int
    title: str
    paragraphs: list[str]


class AudioRuntimeError(ValueError):
    pass


class TextRuntimeError(ValueError):
    pass


class BookTextRuntimeService:
    @staticmethod
    def stream_target(book: Book, *, asset_id: str) -> tuple[Path, str, TextAsset]:
        asset = _text_asset_for_book(book, asset_id)
        if asset.availability_status == "rejected":
            raise TextRuntimeError("This text asset is not available.")
        path = _registered_file(
            asset.local_path,
            missing_message="This text asset has no registered local path.",
            unavailable_message="The registered text file is unavailable.",
        )
        mimetype = TEXT_MIMETYPES.get(asset.format.upper(), "application/octet-stream")
        return path, mimetype, asset

    @staticmethod
    def epub_reader(book: Book, *, asset_id: str) -> dict:
        path, _mimetype, asset = BookTextRuntimeService.stream_target(
            book, asset_id=asset_id
        )
        if asset.format.upper() != "EPUB":
            raise TextRuntimeError("Only EPUB assets can open in the local reader.")
        chapters = _epub_chapters(path)
        if not chapters:
            raise TextRuntimeError("This EPUB has no readable spine content.")
        return {
            "book": book,
            "asset": asset,
            "filename": asset.filename or path.name,
            "chapters": chapters,
            "progress": text_reading_progress(book, asset.id),
        }

    @staticmethod
    def save_progress(
        book: Book,
        *,
        asset_id: str,
        chapter_index: int,
        scroll_percent: float = 0,
    ) -> dict:
        asset = _text_asset_for_book(book, asset_id)
        if asset.availability_status == "rejected":
            raise TextRuntimeError("This text asset is not available.")
        if asset.format.upper() != "EPUB":
            raise TextRuntimeError("Only EPUB reader progress is supported.")
        chapter = max(int(chapter_index or 0), 0)
        percent = _progress_percent(scroll_percent)
        progress = {
            "asset_id": asset.id,
            "chapter_index": chapter,
            "scroll_percent": percent,
            "updated_at": utc_iso(),
        }
        state = dict(book.metadata_state or {})
        progress_map = dict(state.get(TEXT_READING_PROGRESS_KEY) or {})
        progress_map[asset.id] = progress
        state[TEXT_READING_PROGRESS_KEY] = progress_map
        book.metadata_state = state
        HistoryService.record(
            domain="books",
            entity_type="text_asset",
            entity_id=asset.id,
            event_type="reading_progress",
            label=f"{book.title}: EPUB reader progress",
            metadata={
                "chapter_index": chapter,
                "scroll_percent": percent,
            },
        )
        db.session.commit()
        return progress


class BookAudioRuntimeService:
    @staticmethod
    def stream_target(book: Book, *, asset_id: str) -> tuple[Path, str, AudiobookAsset]:
        asset = _audio_asset_for_book(book, asset_id)
        if asset.availability_status == "rejected":
            raise AudioRuntimeError("This audiobook asset is not available.")
        path = _registered_file(
            asset.local_path,
            missing_message="This audiobook asset has no registered local path.",
            unavailable_message="The registered audiobook file is unavailable.",
        )
        mimetype = AUDIO_MIMETYPES.get(asset.format.upper(), "application/octet-stream")
        return path, mimetype, asset

    @staticmethod
    def save_progress(
        book: Book,
        *,
        audiobook_id: str,
        position_seconds: int,
        duration_seconds: int = 0,
        current_chapter: int = 0,
        playback_speed: float = 1.0,
        completed: bool = False,
    ) -> dict:
        audiobook = _audiobook_for_book(book, audiobook_id)
        position = max(int(position_seconds or 0), 0)
        duration = max(int(duration_seconds or audiobook.duration_seconds or 0), 0)
        if duration and position > duration:
            position = duration
        speed = _playback_speed(playback_speed)
        progress = {
            "audiobook_id": audiobook.id,
            "position_seconds": position,
            "duration_seconds": duration,
            "current_chapter": max(int(current_chapter or 0), 0),
            "playback_speed": speed,
            "completed": bool(completed) or bool(duration and position >= int(duration * 0.92)),
            "updated_at": utc_iso(),
        }
        state = dict(book.metadata_state or {})
        progress_map = dict(state.get(LISTENING_PROGRESS_KEY) or {})
        progress_map[audiobook.id] = progress
        state[LISTENING_PROGRESS_KEY] = progress_map
        book.metadata_state = state
        HistoryService.record(
            domain="books",
            entity_type="audiobook",
            entity_id=audiobook.id,
            event_type="listening_progress",
            label=f"{book.title}: audiobook progress",
            metadata={
                "position_seconds": position,
                "duration_seconds": duration,
                "completed": progress["completed"],
            },
        )
        db.session.commit()
        return progress


def listening_progress(book: Book, audiobook_id: str) -> dict:
    progress_map = (book.metadata_state or {}).get(LISTENING_PROGRESS_KEY)
    if not isinstance(progress_map, dict):
        return {}
    progress = progress_map.get(audiobook_id)
    return progress if isinstance(progress, dict) else {}


def text_reading_progress(book: Book, asset_id: str) -> dict:
    progress_map = (book.metadata_state or {}).get(TEXT_READING_PROGRESS_KEY)
    if not isinstance(progress_map, dict):
        return {}
    progress = progress_map.get(asset_id)
    return progress if isinstance(progress, dict) else {}


def _text_asset_for_book(book: Book, asset_id: str) -> TextAsset:
    for edition in book.editions:
        for asset in edition.text_assets:
            if asset.id == asset_id:
                return asset
    raise TextRuntimeError("Text asset was not found for this book.")


def _audio_asset_for_book(book: Book, asset_id: str) -> AudiobookAsset:
    for audiobook in book.audiobooks:
        for asset in audiobook.assets:
            if asset.id == asset_id:
                return asset
    raise AudioRuntimeError("Audiobook asset was not found for this book.")


def _audiobook_for_book(book: Book, audiobook_id: str) -> AudiobookEdition:
    for audiobook in book.audiobooks:
        if audiobook.id == audiobook_id:
            return audiobook
    raise AudioRuntimeError("Audiobook was not found for this book.")


def _registered_file(
    local_path: str, *, missing_message: str, unavailable_message: str
) -> Path:
    raw = str(local_path or "").strip()
    if not raw:
        raise FileNotFoundError(missing_message)
    path = Path(raw).expanduser().resolve(strict=True)
    if not path.is_file():
        raise FileNotFoundError(unavailable_message)
    return path


def _playback_speed(value: float) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return 1.0
    if speed < 0.5 or speed > 3:
        raise AudioRuntimeError("Playback speed must be between 0.5 and 3.")
    return round(speed, 2)


def _progress_percent(value: float) -> float:
    try:
        percent = float(value)
    except (TypeError, ValueError):
        return 0
    return round(min(max(percent, 0), 100), 2)


def _epub_chapters(path: Path) -> list[EpubChapter]:
    try:
        with ZipFile(path) as archive:
            rootfile = _epub_rootfile(archive)
            manifest, spine = _epub_manifest_and_spine(archive, rootfile)
            base = PurePosixPath(rootfile).parent
            chapters: list[EpubChapter] = []
            for item_id in spine:
                href = manifest.get(item_id)
                if not href:
                    continue
                chapter_path = _archive_join(base, href)
                try:
                    raw = archive.read(chapter_path)
                except KeyError:
                    continue
                parsed = _chapter_text(raw)
                if not parsed["paragraphs"]:
                    continue
                title = parsed["title"] or f"Chapter {len(chapters) + 1}"
                chapters.append(
                    EpubChapter(
                        index=len(chapters),
                        title=title,
                        paragraphs=parsed["paragraphs"],
                    )
                )
    except (BadZipFile, OSError, ElementTree.ParseError) as exc:
        raise TextRuntimeError("This EPUB could not be opened.") from exc
    return chapters


def _epub_rootfile(archive: ZipFile) -> str:
    try:
        container = archive.read("META-INF/container.xml")
    except KeyError as exc:
        raise TextRuntimeError("This EPUB is missing its container manifest.") from exc
    root = ElementTree.fromstring(container)
    rootfile = root.find(".//{*}rootfile")
    path = rootfile.attrib.get("full-path", "") if rootfile is not None else ""
    if not path:
        raise TextRuntimeError("This EPUB has no package document.")
    return _archive_join(PurePosixPath(""), path)


def _epub_manifest_and_spine(
    archive: ZipFile, rootfile: str
) -> tuple[dict[str, str], list[str]]:
    package = ElementTree.fromstring(archive.read(rootfile))
    manifest: dict[str, str] = {}
    for item in package.findall(".//{*}manifest/{*}item"):
        item_id = item.attrib.get("id", "")
        href = item.attrib.get("href", "")
        media_type = item.attrib.get("media-type", "")
        if item_id and href and media_type in {
            "application/xhtml+xml",
            "text/html",
        }:
            manifest[item_id] = href
    spine = [
        item.attrib.get("idref", "")
        for item in package.findall(".//{*}spine/{*}itemref")
        if item.attrib.get("idref")
    ]
    return manifest, spine


def _archive_join(base: PurePosixPath, href: str) -> str:
    raw = unquote(str(href or "").split("#", 1)[0]).strip()
    if not raw or raw.startswith("/"):
        raise TextRuntimeError("This EPUB contains an unsafe archive path.")
    candidate = base / PurePosixPath(raw)
    parts: list[str] = []
    for part in candidate.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise TextRuntimeError("This EPUB contains an unsafe archive path.")
            parts.pop()
        else:
            parts.append(part)
    if not parts:
        raise TextRuntimeError("This EPUB contains an unsafe archive path.")
    return "/".join(parts)


def _chapter_text(raw: bytes) -> dict:
    parser = _EpubTextParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    parser.close()
    return {"title": parser.title, "paragraphs": parser.paragraphs}


class _EpubTextParser(HTMLParser):
    _BLOCK_TAGS = {
        "blockquote",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self.title = ""
        self._current: list[str] = []
        self._current_tag = ""
        self._title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in {"script", "style"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
        if tag in self._BLOCK_TAGS:
            self._flush()
            self._current_tag = tag
        elif tag == "br":
            self._current.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
            if not self.title:
                self.title = _clean_text(" ".join(self._title_parts))
        if tag in self._BLOCK_TAGS:
            if tag in {"h1", "h2", "h3"} and not self.title:
                self.title = _clean_text(" ".join(self._current))
            self._flush()
            self._current_tag = ""

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = unescape(data)
        if self._in_title:
            self._title_parts.append(value)
        self._current.append(value)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        text = _clean_text(" ".join(self._current))
        self._current = []
        if text:
            self.paragraphs.append(text)


def _clean_text(value: str) -> str:
    return " ".join(str(value or "").split())
