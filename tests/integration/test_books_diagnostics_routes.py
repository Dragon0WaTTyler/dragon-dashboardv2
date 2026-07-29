import json
from datetime import UTC, datetime
from pathlib import Path

from app.books.book_quotes import BookQuotesSnapshotStore
from app.books.clippings import KindleClippingsStateStore
from app.books.diagnostics import KnowledgeDiagnosticsService
from app.books.models import (
    AudiobookAsset,
    AudiobookEdition,
    AvailabilityCandidate,
    Book,
    BookEdition,
    TextAsset,
)
from app.extensions import db
from tests.conftest import csrf_from


def seed_diagnostics(app) -> dict[str, str]:
    with app.app_context():
        ready = Book(
            title="Ready Book",
            normalized_title="ready book",
            authors=["Example Author"],
            edition_language="English",
            publisher="Ready Press",
            cover_url="https://covers.example.test/ready.jpg",
            metadata_status="verified",
            metadata_confidence="exact_isbn",
            isbn_13="9780140449136",
            last_metadata_refresh_at=datetime(2026, 7, 20, 18, 45, tzinfo=UTC),
        )
        edition = BookEdition(
            book=ready,
            title="Ready Book",
            language="English",
            publisher="Ready Press",
            cover_url="https://covers.example.test/ready-edition.jpg",
            primary=True,
        )
        edition.text_assets.append(
            TextAsset(
                format="KFX",
                source_type="local",
                filename="ready.kfx",
                file_size=2048,
                file_hash="ready-text-hash",
                verification_status="likely",
                preferred_for_kindle=True,
            )
        )
        edition.text_assets.append(
            TextAsset(
                format="PDF",
                source_type="local",
                filename="ready.pdf",
                file_size=1024,
                file_hash="ready-pdf-hash",
                verification_status="verified",
            )
        )
        audiobook = AudiobookEdition(book=ready, title="Ready Book", language="English")
        audiobook.assets.append(
            AudiobookAsset(
                format="MP3",
                source_type="local",
                filename="ready.mp3",
                file_size=4096,
                file_hash="ready-audio-hash",
            )
        )
        needs_review = Book(
            title="Review Book",
            normalized_title="review book",
            authors=["Example Author"],
            metadata_status="needs_review",
            isbn_13="9780140449137",
        )
        needs_review.availability_candidates.append(
            AvailabilityCandidate(
                provider="telegram",
                title="Review Book EPUB",
                format_guess="EPUB",
                language_guess="English",
                review_state="review_required",
            )
        )
        needs_review.availability_candidates.append(
            AvailabilityCandidate(
                provider="telegram",
                title="Review Book EPUB",
                format_guess="EPUB",
                language_guess="English",
                review_state="review_required",
            )
        )
        no_isbn = Book(
            title="Oral Tradition",
            normalized_title="oral tradition",
            authors=["Unknown"],
            edition_language="English",
            publisher="Archive Press",
            cover_url="https://covers.example.test/oral.jpg",
            metadata_status="no_isbn",
            metadata_confidence="manual",
        )
        pdf_only = Book(
            title="PDF Only Book",
            normalized_title="pdf only book",
            authors=["Archive Author"],
            edition_language="English",
            publisher="Archive Press",
            cover_url="https://covers.example.test/pdf-only.jpg",
            metadata_status="verified",
        )
        pdf_edition = BookEdition(
            book=pdf_only,
            title="PDF Only Book",
            language="English",
            publisher="Archive Press",
            primary=True,
        )
        pdf_edition.text_assets.append(
            TextAsset(
                format="PDF",
                source_type="local",
                filename="pdf-only.pdf",
                file_size=512,
                file_hash="pdf-only-hash",
                verification_status="verified",
            )
        )
        db.session.add_all([ready, needs_review, no_isbn, pdf_only])
        db.session.commit()
        return {
            "ready": ready.id,
            "needs_review": needs_review.id,
            "no_isbn": no_isbn.id,
            "pdf_only": pdf_only.id,
        }


def test_knowledge_diagnostics_reports_local_state(authenticated_client, app):
    ids = seed_diagnostics(app)

    response = authenticated_client.get("/settings/knowledge/diagnostics")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Knowledge diagnostics" in html
    assert (
        "See what is healthy, what needs review, and where the local library still "
        "has weak spots" in html
    )
    assert "Open queues" in html
    assert "3" in html
    assert "Verified metadata" in html
    assert "Missing ISBN" in html
    assert "No ISBN" in html
    assert "Unmatched books" in html
    assert "no local text asset or candidate" in html
    assert "Needs review" in html
    assert "Last metadata refresh" in html
    assert "2026-07-20T18:45:00Z" in html
    assert "PDF-only" in html
    assert "final-priority text only" in html
    assert "KFX" in html
    assert "1 registered" in html
    assert "MP3" in html
    assert "1 audio asset" in html
    assert "Local storage" in html
    assert "7.5 KB" in html
    assert "Review Book EPUB" in html
    assert "Oral Tradition" in html
    assert f"/books/{ids['needs_review']}" in html
    assert "Open Library / Google Books" in html
    assert "Explicit only" in html
    assert "PythonAnywhere" in html
    assert "Removed" in html
    assert "ISBN format" in html
    assert "1 issue" in html
    assert "Authors" in html
    assert "Edition language" in html
    assert "Primary edition language coverage" in html
    assert "Publisher" in html
    assert "Primary edition publisher coverage" in html
    assert "Cover" in html
    assert "Book or edition cover coverage" in html
    assert "Duplicate candidates" in html
    assert "Availability candidate dedupe" in html
    with app.app_context():
        summary = {
            item["label"]: item["value"]
            for item in KnowledgeDiagnosticsService.snapshot()["summary"]
        }
    assert summary["Books"] == 4
    assert summary["Unmatched books"] == 1
    assert summary["Last metadata refresh"] == "2026-07-20T18:45:00Z"
    assert summary["Local storage"] == "7.5 KB"
    assert summary["Text assets"] == 3
    assert summary["PDF-only"] == 1


