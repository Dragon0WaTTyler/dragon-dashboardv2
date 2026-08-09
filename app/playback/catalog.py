from __future__ import annotations

import csv
import json
import re
from io import StringIO
from typing import Any
from urllib.parse import unquote, urlsplit

from app.extensions import db
from app.movies.models import Movie
from app.movies.public import tv_episode_exists
from app.playback.models import ImportBatch, ImportRow, PlaybackSource
from app.playback.providers import (
    INDEXED_EMBED_PROVIDER_SPECS,
    canonical_indexed_embed_provider_key,
    catalog_asset_id_from_url,
    catalog_provider_for_host,
    indexed_embed_provider_spec,
)
from app.playback.services import PlaybackService
from app.shared.time import utc_now

CATALOG_PROVIDER_KEYS = frozenset(spec.key for spec in INDEXED_EMBED_PROVIDER_SPECS)
IMDB_ID_PATTERN = re.compile(r"^tt\d{5,12}$", re.IGNORECASE)
SENSITIVE_FIELD_PATTERN = re.compile(r"(?:api.?key|token|secret|password|cookie)", re.I)
MAX_IMPORT_ROWS = 10_000
MAX_CATALOG_BYTES = 2_000_000


class CatalogImportError(ValueError):
    pass


def parse_catalog_json(payload: bytes | str) -> list[dict[str, Any]]:
    try:
        value = json.loads(_decode_payload(payload))
    except json.JSONDecodeError as exc:
        raise CatalogImportError("Catalog JSON could not be read.") from exc
    rows = value.get("rows") if isinstance(value, dict) else value
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise CatalogImportError(
            "Catalog JSON must be a list of mapping rows or an object with rows."
        )
    return _limited_rows(rows)


def parse_catalog_csv(payload: bytes | str) -> list[dict[str, Any]]:
    reader = csv.DictReader(StringIO(_decode_payload(payload)))
    if not reader.fieldnames:
        raise CatalogImportError("Catalog CSV requires a header row.")
    return _limited_rows([dict(row) for row in reader])


def _decode_payload(payload: bytes | str) -> str:
    if isinstance(payload, bytes):
        if len(payload) > MAX_CATALOG_BYTES:
            raise CatalogImportError("Catalog file is too large.")
        try:
            return payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise CatalogImportError("Catalog must use UTF-8 encoding.") from exc
    if len(payload.encode("utf-8")) > MAX_CATALOG_BYTES:
        raise CatalogImportError("Catalog file is too large.")
    return payload


def _limited_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(rows) > MAX_IMPORT_ROWS:
        raise CatalogImportError(f"Catalog contains more than {MAX_IMPORT_ROWS} rows.")
    return rows


def _text(value: Any, *, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _nonnegative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _media_type(value: Any) -> str:
    normalized = _text(value, limit=20).lower()
    if normalized in {"movie", "film"}:
        return "movie"
    if normalized in {"tv", "series", "show"}:
        return "tv"
    return ""


def _normalized_title(value: Any) -> str:
    return re.sub(r"[^\w]+", " ", _text(value, limit=300).casefold()).strip()


def _value(row: dict[str, Any], *keys: str) -> Any:
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key)
        if value is not None and value != "":
            return value
    return ""


def _subtitle_languages(value: Any) -> list[str]:
    parts = value if isinstance(value, list) else _text(value, limit=500).split(",")
    return list(
        dict.fromkeys(_text(part, limit=24).lower() for part in parts if _text(part, limit=24))
    )


