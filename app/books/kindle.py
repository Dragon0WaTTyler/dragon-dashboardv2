from __future__ import annotations

from dataclasses import dataclass

from app.books.models import Book, TextAsset
from app.books.priorities import TEXT_FORMAT_PRIORITY

KINDLE_TRANSFER_FORMATS = {"KFX", "AZW3", "EPUB", "PDF"}


@dataclass(frozen=True, slots=True)
class KindleExportAsset:
    id: str
    format: str
    filename: str
    file_size: int
    file_size_label: str
    file_hash: str
    verification_status: str
    edition_title: str
    edition_language: str
    preferred: bool

    def as_manifest_item(self) -> dict:
        return {
            "asset_id": self.id,
            "format": self.format,
            "filename": self.filename,
            "file_size": self.file_size,
            "file_size_label": self.file_size_label,
            "sha256": self.file_hash,
            "verification_status": self.verification_status,
            "edition_title": self.edition_title,
            "edition_language": self.edition_language,
            "preferred": self.preferred,
        }


class BookKindleExportService:
    @staticmethod
    def export_view(book: Book) -> dict:
        assets = _transfer_assets(book)
        preferred = assets[0] if assets else None
        return {
            "book": book,
            "preferred": preferred,
            "assets": assets,
            "manifest": BookKindleExportService.manifest(book, assets=assets),
        }

    @staticmethod
    def manifest(book: Book, assets: list[KindleExportAsset] | None = None) -> dict:
        assets = assets if assets is not None else _transfer_assets(book)
        return {
            "dragon_book_id": book.dragon_book_id,
            "book_id": book.id,
            "title": book.title,
            "authors": book.authors,
            "preferred_format": assets[0].format if assets else "",
            "format_priority": TEXT_FORMAT_PRIORITY,
            "assets": [asset.as_manifest_item() for asset in assets],
        }

    @staticmethod
    def has_transfer_assets(book: Book) -> bool:
        return bool(_transfer_assets(book))


def _transfer_assets(book: Book) -> list[KindleExportAsset]:
    assets: list[KindleExportAsset] = []
    for edition in book.editions:
        for asset in edition.text_assets:
            item = _transfer_asset(asset)
            if item is None:
                continue
            assets.append(
                KindleExportAsset(
                    **item,
                    edition_title=edition.title,
                    edition_language=edition.language,
                    preferred=False,
                )
            )
    assets.sort(key=_asset_sort_key)
    if not assets:
        return []
    preferred_id = assets[0].id
    return [
        KindleExportAsset(
            id=asset.id,
            format=asset.format,
            filename=asset.filename,
            file_size=asset.file_size,
            file_size_label=asset.file_size_label,
            file_hash=asset.file_hash,
            verification_status=asset.verification_status,
            edition_title=asset.edition_title,
            edition_language=asset.edition_language,
            preferred=asset.id == preferred_id,
        )
        for asset in assets
    ]


def _transfer_asset(asset: TextAsset) -> dict | None:
    text_format = asset.format.upper()
    if text_format not in KINDLE_TRANSFER_FORMATS:
        return None
    if asset.source_type != "local" or asset.availability_status == "rejected":
        return None
    if not str(asset.local_path or "").strip():
        return None
    return {
        "id": asset.id,
        "format": text_format,
        "filename": asset.filename or f"{asset.id}.{text_format.casefold()}",
        "file_size": int(asset.file_size or 0),
        "file_size_label": _file_size_label(asset.file_size),
        "file_hash": asset.file_hash,
        "verification_status": asset.verification_status,
    }


def _asset_sort_key(asset: KindleExportAsset) -> tuple[int, int, str]:
    try:
        priority = TEXT_FORMAT_PRIORITY.index(asset.format)
    except ValueError:
        priority = len(TEXT_FORMAT_PRIORITY)
    return (priority, 0 if asset.verification_status == "verified" else 1, asset.filename)


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
