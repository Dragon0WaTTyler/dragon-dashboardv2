from app.books.models import Book
from app.books.providers import MetadataCandidate
from app.extensions import db
from tests.conftest import csrf_from


class MetadataProvider:
    def __init__(self) -> None:
        self.calls = 0

    def lookup(self, *, title, authors=(), isbn="", language=""):
        self.calls += 1
        assert title == "A Local Book"
        assert authors == ["Example Author"]
        return [
            MetadataCandidate(
                source="Open Library",
                title="A Local Book",
                authors=["Example Author"],
                overview="External overview.",
                cover_url="https://covers.example.test/book.jpg",
                subjects=["Fiction", "Library"],
                publisher="External Publisher",
                published_year=2020,
                page_count=320,
                isbn_13="9780140449136",
                openlibrary_work_id="OL1W",
                confidence="high",
            )
        ]


def seed_book(app) -> str:
    with app.app_context():
        book = Book(
            title="A Local Book",
            normalized_title="a local book",
            authors=["Example Author"],
            status="reading",
            current_page=25,
            page_count=0,
            personal_score=4.5,
            publisher="Manual Publisher",
        )
        db.session.add(book)
        db.session.commit()
        return book.id


def test_metadata_preview_and_apply_are_explicit_safe_posts(authenticated_client, app):
    book_id = seed_book(app)
    provider = MetadataProvider()
    app.extensions["dragon_book_metadata_providers"] = [provider]

    page = authenticated_client.get(f"/books/{book_id}")
    assert page.status_code == 200
    assert provider.calls == 0

    preview_response = authenticated_client.post(
        f"/books/{book_id}/metadata-preview",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )
    preview_html = preview_response.get_data(as_text=True)

    assert provider.calls == 1
    assert "Metadata candidate ready for review." in preview_html
    assert "External overview." in preview_html
    assert "Manual Publisher" in preview_html
    assert "External Publisher" in preview_html
    assert "Apply fill only" in preview_html

    with app.app_context():
        book = db.session.get(Book, book_id)
        assert book.description == ""
        assert book.page_count == 0
        assert book.publisher == "Manual Publisher"
        assert book.status == "reading"
        assert book.metadata_state["metadata_preview"]["fill"]["page_count"] == 320
        assert book.metadata_status == "candidate_found"

    apply_response = authenticated_client.post(
        f"/books/{book_id}/metadata-apply",
        data={"csrf_token": csrf_from(preview_response)},
        follow_redirects=True,
    )
    apply_html = apply_response.get_data(as_text=True)

    assert "Metadata fill applied. Conflicts were left unchanged." in apply_html
    assert "Apply fill only" not in apply_html

    with app.app_context():
        book = db.session.get(Book, book_id)
        assert book.description == "External overview."
        assert book.cover_url == "https://covers.example.test/book.jpg"
        assert book.page_count == 320
        assert book.isbn_13 == "9780140449136"
        assert book.external_ids["openlibrary_work_id"] == "OL1W"
        assert book.publisher == "Manual Publisher"
        assert book.status == "reading"
        assert book.current_page == 25
        assert book.personal_score == 4.5
        assert "metadata_preview" not in book.metadata_state
        assert book.metadata_state["last_metadata_preview"]["conflicts"]["publisher"] == {
            "current": "Manual Publisher",
            "candidate": "External Publisher",
        }


def test_kindle_title_aliases_are_explicit_local_posts(authenticated_client, app):
    with app.app_context():
        book = Book(
            title="Canonical Title",
            normalized_title="canonical title",
            authors=["Example Author"],
            metadata_state={"formats_available": ["EPUB"]},
            status="reading",
        )
        db.session.add(book)
        db.session.commit()
        book_id = book.id

    page = authenticated_client.get(f"/books/{book_id}")
    response = authenticated_client.post(
        f"/books/{book_id}/kindle-aliases",
        data={"csrf_token": csrf_from(page), "alias": "Kindle Store Title"},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Kindle title alias saved." in html
    assert "Kindle Store Title" in html
    with app.app_context():
        book = db.session.get(Book, book_id)
        assert book.metadata_state["formats_available"] == ["EPUB"]
        assert book.metadata_state["kindle_title_aliases"] == ["Kindle Store Title"]

    duplicate = authenticated_client.post(
        f"/books/{book_id}/kindle-aliases",
        data={"csrf_token": csrf_from(response), "alias": "  kindle store title  "},
        follow_redirects=True,
    )
    assert "Kindle title alias already exists." in duplicate.get_data(as_text=True)
    with app.app_context():
        book = db.session.get(Book, book_id)
        assert book.metadata_state["kindle_title_aliases"] == ["Kindle Store Title"]

    removed = authenticated_client.post(
        f"/books/{book_id}/kindle-aliases/remove",
        data={"csrf_token": csrf_from(duplicate), "alias": "Kindle Store Title"},
        follow_redirects=True,
    )

    assert "Kindle title alias removed." in removed.get_data(as_text=True)
    with app.app_context():
        book = db.session.get(Book, book_id)
        assert book.metadata_state["kindle_title_aliases"] == []