def test_knowledge_diagnostics_counts_unmatched_kindle_highlights(
    authenticated_client, app
):
    state_path = Path(app.instance_path) / "knowledge" / "kindle_clippings_sync.json"
    state_path.unlink(missing_ok=True)
    with app.app_context():
        book = Book(
            title="Matched Book",
            normalized_title="matched book",
            authors=["Known Author"],
            metadata_status="verified",
        )
        db.session.add(book)
        db.session.commit()
        KindleClippingsStateStore(state_path).queue_raw(
            """Matched Book (Known Author)
- Your Highlight on page 12 | Location 144-145 | Added on Monday, July 20, 2026 9:15:00 PM

A matched passage.
==========
Unknown Kindle Book (Mystery Author)
- Your Highlight on page 22 | Location 244-245 | Added on Monday, July 20, 2026 9:16:00 PM

An unmatched passage.
==========
Unknown Bookmark (Mystery Author)
- Your Bookmark on page 30 | Location 300 | Added on Monday, July 20, 2026 9:17:00 PM
=========="""
        )
        summary = {
            item["label"]: item["value"]
            for item in KnowledgeDiagnosticsService.snapshot()["summary"]
        }
        review = KnowledgeDiagnosticsService.snapshot()["review"]

    response = authenticated_client.get("/settings/knowledge/diagnostics")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert summary["Unmatched highlights"] == 1
    assert review["kindle_pending"] == 3
    assert review["kindle_matched"] == 1
    assert review["unmatched_highlights"] == 1
    assert review["kindle_needs_review"] == 2
    assert "Unmatched highlights" in html
    assert "local Kindle outbox" in html
    assert "Kindle outbox" in html
    assert "3 pending" in html
    assert "Unknown Kindle Book" in html
    assert "Missing book relation" in html
    assert "/settings/knowledge/kindle-clippings?state=review" in html


def test_knowledge_diagnostics_reports_latest_kindle_outbox_error(authenticated_client, app):
    state_path = Path(app.instance_path) / "knowledge" / "kindle_clippings_sync.json"
    state_path.unlink(missing_ok=True)
    with app.app_context():
        store = KindleClippingsStateStore(state_path)
        queued = store.queue_raw(
            """Failed Book (Known Author)
- Your Highlight on Location 55 | Added on Monday, July 20, 2026 10:15:00 PM

Failed sync payload.
=========="""
        )
        failed_item = queued.queued[0]
        store.save(
            {
                "synced_hashes": [],
                "pending": [
                    {
                        "unique_hash": failed_item.unique_hash,
                        "payload": failed_item.payload,
                        "attempts": 2,
                        "last_error": "Notion request timed out",
                        "last_error_at": "2026-07-21T09:10:00Z",
                    }
                ],
            }
        )
        summary = {
            item["label"]: item["value"]
            for item in KnowledgeDiagnosticsService.snapshot()["summary"]
        }
        review = KnowledgeDiagnosticsService.snapshot()["review"]

    response = authenticated_client.get("/settings/knowledge/diagnostics")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert summary["Last error"] == "Notion request timed out"
    assert review["kindle_failed"] == 1
    assert "Last error" in html
    assert "Notion request timed out" in html
    assert "local Kindle outbox" in html
    assert "2026-07-21T09:10:00Z" in html
    assert "/settings/knowledge/kindle-clippings?state=failed" in html


def test_books_index_links_to_knowledge_diagnostics(authenticated_client, app):
    seed_diagnostics(app)

    response = authenticated_client.get("/books")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Diagnostics" in html
    assert "/settings/knowledge/diagnostics" in html
    assert "Browse the library by maintenance lane" not in html


def test_knowledge_diagnostics_hosts_library_maintenance_lanes(authenticated_client, app):
    seed_diagnostics(app)

    response = authenticated_client.get("/settings/knowledge/diagnostics")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Browse cleanup lanes from diagnostics" in html
    assert "Metadata" in html
    assert "Formats" in html
    assert "Signals" in html
    assert "/books/metadata/inbox" in html
    assert "/books/formats/kfx" in html
    assert "/books/signals/highlights" in html


