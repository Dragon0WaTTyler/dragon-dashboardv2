from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from zipfile import BadZipFile, ZipFile, is_zipfile

from app.books.models import AudiobookAsset, AudiobookEdition, Book, BookEdition, TextAsset
from app.books.priorities import preferred_text_format
from app.extensions import db
from app.shared.time import utc_now

SUPPORTED_TEXT_FORMATS = {
    ".kfx": "KFX",
    ".azw3": "AZW3",
    ".epub": "EPUB",
    ".pdf": "PDF",
}
SUPPORTED_AUDIO_FORMATS = {
    ".m4b": "M4B",
    ".mp3": "MP3",
    ".aac": "AAC",
}
ASSET_PREVIEW_KEY = "local_text_asset_preview"
AUDIO_ASSET_PREVIEW_KEY = "local_audio_asset_preview"


class LocalAssetError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LocalTextAssetPreview:
    local_path: str
    filename: str
    file_size: int
    file_hash: str
    format: str
    verification_status: str
    signature_status: str
    target_edition_id: str
    target_edition_title: str
    duplicate_asset_id: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def preferred_for_kindle(self) -> bool:
        return self.format == preferred_text_format([self.format])

    def as_dict(self) -> dict:
        return {
            "local_path": self.local_path,
            "filename": self.filename,
            "file_size": self.file_size,
            "file_size_label": _file_size_label(self.file_size),
            "file_hash": self.file_hash,
            "format": self.format,
            "verification_status": self.verification_status,
            "signature_status": self.signature_status,
            "target_edition_id": self.target_edition_id,
            "target_edition_title": self.target_edition_title,
            "duplicate_asset_id": self.duplicate_asset_id,
            "warnings": self.warnings,
            "preferred_for_kindle": self.preferred_for_kindle,
        }


@dataclass(frozen=True, slots=True)
class LocalAudioAssetPreview:
    local_path: str
    filename: str
    file_size: int
    file_hash: str
    format: str
    signature_status: str
    target_audiobook_id: str
    target_audiobook_title: str
    duplicate_asset_id: str = ""
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "local_path": self.local_path,
            "filename": self.filename,
            "file_size": self.file_size,
            "file_size_label": _file_size_label(self.file_size),
            "file_hash": self.file_hash,
            "format": self.format,
            "signature_status": self.signature_status,
            "target_audiobook_id": self.target_audiobook_id,
            "target_audiobook_title": self.target_audiobook_title,
            "duplicate_asset_id": self.duplicate_asset_id,
            "warnings": self.warnings,
        }


