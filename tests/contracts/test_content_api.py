from app.books.models import Book
from app.extensions import db
from app.reading.models import Article
from app.youtube.models import YouTubeVideo


def seed_api_content(app) -> dict[str, str]:
    with app.app_context():
        video = YouTubeVideo(external_id="api-video", source="watch_later", title="API video")
        article = Article(title="API article", url="https://example.test/api-article")
        book = Book(title="API book", normalized_title="api book")
        db.session.add_all([video, article, book])
        db.session.commit()
        return {"video": video.id, "article": article.id, "book": book.id}


def test_content_collection_contracts(authenticated_client, app):
    ids = seed_api_content(app)
    for path, expected_id in (
        ("/api/v1/youtube", ids["video"]),
        ("/api/v1/articles", ids["article"]),
        ("/api/v1/books", ids["book"]),
    ):
        payload = authenticated_client.get(path).get_json()
        assert payload["ok"] is True
        assert payload["api_version"] == "v1"
        assert payload["items"][0]["id"] == expected_id
        assert payload["count"] == 1


def test_content_detail_and_sections_contracts(authenticated_client, app):
    ids = seed_api_content(app)
    assert authenticated_client.get(f"/api/v1/youtube/{ids['video']}").status_code == 200
    assert authenticated_client.get(f"/api/v1/articles/{ids['article']}").status_code == 200
    assert authenticated_client.get(f"/api/v1/books/{ids['book']}").status_code == 200
    sections = authenticated_client.get("/api/v1/youtube/sections").get_json()
    assert sections["items"][0]["id"] == "watch_later"


def test_article_fulltext_status_contract(authenticated_client, app):
    article_id = seed_api_content(app)["article"]
    payload = authenticated_client.get(
        f"/api/v1/articles/{article_id}/fulltext-status"
    ).get_json()
    assert payload["item"]["cached"] is False
    assert payload["item"]["state"] == "not_requested"
