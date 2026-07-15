from email.message import Message

import pytest

from app.reading.providers import ArticleExtractor


def public_resolver(host, port, *, type=None):
    return [(2, type, 6, "", ("93.184.216.34", port))]


class FakeResponse:
    def __init__(self, body: bytes, url: str = "https://example.com/story") -> None:
        self.body = body
        self.url = url
        self.headers = Message()
        self.headers["Content-Type"] = "text/html; charset=utf-8"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def geturl(self):
        return self.url

    def read(self, size):
        return self.body[:size]


class FakeOpener:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response

    def open(self, request, timeout):
        assert request.full_url == "https://example.com/story"
        assert timeout == 3
        return self.response


def test_article_extractor_prefers_readable_article_text():
    body = b"""
        <html><nav>Ignore navigation</nav><article>
        <h2>A clear heading</h2>
        <p>This is the first useful paragraph with enough detail for a local reader.</p>
        <p>This is the second useful paragraph and it completes the readable article body.</p>
        </article></html>
    """
    extractor = ArticleExtractor(
        timeout_seconds=3,
        resolver=public_resolver,
        opener=FakeOpener(FakeResponse(body)),
    )

    result = extractor.extract("https://example.com/story")

    assert "A clear heading" in result["content_text"]
    assert "Ignore navigation" not in result["content_text"]
    assert result["canonical_url"] == "https://example.com/story"


def test_article_extractor_rejects_private_hosts():
    def private_resolver(host, port, *, type=None):
        return [(2, type, 6, "", ("127.0.0.1", port))]

    extractor = ArticleExtractor(resolver=private_resolver)

    with pytest.raises(ValueError, match="public host"):
        extractor.extract("http://localhost/internal")
