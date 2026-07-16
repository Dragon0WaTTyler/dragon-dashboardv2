from __future__ import annotations

from typing import Protocol
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests


class ReleaseProviderError(RuntimeError):
    pass


class ReleaseProvider(Protocol):
    @property
    def configured(self) -> bool: ...

    def search(self, query: str, media_type: str = "all") -> list[dict]: ...


class JackettProvider:
    def __init__(self, config: dict):
        self.base_url = config["JACKETT_URL"].rstrip("/") + "/"
        self.api_key = config.get("JACKETT_API_KEY", "")
        self.min_seeders = max(0, int(config["JACKETT_MIN_SEEDERS"]))
        self.limit = max(1, min(200, int(config["JACKETT_RESULT_LIMIT"])))
        self.timeout = config["MEDIA_HTTP_TIMEOUT"]
        self.session = requests.Session()
        self.session.headers.update(
            {"Accept": "application/json, application/xml;q=0.9", "User-Agent": "My-TV-Media/1.0"}
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def search(self, query: str, media_type: str = "all") -> list[dict]:
        if not self.configured:
            raise ReleaseProviderError("Jackett is not configured")
        categories = {"movie": "2000", "tv": "5000"}.get(media_type, "2000,5000")
        json_url = urljoin(self.base_url, "api/v2.0/indexers/all/results")
        try:
            response = self.session.get(
                json_url,
                params={"apikey": self.api_key, "Query": query, "Category": categories},
                timeout=self.timeout,
            )
            if response.ok:
                try:
                    return self._filter(self._parse_json(response.json()))
                except ValueError:
                    pass
            return self._search_torznab(query, media_type, categories)
        except requests.RequestException as error:
            raise ReleaseProviderError(f"Jackett request failed: {error}") from error

    def _search_torznab(self, query: str, media_type: str, categories: str) -> list[dict]:
        url = urljoin(self.base_url, "api/v2.0/indexers/all/results/torznab/api")
        search_type = "movie" if media_type == "movie" else "tvsearch" if media_type == "tv" else "search"
        response = self.session.get(
            url,
            params={"apikey": self.api_key, "t": search_type, "q": query, "cat": categories},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise ReleaseProviderError(f"Jackett returned HTTP {response.status_code}")
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as error:
            raise ReleaseProviderError("Jackett returned an unsupported response") from error
        return self._filter(self._parse_xml(root))

    def _parse_json(self, payload) -> list[dict]:
        rows = payload.get("Results", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("Unexpected Jackett JSON")
        parsed = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            magnet = row.get("MagnetUri") or row.get("MagnetURI")
            if not magnet and str(row.get("Link", "")).startswith("magnet:?"):
                magnet = row["Link"]
            parsed.append(
                {
                    "magnet_uri": magnet,
                    "title": row.get("Title") or "Untitled release",
                    "seeders": _integer(row.get("Seeders")),
                    "leechers": _integer(row.get("Peers") or row.get("Leechers")),
                    "size": _integer(row.get("Size")),
                    "tracker": row.get("Tracker") or row.get("TrackerId") or "Unknown tracker",
                    "published": row.get("PublishDate") or row.get("FirstSeen"),
                }
            )
        return parsed

    def _parse_xml(self, root) -> list[dict]:
        parsed = []
        for item in root.findall(".//item"):
            attrs = {}
            for child in list(item):
                if child.tag.endswith("attr") and child.attrib.get("name"):
                    attrs[child.attrib["name"].lower()] = child.attrib.get("value")
            enclosure = item.find("enclosure")
            link = item.findtext("link") or ""
            magnet = attrs.get("magneturl") or attrs.get("magneturi")
            if not magnet and enclosure is not None and enclosure.attrib.get("url", "").startswith("magnet:?"):
                magnet = enclosure.attrib["url"]
            if not magnet and link.startswith("magnet:?"):
                magnet = link
            parsed.append(
                {
                    "magnet_uri": magnet,
                    "title": item.findtext("title") or "Untitled release",
                    "seeders": _integer(attrs.get("seeders")),
                    "leechers": _integer(attrs.get("peers") or attrs.get("leechers")),
                    "size": _integer(item.findtext("size") or attrs.get("size")),
                    "tracker": attrs.get("indexer") or item.findtext("author") or "Unknown tracker",
                    "published": item.findtext("pubDate"),
                }
            )
        return parsed

    def _filter(self, rows: list[dict]) -> list[dict]:
        unique = {}
        for row in rows:
            magnet = row.get("magnet_uri")
            if not magnet or not str(magnet).startswith("magnet:?"):
                continue
            if row.get("seeders", 0) < self.min_seeders:
                continue
            key = magnet.split("&", 1)[0].casefold()
            previous = unique.get(key)
            if not previous or row["seeders"] > previous["seeders"]:
                unique[key] = row
        return sorted(unique.values(), key=lambda item: (-item["seeders"], item["title"].casefold()))[: self.limit]


def build_release_provider(config: dict) -> ReleaseProvider:
    provider = config.get("MEDIA_RELEASE_PROVIDER", "jackett").casefold()
    if provider == "jackett":
        return JackettProvider(config)
    raise ReleaseProviderError(f"Unknown release provider: {provider}")


def _integer(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