def _sanitized_row(row: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key in (
        "imdb_id",
        "imdb",
        "tmdb_id",
        "tmdb",
        "media_type",
        "type",
        "title",
        "year",
        "season",
        "episode",
        "provider",
        "server",
        "provider_asset_id",
        "asset_id",
        "language",
        "subtitle_languages",
        "quality",
    ):
        if SENSITIVE_FIELD_PATTERN.search(key):
            continue
        value = _value(row, key)
        if value is not None and value != "":
            values[key] = value if isinstance(value, list) else _text(value, limit=1000)
    if _value(row, "embed_url", "url"):
        # The importer may use an allowlisted URL to derive a native asset ID,
        # but neither the durable source nor its audit payload retains that URL.
        values["embed_reference_provided"] = True
    return values


class CatalogImportService:
    @classmethod
    def import_rows(
        cls,
        rows: list[dict[str, Any]],
        *,
        import_method: str,
        source_name: str,
        filename: str = "",
    ) -> ImportBatch:
        if import_method not in {"csv", "json", "manual"}:
            raise CatalogImportError("Catalog import method is invalid.")
        if not rows:
            raise CatalogImportError("Catalog contains no rows.")
        _limited_rows(rows)
        batch = ImportBatch(
            import_method=import_method,
            source_name=_text(source_name, limit=200) or "authorized catalog",
            filename=_text(filename, limit=300),
            total_rows=len(rows),
        )
        db.session.add(batch)
        db.session.flush()

        for row_number, values in enumerate(rows, start=1):
            outcome = cls._process_row(batch, row_number, values)
            if outcome.match_status == "accepted":
                batch.accepted_rows += 1
            elif outcome.match_status == "review_required":
                batch.review_rows += 1
            elif outcome.match_status == "rejected":
                batch.rejected_rows += 1
            else:
                batch.error_rows += 1

        batch.completed_at = utc_now()
        db.session.commit()
        return batch

    @classmethod
    def _process_row(cls, batch: ImportBatch, row_number: int, values: dict[str, Any]) -> ImportRow:
        sanitized = _sanitized_row(values if isinstance(values, dict) else {})
        row = ImportRow(
            batch_id=batch.id,
            row_number=row_number,
            raw_data=sanitized,
            match_status="error",
        )
        db.session.add(row)
        if not isinstance(values, dict):
            row.reason = "Catalog row must be an object."
            return row
        try:
            provider, asset_id = cls._provider_asset(values)
            row.provider = provider
            row.provider_asset_id = asset_id
            row.raw_reference = asset_id
            movie, status, reason, confidence, season, episode = cls._match_content(values)
            row.match_status = status
            row.reason = reason
            row.confidence = confidence
            row.matched_movie_id = movie.id if movie else None
            if status != "accepted" or movie is None:
                return row

            conflict = db.session.scalar(
                db.select(PlaybackSource).where(
                    PlaybackSource.movie_id == movie.id,
                    PlaybackSource.scope_key == _scope_key(season=season, episode=episode),
                    PlaybackSource.provider == provider,
                    PlaybackSource.provider_asset_id != asset_id,
                )
            )
            if conflict is not None:
                row.match_status = "review_required"
                row.reason = "A different asset already exists for this provider and content scope."
                row.confidence = 1.0
                return row

            source = PlaybackService.upsert_indexed_embed_source(
                movie_id=movie.id,
                provider=provider,
                provider_asset_id=asset_id,
                label=_text(_value(values, "label"), limit=300) or provider.title(),
                season=season,
                episode=episode,
                language=_text(_value(values, "language"), limit=24).lower(),
                subtitle_languages=_subtitle_languages(_value(values, "subtitle_languages")),
                quality=_text(_value(values, "quality"), limit=80),
                provenance={
                    "origin": "catalog_import",
                    "import_batch_id": batch.id,
                    "import_method": batch.import_method,
                    "source_name": batch.source_name,
                },
            )
            source.authorization_status = "catalog_authorized"
            source.match_confidence = confidence
            source.priority_override = _nonnegative_int(_value(values, "priority_override"))
            db.session.flush()
            row.created_playback_source_id = source.id
        except CatalogImportError as exc:
            row.match_status = "rejected"
            row.reason = str(exc)
        except (TypeError, ValueError) as exc:
            row.match_status = "error"
            row.reason = str(exc)[:500]
        return row

    @staticmethod
    def _provider_asset(values: dict[str, Any]) -> tuple[str, str]:
        provider = _text(_value(values, "provider", "server"), limit=40).lower()
        provider = canonical_indexed_embed_provider_key(provider) or provider
        reference = _text(_value(values, "embed_url", "url"), limit=1000)
        asset_id = _text(_value(values, "provider_asset_id", "asset_id"), limit=300)
        if reference:
            parsed = urlsplit(reference)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise CatalogImportError("Catalog embed URL must be a plain HTTPS URL.")
            url_provider = catalog_provider_for_host(parsed.hostname)
            if url_provider is None:
                raise CatalogImportError("Catalog embed URL domain is not allowlisted.")
            if provider and provider != url_provider:
                raise CatalogImportError("Catalog provider does not match its embed URL domain.")
            provider = url_provider
            if not asset_id:
                asset_id = catalog_asset_id_from_url(provider, unquote(reference)) or ""
                if not asset_id:
                    raise CatalogImportError(
                        "Catalog embed URL does not match this provider's supported embed path."
                    )
        if provider == "vidsrc":
            raise CatalogImportError(
                "VidSrc is resolved from content identity and is not catalog-imported."
            )
        if provider not in CATALOG_PROVIDER_KEYS:
            raise CatalogImportError("Catalog provider is not supported.")
        spec = indexed_embed_provider_spec(provider)
        if spec is None or not re.fullmatch(spec.asset_id_pattern, asset_id):
            raise CatalogImportError("Catalog provider asset ID is invalid.")
        return provider, asset_id

    @staticmethod
    def _match_content(
        values: dict[str, Any],
    ) -> tuple[Movie | None, str, str, float | None, int | None, int | None]:
        media_type = _media_type(_value(values, "media_type", "type"))
        if not media_type:
            return None, "review_required", "Catalog media type is required.", None, None, None
        season = _positive_int(_value(values, "season"))
        episode = _positive_int(_value(values, "episode"))
        if (season is None) != (episode is None):
            return (
                None,
                "review_required",
                "TV catalog rows require both season and episode.",
                None,
                season,
                episode,
            )
        if media_type == "tv" and (season is None or episode is None):
            return (
                None,
                "review_required",
                "TV catalog rows require an exact season and episode.",
                None,
                season,
                episode,
            )
        if media_type == "movie" and (season is not None or episode is not None):
            return (
                None,
                "rejected",
                "Movie catalog rows cannot include a TV season or episode.",
                None,
                season,
                episode,
            )

        imdb_id = _text(_value(values, "imdb_id", "imdb"), limit=20).lower()
        tmdb_id = _text(_value(values, "tmdb_id", "tmdb"), limit=20)
        if imdb_id and not IMDB_ID_PATTERN.fullmatch(imdb_id):
            return None, "rejected", "Catalog IMDb ID is invalid.", None, season, episode
        if tmdb_id and not tmdb_id.isdigit():
            return None, "rejected", "Catalog TMDb ID is invalid.", None, season, episode

        movies = list(db.session.scalars(db.select(Movie)))
        imdb_matches = [
            movie
            for movie in movies
            if imdb_id and str((movie.external_ids or {}).get("imdb_id") or "").lower() == imdb_id
        ]
        tmdb_matches = [
            movie
            for movie in movies
            if tmdb_id and str((movie.external_ids or {}).get("tmdb_id") or "") == tmdb_id
        ]
        if (
            imdb_id
            and tmdb_id
            and {movie.id for movie in imdb_matches} != {movie.id for movie in tmdb_matches}
        ):
            return None, "rejected", "Catalog IMDb and TMDb IDs conflict.", None, season, episode
        identifier_matches = imdb_matches or tmdb_matches
        if identifier_matches:
            if len(identifier_matches) != 1:
                return (
                    None,
                    "review_required",
                    "Catalog identity matches multiple Dragon items.",
                    None,
                    season,
                    episode,
                )
            movie = identifier_matches[0]
            if movie.media_type != media_type:
                return (
                    None,
                    "rejected",
                    "Catalog media type conflicts with Dragon content.",
                    None,
                    season,
                    episode,
                )
            if media_type == "tv" and not tv_episode_exists(
                movie.id, season=season, episode=episode
            ):
                return (
                    movie,
                    "review_required",
                    "Catalog TV episode is not present in Dragon.",
                    1.0,
                    season,
                    episode,
                )
            return movie, "accepted", "Exact external identity match.", 1.0, season, episode

        title = _normalized_title(_value(values, "title"))
        year = _positive_int(_value(values, "year"))
        if title and year:
            candidates = [
                movie
                for movie in movies
                if movie.media_type == media_type
                and movie.normalized_title == title
                and movie.year == year
            ]
            if len(candidates) == 1:
                return (
                    candidates[0],
                    "review_required",
                    "Title and year require manual review.",
                    0.8,
                    season,
                    episode,
                )
            if len(candidates) > 1:
                return (
                    None,
                    "review_required",
                    "Title and year are ambiguous.",
                    None,
                    season,
                    episode,
                )
        return None, "review_required", "No exact external identity match.", None, season, episode


def _scope_key(*, season: int | None, episode: int | None) -> str:
    return f"s{season:02d}e{episode:02d}" if season is not None and episode is not None else "movie"


def import_batch_report(batch: ImportBatch) -> dict[str, Any]:
    rows = list(
        db.session.scalars(
            db.select(ImportRow)
            .where(ImportRow.batch_id == batch.id)
            .order_by(ImportRow.row_number)
        )
    )
    return {
        "id": batch.id,
        "import_method": batch.import_method,
        "source_name": batch.source_name,
        "filename": batch.filename,
        "total_rows": batch.total_rows,
        "accepted_rows": batch.accepted_rows,
        "review_rows": batch.review_rows,
        "rejected_rows": batch.rejected_rows,
        "error_rows": batch.error_rows,
        "rows": [
            {
                "row_number": row.row_number,
                "match_status": row.match_status,
                "matched_movie_id": row.matched_movie_id,
                "provider": row.provider,
                "provider_asset_id": row.provider_asset_id,
                "reason": row.reason,
                "confidence": row.confidence,
                "created_playback_source_id": row.created_playback_source_id,
            }
            for row in rows
        ],
    }
