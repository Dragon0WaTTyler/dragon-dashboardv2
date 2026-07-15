from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

MAX_ARTICLE_BYTES = 2_000_000
MAX_FEED_BYTES = 2_000_000
MAX_FEED_ENTRIES = 80
SKIPPED_TAGS = frozenset(
    {"script", "style", "noscript", "svg", "nav", "footer", "aside", "form"}
)
CONTENT_TAGS = frozenset({"p", "h2", "h3", "blockquote", "li"})


def _validate_public_url(url: str, resolver: Callable[..., list[Any]]) -> str:
    normalized = str(url or "").strip()
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Article URL must use HTTP or HTTPS.")
    if parsed.username or parsed.password:
        raise ValueError("Article URL cannot contain credentials.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = resolver(parsed.hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Article host could not be resolved.") from exc
    if not addresses:
        raise ValueError("Article host could not be resolved.")
    for address in addresses:
        raw_address = str(address[4][0]).split("%", 1)[0]
        if not ipaddress.ip_address(raw_address).is_global:
            raise ValueError("Article URL must resolve to a public host.")
    return normalized


class _SafeRedirectHandler(HTTPRedirectHandler):
    def __init__(self, resolver: Callable[..., list[Any]]) -> None:
        super().__init__()
        self.resolver = resolver

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        _validate_public_url(new_url, self.resolver)
        return super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )


class _ArticleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._preferred_depth = 0
        self._capture_tag = ""
        self._buffer: list[str] = []
        self._all_blocks: list[str] = []
        self._preferred_blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if self._skip_depth:
            self._skip_depth += 1
            return
        if tag in SKIPPED_TAGS:
            self._skip_depth = 1
            return
        if tag in {"article", "main"}:
            self._preferred_depth += 1
        if tag in CONTENT_TAGS and not self._capture_tag:
            self._capture_tag = tag
            self._buffer = []
        elif tag == "br" and self._capture_tag:
            self._buffer.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if self._capture_tag == tag:
            block = " ".join("".join(self._buffer).split())
            if block and (not self._all_blocks or self._all_blocks[-1] != block):
                self._all_blocks.append(block)
                if self._preferred_depth:
                    self._preferred_blocks.append(block)
            self._capture_tag = ""
            self._buffer = []
        if tag in {"article", "main"} and self._preferred_depth:
            self._preferred_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and self._capture_tag:
            self._buffer.append(data)

    def readable_text(self) -> str:
        preferred = "\n\n".join(self._preferred_blocks)
        fallback = "\n\n".join(self._all_blocks)
        return preferred if len(preferred) >= 160 else fallback


class _FeedMarkupParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []
        self.image_url = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if self._skip_depth:
            self._skip_depth += 1
            return
        if tag in SKIPPED_TAGS:
            self._skip_depth = 1
            return
        if tag == "img" and not self.image_url:
            attributes = dict(attrs)
            self.image_url = str(attributes.get("src") or "").strip()

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)

    def readable_text(self) -> str:
        return " ".join(" ".join(self.parts).split())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(node, *names: str) -> str:
    wanted = set(names)
    for child in node:
        if _local_name(child.tag) in wanted:
            return "".join(child.itertext()).strip()
    return ""


def _entry_link(node) -> str:
    fallback = ""
    for child in node:
        if _local_name(child.tag) != "link":
            continue
        href = str(child.attrib.get("href") or "").strip()
        if href and str(child.attrib.get("rel") or "alternate") == "alternate":
            return href
        text = "".join(child.itertext()).strip()
        if text:
            return text
        fallback = fallback or href
    return fallback


def _entry_image(node, markup_image: str) -> str:
    for child in node.iter():
        name = _local_name(child.tag)
        url = str(child.attrib.get("url") or child.attrib.get("href") or "").strip()
        media_type = str(child.attrib.get("type") or "").lower()
        media_kind = str(child.attrib.get("medium") or "").lower()
        is_image = name == "thumbnail" or (
            name in {"content", "enclosure"}
            and (media_type.startswith("image/") or media_kind == "image")
        )
        if url and is_image:
            return url
    return markup_image


