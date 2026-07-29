from types import SimpleNamespace

from app.books.clippings import (
    KindleClippingsStateStore,
    KindleClippingsSyncState,
    assign_clipping_book,
    clipping_unique_hash,
    mark_clippings_failed,
    mark_clippings_uploaded,
    match_clipping_payload,
    parse_my_clippings,
    project_clippings_outbox,
    queue_my_clippings,
    remove_clipping_from_outbox,
    remove_clippings_from_outbox,
    reset_clipping_failures,
)
from app.books.kindle_sync import KindleBookQuotesClient, KindleSyncCredentialStore
from app.books.book_quotes import BookQuotesProjection, BookQuotesSnapshotItem, _highlight_payload
from app.books.clippings import KindleClippingMatch
from app.books.matching import (
    normalize_isbn,
    normalize_title,
    title_similarity,
    valid_isbn10,
    valid_isbn13,
)
from app.books.metadata import BookMetadataService
from app.books.models import AudiobookEdition, Book, BookEdition, TextAsset
from app.books.priorities import preferred_text_format, sort_text_formats, text_format_slots
from app.books.providers import MetadataCandidate
from app.books.repositories import BookRepository
from app.books.services import book_detail, book_item
from app.extensions import db


def test_text_format_priority_is_kindle_first():
    formats = ["pdf", "EPUB", "KFX", "azw3", "mobi"]

    assert sort_text_formats(formats) == ["KFX", "AZW3", "EPUB", "PDF"]
    assert preferred_text_format(formats) == "KFX"
    assert text_format_slots(["PDF", "AZW3"]) == [
        {"format": "KFX", "available": False},
        {"format": "AZW3", "available": True},
        {"format": "EPUB", "available": False},
        {"format": "PDF", "available": True},
    ]


def test_book_projection_separates_text_assets_from_audiobooks(app):
    with app.app_context():
        book = Book(
            title="Crime and Punishment",
            normalized_title="crime and punishment",
            authors=["Fyodor Dostoevsky"],
            status="reading",
            current_page=120,
            page_count=600,
            metadata_status="needs_review",
            metadata_state={"formats_available": ["pdf"]},
        )
        edition = BookEdition(
            book=book,
            title="Crime and Punishment",
            language="English",
            translator="Constance Garnett",
            publisher="Local Press",
            page_count=600,
            verification_status="likely",
            primary=True,
        )
        edition.text_assets.extend(
            [
                TextAsset(
                    format="EPUB",
                    source_type="local",
                    filename="crime-and-punishment.epub",
                    verification_status="verified",
                ),
                TextAsset(
                    format="KFX",
                    source_type="local",
                    filename="crime-and-punishment.kfx",
                    verification_status="verified",
                ),
            ]
        )
        book.audiobooks.append(
            AudiobookEdition(
                title="Crime and Punishment",
                language="English",
                narrator="Narrator A",
                abridgement_type="unabridged",
                production_type="single_narrator",
            )
        )
        db.session.add(book)
        db.session.commit()

        item = book_item(book)
        detail = book_detail(book)

        assert book.dragon_book_id.startswith("dragon-book-")
        assert item["preferred_format"] == "KFX"
        assert item["other_formats"] == ["EPUB", "PDF"]
        assert item["has_audiobook"] is True
        assert [asset["format"] for asset in detail["text_assets"]] == ["KFX", "EPUB"]
        assert detail["audiobooks"][0]["narrator"] == "Narrator A"


def test_book_projection_falls_back_to_primary_edition_fields(app):
    with app.app_context():
        book = Book(
            title="Fallback Book",
            normalized_title="fallback book",
            authors=["Example Author"],
            current_page=25,
        )
        edition = BookEdition(
            book=book,
            title="Fallback Book",
            language="English",
            translator="Edition Translator",
            publisher="Edition Publisher",
            publication_year=2024,
            page_count=320,
            isbn_13="9780140449136",
            cover_url="https://images.example.test/fallback-book.jpg",
            primary=True,
        )
        db.session.add(book)
        db.session.commit()

        item = book_item(book)
        detail = book_detail(book)

        assert item["page_count"] == 320
        assert item["cover_url"] == "https://images.example.test/fallback-book.jpg"
        assert detail["edition_language"] == "English"
        assert detail["translator"] == "Edition Translator"
        assert detail["publisher"] == "Edition Publisher"
        assert detail["published_year"] == 2024
        assert detail["isbn_13"] == "9780140449136"


