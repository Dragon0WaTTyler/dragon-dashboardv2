from __future__ import annotations

from datetime import datetime, timezone

import requests


class NotionMediaError(RuntimeError):
    pass


class NotionMediaClient:
    FIELD_CONFIG = {
        "title": "NOTION_PROP_TITLE",
        "tmdb_id": "NOTION_PROP_TMDB_ID",
        "media_type": "NOTION_PROP_TYPE",
        "year": "NOTION_PROP_YEAR",
        "poster_url": "NOTION_PROP_POSTER",
        "overview": "NOTION_PROP_OVERVIEW",
        "magnet_uri": "NOTION_PROP_MAGNET",
        "release_title": "NOTION_PROP_RELEASE_TITLE",
        "watched": "NOTION_PROP_WATCHED",
        "date_watched": "NOTION_PROP_DATE_WATCHED",
        "season": "NOTION_PROP_SEASON",
        "episode": "NOTION_PROP_EPISODE",
    }

    def __init__(self, config: dict):
        self.token = config.get("NOTION_TOKEN", "")
        self.database_id = _clean_id(config.get("NOTION_DATABASE_ID", ""))
        self._configured_data_source_id = _clean_id(config.get("NOTION_DATA_SOURCE_ID", ""))
        self.version = config["NOTION_VERSION"]
        self.timeout = config["MEDIA_HTTP_TIMEOUT"]
        self.property_names = {
            field: config[config_key] for field, config_key in self.FIELD_CONFIG.items()
        }
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": self.version,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        self._resolved_data_source_id: str | None = None
        self._schema_cache: dict | None = None

    @property
    def configured(self) -> bool:
        return bool(self.token and (self._configured_data_source_id or self.database_id))

    def configuration(self) -> dict:
        result = {
            "configured": self.configured,
            "database_id_set": bool(self.database_id),
            "data_source_id_set": bool(self._configured_data_source_id),
            "missing_properties": [],
        }
        if not self.configured:
            return result
        schema = self.schema()
        title_property = self._title_property_name(schema)
        missing = []
        for field, name in self.property_names.items():
            if field == "title" and title_property:
                continue
            if name not in schema:
                missing.append(name)
        result["missing_properties"] = missing
        result["data_source_id"] = self.data_source_id
        return result

    @property
    def data_source_id(self) -> str:
        if self._resolved_data_source_id:
            return self._resolved_data_source_id
        if self._configured_data_source_id:
            self._resolved_data_source_id = self._configured_data_source_id
            return self._resolved_data_source_id
        if not self.database_id:
            raise NotionMediaError("Notion database or data source ID is not configured")
        payload = self._request("GET", f"/databases/{self.database_id}")
        sources = payload.get("data_sources") or []
        if not sources:
            raise NotionMediaError("The Notion database has no accessible data source")
        self._resolved_data_source_id = sources[0]["id"]
        return self._resolved_data_source_id

    def schema(self) -> dict:
        if self._schema_cache is None:
            payload = self._request("GET", f"/data_sources/{self.data_source_id}")
            self._schema_cache = payload.get("properties") or {}
        return self._schema_cache

    def list_media(self) -> list[dict]:
        if not self.configured:
            raise NotionMediaError("Notion is not configured")
        pages = []
        cursor = None
        while True:
            body = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            payload = self._request(
                "POST", f"/data_sources/{self.data_source_id}/query", json=body
            )
            pages.extend(payload.get("results", []))
            if not payload.get("has_more") or not payload.get("next_cursor"):
                break
            cursor = payload["next_cursor"]
        items = [self._page_to_media(page) for page in pages if not page.get("in_trash")]
        return sorted(items, key=lambda item: (item.get("title") or "").casefold())

    def find(self, media_type: str, tmdb_id: int) -> dict | None:
        normalized_type = _normalize_type(media_type)
        for item in self.list_media():
            if item.get("tmdb_id") == int(tmdb_id) and item.get("media_type") == normalized_type:
                return item
        return None

    def upsert(self, media: dict) -> dict:
        media_type = _normalize_type(media.get("media_type"))
        if media_type not in {"movie", "tv"}:
            raise NotionMediaError("media_type must be movie or tv")
        tmdb_id = int(media["tmdb_id"])
        existing = self.find(media_type, tmdb_id)
        values = dict(media)
        values["media_type"] = "Movie" if media_type == "movie" else "Series"
        properties = self._properties_payload(values)
        if existing:
            payload = self._request(
                "PATCH", f"/pages/{existing['notion_page_id']}", json={"properties": properties}
            )
            created = False
        else:
            payload = self._request(
                "POST",
                "/pages",
                json={
                    "parent": {"type": "data_source_id", "data_source_id": self.data_source_id},
                    "properties": properties,
                },
            )
            created = True
        item = self._page_to_media(payload)
        item["created"] = created
        return item

    def mark_watched(self, page_id: str, watched: bool = True) -> dict:
        values = {
            "watched": bool(watched),
            "date_watched": datetime.now(timezone.utc).isoformat() if watched else None,
        }
        payload = self._request(
            "PATCH", f"/pages/{_clean_id(page_id)}", json={"properties": self._properties_payload(values)}
        )
        return self._page_to_media(payload)

    def _page_to_media(self, page: dict) -> dict:
        properties = page.get("properties") or {}
        schema = self.schema()
        title_name = self._title_property_name(schema) or self.property_names["title"]
        fields = {}
        for field, configured_name in self.property_names.items():
            name = title_name if field == "title" else configured_name
            fields[field] = _decode_property(properties.get(name))
        fields["tmdb_id"] = _optional_int(fields.get("tmdb_id"))
        fields["year"] = _optional_int(fields.get("year"))
        fields["season"] = _optional_int(fields.get("season"))
        fields["episode"] = _optional_int(fields.get("episode"))
        # Existing personal movie databases often predate the Type property.
        # Treat those rows as movies; new series writes always persist Type=Series.
        fields["media_type"] = _normalize_type(fields.get("media_type")) or "movie"
        fields["notion_page_id"] = page.get("id")
        fields["notion_url"] = page.get("url")
        fields["last_edited_time"] = page.get("last_edited_time")
        fields["watched"] = bool(fields.get("watched"))
        return fields

    def _properties_payload(self, values: dict) -> dict:
        schema = self.schema()
        title_name = self._title_property_name(schema) or self.property_names["title"]
        result = {}
        for field, value in values.items():
            if field not in self.property_names:
                continue
            name = title_name if field == "title" else self.property_names[field]
            definition = schema.get(name)
            if not definition:
                continue
            encoded = _encode_property(definition.get("type"), value)
            if encoded is not None:
                result[name] = encoded
        if "title" in values and title_name not in result:
            raise NotionMediaError("The Notion data source needs a title property")
        return result

    @staticmethod
    def _title_property_name(schema: dict) -> str | None:
        for name, definition in schema.items():
            if definition.get("type") == "title":
                return name
        return None

    def _request(self, method: str, path: str, **kwargs) -> dict:
        if not self.configured:
            raise NotionMediaError("Notion is not configured")
        try:
            response = self.session.request(
                method, f"https://api.notion.com/v1{path}", timeout=self.timeout, **kwargs
            )
        except requests.RequestException as error:
            raise NotionMediaError(f"Notion request failed: {error}") from error
        if response.status_code >= 400:
            try:
                message = response.json().get("message")
            except ValueError:
                message = None
            raise NotionMediaError(message or f"Notion returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as error:
            raise NotionMediaError("Notion returned invalid JSON") from error


def _decode_property(prop: dict | None):
    if not prop:
        return None
    prop_type = prop.get("type")
    value = prop.get(prop_type)
    if prop_type in {"title", "rich_text"}:
        return "".join(part.get("plain_text", "") for part in value or [])
    if prop_type == "number":
        return value
    if prop_type == "checkbox":
        return bool(value)
    if prop_type in {"select", "status"}:
        return value.get("name") if value else None
    if prop_type == "date":
        return value.get("start") if value else None
    if prop_type in {"url", "email", "phone_number"}:
        return value
    if prop_type == "formula" and isinstance(value, dict):
        formula_type = value.get("type")
        return value.get(formula_type)
    return None


def _encode_property(prop_type: str | None, value):
    if prop_type in {"title", "rich_text"}:
        key = prop_type
        content = str(value or "")[:2000]
        return {key: [] if not content else [{"type": "text", "text": {"content": content}}]}
    if prop_type == "number":
        return {"number": None if value in {None, ""} else int(value)}
    if prop_type == "checkbox":
        return {"checkbox": bool(value)}
    if prop_type in {"select", "status"}:
        return {prop_type: None if not value else {"name": str(value)}}
    if prop_type == "date":
        return {"date": None if not value else {"start": str(value)}}
    if prop_type == "url":
        return {"url": str(value)[:2000] if value else None}
    return None


def _normalize_type(value) -> str | None:
    text = str(value or "").strip().casefold()
    if text in {"movie", "film"}:
        return "movie"
    if text in {"tv", "series", "serie", "show"}:
        return "tv"
    return text or None


def _optional_int(value) -> int | None:
    try:
        return int(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None


def _clean_id(value: str | None) -> str:
    return str(value or "").strip().replace("-", "")