def _published_at(value: str) -> datetime | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = parsedate_to_datetime(normalized)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class FeedClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 10,
        resolver: Callable[..., list[Any]] = socket.getaddrinfo,
        opener=None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.resolver = resolver
        self.opener = opener or build_opener(_SafeRedirectHandler(resolver))

    def _public_entry_url(self, value: str, base_url: str) -> str:
        candidate = urljoin(base_url, str(value or "").strip())
        if not candidate:
            return ""
        try:
            return _validate_public_url(candidate, self.resolver)
        except ValueError:
            return ""

    def fetch(self, url: str) -> dict[str, Any]:
        safe_url = _validate_public_url(url, self.resolver)
        request = Request(  # noqa: S310 - validated HTTP(S) public URL only.
            safe_url,
            headers={
                "Accept": "application/atom+xml,application/rss+xml,application/xml,text/xml",
                "User-Agent": "Dragon/0.11 (+local feed reader)",
            },
        )
        try:
            with self.opener.open(  # noqa: S310 - URL and redirects are public-host validated.
                request, timeout=self.timeout_seconds
            ) as response:
                final_url = _validate_public_url(response.geturl(), self.resolver)
                payload = response.read(MAX_FEED_BYTES + 1)
                if len(payload) > MAX_FEED_BYTES:
                    raise ValueError("Article feed response is too large.")
                charset = response.headers.get_content_charset() or "utf-8"
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("Article feed could not be reached.") from exc

        document = payload.decode(charset, errors="replace")
        if "<!DOCTYPE" in document.upper() or "<!ENTITY" in document.upper():
            raise ValueError("Article feed contains unsupported XML declarations.")
        try:
            root = ElementTree.fromstring(  # noqa: S314 - DTD/entities rejected above.
                document
            )
        except (ElementTree.ParseError, LookupError, UnicodeError) as exc:
            raise ValueError("Article source did not return a valid RSS or Atom feed.") from exc

        entries: list[dict[str, Any]] = []
        nodes = [
            node for node in root.iter() if _local_name(node.tag) in {"item", "entry"}
        ][:MAX_FEED_ENTRIES]
        for node in nodes:
            raw_link = _entry_link(node)
            article_url = self._public_entry_url(raw_link, final_url)
            title = _child_text(node, "title")
            if not title or not article_url:
                continue
            markup = _child_text(node, "description", "summary", "encoded", "content")
            markup_parser = _FeedMarkupParser()
            markup_parser.feed(markup)
            markup_parser.close()
            raw_image = _entry_image(node, markup_parser.image_url)
            entries.append(
                {
                    "external_id": _child_text(node, "guid", "id") or article_url,
                    "title": title,
                    "url": article_url,
                    "author": _child_text(node, "author", "creator"),
                    "topic": _child_text(node, "category"),
                    "excerpt": markup_parser.readable_text(),
                    "image_url": self._public_entry_url(raw_image, final_url),
                    "published_at": _published_at(
                        _child_text(node, "pubdate", "published", "updated", "date")
                    ),
                }
            )
        return {"canonical_url": final_url, "entries": entries}


class ArticleExtractor:
    def __init__(
        self,
        *,
        timeout_seconds: float = 10,
        resolver: Callable[..., list[Any]] = socket.getaddrinfo,
        opener=None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.resolver = resolver
        self.opener = opener or build_opener(_SafeRedirectHandler(resolver))

    def extract(self, url: str) -> dict[str, str]:
        safe_url = _validate_public_url(url, self.resolver)
        request = Request(  # noqa: S310 - validated HTTP(S) public URL only.
            safe_url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "Dragon/0.11 (+local article reader)",
            },
        )
        try:
            with self.opener.open(  # noqa: S310 - URL and redirects are public-host validated.
                request, timeout=self.timeout_seconds
            ) as response:
                final_url = _validate_public_url(response.geturl(), self.resolver)
                content_type = str(response.headers.get("Content-Type") or "").lower()
                if "html" not in content_type:
                    raise ValueError("Article source did not return HTML.")
                payload = response.read(MAX_ARTICLE_BYTES + 1)
                if len(payload) > MAX_ARTICLE_BYTES:
                    raise ValueError("Article response is too large.")
                charset = response.headers.get_content_charset() or "utf-8"
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("Article source could not be loaded.") from exc

        parser = _ArticleTextParser()
        try:
            parser.feed(payload.decode(charset, errors="replace"))
            parser.close()
        except (LookupError, UnicodeError) as exc:
            raise ValueError("Article text encoding is unsupported.") from exc
        content_text = parser.readable_text().strip()
        if len(content_text) < 80:
            raise ValueError("No readable article body was found.")
        return {"content_text": content_text, "canonical_url": final_url}
