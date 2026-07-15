from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

BLOCK_TAGS = frozenset(
    {
        "article",
        "blockquote",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "main",
        "p",
        "section",
        "tr",
    }
)
SKIPPED_TAGS = frozenset({"script", "style", "noscript", "svg", "template"})
INLINE_SPACE_PATTERN = re.compile(r"[^\S\r\n]+")
AROUND_BREAK_PATTERN = re.compile(r" *\n *")
EXCESS_BREAK_PATTERN = re.compile(r"\n{3,}")


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if self.skip_depth:
            self.skip_depth += 1
            return
        if tag in SKIPPED_TAGS:
            self.skip_depth = 1
            return
        if tag == "br" or tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def normalize_article_text(value: object) -> str:
    text = str(value or "").replace("\x00", "")
    for _ in range(2):
        decoded = unescape(text)
        if decoded == text:
            break
        text = decoded

    parser = _PlainTextParser()
    parser.feed(text)
    parser.close()
    normalized = INLINE_SPACE_PATTERN.sub(" ", "".join(parser.parts))
    normalized = AROUND_BREAK_PATTERN.sub("\n", normalized)
    normalized = EXCESS_BREAK_PATTERN.sub("\n\n", normalized)
    return normalized.strip()


def article_paragraphs(value: object) -> list[str]:
    parts = re.split(r"\n+", normalize_article_text(value))
    return [part.strip() for part in parts if part.strip()]