def test_finished_book_always_projects_as_complete_progress(app):
    with app.app_context():
        book = Book(
            title="Finished without page metadata",
            normalized_title="finished without page metadata",
            status="finished",
            current_page=0,
            page_count=0,
        )
        db.session.add(book)
        db.session.commit()

        item = book_item(book)

        assert item["status"] == "finished"
        assert item["progress_percent"] == 100


def test_book_repository_resolves_stable_dragon_book_id(app):
    with app.app_context():
        book = Book(title="Stable Work", normalized_title="stable work")
        db.session.add(book)
        db.session.commit()
        dragon_book_id = book.dragon_book_id

        resolved = BookRepository.get(dragon_book_id)

        assert resolved is not None
        assert resolved.id == book.id


def test_book_repository_treats_wishlist_as_legacy_alias_filter(app):
    with app.app_context():
        legacy = Book(title="Legacy Wish", normalized_title="legacy wish", status="want_to_read")
        canonical = Book(title="Canonical Wish", normalized_title="canonical wish", status="wishlist")
        db.session.add_all([legacy, canonical])
        db.session.commit()

        books = BookRepository.list(status="wishlist")

        assert {book.title for book in books} == {"Legacy Wish", "Canonical Wish"}


def test_book_matching_validates_isbn_and_arabic_title_noise():
    assert normalize_isbn("978-0-14-044913-6") == "9780140449136"
    assert valid_isbn13("9780140449136") is True
    assert valid_isbn10("043942089X") is True
    assert valid_isbn13("9780140449137") is False
    assert normalize_title("تحميل كتاب الإخوة كارامازوف PDF") == "الاخوة كارامازوف"
    assert title_similarity("الإخوة كارامازوف", "الاخوة كارامازوف") == 1


def test_metadata_preview_and_apply_preserve_personal_state(app):
    class Provider:
        @staticmethod
        def lookup(*, title, authors=(), isbn="", language=""):
            assert title == "A Local Book"
            assert authors == ["Example Author"]
            return [
                MetadataCandidate(
                    source="Open Library",
                    title="A Local Book",
                    authors=["Example Author"],
                    overview="External overview.",
                    cover_url="https://covers.example.test/book.jpg",
                    subjects=["Fiction"],
                    publisher="External Publisher",
                    published_year=2020,
                    page_count=320,
                    isbn_13="9780140449136",
                    openlibrary_work_id="OL1W",
                    confidence="high",
                )
            ]

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

        proposal = BookMetadataService.preview(book, providers=[Provider()])
        assert proposal is not None
        payload = proposal.as_dict()

        assert payload["status"] == "candidate_found"
        assert payload["fill"]["description"] == "External overview."
        assert payload["fill"]["page_count"] == 320
        assert payload["fill"]["isbn_13"] == "9780140449136"
        assert payload["fill"]["openlibrary_work_id"] == "OL1W"
        assert payload["conflicts"]["publisher"] == {
            "current": "Manual Publisher",
            "candidate": "External Publisher",
        }

        BookMetadataService.apply_fill(book, proposal)

        assert book.status == "reading"
        assert book.current_page == 25
        assert book.personal_score == 4.5
        assert book.publisher == "Manual Publisher"
        assert book.description == "External overview."
        assert book.page_count == 320
        assert book.isbn_13 == "9780140449136"
        assert book.external_ids["openlibrary_work_id"] == "OL1W"
        assert book.metadata_status == "candidate_found"
        assert book.metadata_sources == ["Open Library"]


def test_metadata_queries_fall_back_to_primary_edition_identity(app):
    class Provider:
        calls: list[dict] = []

        @classmethod
        def lookup(cls, *, title, authors=(), isbn="", language=""):
            cls.calls.append(
                {
                    "title": title,
                    "authors": list(authors),
                    "isbn": isbn,
                    "language": language,
                }
            )
            return []

    with app.app_context():
        book = Book(
            title="Edition Led Book",
            normalized_title="edition led book",
            authors=["Example Author"],
        )
        book.editions.append(
            BookEdition(
                title="Edition Led Book",
                language="Arabic",
                isbn_13="9780140449136",
                primary=True,
            )
        )
        db.session.add(book)
        db.session.commit()

        assert BookMetadataService.preview(book, providers=[Provider()]) is None

        assert Provider.calls[0]["isbn"] == "9780140449136"
        assert Provider.calls[0]["language"] == "Arabic"