class BookAssetService:
    @staticmethod
    def preview_text_asset(
        book: Book, *, local_path: str, edition_id: str = ""
    ) -> LocalTextAssetPreview:
        path = _existing_file(local_path)
        detected = _detect_text_format(path)
        file_hash = _sha256(path)
        target = _target_edition(book, edition_id=edition_id, create=False)
        duplicate = db.session.scalar(db.select(TextAsset).where(TextAsset.file_hash == file_hash))
        return LocalTextAssetPreview(
            local_path=str(path),
            filename=path.name,
            file_size=path.stat().st_size,
            file_hash=file_hash,
            format=detected["format"],
            verification_status=detected["verification_status"],
            signature_status=detected["signature_status"],
            target_edition_id=target.id if target else "",
            target_edition_title=target.title if target else f"{book.title} primary edition",
            duplicate_asset_id=duplicate.id if duplicate else "",
            warnings=detected["warnings"],
        )

    @staticmethod
    def store_text_asset_preview(book: Book, preview: LocalTextAssetPreview) -> None:
        book.metadata_state = {
            **(book.metadata_state or {}),
            ASSET_PREVIEW_KEY: preview.as_dict(),
        }
        db.session.commit()

    @staticmethod
    def clear_text_asset_preview(book: Book) -> None:
        state = dict(book.metadata_state or {})
        state.pop(ASSET_PREVIEW_KEY, None)
        book.metadata_state = state
        db.session.commit()

    @staticmethod
    def register_stored_text_asset(book: Book) -> TextAsset:
        payload = (book.metadata_state or {}).get(ASSET_PREVIEW_KEY)
        if not isinstance(payload, dict):
            raise LocalAssetError("No local asset preview is ready to register.")
        preview = BookAssetService.preview_text_asset(
            book,
            local_path=str(payload.get("local_path") or ""),
            edition_id=str(payload.get("target_edition_id") or ""),
        )
        if preview.duplicate_asset_id:
            raise LocalAssetError("This file hash is already registered.")
        edition = _target_edition(book, edition_id=preview.target_edition_id, create=True)
        if edition is None:
            raise LocalAssetError("Could not create a target edition for this asset.")
        asset = TextAsset(
            edition=edition,
            format=preview.format,
            source_type="local",
            source_reference=preview.local_path,
            local_path=preview.local_path,
            filename=preview.filename,
            file_size=preview.file_size,
            file_hash=preview.file_hash,
            availability_status="available",
            verification_status=preview.verification_status,
        )
        db.session.add(asset)
        db.session.flush()
        _refresh_preferred_for_kindle(book)
        state = dict(book.metadata_state or {})
        state.pop(ASSET_PREVIEW_KEY, None)
        state["last_local_text_asset"] = {
            **preview.as_dict(),
            "registered_asset_id": asset.id,
            "registered_at": utc_now().isoformat(),
        }
        book.metadata_state = state
        db.session.commit()
        return asset

    @staticmethod
    def preview_audio_asset(
        book: Book, *, local_path: str, audiobook_id: str = ""
    ) -> LocalAudioAssetPreview:
        path = _existing_file(local_path)
        detected = _detect_audio_format(path)
        file_hash = _sha256(path)
        target = _target_audiobook(book, audiobook_id=audiobook_id, create=False)
        duplicate = db.session.scalar(
            db.select(AudiobookAsset).where(AudiobookAsset.file_hash == file_hash)
        )
        return LocalAudioAssetPreview(
            local_path=str(path),
            filename=path.name,
            file_size=path.stat().st_size,
            file_hash=file_hash,
            format=detected["format"],
            signature_status=detected["signature_status"],
            target_audiobook_id=target.id if target else "",
            target_audiobook_title=target.title if target else f"{book.title} audiobook",
            duplicate_asset_id=duplicate.id if duplicate else "",
            warnings=detected["warnings"],
        )

    @staticmethod
    def store_audio_asset_preview(book: Book, preview: LocalAudioAssetPreview) -> None:
        book.metadata_state = {
            **(book.metadata_state or {}),
            AUDIO_ASSET_PREVIEW_KEY: preview.as_dict(),
        }
        db.session.commit()

    @staticmethod
    def clear_audio_asset_preview(book: Book) -> None:
        state = dict(book.metadata_state or {})
        state.pop(AUDIO_ASSET_PREVIEW_KEY, None)
        book.metadata_state = state
        db.session.commit()

    @staticmethod
    def register_stored_audio_asset(book: Book) -> AudiobookAsset:
        payload = (book.metadata_state or {}).get(AUDIO_ASSET_PREVIEW_KEY)
        if not isinstance(payload, dict):
            raise LocalAssetError("No audiobook asset preview is ready to register.")
        preview = BookAssetService.preview_audio_asset(
            book,
            local_path=str(payload.get("local_path") or ""),
            audiobook_id=str(payload.get("target_audiobook_id") or ""),
        )
        if preview.duplicate_asset_id:
            raise LocalAssetError("This audiobook file hash is already registered.")
        audiobook = _target_audiobook(
            book, audiobook_id=preview.target_audiobook_id, create=True
        )
        if audiobook is None:
            raise LocalAssetError("Could not create a target audiobook edition.")
        asset = AudiobookAsset(
            audiobook=audiobook,
            format=preview.format,
            source_type="local",
            source_reference=preview.local_path,
            local_path=preview.local_path,
            filename=preview.filename,
            file_size=preview.file_size,
            file_hash=preview.file_hash,
            availability_status="available",
        )
        db.session.add(asset)
        db.session.flush()
        state = dict(book.metadata_state or {})
        state.pop(AUDIO_ASSET_PREVIEW_KEY, None)
        state["last_local_audio_asset"] = {
            **preview.as_dict(),
            "registered_asset_id": asset.id,
            "registered_at": utc_now().isoformat(),
        }
        book.metadata_state = state
        db.session.commit()
        return asset