def test_book_quotes_refresh_surfaces_matched_highlights_on_book_detail(
    authenticated_client, app, monkeypatch
):
    def notion_text(value: str) -> list[dict]:
        return [{"type": "text", "text": {"content": value}, "plain_text": value}]

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class FakeSession:
        def request(self, method, url, timeout=None, headers=None, **kwargs):
            if method == "GET" and url.endswith("/data_sources/bookquotessource"):
                return FakeResponse(
                    200,
                    {
                        "properties": {
                            "Name": {"type": "title"},
                            "Book Title": {"type": "rich_text"},
                            "Author": {"type": "rich_text"},
                            "Dragon Book ID": {"type": "rich_text"},
                            "Location": {"type": "rich_text"},
                            "Page": {"type": "number"},
                            "Created At": {"type": "date"},
                            "Source": {"type": "rich_text"},
                            "Kind": {"type": "rich_text"},
                        }
                    },
                )
            if method == "POST" and url.endswith("/data_sources/bookquotessource/query"):
                return FakeResponse(
                    200,
                    {
                        "results": [
                            {
                                "id": "quote-page-1",
                                "url": "https://notion.example.test/quote-page-1",
                                "last_edited_time": "2026-07-21T12:55:00Z",
                                "properties": {
                                    "Name": {
                                        "type": "title",
                                        "title": notion_text(
                                            "Pain and suffering are always inevitable."
                                        ),
                                    },
                                    "Book Title": {
                                        "type": "rich_text",
                                        "rich_text": notion_text("Book Quotes Match"),
                                    },
                                    "Author": {
                                        "type": "rich_text",
                                        "rich_text": notion_text("Known Author"),
                                    },
                                    "Dragon Book ID": {
                                        "type": "rich_text",
                                        "rich_text": notion_text(dragon_book_id),
                                    },
                                    "Location": {
                                        "type": "rich_text",
                                        "rich_text": notion_text("620-621"),
                                    },
                                    "Page": {"type": "number", "number": 41},
                                    "Created At": {
                                        "type": "date",
                                        "date": {"start": "2026-07-20T21:15:00Z"},
                                    },
                                    "Source": {
                                        "type": "rich_text",
                                        "rich_text": notion_text("Kindle"),
                                    },
                                    "Kind": {
                                        "type": "rich_text",
                                        "rich_text": notion_text("highlight"),
                                    },
                                },
                            }
                        ],
                        "has_more": False,
                        "next_cursor": None,
                    },
                )
            raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr("app.books.kindle_sync.requests.Session", lambda: FakeSession())
    monkeypatch.setattr("app.books.book_quotes.utc_iso", lambda value=None: "2026-07-21T13:00:00Z")

    with app.app_context():
        book = Book(
            title="Book Quotes Match",
            normalized_title="book quotes match",
            authors=["Known Author"],
            metadata_status="verified",
        )
        db.session.add(book)
        db.session.commit()
        book_id = book.id
        dragon_book_id = book.dragon_book_id

    token_path = Path(app.instance_path) / "secrets" / "kindle_book_quotes_token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text("secret-token-value", encoding="utf-8")
    metadata_path = Path(app.instance_path) / "knowledge" / "kindle_sync_credentials.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        """
        {
          "destination": {
            "label": "Book Quotes",
            "kind": "data_source",
            "data_source_id": "bookquotessource"
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    snapshot_path = Path(app.instance_path) / "knowledge" / "book_quotes_snapshot.json"
    snapshot_path.unlink(missing_ok=True)

    page = authenticated_client.get("/settings/knowledge/diagnostics")
    response = authenticated_client.post(
        "/settings/knowledge/book-quotes/refresh",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert response.status_code == 200
    assert "Refreshed 1 Book Quotes row into the local snapshot." in html
    assert "Matched 1 refreshed highlight to local books." in html
    assert snapshot["refreshed_at"] == "2026-07-21T13:00:00Z"
    assert snapshot["last_error"] == ""
    assert len(snapshot["items"]) == 1
    assert "secret-token-value" not in snapshot_path.read_text(encoding="utf-8")

    detail = authenticated_client.get(f"/books/{book_id}")
    detail_html = detail.get_data(as_text=True)

    assert detail.status_code == 200
    assert "Highlights" in detail_html
    assert "Pain and suffering are always inevitable." in detail_html
    assert "Location 620-621" in detail_html
    assert "Page 41" in detail_html
    assert "Refreshed 2026-07-21T13:00:00Z" in detail_html


def test_book_quotes_refresh_reports_unmatched_rows_in_diagnostics(
    authenticated_client, app, monkeypatch
):
    def notion_text(value: str) -> list[dict]:
        return [{"type": "text", "text": {"content": value}, "plain_text": value}]

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class FakeSession:
        def request(self, method, url, timeout=None, headers=None, **kwargs):
            if method == "GET" and url.endswith("/data_sources/bookquotessource"):
                return FakeResponse(
                    200,
                    {
                        "properties": {
                            "Name": {"type": "title"},
                            "Book Title": {"type": "rich_text"},
                            "Author": {"type": "rich_text"},
                        }
                    },
                )
            if method == "POST" and url.endswith("/data_sources/bookquotessource/query"):
                return FakeResponse(
                    200,
                    {
                        "results": [
                            {
                                "id": "quote-page-2",
                                "url": "https://notion.example.test/quote-page-2",
                                "last_edited_time": "2026-07-21T12:58:00Z",
                                "properties": {
                                    "Name": {
                                        "type": "title",
                                        "title": notion_text("An unmatched synced highlight."),
                                    },
                                    "Book Title": {
                                        "type": "rich_text",
                                        "rich_text": notion_text("Unknown Synced Book"),
                                    },
                                    "Author": {
                                        "type": "rich_text",
                                        "rich_text": notion_text("Mystery Author"),
                                    },
                                },
                            }
                        ],
                        "has_more": False,
                        "next_cursor": None,
                    },
                )
            raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr("app.books.kindle_sync.requests.Session", lambda: FakeSession())
    monkeypatch.setattr("app.books.book_quotes.utc_iso", lambda value=None: "2026-07-21T13:05:00Z")

    token_path = Path(app.instance_path) / "secrets" / "kindle_book_quotes_token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text("secret-token-value", encoding="utf-8")
    metadata_path = Path(app.instance_path) / "knowledge" / "kindle_sync_credentials.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        """
        {
          "destination": {
            "label": "Book Quotes",
            "kind": "data_source",
            "data_source_id": "bookquotessource"
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    snapshot_path = Path(app.instance_path) / "knowledge" / "book_quotes_snapshot.json"
    snapshot_path.unlink(missing_ok=True)

    page = authenticated_client.get("/settings/knowledge/diagnostics")
    refreshed = authenticated_client.post(
        "/settings/knowledge/book-quotes/refresh",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )
    html = refreshed.get_data(as_text=True)

    assert refreshed.status_code == 200
    assert "1 refreshed highlight still need local review." in html

    diagnostics = authenticated_client.get("/settings/knowledge/diagnostics")
    diagnostics_html = diagnostics.get_data(as_text=True)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert diagnostics.status_code == 200
    assert "Last Book Quotes refresh" in diagnostics_html
    assert "Book Quotes review" in diagnostics_html
    assert "Unknown Synced Book" in diagnostics_html
    assert "Missing book relation" in diagnostics_html
    assert snapshot["refreshed_at"] == "2026-07-21T13:05:00Z"


def test_kindle_clippings_outbox_queues_pasted_export(authenticated_client, app):
    state_path = Path(app.instance_path) / "knowledge" / "kindle_clippings_sync.json"
    state_path.unlink(missing_ok=True)
    with app.app_context():
        book = Book(
            title="Example Book",
            normalized_title="example book",
            authors=["Example Author"],
            metadata_status="verified",
        )
        db.session.add(book)
        db.session.commit()
        book_id = book.id
    page = authenticated_client.get("/settings/knowledge/kindle-clippings")
    html = page.get_data(as_text=True)

    assert page.status_code == 200
    assert "Kindle clippings outbox" in html
    assert "Local queue only" in html
    assert "Move between matched rows, review work, and failures" in html

    raw_text = """Example Book (Example Author)
- Your Highlight on page 12 | Location 144-145 | Added on Monday, July 20, 2026 9:15:00 PM

A passage worth keeping.
==========
Example Book (Example Author)
- Your Note on page 14 | Location 188 | Added on Monday, July 20, 2026 9:18:00 PM

A note for later.
=========="""
    response = authenticated_client.post(
        "/settings/knowledge/kindle-clippings/queue",
        data={"csrf_token": csrf_from(page), "raw_text": raw_text},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert response.status_code == 200
    assert "Queued 2 Kindle clippings." in html
    assert (
        "Parse Kindle exports, triage the local queue, then sync only when the "
        "review state is clean" in html
    )
    assert "A passage worth keeping." in html
    assert "Matched" in html
    assert f"/books/{book_id}" in html
    assert len(payload["pending"]) == 2
    assert payload["pending"][0]["payload"]["source"] == "Kindle"
    assert payload["pending"][0]["payload"]["book_title"] == "Example Book"
    assert "local_path" not in state_path.read_text(encoding="utf-8")

    duplicate = authenticated_client.post(
        "/settings/knowledge/kindle-clippings/queue",
        data={"csrf_token": csrf_from(response), "raw_text": raw_text},
        follow_redirects=True,
    )
    duplicate_payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert "No new Kindle clippings queued." in duplicate.get_data(as_text=True)
    assert len(duplicate_payload["pending"]) == 2


def test_kindle_clippings_settings_show_missing_sync_readiness(authenticated_client, app):
    token_path = Path(app.instance_path) / "secrets" / "kindle_book_quotes_token"
    metadata_path = (
        Path(app.instance_path) / "knowledge" / "kindle_sync_credentials.json"
    )
    token_path.unlink(missing_ok=True)
    metadata_path.unlink(missing_ok=True)

    response = authenticated_client.get("/settings/knowledge/kindle-clippings")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Sync readiness" in html
    assert "Not configured" in html
    assert "No local Kindle sync credentials are configured." in html
    assert "Destination locked to Book Quotes" in html
    assert "Book Quotes target missing" in html
    assert "Validation not run yet" in html
    assert "No background sync" in html


def test_kindle_clippings_settings_can_clear_local_sync_credentials(
    authenticated_client, app
):
    token_path = Path(app.instance_path) / "secrets" / "kindle_book_quotes_token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text("secret-token-value", encoding="utf-8")
    metadata_path = (
        Path(app.instance_path) / "knowledge" / "kindle_sync_credentials.json"
    )
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        """
        {
          "destination": {
            "label": "Book Quotes",
            "kind": "data_source",
            "data_source_id": "book-quotes-source"
          },
          "validated_at": "2026-07-21T09:10:00Z"
        }
        """.strip(),
        encoding="utf-8",
    )

    page = authenticated_client.get("/settings/knowledge/kindle-clippings?state=failed")
    response = authenticated_client.post(
        "/settings/knowledge/kindle-clippings/clear-credentials",
        data={"csrf_token": csrf_from(page), "state": "failed"},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Cleared local Kindle sync credentials." in html
    assert "No local Kindle sync credentials are configured." in html
    assert "state=failed" in html
    assert token_path.exists() is False
    assert metadata_path.exists() is False


def test_kindle_clippings_settings_can_validate_local_sync_credentials(
    authenticated_client, app, monkeypatch
):
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "id": "book-quotes-source",
                "title": [{"plain_text": "Book Quotes"}],
                "parent": {"database_id": "book-quotes-db"},
            }

    class FakeSession:
        def __init__(self):
            self.calls = []

        def request(self, method, url, timeout=None, headers=None):
            self.calls.append((method, url, timeout, headers or {}))
            return FakeResponse()

    sessions = []

    def build_session():
        session = FakeSession()
        sessions.append(session)
        return session

    monkeypatch.setattr("app.books.kindle_sync.requests.Session", build_session)
    monkeypatch.setattr("app.books.kindle_sync.utc_iso", lambda value=None: "2026-07-21T11:15:00Z")

    token_path = Path(app.instance_path) / "secrets" / "kindle_book_quotes_token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text("secret-token-value", encoding="utf-8")
    metadata_path = (
        Path(app.instance_path) / "knowledge" / "kindle_sync_credentials.json"
    )
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        """
        {
          "destination": {
            "label": "Book Quotes",
            "kind": "data_source",
            "data_source_id": "book-quotes-source"
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    page = authenticated_client.get("/settings/knowledge/kindle-clippings?state=matched")
    response = authenticated_client.post(
        "/settings/knowledge/kindle-clippings/validate-credentials",
        data={"csrf_token": csrf_from(page), "state": "matched"},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert response.status_code == 200
    assert "Validated local Kindle sync credentials against Book Quotes." in html
    assert "Validated" in html
    assert "Validated on 2026-07-21T11:15:00Z" in html
    assert "state=matched" in html
    assert payload["validated_at"] == "2026-07-21T11:15:00Z"
    assert payload["last_validation_error"] == ""
    assert sessions
    assert sessions[0].calls[0][1].endswith("/data_sources/bookquotessource")


def test_kindle_clippings_settings_surface_validation_failure(
    authenticated_client, app, monkeypatch
):
    class FakeResponse:
        status_code = 403

        @staticmethod
        def json():
            return {"message": "Forbidden"}

    class FakeSession:
        @staticmethod
        def request(method, url, timeout=None, headers=None):
            return FakeResponse()

    monkeypatch.setattr("app.books.kindle_sync.requests.Session", lambda: FakeSession())
    monkeypatch.setattr("app.books.kindle_sync.utc_iso", lambda value=None: "2026-07-21T11:20:00Z")

    token_path = Path(app.instance_path) / "secrets" / "kindle_book_quotes_token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text("secret-token-value", encoding="utf-8")
    metadata_path = (
        Path(app.instance_path) / "knowledge" / "kindle_sync_credentials.json"
    )
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        """
        {
          "destination": {
            "label": "Book Quotes",
            "kind": "data_source",
            "data_source_id": "book-quotes-source"
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    page = authenticated_client.get("/settings/knowledge/kindle-clippings?state=failed")
    response = authenticated_client.post(
        "/settings/knowledge/kindle-clippings/validate-credentials",
        data={"csrf_token": csrf_from(page), "state": "failed"},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert response.status_code == 200
    assert "Forbidden" in html
    assert "Last validation failed" in html
    assert "Checked 2026-07-21T11:20:00Z." in html
    assert "state=failed" in html
    assert payload["validated_at"] == ""
    assert payload["last_checked_at"] == "2026-07-21T11:20:00Z"
    assert payload["last_validation_error"] == "Forbidden"


def test_kindle_clippings_settings_can_sync_pending_to_book_quotes(
    authenticated_client, app, monkeypatch
):
    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self):
            self.calls = []

        def request(self, method, url, timeout=None, headers=None, **kwargs):
            self.calls.append((method, url, kwargs.get("json")))
            if method == "GET" and url.endswith("/data_sources/bookquotessource"):
                return FakeResponse(
                    200,
                    {
                        "properties": {
                            "Name": {"type": "title"},
                            "Unique Hash": {"type": "rich_text"},
                            "Book Title": {"type": "rich_text"},
                            "Author": {"type": "rich_text"},
                            "Source": {"type": "rich_text"},
                        }
                    },
                )
            if method == "POST" and url.endswith("/data_sources/bookquotessource/query"):
                unique_hash = kwargs["json"]["filter"]["rich_text"]["equals"]
                if unique_hash.endswith("existing"):
                    return FakeResponse(200, {"results": [{"id": "existing-page"}]})
                return FakeResponse(200, {"results": []})
            if method == "POST" and url.endswith("/pages"):
                return FakeResponse(200, {"id": "created-page"})
            raise AssertionError(f"Unexpected request: {method} {url}")

    sessions = []

    def build_session():
        session = FakeSession()
        sessions.append(session)
        return session

    monkeypatch.setattr("app.books.kindle_sync.requests.Session", build_session)
    monkeypatch.setattr("app.books.kindle_sync.utc_iso", lambda value=None: "2026-07-21T12:30:00Z")

    token_path = Path(app.instance_path) / "secrets" / "kindle_book_quotes_token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text("secret-token-value", encoding="utf-8")
    metadata_path = (
        Path(app.instance_path) / "knowledge" / "kindle_sync_credentials.json"
    )
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        """
        {
          "destination": {
            "label": "Book Quotes",
            "kind": "data_source",
            "data_source_id": "bookquotessource"
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    state_path = Path(app.instance_path) / "knowledge" / "kindle_clippings_sync.json"
    state_path.unlink(missing_ok=True)
    page = authenticated_client.get("/settings/knowledge/kindle-clippings")
    queued = authenticated_client.post(
        "/settings/knowledge/kindle-clippings/queue",
        data={
            "csrf_token": csrf_from(page),
            "raw_text": """Sync First (Author A)
- Your Highlight on Location 12 | Added on Monday, July 20, 2026 9:15:00 PM

First sync payload.
==========
Sync Existing (Author B)
- Your Highlight on Location 44 | Added on Monday, July 20, 2026 9:18:00 PM

Second sync payload.
==========""",
        },
        follow_redirects=True,
    )
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["pending"][1]["unique_hash"] = f"{payload['pending'][1]['unique_hash']}-existing"
    state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    response = authenticated_client.post(
        "/settings/knowledge/kindle-clippings/sync",
        data={"csrf_token": csrf_from(queued), "state": "all"},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert response.status_code == 200
    assert "Uploaded 1 Kindle clipping to Book Quotes." in html
    assert "Skipped 1 Kindle clipping already in Book Quotes." in html
    assert "No pending clippings." in html
    assert payload["pending"] == []
    assert len(payload["synced_hashes"]) == 2
    assert sessions
    assert any(call[1].endswith("/pages") for call in sessions[0].calls)


def test_kindle_clippings_settings_keep_failed_items_after_manual_sync_error(
    authenticated_client, app, monkeypatch
):
    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class FakeSession:
        def request(self, method, url, timeout=None, headers=None, **kwargs):
            if method == "GET" and url.endswith("/data_sources/bookquotessource"):
                return FakeResponse(
                    200,
                    {
                        "properties": {
                            "Name": {"type": "title"},
                            "Unique Hash": {"type": "rich_text"},
                        }
                    },
                )
            if method == "POST" and url.endswith("/data_sources/bookquotessource/query"):
                return FakeResponse(200, {"results": []})
            if method == "POST" and url.endswith("/pages"):
                return FakeResponse(503, {"message": "Service unavailable"})
            raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr("app.books.kindle_sync.requests.Session", lambda: FakeSession())
    monkeypatch.setattr("app.books.kindle_sync.utc_iso", lambda value=None: "2026-07-21T12:35:00Z")

    token_path = Path(app.instance_path) / "secrets" / "kindle_book_quotes_token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text("secret-token-value", encoding="utf-8")
    metadata_path = (
        Path(app.instance_path) / "knowledge" / "kindle_sync_credentials.json"
    )
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        """
        {
          "destination": {
            "label": "Book Quotes",
            "kind": "data_source",
            "data_source_id": "bookquotessource"
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    state_path = Path(app.instance_path) / "knowledge" / "kindle_clippings_sync.json"
    state_path.unlink(missing_ok=True)
    page = authenticated_client.get("/settings/knowledge/kindle-clippings")
    queued = authenticated_client.post(
        "/settings/knowledge/kindle-clippings/queue",
        data={
            "csrf_token": csrf_from(page),
            "raw_text": """Retry Sync (Author A)
- Your Highlight on Location 12 | Added on Monday, July 20, 2026 9:15:00 PM

Retry sync payload.
==========""",
        },
        follow_redirects=True,
    )

    response = authenticated_client.post(
        "/settings/knowledge/kindle-clippings/sync",
        data={"csrf_token": csrf_from(queued), "state": "all"},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert response.status_code == 200
    assert "1 Kindle clipping stayed in the local outbox for retry." in html
    assert payload["synced_hashes"] == []
    assert payload["pending"][0]["attempts"] == 1
    assert payload["pending"][0]["last_error"] == "Service unavailable"


def test_kindle_clippings_outbox_can_save_manual_book_match(authenticated_client, app):
    state_path = Path(app.instance_path) / "knowledge" / "kindle_clippings_sync.json"
    state_path.unlink(missing_ok=True)
    with app.app_context():
        book = Book(
            title="Canonical Local Book",
            normalized_title="canonical local book",
            authors=["Known Author"],
            metadata_status="verified",
        )
        db.session.add(book)
        db.session.commit()
        book_id = book.id
        dragon_book_id = book.dragon_book_id

    page = authenticated_client.get("/settings/knowledge/kindle-clippings")
    raw_text = """Odd Kindle Store Title (Unknown Author)
- Your Highlight on Location 77 | Added on Monday, July 20, 2026 9:15:00 PM

A passage that needs a manual relation.
=========="""
    queued = authenticated_client.post(
        "/settings/knowledge/kindle-clippings/queue",
        data={"csrf_token": csrf_from(page), "raw_text": raw_text},
        follow_redirects=True,
    )
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    unique_hash = payload["pending"][0]["unique_hash"]

    response = authenticated_client.post(
        f"/settings/knowledge/kindle-clippings/{unique_hash}/assign-book",
        data={"csrf_token": csrf_from(queued), "book_id": book_id},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    pending_payload = payload["pending"][0]["payload"]

    assert response.status_code == 200
    assert "Kindle clipping match saved locally." in html
    assert "Matched by manual local review" in html
    assert f"/books/{book_id}" in html
    assert pending_payload["book_id"] == book_id
    assert pending_payload["dragon_book_id"] == dragon_book_id
    assert pending_payload["match_source"] == "manual_local_review"
    assert payload["synced_hashes"] == []


def test_kindle_clippings_outbox_can_remove_pending_item(authenticated_client, app):
    state_path = Path(app.instance_path) / "knowledge" / "kindle_clippings_sync.json"
    state_path.unlink(missing_ok=True)
    page = authenticated_client.get("/settings/knowledge/kindle-clippings")
    queued = authenticated_client.post(
        "/settings/knowledge/kindle-clippings/queue",
        data={
            "csrf_token": csrf_from(page),
            "raw_text": """Remove This (Unknown Author)
- Your Highlight on Location 77 | Added on Monday, July 20, 2026 9:15:00 PM

Dismiss me locally.
==========""",
            "state": "failed",
        },
        follow_redirects=True,
    )
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    unique_hash = payload["pending"][0]["unique_hash"]

    response = authenticated_client.post(
        f"/settings/knowledge/kindle-clippings/{unique_hash}/remove",
        data={"csrf_token": csrf_from(queued), "state": "failed"},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert response.status_code == 200
    assert "Kindle clipping removed from the local outbox." in html
    assert "No pending clippings." in html
    assert "state=failed" in html
    assert payload["pending"] == []
    assert payload["synced_hashes"] == []


def test_kindle_clippings_outbox_shows_retry_failures(authenticated_client, app):
    state_path = Path(app.instance_path) / "knowledge" / "kindle_clippings_sync.json"
    state_path.unlink(missing_ok=True)
    with app.app_context():
        store = KindleClippingsStateStore(state_path)
        queued = store.queue_raw(
            """Retry Book (Known Author)
- Your Highlight on Location 55 | Added on Monday, July 20, 2026 10:15:00 PM

Failed sync payload.
=========="""
        )
        failed_item = queued.queued[0]
        store.save(
            {
                "synced_hashes": [],
                "pending": [
                    {
                        "unique_hash": failed_item.unique_hash,
                        "payload": failed_item.payload,
                        "attempts": 2,
                        "last_error": "Notion request timed out",
                        "last_error_at": "2026-07-21T09:10:00Z",
                    }
                ],
            }
        )

    response = authenticated_client.get("/settings/knowledge/kindle-clippings")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "1 failed" in html
    assert "Failures" in html
    assert "Notion request timed out" in html
    assert "2026-07-21T09:10:00Z" in html
    assert "2 retries" in html


def test_kindle_clippings_outbox_filters_review_matched_and_failed(authenticated_client, app):
    state_path = Path(app.instance_path) / "knowledge" / "kindle_clippings_sync.json"
    state_path.unlink(missing_ok=True)
    with app.app_context():
        matched = Book(
            title="Matched Filter Book",
            normalized_title="matched filter book",
            authors=["Known Author"],
            metadata_status="verified",
        )
        db.session.add(matched)
        db.session.commit()
        store = KindleClippingsStateStore(state_path)
        queued = store.queue_raw(
            """Matched Filter Book (Known Author)
- Your Highlight on Location 55 | Added on Monday, July 20, 2026 10:15:00 PM

Matched payload.
==========
Review Filter Book (Unknown Author)
- Your Highlight on Location 77 | Added on Monday, July 20, 2026 10:16:00 PM

Needs local review.
==========
Failed Filter Book (Unknown Author)
- Your Highlight on Location 88 | Added on Monday, July 20, 2026 10:17:00 PM

Failed local sync.
=========="""
        )
        matched_item, review_item, failed_item = queued.queued
        store.save(
            {
                "synced_hashes": [],
                "pending": [
                    matched_item.as_dict(),
                    review_item.as_dict(),
                    {
                        "unique_hash": failed_item.unique_hash,
                        "payload": failed_item.payload,
                        "attempts": 1,
                        "last_error": "Wi-Fi offline",
                        "last_error_at": "2026-07-21T10:00:00Z",
                    },
                ],
            }
        )

    review_response = authenticated_client.get("/settings/knowledge/kindle-clippings?state=review")
    review_html = review_response.get_data(as_text=True)
    matched_response = authenticated_client.get(
        "/settings/knowledge/kindle-clippings?state=matched"
    )
    matched_html = matched_response.get_data(as_text=True)
    failed_response = authenticated_client.get("/settings/knowledge/kindle-clippings?state=failed")
    failed_html = failed_response.get_data(as_text=True)

    assert review_response.status_code == 200
    assert "Review Filter Book" in review_html
    assert "Failed Filter Book" in review_html
    assert "Matched payload." not in review_html
    assert "2 shown" in review_html
    assert "Review · 2" in review_html
    assert "state=review" in review_html

    assert matched_response.status_code == 200
    assert "Matched Filter Book" in matched_html
    assert "Needs local review." not in matched_html
    assert "Failed local sync." not in matched_html
    assert "1 shown" in matched_html

    assert failed_response.status_code == 200
    assert "Failed Filter Book" in failed_html
    assert "Wi-Fi offline" in failed_html
    assert "Matched payload." not in failed_html
    assert "Needs local review." not in failed_html
    assert "1 shown" in failed_html


def test_kindle_clippings_outbox_can_bulk_clear_matched_filter(authenticated_client, app):
    state_path = Path(app.instance_path) / "knowledge" / "kindle_clippings_sync.json"
    state_path.unlink(missing_ok=True)
    with app.app_context():
        matched = Book(
            title="Bulk Matched Book",
            normalized_title="bulk matched book",
            authors=["Known Author"],
            metadata_status="verified",
        )
        db.session.add(matched)
        db.session.commit()
        store = KindleClippingsStateStore(state_path)
        queued = store.queue_raw(
            """Bulk Matched Book (Known Author)
- Your Highlight on Location 55 | Added on Monday, July 20, 2026 10:15:00 PM

Matched payload.
==========
Bulk Review Book (Unknown Author)
- Your Highlight on Location 77 | Added on Monday, July 20, 2026 10:16:00 PM

Needs local review.
==========
Bulk Failed Book (Unknown Author)
- Your Highlight on Location 88 | Added on Monday, July 20, 2026 10:17:00 PM

Failed local sync.
=========="""
        )
        matched_item, review_item, failed_item = queued.queued
        store.save(
            {
                "synced_hashes": [],
                "pending": [
                    matched_item.as_dict(),
                    review_item.as_dict(),
                    {
                        "unique_hash": failed_item.unique_hash,
                        "payload": failed_item.payload,
                        "attempts": 1,
                        "last_error": "Wi-Fi offline",
                        "last_error_at": "2026-07-21T10:00:00Z",
                    },
                ],
            }
        )

    page = authenticated_client.get("/settings/knowledge/kindle-clippings?state=matched")
    response = authenticated_client.post(
        "/settings/knowledge/kindle-clippings/clear",
        data={"csrf_token": csrf_from(page), "state": "matched"},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert response.status_code == 200
    assert "Cleared 1 matched Kindle clipping from the local outbox." in html
    assert "No clippings in this filter." in html
    assert "state=matched" in html
    assert len(payload["pending"]) == 2
    assert payload["pending"][0]["payload"]["book_title"] == "Bulk Review Book"
    assert payload["pending"][1]["payload"]["book_title"] == "Bulk Failed Book"


def test_kindle_clippings_outbox_bulk_clear_rejects_review_filter(authenticated_client, app):
    state_path = Path(app.instance_path) / "knowledge" / "kindle_clippings_sync.json"
    state_path.unlink(missing_ok=True)
    page = authenticated_client.get("/settings/knowledge/kindle-clippings")
    queued = authenticated_client.post(
        "/settings/knowledge/kindle-clippings/queue",
        data={
            "csrf_token": csrf_from(page),
            "raw_text": """Review Queue Book (Unknown Author)
- Your Highlight on Location 77 | Added on Monday, July 20, 2026 9:15:00 PM

Keep me for review.
==========""",
            "state": "review",
        },
        follow_redirects=True,
    )

    response = authenticated_client.post(
        "/settings/knowledge/kindle-clippings/clear",
        data={"csrf_token": csrf_from(queued), "state": "review"},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert response.status_code == 200
    assert "Bulk clear is only available for matched or failed outbox filters." in html
    assert "Review Queue Book" in html
    assert len(payload["pending"]) == 1


def test_kindle_clippings_outbox_can_reset_failed_filter(authenticated_client, app):
    state_path = Path(app.instance_path) / "knowledge" / "kindle_clippings_sync.json"
    state_path.unlink(missing_ok=True)
    with app.app_context():
        matched = Book(
            title="Reset Matched Book",
            normalized_title="reset matched book",
            authors=["Known Author"],
            metadata_status="verified",
        )
        db.session.add(matched)
        db.session.commit()
        store = KindleClippingsStateStore(state_path)
        queued = store.queue_raw(
            """Reset Failed Book (Unknown Author)
- Your Highlight on Location 88 | Added on Monday, July 20, 2026 10:17:00 PM

Failed local sync.
==========
Reset Matched Book (Known Author)
- Your Highlight on Location 55 | Added on Monday, July 20, 2026 10:15:00 PM

Matched payload.
=========="""
        )
        failed_item, matched_item = queued.queued
        store.save(
            {
                "synced_hashes": [],
                "pending": [
                    {
                        "unique_hash": failed_item.unique_hash,
                        "payload": failed_item.payload,
                        "attempts": 2,
                        "last_error": "Notion request timed out",
                        "last_error_at": "2026-07-21T09:10:00Z",
                    },
                    matched_item.as_dict(),
                ],
            }
        )

    page = authenticated_client.get("/settings/knowledge/kindle-clippings?state=failed")
    response = authenticated_client.post(
        "/settings/knowledge/kindle-clippings/reset-failures",
        data={"csrf_token": csrf_from(page), "state": "failed"},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert response.status_code == 200
    assert "Reset 1 failed Kindle clipping for a future retry." in html
    assert "No clippings in this filter." in html
    assert "state=failed" in html
    assert payload["pending"][0]["attempts"] == 2
    assert payload["pending"][0]["last_error"] == ""
    assert payload["pending"][0]["last_error_at"] == ""
    assert payload["pending"][1]["payload"]["book_title"] == "Reset Matched Book"


def test_kindle_clippings_outbox_failure_reset_rejects_matched_filter(authenticated_client, app):
    state_path = Path(app.instance_path) / "knowledge" / "kindle_clippings_sync.json"
    state_path.unlink(missing_ok=True)
    with app.app_context():
        matched = Book(
            title="Reject Reset Book",
            normalized_title="reject reset book",
            authors=["Known Author"],
            metadata_status="verified",
        )
        db.session.add(matched)
        db.session.commit()
        KindleClippingsStateStore(state_path).queue_raw(
            """Reject Reset Book (Known Author)
- Your Highlight on Location 55 | Added on Monday, July 20, 2026 10:15:00 PM

Matched payload.
=========="""
        )

    page = authenticated_client.get("/settings/knowledge/kindle-clippings?state=matched")
    response = authenticated_client.post(
        "/settings/knowledge/kindle-clippings/reset-failures",
        data={"csrf_token": csrf_from(page), "state": "matched"},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    payload = json.loads(state_path.read_text(encoding="utf-8"))

    assert response.status_code == 200
    assert "Failure reset is only available for failed outbox filters." in html
    assert "Reject Reset Book" in html
    assert len(payload["pending"]) == 1


def test_book_quotes_review_page_can_save_manual_local_match(authenticated_client, app):
    snapshot_path = Path(app.instance_path) / "knowledge" / "book_quotes_snapshot.json"
    snapshot_path.unlink(missing_ok=True)
    with app.app_context():
        book = Book(
            title="Canonical Review Book",
            normalized_title="canonical review book",
            authors=["Known Author"],
            metadata_status="verified",
        )
        db.session.add(book)
        db.session.commit()
        book_id = book.id
        dragon_book_id = book.dragon_book_id
        BookQuotesSnapshotStore(snapshot_path).save(
            {
                "refreshed_at": "2026-07-21T13:20:00Z",
                "last_checked_at": "2026-07-21T13:20:00Z",
                "last_error": "",
                "items": [
                    {
                        "notion_page_id": "quote-page-review",
                        "payload": {
                            "quote": "A synced highlight waiting for a local match.",
                            "book_title": "Odd Kindle Store Title",
                            "author": "Unknown Author",
                            "source": "Kindle",
                            "kind": "highlight",
                        },
                        "notion_url": "https://notion.example.test/quote-page-review",
                    }
                ],
            }
        )

    page = authenticated_client.get("/settings/knowledge/book-quotes")
    response = authenticated_client.post(
        "/settings/knowledge/book-quotes/quote-page-review/assign-book",
        data={
            "csrf_token": csrf_from(page),
            "book_id": book_id,
            "state": "all",
        },
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    stored = payload["items"][0]["payload"]

    assert response.status_code == 200
    assert "Book Quotes match saved locally." in html
    assert "Triage synced Book Quotes rows before they belong in the library stream" in html
    assert "Move between clean matches and review work" in html
    assert "Matched by manual local review" in html
    assert f"/books/{book_id}" in html
    assert stored["book_id"] == book_id
    assert stored["dragon_book_id"] == dragon_book_id
    assert stored["match_source"] == "manual_local_review"


def test_book_quotes_review_page_can_clear_manual_local_match(authenticated_client, app):
    snapshot_path = Path(app.instance_path) / "knowledge" / "book_quotes_snapshot.json"
    snapshot_path.unlink(missing_ok=True)
    with app.app_context():
        book = Book(
            title="Manual Match Book",
            normalized_title="manual match book",
            authors=["Known Author"],
            metadata_status="verified",
        )
        db.session.add(book)
        db.session.commit()
        BookQuotesSnapshotStore(snapshot_path).save(
            {
                "refreshed_at": "2026-07-21T13:25:00Z",
                "last_checked_at": "2026-07-21T13:25:00Z",
                "last_error": "",
                "items": [
                    {
                        "notion_page_id": "quote-page-clear",
                        "payload": {
                            "quote": "A synced highlight with a local review hint.",
                            "book_title": "Unknown Synced Book",
                            "author": "Unknown Author",
                            "book_id": book.id,
                            "dragon_book_id": book.dragon_book_id,
                            "matched_book_title": book.title,
                            "match_source": "manual_local_review",
                            "source": "Kindle",
                            "kind": "highlight",
                        },
                    }
                ],
            }
        )

    page = authenticated_client.get("/settings/knowledge/book-quotes")
    response = authenticated_client.post(
        "/settings/knowledge/book-quotes/quote-page-clear/clear-match",
        data={
            "csrf_token": csrf_from(page),
            "state": "all",
        },
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    stored = payload["items"][0]["payload"]

    assert response.status_code == 200
    assert "Book Quotes local match cleared." in html
    assert "Triage synced Book Quotes rows before they belong in the library stream" in html
    assert "Missing book relation" in html
    assert "match_source" not in stored
    assert "book_id" not in stored
    assert "dragon_book_id" not in stored


def test_book_quotes_refresh_preserves_manual_local_match_without_canonical_relation(
    authenticated_client, app, monkeypatch
):
    def notion_text(value: str) -> list[dict]:
        return [{"type": "text", "text": {"content": value}, "plain_text": value}]

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class FakeSession:
        def request(self, method, url, timeout=None, headers=None, **kwargs):
            if method == "GET" and url.endswith("/data_sources/bookquotessource"):
                return FakeResponse(
                    200,
                    {
                        "properties": {
                            "Name": {"type": "title"},
                            "Book Title": {"type": "rich_text"},
                            "Author": {"type": "rich_text"},
                        }
                    },
                )
            if method == "POST" and url.endswith("/data_sources/bookquotessource/query"):
                return FakeResponse(
                    200,
                    {
                        "results": [
                            {
                                "id": "quote-page-persist",
                                "url": "https://notion.example.test/quote-page-persist",
                                "last_edited_time": "2026-07-21T13:29:00Z",
                                "properties": {
                                    "Name": {
                                        "type": "title",
                                        "title": notion_text("Persist this local review hint."),
                                    },
                                    "Book Title": {
                                        "type": "rich_text",
                                        "rich_text": notion_text("Unclear Synced Title"),
                                    },
                                    "Author": {
                                        "type": "rich_text",
                                        "rich_text": notion_text("Unknown Author"),
                                    },
                                },
                            }
                        ],
                        "has_more": False,
                        "next_cursor": None,
                    },
                )
            raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr("app.books.kindle_sync.requests.Session", lambda: FakeSession())
    monkeypatch.setattr("app.books.book_quotes.utc_iso", lambda value=None: "2026-07-21T13:30:00Z")

    snapshot_path = Path(app.instance_path) / "knowledge" / "book_quotes_snapshot.json"
    snapshot_path.unlink(missing_ok=True)
    with app.app_context():
        book = Book(
            title="Persistent Local Match",
            normalized_title="persistent local match",
            authors=["Known Author"],
            metadata_status="verified",
        )
        db.session.add(book)
        db.session.commit()
        BookQuotesSnapshotStore(snapshot_path).save(
            {
                "refreshed_at": "2026-07-21T13:10:00Z",
                "last_checked_at": "2026-07-21T13:10:00Z",
                "last_error": "",
                "items": [
                    {
                        "notion_page_id": "quote-page-persist",
                        "payload": {
                            "quote": "Persist this local review hint.",
                            "book_title": "Unclear Synced Title",
                            "author": "Unknown Author",
                            "book_id": book.id,
                            "dragon_book_id": book.dragon_book_id,
                            "matched_book_title": book.title,
                            "match_source": "manual_local_review",
                            "source": "Kindle",
                            "kind": "highlight",
                        },
                    }
                ],
            }
        )

    token_path = Path(app.instance_path) / "secrets" / "kindle_book_quotes_token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text("secret-token-value", encoding="utf-8")
    metadata_path = Path(app.instance_path) / "knowledge" / "kindle_sync_credentials.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        """
        {
          "destination": {
            "label": "Book Quotes",
            "kind": "data_source",
            "data_source_id": "bookquotessource"
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    page = authenticated_client.get("/settings/knowledge/diagnostics")
    response = authenticated_client.post(
        "/settings/knowledge/book-quotes/refresh",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    stored = payload["items"][0]["payload"]

    assert response.status_code == 200
    assert stored["match_source"] == "manual_local_review"
    assert stored["book_id"]
    assert stored["dragon_book_id"]

    review = authenticated_client.get("/settings/knowledge/book-quotes?state=matched")
    review_html = review.get_data(as_text=True)

    assert review.status_code == 200
    assert "Persist this local review hint." in review_html
    assert "Matched by manual local review" in review_html
