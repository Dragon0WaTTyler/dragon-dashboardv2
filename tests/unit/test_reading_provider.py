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
    def __init__(
        self,
        response: FakeResponse,
        expected_url: str = "https://example.com/story",
    ) -> None:
        self.response = response
        self.expected_url = expected_url

    def open(self, request, timeout):
        assert request.full_url == self.expected_url
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


def test_feed_client_parses_rss_metadata_and_thumbnail():
    from app.reading.providers import FeedClient

    body = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Journal</title><item>
        <guid>story-123</guid><title>A fresh story</title>
        <link>https://example.com/stories/fresh</link>
        <description><![CDATA[
          <p>A useful summary from the article feed.</p>
          <img src="https://example.com/images/fresh.jpg">
        ]]></description>
        <author>Editorial desk</author><category>World</category>
        <pubDate>Wed, 15 Jul 2026 08:00:00 GMT</pubDate>
        </item></channel></rss>
    """
    feed_url = "https://example.com/feed.xml"
    client = FeedClient(
        timeout_seconds=3,
        resolver=public_resolver,
        opener=FakeOpener(
            FakeResponse(body, url=feed_url),
            expected_url=feed_url,
        ),
    )

    result = client.fetch(feed_url)

    assert len(result["entries"]) == 1
    entry = result["entries"][0]
    assert entry["external_id"] == "story-123"
    assert entry["title"] == "A fresh story"
    assert entry["excerpt"] == "A useful summary from the article feed."
    assert entry["image_url"] == "https://example.com/images/fresh.jpg"
    assert entry["published_at"].year == 2026