def _existing_file(value: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise LocalAssetError("Local file path is required.")
    path = Path(raw).expanduser().resolve(strict=True)
    if not path.is_file():
        raise LocalAssetError("Local file path must point to a file.")
    return path


def _detect_text_format(path: Path) -> dict:
    extension_format = SUPPORTED_TEXT_FORMATS.get(path.suffix.casefold())
    if extension_format is None:
        raise LocalAssetError("Unsupported text format. Use KFX, AZW3, EPUB, or PDF.")
    header = _header(path)
    warnings: list[str] = []
    signature_status = "extension_only"
    verification_status = "needs_review"

    if extension_format == "PDF":
        if header.startswith(b"%PDF"):
            signature_status = "verified_header"
            verification_status = "verified"
        else:
            warnings.append("PDF extension does not match a PDF header.")
    elif extension_format == "EPUB":
        if _valid_epub(path):
            signature_status = "verified_container"
            verification_status = "verified"
        else:
            warnings.append("EPUB extension does not match a valid EPUB container.")
    elif extension_format == "AZW3":
        if b"BOOKMOBI" in header[:128]:
            signature_status = "verified_header"
            verification_status = "likely"
        else:
            warnings.append("AZW3 uses extension-only detection and needs review.")
    elif extension_format == "KFX":
        if b"CONTBOUNDARY" in header[:512]:
            signature_status = "verified_header"
            verification_status = "likely"
        else:
            warnings.append("KFX uses extension-only detection and needs review.")

    return {
        "format": extension_format,
        "signature_status": signature_status,
        "verification_status": verification_status,
        "warnings": warnings,
    }


def _detect_audio_format(path: Path) -> dict:
    extension_format = SUPPORTED_AUDIO_FORMATS.get(path.suffix.casefold())
    if extension_format is None:
        raise LocalAssetError("Unsupported audiobook format. Use M4B, MP3, or AAC.")
    header = _header(path)
    warnings: list[str] = []
    signature_status = "extension_only"

    if extension_format == "MP3":
        if header.startswith(b"ID3") or header[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
            signature_status = "verified_header"
        else:
            warnings.append("MP3 extension does not match a common MP3 header.")
    elif extension_format == "M4B":
        if b"ftyp" in header[:16]:
            signature_status = "verified_container"
        else:
            warnings.append("M4B extension does not match a common MP4/M4B container.")
    elif extension_format == "AAC":
        if header[:2] in {b"\xff\xf1", b"\xff\xf9"}:
            signature_status = "verified_header"
        else:
            warnings.append("AAC uses extension-only detection and needs review.")

    return {
        "format": extension_format,
        "signature_status": signature_status,
        "warnings": warnings,
    }


def _valid_epub(path: Path) -> bool:
    if not is_zipfile(path):
        return False
    try:
        with ZipFile(path) as archive:
            try:
                mimetype = archive.read("mimetype", pwd=None)
            except KeyError:
                return False
    except (BadZipFile, OSError):
        return False
    return mimetype.strip() == b"application/epub+zip"


def _header(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read(8192)


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_size_label(size: int) -> str:
    value = max(int(size or 0), 0)
    units = ["B", "KB", "MB", "GB"]
    amount = float(value)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    if unit == "B":
        return f"{value} B"
    return f"{amount:.1f} {unit}"


def _target_edition(book: Book, *, edition_id: str = "", create: bool) -> BookEdition | None:
    if edition_id:
        for edition in book.editions:
            if edition.id == edition_id:
                return edition
        raise LocalAssetError("Selected edition does not belong to this book.")
    existing = next((edition for edition in book.editions if edition.primary), None)
    existing = existing or (book.editions[0] if book.editions else None)
    if existing or not create:
        return existing
    edition = BookEdition(
        book=book,
        title=book.title,
        language=book.edition_language,
        translator=book.translator,
        publisher=book.publisher,
        publication_year=book.published_year,
        page_count=book.page_count,
        isbn_10=book.isbn_10,
        isbn_13=book.isbn_13,
        verification_status="needs_review",
        primary=True,
    )
    db.session.add(edition)
    return edition


def _target_audiobook(
    book: Book, *, audiobook_id: str = "", create: bool
) -> AudiobookEdition | None:
    if audiobook_id:
        for audiobook in book.audiobooks:
            if audiobook.id == audiobook_id:
                return audiobook
        raise LocalAssetError("Selected audiobook does not belong to this book.")
    existing = book.audiobooks[0] if book.audiobooks else None
    if existing or not create:
        return existing
    audiobook = AudiobookEdition(
        book=book,
        title=book.title,
        language=book.edition_language,
        verification_status="needs_review",
    )
    db.session.add(audiobook)
    return audiobook


def _refresh_preferred_for_kindle(book: Book) -> None:
    assets = [
        asset
        for edition in book.editions
        for asset in edition.text_assets
        if asset.availability_status != "rejected"
    ]
    preferred = preferred_text_format([asset.format for asset in assets])
    selected = next((asset for asset in assets if asset.format.upper() == preferred), None)
    for asset in assets:
        asset.preferred_for_kindle = asset is selected