def test_metadata_fallback_does_not_fill_isbn_for_translation_without_language(app):
    class Provider:
        @staticmethod
        def lookup(*, title, authors=(), isbn="", language=""):
            assert isbn == ""
            assert language == "Arabic"
            return [
                MetadataCandidate(
                    source="Open Library",
                    title="Crime and Punishment",
                    authors=["Fyodor Dostoevsky"],
                    publisher="External Publisher",
                    published_year=1866,
                    page_count=520,
                    isbn_13="9780140449136",
                    confidence="high",
                )
            ]

    with app.app_context():
        book = Book(
            title="Crime and Punishment",
            normalized_title="crime and punishment",
            authors=["Fyodor Dostoevsky"],
            edition_language="Arabic",
            translator="Unknown translator",
        )
        db.session.add(book)
        db.session.commit()

        proposal = BookMetadataService.preview(book, providers=[Provider()])

        assert proposal is not None
        assert proposal.status == "needs_review"
        assert proposal.confidence == "low"
        assert proposal.fill["page_count"] == 520
        assert "isbn_13" not in proposal.fill


def test_metadata_fallback_rejects_wrong_language_candidate(app):
    class Provider:
        @staticmethod
        def lookup(*, title, authors=(), isbn="", language=""):
            return [
                MetadataCandidate(
                    source="Google Books",
                    title="Crime and Punishment",
                    authors=["Fyodor Dostoevsky"],
                    language="en",
                    isbn_13="9780140449136",
                    confidence="medium",
                )
            ]

    with app.app_context():
        book = Book(
            title="Crime and Punishment",
            normalized_title="crime and punishment",
            authors=["Fyodor Dostoevsky"],
            edition_language="Arabic",
        )
        db.session.add(book)
        db.session.commit()

        assert BookMetadataService.preview(book, providers=[Provider()]) is None


def test_kindle_my_clippings_parser_builds_book_quote_payloads():
    raw = """Crime and Punishment (Fyodor Dostoevsky)
- Your Highlight on page 41 | Location 620-621 | Added on Monday, January 1, 2024 8:15:00 PM

Pain and suffering are always inevitable for a large intelligence.
==========
كويكول (حنان لاشين)
- Your Note on Location 88 | Added on Tuesday, January 2, 2024 9:30:10 AM

ملاحظة قصيرة من كيندل
==========
Malformed entry
missing metadata
=========="""

    result = parse_my_clippings(raw)

    assert result.skipped == 1
    assert len(result.clippings) == 2
    first = result.clippings[0]
    assert first.book_title == "Crime and Punishment"
    assert first.author == "Fyodor Dostoevsky"
    assert first.kind == "highlight"
    assert first.page == "41"
    assert first.location == "620-621"
    assert first.text == "Pain and suffering are always inevitable for a large intelligence."
    assert len(first.unique_hash) == 64
    assert first.as_book_quote_payload() == {
        "quote": "Pain and suffering are always inevitable for a large intelligence.",
        "book_title": "Crime and Punishment",
        "author": "Fyodor Dostoevsky",
        "page": "41",
        "location": "620-621",
        "created_at": "Monday, January 1, 2024 8:15:00 PM",
        "source": "Kindle",
        "unique_hash": first.unique_hash,
        "kind": "highlight",
    }
    second = result.clippings[1]
    assert second.book_title == "كويكول"
    assert second.author == "حنان لاشين"
    assert second.kind == "note"
    assert second.location == "88"
    assert second.text == "ملاحظة قصيرة من كيندل"


def test_kindle_clipping_hash_uses_normalized_roadmap_ingredients():
    left = clipping_unique_hash(
        book_title="تحميل كتاب الإخوة كارامازوف PDF",
        text="  Same   Highlight  ",
        location=" Location 12 ",
        created_at=" Monday,  January 1, 2024 ",
    )
    right = clipping_unique_hash(
        book_title="الاخوة كارامازوف",
        text="same highlight",
        location="location 12",
        created_at="Monday, January 1, 2024",
    )
    changed_text = clipping_unique_hash(
        book_title="الاخوة كارامازوف",
        text="different highlight",
        location="location 12",
        created_at="Monday, January 1, 2024",
    )

    assert left == right
    assert left != changed_text


def test_kindle_clippings_outbox_skips_synced_pending_and_duplicates():
    raw = """Book A (Author A)
- Your Highlight on Location 12 | Added on Monday, January 1, 2024 8:15:00 PM

First quote.
==========
Book A (Author A)
- Your Highlight on Location 12 | Added on Monday, January 1, 2024 8:15:00 PM

First quote.
==========
Book B (Author B)
- Your Highlight on Location 99 | Added on Monday, January 1, 2024 8:20:00 PM

Second quote.
=========="""
    first = queue_my_clippings(raw)
    first_hash = first.queued[0].unique_hash
    second_hash = first.queued[1].unique_hash
    state = KindleClippingsSyncState(
        synced_hashes=frozenset({first_hash}),
        pending=(first.queued[1],),
    )

    result = queue_my_clippings(raw, state)

    assert result.parsed == 3
    assert result.skipped_duplicate == 1
    assert result.skipped_synced == 1
    assert result.skipped_pending == 1
    assert result.queued == []
    assert [item.unique_hash for item in result.state.pending] == [second_hash]


