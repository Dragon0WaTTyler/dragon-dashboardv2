from app.books.availability_providers import AvailabilitySearchResult
from app.books.models import AvailabilityCandidate, Book, TextAsset
from app.extensions import db
from tests.conftest import csrf_from


def seed_book(app) -> str:
    with app.app_context():
        book = Book(
            title="Candidate Book",
            normalized_title="candidate book",
            authors=["Example Author"],
            status="wishlist",
        )
        db.session.add(book)
        db.session.commit()
        return book.id


def test_availability_candidate_review_does_not_create_assets(authenticated_client, app):
    book_id = seed_book(app)
    page = authenticated_client.get(f"/books/{book_id}")

    add_response = authenticated_client.post(
        f"/books/{book_id}/availability-candidates",
        data={
            "csrf_token": csrf_from(page),
            "provider": "telegram",
            "title": "Candidate Book AZW3",
            "format_guess": "azw3",
            "language_guess": "English",
            "source_reference": "telegram://message/1",
        },
        follow_redirects=True,
    )
    add_html = add_response.get_data(as_text=True)

    assert "Availability candidate saved for review." in add_html
    assert "Candidate Book AZW3" in add_html
    assert "Review Required" in add_html
    assert "Confirm" in add_html

    with app.app_context():
        candidate = db.session.scalar(db.select(AvailabilityCandidate))
        assert candidate is not None
        assert candidate.provider == "telegram"
        assert candidate.format_guess == "AZW3"
        assert candidate.review_state == "review_required"
        assert db.session.scalars(db.select(TextAsset)).all() == []
        candidate_id = candidate.id

    confirm_response = authenticated_client.post(
        f"/books/{book_id}/availability-candidates/{candidate_id}/confirm",
        data={"csrf_token": csrf_from(add_response)},
        follow_redirects=True,
    )
    confirm_html = confirm_response.get_data(as_text=True)

    assert "Availability candidate confirmed." in confirm_html
    assert "Confirmed" in confirm_html
    assert f"/availability-candidates/{candidate_id}/confirm" not in confirm_html

    with app.app_context():
        candidate = db.session.get(AvailabilityCandidate, candidate_id)
        assert candidate.review_state == "confirmed"
        assert candidate.match_confidence == "high"
        assert db.session.scalars(db.select(TextAsset)).all() == []

    reject_response = authenticated_client.post(
        f"/books/{book_id}/availability-candidates/{candidate_id}/reject",
        data={"csrf_token": csrf_from(confirm_response)},
        follow_redirects=True,
    )
    reject_html = reject_response.get_data(as_text=True)

    assert "Availability candidate rejected." in reject_html
    assert "Rejected" in reject_html

    with app.app_context():
        candidate = db.session.get(AvailabilityCandidate, candidate_id)
        assert candidate.review_state == "rejected"
        assert candidate.match_confidence == "needs_review"
        assert db.session.scalars(db.select(TextAsset)).all() == []


def test_availability_candidate_requires_supported_format(authenticated_client, app):
    book_id = seed_book(app)
    page = authenticated_client.get(f"/books/{book_id}")

    response = authenticated_client.post(
        f"/books/{book_id}/availability-candidates",
        data={
            "csrf_token": csrf_from(page),
            "provider": "telegram",
            "title": "Candidate Book MOBI",
            "format_guess": "mobi",
        },
        follow_redirects=True,
    )

    assert "Candidate format must be KFX, AZW3, EPUB, or PDF." in response.get_data(
        as_text=True
    )
    with app.app_context():
        assert db.session.scalars(db.select(AvailabilityCandidate)).all() == []


def test_availability_candidate_parse_pasted_provider_text(authenticated_client, app):
    book_id = seed_book(app)
    page = authenticated_client.get(f"/books/{book_id}")

    response = authenticated_client.post(
        f"/books/{book_id}/availability-candidates/parse",
        data={
            "csrf_token": csrf_from(page),
            "provider": "telegram",
            "raw_text": "\n".join(
                [
                    "https://t.me/library_drop/42",
                    "Candidate Book - Example Author [English] (AZW3) 12.5 MB",
                ]
            ),
        },
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)

    assert "Availability candidate parsed for review." in html
    assert "Candidate Book - Example Author" in html
    assert "AZW3" in html
    assert "Review Required" in html

    with app.app_context():
        candidate = db.session.scalar(db.select(AvailabilityCandidate))
        assert candidate is not None
        assert candidate.provider == "telegram"
        assert candidate.title == "Candidate Book - Example Author"
        assert candidate.format_guess == "AZW3"
        assert candidate.language_guess == "English"
        assert candidate.size_bytes == 13_107_200
        assert candidate.source_reference == "https://t.me/library_drop/42"
        assert candidate.review_state == "review_required"
        assert db.session.scalars(db.select(TextAsset)).all() == []


def test_jackett_search_adds_review_only_candidates(authenticated_client, app):
    class Provider:
        def search(self, book, *, limit):
            assert book.title == "Candidate Book"
            assert limit == 12
            return [
                AvailabilitySearchResult(
                    provider="jackett",
                    title="Candidate Book - Example Author",
                    format_guess="KFX",
                    language_guess="English",
                    size_bytes=21_000_000,
                    source_reference="https://tracker.example/release/1",
                    match_confidence="medium",
                    metadata_json={"tracker": "Books", "seeders": 9},
                )
            ]

    book_id = seed_book(app)
    page = authenticated_client.get(f"/books/{book_id}")
    with app.app_context():
        app.extensions["dragon_book_availability_providers"] = [Provider()]

    response = authenticated_client.post(
        f"/books/{book_id}/availability-candidates/jackett-search",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)

    assert "Jackett search added 1 candidate for review." in html
    assert "Candidate Book - Example Author" in html
    assert "Medium" in html
    assert "KFX" in html

    with app.app_context():
        candidate = db.session.scalar(db.select(AvailabilityCandidate))
        assert candidate is not None
        assert candidate.provider == "jackett"
        assert candidate.format_guess == "KFX"
        assert candidate.match_confidence == "medium"
        assert candidate.review_state == "review_required"
        assert candidate.metadata_json["tracker"] == "Books"
        assert db.session.scalars(db.select(TextAsset)).all() == []
