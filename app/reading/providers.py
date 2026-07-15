from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_ARTICLE_BYTES = 2_000_000
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