def test_kindle_clippings_sync_state_marks_uploaded_and_failed_items(monkeypatch):
    raw = """Book A (Author A)
- Your Highlight on Location 12 | Added on Monday, January 1, 2024 8:15:00 PM

First quote.
==========
Book B (Author B)
- Your Note on Location 99 | Added on Monday, January 1, 2024 8:20:00 PM

Second note.
=========="""
    monkeypatch.setattr("app.books.clippings.utc_iso", lambda value=None: "2026-07-21T10:00:00Z")

    queued = queue_my_clippings(raw)
    first_hash = queued.queued[0].unique_hash
    second_hash = queued.queued[1].unique_hash

    failed = mark_clippings_failed(
        queued.state,
        {second_hash: "No Wi-Fi"},
    )
    assert failed.failed == 1
    assert failed.missing == 0
    assert failed.state.pending[1].attempts == 1
    assert failed.state.pending[1].last_error == "No Wi-Fi"
    assert failed.state.pending[1].last_error_at == "2026-07-21T10:00:00Z"

    uploaded = mark_clippings_uploaded(failed.state, [first_hash, "missing-hash"])
    assert uploaded.uploaded == 1
    assert uploaded.missing == 1
    assert first_hash in uploaded.state.synced_hashes
    assert [item.unique_hash for item in uploaded.state.pending] == [second_hash]

    restored = KindleClippingsSyncState.from_dict(uploaded.state.as_dict())
    assert restored == uploaded.state


def test_kindle_clippings_state_store_quarantines_corrupt_json(tmp_path):
    state_path = tmp_path / "kindle_clippings_sync.json"
    state_path.write_text("{not json", encoding="utf-8")
    store = KindleClippingsStateStore(state_path)

    state = store.load()

    assert state == KindleClippingsSyncState()
    assert not state_path.exists()
    quarantined = list(tmp_path.glob("kindle_clippings_sync.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{not json"

    result = store.queue_raw(
        """Recovered Book (Recovered Author)
- Your Highlight on Location 7 | Added on Monday, January 1, 2024 8:15:00 PM

Fresh queue after recovery.
=========="""
    )

    assert len(result.queued) == 1
    assert state_path.exists()
    assert len(list(tmp_path.glob("kindle_clippings_sync.json.corrupt-*"))) == 1


def test_kindle_sync_credential_store_reports_missing_status_by_default(tmp_path):
    store = KindleSyncCredentialStore(
        token_path=tmp_path / "secrets" / "kindle_book_quotes_token",
        metadata_path=tmp_path / "knowledge" / "kindle_sync_credentials.json",
    )

    status = store.status()

    assert status.state == "missing"
    assert status.clearable is False
    assert status.token_configured is False
    assert status.metadata_present is False
    assert status.destination_label == "Book Quotes"


def test_kindle_sync_credential_store_reports_configured_status_without_exposing_secret(
    tmp_path,
):
    token_path = tmp_path / "secrets" / "kindle_book_quotes_token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("secret-token-value", encoding="utf-8")
    metadata_path = tmp_path / "knowledge" / "kindle_sync_credentials.json"
    metadata_path.parent.mkdir(parents=True)
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
    store = KindleSyncCredentialStore(
        token_path=token_path,
        metadata_path=metadata_path,
    )

    status = store.status()

    assert status.state == "validated"
    assert status.clearable is True
    assert status.token_configured is True
    assert status.metadata_valid is True
    assert status.target_id_configured is True
    assert status.validated_at == "2026-07-21T09:10:00Z"
    assert "secret-token-value" not in repr(status)


def test_kindle_sync_credential_store_clear_removes_local_files(tmp_path):
    token_path = tmp_path / "secrets" / "kindle_book_quotes_token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("secret-token-value", encoding="utf-8")
    metadata_path = tmp_path / "knowledge" / "kindle_sync_credentials.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text('{"destination":{"label":"Book Quotes"}}', encoding="utf-8")
    store = KindleSyncCredentialStore(
        token_path=token_path,
        metadata_path=metadata_path,
    )

    result = store.clear()

    assert result.cleared == 2
    assert result.status.state == "missing"
    assert token_path.exists() is False
    assert metadata_path.exists() is False


def test_kindle_sync_credential_store_flags_unreadable_metadata(tmp_path):
    token_path = tmp_path / "secrets" / "kindle_book_quotes_token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("secret-token-value", encoding="utf-8")
    metadata_path = tmp_path / "knowledge" / "kindle_sync_credentials.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text("{not-json", encoding="utf-8")
    store = KindleSyncCredentialStore(
        token_path=token_path,
        metadata_path=metadata_path,
    )

    status = store.status()

    assert status.state == "needs_review"
    assert status.clearable is True
    assert status.note == "Local Kindle sync metadata could not be read."


def test_kindle_sync_credential_store_requires_target_id_for_ready_state(tmp_path):
    token_path = tmp_path / "secrets" / "kindle_book_quotes_token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("secret-token-value", encoding="utf-8")
    metadata_path = tmp_path / "knowledge" / "kindle_sync_credentials.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text('{"destination":{"label":"Book Quotes"}}', encoding="utf-8")
    store = KindleSyncCredentialStore(
        token_path=token_path,
        metadata_path=metadata_path,
    )

    status = store.status()

    assert status.state == "needs_review"
    assert status.target_id_configured is False
    assert status.note == "Local Book Quotes target ID is missing."


def test_kindle_sync_credential_store_validate_success_updates_metadata(
    tmp_path, monkeypatch
):
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "id": "data-source-1",
                "title": [{"plain_text": "Book Quotes"}],
                "parent": {"database_id": "database-1"},
            }

    class FakeSession:
        def __init__(self):
            self.calls = []

        def request(self, method, url, timeout=None, headers=None):
            self.calls.append(
                {
                    "method": method,
                    "url": url,
                    "timeout": timeout,
                    "headers": headers or {},
                }
            )
            return FakeResponse()

    monkeypatch.setattr("app.books.kindle_sync.utc_iso", lambda value=None: "2026-07-21T11:00:00Z")
    token_path = tmp_path / "secrets" / "kindle_book_quotes_token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("secret-token-value", encoding="utf-8")
    metadata_path = tmp_path / "knowledge" / "kindle_sync_credentials.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        """
        {
          "destination": {
            "label": "Book Quotes",
            "kind": "data_source",
            "data_source_id": "data-source-1"
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    session = FakeSession()
    store = KindleSyncCredentialStore(
        token_path=token_path,
        metadata_path=metadata_path,
    )

    result = store.validate(session=session)
    status = store.status()

    assert result.validated is True
    assert status.state == "validated"
    assert status.validated_at == "2026-07-21T11:00:00Z"
    assert status.last_validation_error == ""
    assert session.calls[0]["url"].endswith("/data_sources/datasource1")
    assert session.calls[0]["headers"]["Authorization"] == "Bearer secret-token-value"


def test_kindle_sync_credential_store_validate_failure_records_safe_error(
    tmp_path, monkeypatch
):
    class FakeResponse:
        status_code = 401

        @staticmethod
        def json():
            return {"message": "Unauthorized"}

    class FakeSession:
        @staticmethod
        def request(method, url, timeout=None, headers=None):
            return FakeResponse()

    monkeypatch.setattr("app.books.kindle_sync.utc_iso", lambda value=None: "2026-07-21T11:05:00Z")
    token_path = tmp_path / "secrets" / "kindle_book_quotes_token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("secret-token-value", encoding="utf-8")
    metadata_path = tmp_path / "knowledge" / "kindle_sync_credentials.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        """
        {
          "destination": {
            "label": "Book Quotes",
            "kind": "data_source",
            "data_source_id": "data-source-1"
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    store = KindleSyncCredentialStore(
        token_path=token_path,
        metadata_path=metadata_path,
    )

    result = store.validate(session=FakeSession())
    status = store.status()

    assert result.validated is False
    assert status.state == "needs_review"
    assert status.validation_state == "invalid"
    assert status.last_checked_at == "2026-07-21T11:05:00Z"
    assert status.last_validation_error == "Unauthorized"


def test_kindle_sync_credential_store_sync_pending_uploads_and_skips_existing(
    tmp_path, monkeypatch
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
            self.calls.append(
                {
                    "method": method,
                    "url": url,
                    "timeout": timeout,
                    "headers": headers or {},
                    "json": kwargs.get("json"),
                }
            )
            if method == "GET" and url.endswith("/data_sources/datasource1"):
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
            if method == "POST" and url.endswith("/data_sources/datasource1/query"):
                unique_hash = kwargs["json"]["filter"]["rich_text"]["equals"]
                if unique_hash.endswith("second"):
                    return FakeResponse(200, {"results": [{"id": "existing-page"}]})
                return FakeResponse(200, {"results": []})
            if method == "POST" and url.endswith("/pages"):
                return FakeResponse(200, {"id": "created-page"})
            raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr("app.books.kindle_sync.utc_iso", lambda value=None: "2026-07-21T12:00:00Z")
    token_path = tmp_path / "secrets" / "kindle_book_quotes_token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("secret-token-value", encoding="utf-8")
    metadata_path = tmp_path / "knowledge" / "kindle_sync_credentials.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        """
        {
          "destination": {
            "label": "Book Quotes",
            "kind": "data_source",
            "data_source_id": "datasource1"
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    queued = queue_my_clippings(
        """First Book (Author A)
- Your Highlight on Location 12 | Added on Monday, January 1, 2024 8:15:00 PM

First quote.
==========
Second Book (Author B)
- Your Highlight on Location 77 | Added on Monday, January 1, 2024 9:15:00 PM

Second quote.
=========="""
    )
    first_item, second_item = queued.queued
    first_item = type(first_item)(
        unique_hash=f"{first_item.unique_hash}-first",
        payload=first_item.payload,
    )
    second_item = type(second_item)(
        unique_hash=f"{second_item.unique_hash}-second",
        payload=second_item.payload,
    )
    state = KindleClippingsSyncState(
        synced_hashes=frozenset(),
        pending=(first_item, second_item),
    )
    store = KindleSyncCredentialStore(token_path=token_path, metadata_path=metadata_path)
    session = FakeSession()

    result = store.sync_pending(state, session=session)

    assert result.uploaded == 1
    assert result.skipped_existing == 1
    assert result.failed == 0
    assert result.state.pending == ()
    assert result.state.synced_hashes == frozenset(
        {first_item.unique_hash, second_item.unique_hash}
    )
    assert any(call["url"].endswith("/pages") for call in session.calls)


def test_kindle_sync_credential_store_sync_pending_keeps_failed_item_for_retry(
    tmp_path, monkeypatch
):
    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class FakeSession:
        def request(self, method, url, timeout=None, headers=None, **kwargs):
            if method == "GET" and url.endswith("/data_sources/datasource1"):
                return FakeResponse(
                    200,
                    {
                        "properties": {
                            "Name": {"type": "title"},
                            "Unique Hash": {"type": "rich_text"},
                        }
                    },
                )
            if method == "POST" and url.endswith("/data_sources/datasource1/query"):
                return FakeResponse(200, {"results": []})
            if method == "POST" and url.endswith("/pages"):
                return FakeResponse(503, {"message": "Service unavailable"})
            raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr("app.books.kindle_sync.utc_iso", lambda value=None: "2026-07-21T12:10:00Z")
    token_path = tmp_path / "secrets" / "kindle_book_quotes_token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("secret-token-value", encoding="utf-8")
    metadata_path = tmp_path / "knowledge" / "kindle_sync_credentials.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        """
        {
          "destination": {
            "label": "Book Quotes",
            "kind": "data_source",
            "data_source_id": "datasource1"
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    queued = queue_my_clippings(
        """Retry Book (Author A)
- Your Highlight on Location 12 | Added on Monday, January 1, 2024 8:15:00 PM

Retry quote.
=========="""
    )
    store = KindleSyncCredentialStore(token_path=token_path, metadata_path=metadata_path)

    result = store.sync_pending(queued.state, session=FakeSession())

    assert result.uploaded == 0
    assert result.skipped_existing == 0
    assert result.failed == 1
    assert len(result.state.pending) == 1
    assert result.state.pending[0].attempts == 1
    assert result.state.pending[0].last_error == "Service unavailable"


def test_kindle_clippings_manual_assignment_adds_local_relation_only():
    book = SimpleNamespace(
        id="book-1",
        dragon_book_id="dragon-book-1",
        title="Canonical Book",
    )
    queued = queue_my_clippings(
        """Unmatched Kindle Title (Unknown Author)
- Your Highlight on Location 12 | Added on Monday, January 1, 2024 8:15:00 PM

First quote.
=========="""
    )
    unique_hash = queued.queued[0].unique_hash

    assigned = assign_clipping_book(queued.state, unique_hash=unique_hash, book=book)

    assert assigned.updated is True
    assert assigned.state.synced_hashes == frozenset()
    assert len(assigned.state.pending) == 1
    payload = assigned.state.pending[0].payload
    assert payload["book_id"] == "book-1"
    assert payload["dragon_book_id"] == "dragon-book-1"
    assert payload["match_source"] == "manual_local_review"

    projection = project_clippings_outbox(assigned.state, [book])
    assert projection[0].match.state == "matched"
    assert projection[0].match.confidence == "manual_local_review"


def test_kindle_clippings_outbox_remove_keeps_synced_hashes():
    queued = queue_my_clippings(
        """Remove Me (Unknown Author)
- Your Highlight on Location 12 | Added on Monday, January 1, 2024 8:15:00 PM

First quote.
==========
Keep Me (Known Author)
- Your Highlight on Location 99 | Added on Monday, January 1, 2024 8:20:00 PM

Second quote.
=========="""
    )
    remove_hash = queued.queued[0].unique_hash
    keep_hash = queued.queued[1].unique_hash
    state = KindleClippingsSyncState(
        synced_hashes=frozenset({"already-synced"}),
        pending=tuple(queued.queued),
    )

    removed = remove_clipping_from_outbox(state, unique_hash=remove_hash)
    missing = remove_clipping_from_outbox(removed.state, unique_hash="missing-hash")

    assert removed.removed is True
    assert removed.state.synced_hashes == frozenset({"already-synced"})
    assert [item.unique_hash for item in removed.state.pending] == [keep_hash]
    assert missing.removed is False
    assert missing.state == removed.state


def test_kindle_clippings_bulk_remove_keeps_only_unselected_items():
    queued = queue_my_clippings(
        """Matched One (Known Author)
- Your Highlight on Location 12 | Added on Monday, January 1, 2024 8:15:00 PM

First quote.
==========
Matched Two (Known Author)
- Your Highlight on Location 18 | Added on Monday, January 1, 2024 8:16:00 PM

Second quote.
==========
Keep Me (Known Author)
- Your Highlight on Location 99 | Added on Monday, January 1, 2024 8:20:00 PM

Third quote.
=========="""
    )
    remove_hashes = [queued.queued[0].unique_hash, queued.queued[1].unique_hash]
    keep_hash = queued.queued[2].unique_hash
    state = KindleClippingsSyncState(
        synced_hashes=frozenset({"already-synced"}),
        pending=tuple(queued.queued),
    )

    removed = remove_clippings_from_outbox(state, unique_hashes=remove_hashes)
    empty = remove_clippings_from_outbox(removed.state, unique_hashes=[])

    assert removed.removed == 2
    assert removed.state.synced_hashes == frozenset({"already-synced"})
    assert [item.unique_hash for item in removed.state.pending] == [keep_hash]
    assert empty.removed == 0
    assert empty.state == removed.state


def test_kindle_clippings_failure_reset_clears_error_but_keeps_attempts():
    queued = queue_my_clippings(
        """Reset Me (Known Author)
- Your Highlight on Location 12 | Added on Monday, January 1, 2024 8:15:00 PM

First quote.
==========
Keep Error (Known Author)
- Your Highlight on Location 18 | Added on Monday, January 1, 2024 8:16:00 PM

Second quote.
=========="""
    )
    reset_hash = queued.queued[0].unique_hash
    keep_hash = queued.queued[1].unique_hash
    state = KindleClippingsSyncState(
        synced_hashes=frozenset({"already-synced"}),
        pending=(
            type(queued.queued[0])(
                unique_hash=reset_hash,
                payload=queued.queued[0].payload,
                attempts=2,
                last_error="Wi-Fi offline",
                last_error_at="2026-07-21T10:00:00Z",
            ),
            type(queued.queued[1])(
                unique_hash=keep_hash,
                payload=queued.queued[1].payload,
                attempts=3,
                last_error="Still failing",
                last_error_at="2026-07-21T11:00:00Z",
            ),
        ),
    )

    reset = reset_clipping_failures(state, unique_hashes=[reset_hash])
    empty = reset_clipping_failures(reset.state, unique_hashes=[])

    assert reset.reset == 1
    assert reset.state.synced_hashes == frozenset({"already-synced"})
    assert reset.state.pending[0].attempts == 2
    assert reset.state.pending[0].last_error == ""
    assert reset.state.pending[0].last_error_at == ""
    assert reset.state.pending[1].attempts == 3
    assert reset.state.pending[1].last_error == "Still failing"
    assert empty.reset == 0
    assert empty.state == reset.state


def test_kindle_clipping_matching_uses_normalized_title_and_author():
    book = SimpleNamespace(
        id="book-1",
        dragon_book_id="dragon-book-1",
        title="Crime and Punishment",
        original_title="",
        authors=["Fyodor Dostoevsky"],
        additional_authors=[],
        editions=[],
        metadata_state={},
    )
    payload = {
        "book_title": "تحميل كتاب Crime and Punishment PDF",
        "author": "fyodor dostoevsky",
    }

    match = match_clipping_payload(payload, [book])

    assert match.state == "matched"
    assert match.confidence == "normalized_title_author"
    assert match.book_id == "book-1"
    assert match.dragon_book_id == "dragon-book-1"


def test_kindle_clipping_matching_uses_known_title_aliases():
    book = SimpleNamespace(
        id="book-1",
        dragon_book_id="dragon-book-1",
        title="Canonical Title",
        original_title="",
        authors=["Example Author"],
        additional_authors=[],
        editions=[],
        metadata_state={"kindle_title_aliases": ["Kindle Store Title"]},
    )

    match = match_clipping_payload(
        {"book_title": "Kindle Store Title", "author": "Example Author"},
        [book],
    )

    assert match.state == "matched"
    assert match.confidence == "known_kindle_title_alias"


def test_kindle_clipping_matching_uses_notion_book_relation():
    book = SimpleNamespace(
        id="book-1",
        dragon_book_id="dragon-book-1",
        title="New technique book",
        original_title="",
        authors=[],
        additional_authors=[],
        editions=[],
        metadata_state={},
        external_ids={"notion_page_id": "8eaf2d10-4dbb-4a31-bef4-2fe718bf4b73"},
    )

    match = match_clipping_payload(
        {"book_relation_ids": "8eaf2d104dbb4a31bef42fe718bf4b73"}, [book]
    )

    assert match.state == "matched"
    assert match.confidence == "notion_book_relation"
    assert match.book_id == "book-1"


def test_book_quotes_client_reads_the_new_book_relation_field():
    client = KindleBookQuotesClient(
        token="test-token",
        target_kind="data_source",
        target_id="book-quotes",
    )
    client._schema = {
        "Name": {"type": "title"},
        "الكتاب": {"type": "relation"},
        "Quote": {"type": "rich_text"},
    }

    payload = client.quote_payload_from_page(
        {
            "id": "quote-page",
            "properties": {
                "Name": {"type": "title", "title": []},
                "الكتاب": {
                    "type": "relation",
                    "relation": [{"id": "8eaf2d10-4dbb-4a31-bef4-2fe718bf4b73"}],
                },
                "Quote": {
                    "type": "rich_text",
                    "rich_text": [{"plain_text": "New technique quote"}],
                },
            },
        }
    )

    assert payload["quote"] == "New technique quote"
    assert payload["book_relation_ids"] == "8eaf2d104dbb4a31bef42fe718bf4b73"


def test_highlight_view_hides_technical_reader_locations():
    projection = BookQuotesProjection(
        item=BookQuotesSnapshotItem(
            notion_page_id="quote-page",
            payload={
                "quote": "A readable highlight.",
                "location": "pos0=/body/DocFragment[32]/body/p[12]/text().38",
            },
        ),
        match=KindleClippingMatch(state="matched", confidence="dragon_book_id"),
    )

    highlight = _highlight_payload(projection)

    assert highlight["location"] == ""


def test_kindle_clipping_matching_flags_review_and_ambiguity():
    left = SimpleNamespace(
        id="left",
        dragon_book_id="dragon-left",
        title="Shared Title",
        original_title="",
        authors=["Author A"],
        additional_authors=[],
        editions=[],
        metadata_state={},
    )
    right = SimpleNamespace(
        id="right",
        dragon_book_id="dragon-right",
        title="Shared Title",
        original_title="",
        authors=["Author B"],
        additional_authors=[],
        editions=[],
        metadata_state={},
    )

    ambiguous = match_clipping_payload(
        {"book_title": "Shared Title", "author": "Unknown Author"},
        [left, right],
    )
    unknown_author = match_clipping_payload(
        {"book_title": "Shared Title", "author": ""},
        [left],
    )

    assert ambiguous.state == "ambiguous"
    assert ambiguous.note == "Ambiguous title"
    assert unknown_author.state == "needs_review"
    assert unknown_author.note == "Unknown author"


def test_kindle_clippings_outbox_projection_attaches_match_state():
    book = SimpleNamespace(
        id="book-1",
        dragon_book_id="dragon-book-1",
        title="Book A",
        original_title="",
        authors=["Author A"],
        additional_authors=[],
        editions=[],
        metadata_state={},
    )
    queued = queue_my_clippings(
        """Book A (Author A)
- Your Highlight on Location 12 | Added on Monday, January 1, 2024 8:15:00 PM

First quote.
=========="""
    )

    projection = project_clippings_outbox(queued.state, [book])

    assert len(projection) == 1
    assert projection[0].item.unique_hash == queued.queued[0].unique_hash
    assert projection[0].match.state == "matched"
