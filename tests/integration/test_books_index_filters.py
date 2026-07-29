from pathlib import Path

from app.books.book_quotes import BookQuotesSnapshotStore
from app.books.models import (
    AudiobookEdition,
    AvailabilityCandidate,
    Book,
    BookEdition,
    Quote,
    TextAsset,
)
from app.extensions import db


def seed_filter_books(app) -> dict[str, str]:
    with app.app_context():
        kfx = Book(
            title="Kindle First",
            normalized_title="kindle first",
            authors=["Example Author"],
            status="reading",
            metadata_status="verified",
            edition_language="English",
            translator="Hidden Translator",
            isbn_13="9780140449136",
            collections=["Kindle Shelf", "Classics"],
            personal_notes="Keep this for the export rehearsal.",
        )
        kfx_edition = BookEdition(
            book=kfx, title="Kindle First", language="English", primary=True
        )
        kfx_edition.text_assets.append(
            TextAsset(
                format="KFX",
                filename="kindle-first.kfx",
                file_hash="kfx-filter-hash",
                verification_status="verified",
            )
        )
        kfx.audiobooks.append(
            AudiobookEdition(
                title="Kindle First",
                narrator="Audio Narrator",
                language="English",
            )
        )

        epub = Book(
            title="Portable Edition",
            normalized_title="portable edition",
            authors=["Another Author"],
            additional_authors=["Co Author"],
            status="wishlist",
            metadata_status="verified",
            edition_language="French",
            isbn_13="9780140449266",
            collections=["Portable Shelf"],
        )
        epub_edition = BookEdition(
            book=epub,
            title="Portable Edition",
            language="French",
            translator="Edition Translator",
            primary=True,
        )
        epub_edition.text_assets.append(
            TextAsset(
                format="EPUB",
                filename="portable-edition.epub",
                file_hash="epub-filter-hash",
                verification_status="verified",
            )
        )
        epub.quotes.append(
            Quote(
                text="A lighthouse sentence for rediscovery.",
                note="Private marginalia marker",
            )
        )

        pdf_only = Book(
            title="Scanned Archive",
            normalized_title="scanned archive",
            authors=["Archive Author"],
            status="reference",
            metadata_status="verified",
            edition_language="English",
            collections=["Archive"],
        )
        pdf_edition = BookEdition(
            book=pdf_only, title="Scanned Archive", language="English", primary=True
        )
        pdf_edition.text_assets.append(
            TextAsset(
                format="PDF",
                filename="scanned-archive.pdf",
                file_hash="pdf-filter-hash",
                verification_status="verified",
            )
        )

        review = Book(
            title="Review Queue",
            normalized_title="review queue",
            authors=["Queue Author"],
            status="paused",
            metadata_status="needs_review",
            collections=["Review Shelf"],
        )
        review.availability_candidates.append(
            AvailabilityCandidate(
                provider="jackett",
                title="Review Queue AZW3",
                format_guess="AZW3",
                review_state="review_required",
            )
        )
        no_isbn = Book(
            title="Archive Without ISBN",
            normalized_title="archive without isbn",
            authors=["Archive Author"],
            status="reference",
            metadata_status="no_isbn",
            collections=["Archive"],
        )

        db.session.add_all([kfx, epub, pdf_only, review, no_isbn])
        db.session.commit()
        snapshot_path = Path(app.instance_path) / "knowledge" / "book_quotes_snapshot.json"
        snapshot_path.unlink(missing_ok=True)
        BookQuotesSnapshotStore(snapshot_path).save(
            {
                "refreshed_at": "2026-07-21T14:00:00Z",
                "last_checked_at": "2026-07-21T14:00:00Z",
                "last_error": "",
                "items": [
                    {
                        "notion_page_id": "filter-highlight-kfx",
                        "payload": {
                            "quote": "A bright synced highlight about export rehearsal.",
                            "book_title": "Kindle First",
                            "author": "Example Author",
                            "dragon_book_id": kfx.dragon_book_id,
                            "source": "Kindle",
                            "kind": "highlight",
                        },
                    },
                    {
                        "notion_page_id": "filter-highlight-epub",
                        "payload": {
                            "quote": "A synced highlight about portable constellations.",
                            "book_title": "Portable Edition",
                            "author": "Another Author",
                            "dragon_book_id": epub.dragon_book_id,
                            "source": "Kindle",
                            "kind": "highlight",
                        },
                    },
                    {
                        "notion_page_id": "filter-highlight-unmatched",
                        "payload": {
                            "quote": (
                                "An unmatched synced highlight should not land on a "
                                "book card."
                            ),
                            "book_title": "Unknown Synced Book",
                            "author": "Mystery Author",
                            "source": "Kindle",
                            "kind": "highlight",
                        },
                    },
                ],
            }
        )
        return {
            "kfx": kfx.id,
            "epub": epub.id,
            "pdf_only": pdf_only.id,
            "review": review.id,
            "no_isbn": no_isbn.id,
        }


def test_books_index_filters_by_format_audio_and_review(authenticated_client, app):
    seed_filter_books(app)

    kfx_html = authenticated_client.get("/books?format=KFX").get_data(as_text=True)
    assert "Kindle First" in kfx_html
    assert "Portable Edition" not in kfx_html
    assert "Scanned Archive" not in kfx_html
    assert "Review Queue" not in kfx_html

    pdf_html = authenticated_client.get("/books?format=PDF").get_data(as_text=True)
    assert "Scanned Archive" in pdf_html
    assert "Kindle First" not in pdf_html
    assert "Portable Edition" not in pdf_html

    pdf_only_html = authenticated_client.get("/books?format=pdf_only").get_data(
        as_text=True
    )
    assert "Scanned Archive" in pdf_only_html
    assert "Kindle First" not in pdf_only_html
    assert "Portable Edition" not in pdf_only_html
    assert '<option value="pdf_only" selected>PDF only</option>' in pdf_only_html

    missing_format_html = authenticated_client.get("/books?format=missing").get_data(
        as_text=True
    )
    assert "Review Queue" in missing_format_html
    assert "Archive Without ISBN" in missing_format_html
    assert "Scanned Archive" not in missing_format_html
    assert '<option value="missing" selected>No digital format</option>' in missing_format_html

    audio_html = authenticated_client.get("/books?audiobook=yes").get_data(as_text=True)
    assert "Kindle First" in audio_html
    assert "Portable Edition" not in audio_html

    missing_audio_html = authenticated_client.get("/books?audiobook=no").get_data(
        as_text=True
    )
    assert "Kindle First" not in missing_audio_html
    assert "Portable Edition" in missing_audio_html
    assert "Scanned Archive" in missing_audio_html
    assert "Review Queue" in missing_audio_html
    assert "Archive Without ISBN" in missing_audio_html

    review_html = authenticated_client.get("/books?review=yes").get_data(as_text=True)
    assert "Review Queue" in review_html
    assert "Kindle First" not in review_html


def test_books_index_filters_by_language(authenticated_client, app):
    seed_filter_books(app)

    english_html = authenticated_client.get("/books?language=English").get_data(
        as_text=True
    )
    assert "Kindle First" in english_html
    assert "Portable Edition" not in english_html
    assert "Review Queue" not in english_html
    assert '<option value="English" selected>English</option>' in english_html

    french_html = authenticated_client.get("/books?language=French").get_data(
        as_text=True
    )
    assert "Portable Edition" in french_html
    assert "Kindle First" not in french_html


def test_books_index_filters_by_metadata_view(authenticated_client, app):
    seed_filter_books(app)

    inbox_html = authenticated_client.get("/books?metadata=inbox").get_data(as_text=True)
    assert "Review Queue" in inbox_html
    assert "Kindle First" not in inbox_html
    assert '<option value="inbox" selected>Inbox</option>' in inbox_html

    missing_isbn_html = authenticated_client.get(
        "/books?metadata=missing_isbn"
    ).get_data(as_text=True)
    assert "Review Queue" in missing_isbn_html
    assert "Archive Without ISBN" not in missing_isbn_html
    assert "Kindle First" not in missing_isbn_html

    no_isbn_html = authenticated_client.get("/books?metadata=no_isbn").get_data(
        as_text=True
    )
    assert "Archive Without ISBN" in no_isbn_html
    assert "Review Queue" not in no_isbn_html

    verified_html = authenticated_client.get("/books?metadata=verified").get_data(
        as_text=True
    )
    assert "Kindle First" in verified_html
    assert "Portable Edition" in verified_html
    assert "Review Queue" not in verified_html


def test_books_index_filters_by_collection(authenticated_client, app):
    seed_filter_books(app)

    archive_html = authenticated_client.get("/books?collection=Archive").get_data(
        as_text=True
    )
    assert "Scanned Archive" in archive_html
    assert "Archive Without ISBN" in archive_html
    assert "Kindle First" not in archive_html
    assert '<option value="Archive" selected>Archive</option>' in archive_html

    classics_html = authenticated_client.get("/books?collection=classics").get_data(
        as_text=True
    )
    assert "Kindle First" in classics_html
    assert "Portable Edition" not in classics_html
    assert "Archive Without ISBN" not in classics_html


def test_books_index_filters_by_author(authenticated_client, app):
    seed_filter_books(app)

    archive_html = authenticated_client.get("/books?author=Archive+Author").get_data(
        as_text=True
    )
    assert "Scanned Archive" in archive_html
    assert "Archive Without ISBN" in archive_html
    assert "Kindle First" not in archive_html
    assert '<option value="Archive Author" selected>Archive Author</option>' in archive_html

    co_author_html = authenticated_client.get("/books?author=co+author").get_data(
        as_text=True
    )
    assert "Portable Edition" in co_author_html
    assert "Kindle First" not in co_author_html
    assert '<option value="Co Author" selected>Co Author</option>' in co_author_html


def test_books_index_filters_by_translator(authenticated_client, app):
    seed_filter_books(app)

    book_translator_html = authenticated_client.get(
        "/books?translator=Hidden+Translator"
    ).get_data(as_text=True)
    assert "Kindle First" in book_translator_html
    assert "Portable Edition" not in book_translator_html
    assert (
        '<option value="Hidden Translator" selected>Hidden Translator</option>'
        in book_translator_html
    )

    edition_translator_html = authenticated_client.get(
        "/books?translator=edition+translator"
    ).get_data(as_text=True)
    assert "Portable Edition" in edition_translator_html
    assert "Kindle First" not in edition_translator_html
    assert (
        '<option value="Edition Translator" selected>Edition Translator</option>'
        in edition_translator_html
    )


def test_books_index_filters_by_quotes(authenticated_client, app):
    seed_filter_books(app)

    quoted_html = authenticated_client.get("/books?quotes=yes").get_data(as_text=True)
    assert "Portable Edition" in quoted_html
    assert "Kindle First" not in quoted_html
    assert '<option value="yes" selected>Available</option>' in quoted_html

    unquoted_html = authenticated_client.get("/books?quotes=no").get_data(as_text=True)
    assert "Portable Edition" not in unquoted_html
    assert "Kindle First" in unquoted_html
    assert "Scanned Archive" in unquoted_html
    assert "Review Queue" in unquoted_html
    assert "Archive Without ISBN" in unquoted_html
    assert '<option value="no" selected>Missing</option>' in unquoted_html


def test_books_index_filters_by_highlights(authenticated_client, app):
    seed_filter_books(app)

    highlighted_html = authenticated_client.get("/books?highlights=yes").get_data(
        as_text=True
    )
    assert "Kindle First" in highlighted_html
    assert "Portable Edition" in highlighted_html
    assert "Scanned Archive" not in highlighted_html
    assert "Review Queue" not in highlighted_html
    assert "Archive Without ISBN" not in highlighted_html
    assert "1 highlight" in highlighted_html
    assert '<option value="yes" selected>Available</option>' in highlighted_html

    missing_highlights_html = authenticated_client.get("/books?highlights=no").get_data(
        as_text=True
    )
    assert "Kindle First" not in missing_highlights_html
    assert "Portable Edition" not in missing_highlights_html
    assert "Scanned Archive" in missing_highlights_html
    assert "Review Queue" in missing_highlights_html
    assert "Archive Without ISBN" in missing_highlights_html
    assert '<option value="no" selected>Missing</option>' in missing_highlights_html


def test_books_index_filters_by_notes(authenticated_client, app):
    seed_filter_books(app)

    noted_html = authenticated_client.get("/books?notes=yes").get_data(as_text=True)
    assert "Kindle First" in noted_html
    assert "Portable Edition" not in noted_html
    assert '<option value="yes" selected>Available</option>' in noted_html

    missing_notes_html = authenticated_client.get("/books?notes=no").get_data(
        as_text=True
    )
    assert "Kindle First" not in missing_notes_html
    assert "Portable Edition" in missing_notes_html
    assert "Scanned Archive" in missing_notes_html
    assert "Review Queue" in missing_notes_html
    assert "Archive Without ISBN" in missing_notes_html
    assert '<option value="no" selected>Missing</option>' in missing_notes_html


def test_books_index_searches_knowledge_fields(authenticated_client, app):
    seed_filter_books(app)

    translator_html = authenticated_client.get("/books?q=Hidden+Translator").get_data(
        as_text=True
    )
    assert "Kindle First" in translator_html
    assert "Portable Edition" not in translator_html

    candidate_html = authenticated_client.get("/books?q=AZW3").get_data(as_text=True)
    assert "Review Queue" in candidate_html
    assert "Kindle First" not in candidate_html

    quote_html = authenticated_client.get("/books?q=lighthouse+sentence").get_data(
        as_text=True
    )
    assert "Portable Edition" in quote_html
    assert "Kindle First" not in quote_html

    language_html = authenticated_client.get("/books?q=French").get_data(as_text=True)
    assert "Portable Edition" in language_html
    assert "Kindle First" not in language_html

    personal_note_html = authenticated_client.get("/books?q=export+rehearsal").get_data(
        as_text=True
    )
    assert "Kindle First" in personal_note_html
    assert "Portable Edition" not in personal_note_html

    highlight_html = authenticated_client.get(
        "/books?q=portable+constellations"
    ).get_data(as_text=True)
    assert "Portable Edition" in highlight_html
    assert "Kindle First" not in highlight_html


def test_books_highlights_page_lists_matched_snapshot_rows(authenticated_client, app):
    ids = seed_filter_books(app)

    page_html = authenticated_client.get("/books/highlights").get_data(as_text=True)

    assert "Highlights" in page_html
    assert "Follow the Book Quotes lines that already belong to local books" in page_html
    assert "Find synced highlights" in page_html
    assert "Kindle First" in page_html
    assert "Portable Edition" in page_html
    assert "A bright synced highlight about export rehearsal." in page_html
    assert "A synced highlight about portable constellations." in page_html
    assert "Unknown Synced Book" not in page_html
    assert "Review queue" in page_html

    filtered_html = authenticated_client.get(
        "/books/highlights?q=portable+constellations"
    ).get_data(as_text=True)
    assert "Portable Edition" in filtered_html
    assert "A synced highlight about portable constellations." in filtered_html
    assert "A bright synced highlight about export rehearsal." not in filtered_html

    selected_html = authenticated_client.get(
        f"/books/highlights?book_id={ids['kfx']}"
    ).get_data(as_text=True)
    assert "Kindle First" in selected_html
    assert "A bright synced highlight about export rehearsal." in selected_html
    assert "A synced highlight about portable constellations." not in selected_html
    assert f'value="{ids["kfx"]}" selected' in selected_html


def test_books_quotes_page_lists_saved_local_quotes(authenticated_client, app):
    ids = seed_filter_books(app)
    with app.app_context():
        kfx = db.session.get(Book, ids["kfx"])
        assert kfx is not None
        kfx.quotes.append(
            Quote(
                text="A second line worth keeping for the Kindle shelf.",
                page=17,
                note="Marked during a reread.",
            )
        )
        db.session.commit()

    page_html = authenticated_client.get("/books/quotes").get_data(as_text=True)

    assert "Quotes" in page_html
    assert "Keep the lines you saved inside Dragon close to the books they came from" in page_html
    assert "Find saved quotes" in page_html
    assert "Portable Edition" in page_html
    assert "Kindle First" in page_html
    assert "A lighthouse sentence for rediscovery." in page_html
    assert "A second line worth keeping for the Kindle shelf." in page_html
    assert "Notebook only" in page_html

    filtered_html = authenticated_client.get(
        "/books/quotes?q=private+marginalia"
    ).get_data(as_text=True)
    assert "A lighthouse sentence for rediscovery." in filtered_html
    assert "A second line worth keeping for the Kindle shelf." not in filtered_html

    selected_html = authenticated_client.get(
        f"/books/quotes?book_id={ids['kfx']}"
    ).get_data(as_text=True)
    assert "A second line worth keeping for the Kindle shelf." in selected_html
    assert "A lighthouse sentence for rediscovery." not in selected_html
    assert f'value="{ids["kfx"]}" selected' in selected_html


def test_books_direct_views_lock_core_library_sections(authenticated_client, app):
    seed_filter_books(app)
    with app.app_context():
        finished = Book(
            title="Closed Ledger",
            normalized_title="closed ledger",
            authors=["Finished Author"],
            status="finished",
            metadata_status="verified",
        )
        want_to_read = Book(
            title="Next Orbit",
            normalized_title="next orbit",
            authors=["Wish Author"],
            status="want_to_read",
            metadata_status="verified",
        )
        dropped = Book(
            title="Abandoned Orbit",
            normalized_title="abandoned orbit",
            authors=["Dropped Author"],
            status="dropped",
            metadata_status="verified",
        )
        db.session.add_all([finished, want_to_read, dropped])
        db.session.commit()

    reading_html = authenticated_client.get("/books/reading").get_data(as_text=True)
    assert "<h1>Reading</h1>" in reading_html
    assert "Kindle First" in reading_html
    assert "Portable Edition" not in reading_html
    assert 'select name="status" disabled' in reading_html

    finished_html = authenticated_client.get("/books/finished").get_data(as_text=True)
    assert "<h1>Finished</h1>" in finished_html
    assert "Closed Ledger" in finished_html
    assert "Kindle First" not in finished_html

    wishlist_html = authenticated_client.get("/books/wishlist").get_data(as_text=True)
    assert "<h1>Wishlist</h1>" in wishlist_html
    assert "Portable Edition" in wishlist_html
    assert "Next Orbit" in wishlist_html
    assert "Kindle First" not in wishlist_html
    assert 'href="/books/wishlist"' in wishlist_html

    paused_html = authenticated_client.get("/books/paused").get_data(as_text=True)
    assert "<h1>Paused</h1>" in paused_html
    assert "Review Queue" in paused_html
    assert "Kindle First" not in paused_html
    assert 'select name="status" disabled' in paused_html
    assert 'href="/books/paused"' in paused_html

    dropped_html = authenticated_client.get("/books/dropped").get_data(as_text=True)
    assert "<h1>Dropped</h1>" in dropped_html
    assert "Abandoned Orbit" in dropped_html
    assert "Kindle First" not in dropped_html
    assert 'href="/books/dropped"' in dropped_html

    reference_html = authenticated_client.get("/books/reference").get_data(as_text=True)
    assert "<h1>Reference</h1>" in reference_html
    assert "Scanned Archive" in reference_html
    assert "Archive Without ISBN" in reference_html
    assert "Kindle First" not in reference_html
    assert 'href="/books/reference"' in reference_html

    review_html = authenticated_client.get("/books/needs-review").get_data(as_text=True)
    assert "<h1>Needs Review</h1>" in review_html
    assert "Review Queue" in review_html
    assert "Kindle First" not in review_html
    assert 'select name="review" disabled' in review_html
    assert 'href="/books/needs-review"' in review_html


def test_books_audiobooks_and_collections_views(authenticated_client, app):
    seed_filter_books(app)

    audiobooks_html = authenticated_client.get("/books/audiobooks").get_data(
        as_text=True
    )
    assert "<h1>Audiobooks</h1>" in audiobooks_html
    assert "Kindle First" in audiobooks_html
    assert "Portable Edition" not in audiobooks_html
    assert 'select name="audiobook" disabled' in audiobooks_html

    collections_html = authenticated_client.get("/books/collections").get_data(
        as_text=True
    )
    assert "<h1>Collections</h1>" in collections_html
    assert "Kindle Shelf" in collections_html
    assert "Portable Shelf" in collections_html
    assert "Archive" in collections_html
    assert "Kindle First" in collections_html
    assert "Portable Edition" in collections_html

    selected_collection_html = authenticated_client.get(
        "/books/collections?collection=Classics"
    ).get_data(as_text=True)
    assert "Kindle First" in selected_collection_html
    assert selected_collection_html.count('class="book-card"') == 1
    assert 'value="Classics" selected' in selected_collection_html
    assert 'href="/books/collections?collection=Classics"' in selected_collection_html


def test_books_metadata_direct_views(authenticated_client, app):
    seed_filter_books(app)
    with app.app_context():
        candidate = Book(
            title="Candidate Shelf",
            normalized_title="candidate shelf",
            authors=["Candidate Author"],
            metadata_status="candidate_found",
        )
        error = Book(
            title="Broken Metadata",
            normalized_title="broken metadata",
            authors=["Error Author"],
            metadata_status="error",
        )
        db.session.add_all([candidate, error])
        db.session.commit()

    inbox_html = authenticated_client.get("/books/metadata/inbox").get_data(as_text=True)
    assert "<h1>Metadata Inbox</h1>" in inbox_html
    assert "Review Queue" in inbox_html
    assert "Candidate Shelf" in inbox_html
    assert "Broken Metadata" in inbox_html
    assert 'select name="metadata" disabled' in inbox_html

    missing_isbn_html = authenticated_client.get(
        "/books/metadata/missing-isbn"
    ).get_data(as_text=True)
    assert "<h1>Missing ISBN</h1>" in missing_isbn_html
    assert "Review Queue" in missing_isbn_html
    assert "Archive Without ISBN" not in missing_isbn_html

    candidate_html = authenticated_client.get(
        "/books/metadata/candidate-found"
    ).get_data(as_text=True)
    assert "<h1>Candidate Found</h1>" in candidate_html
    assert "Candidate Shelf" in candidate_html
    assert "Review Queue" not in candidate_html

    review_html = authenticated_client.get(
        "/books/metadata/needs-review"
    ).get_data(as_text=True)
    assert "<h1>Metadata Needs Review</h1>" in review_html
    assert "Review Queue" in review_html
    assert "Candidate Shelf" not in review_html

    verified_html = authenticated_client.get("/books/metadata/verified").get_data(
        as_text=True
    )
    assert "<h1>Verified Metadata</h1>" in verified_html
    assert "Kindle First" in verified_html
    assert "Portable Edition" in verified_html
    assert "Review Queue" not in verified_html

    no_isbn_html = authenticated_client.get("/books/metadata/no-isbn").get_data(
        as_text=True
    )
    assert "<h1>No ISBN</h1>" in no_isbn_html
    assert "Archive Without ISBN" in no_isbn_html
    assert "Review Queue" not in no_isbn_html

    error_html = authenticated_client.get("/books/metadata/errors").get_data(
        as_text=True
    )
    assert "<h1>Metadata Errors</h1>" in error_html
    assert "Broken Metadata" in error_html
    assert "Candidate Shelf" not in error_html


def test_books_format_direct_views(authenticated_client, app):
    seed_filter_books(app)
    with app.app_context():
        azw3 = Book(
            title="Kindle Backup",
            normalized_title="kindle backup",
            authors=["Backup Author"],
            metadata_status="verified",
        )
        azw3_edition = BookEdition(
            book=azw3,
            title="Kindle Backup",
            language="English",
            primary=True,
        )
        azw3_edition.text_assets.append(
            TextAsset(
                format="AZW3",
                filename="kindle-backup.azw3",
                file_hash="azw3-filter-hash",
                verification_status="verified",
            )
        )
        db.session.add(azw3)
        db.session.commit()

    kfx_html = authenticated_client.get("/books/formats/kfx").get_data(as_text=True)
    assert "<h1>Has KFX</h1>" in kfx_html
    assert "Kindle First" in kfx_html
    assert "Portable Edition" not in kfx_html
    assert 'select name="format" disabled' in kfx_html

    azw3_html = authenticated_client.get("/books/formats/azw3").get_data(as_text=True)
    assert "<h1>Has AZW3</h1>" in azw3_html
    assert "Kindle Backup" in azw3_html
    assert "Kindle First" not in azw3_html

    epub_html = authenticated_client.get("/books/formats/epub").get_data(as_text=True)
    assert "<h1>Has EPUB</h1>" in epub_html
    assert "Portable Edition" in epub_html
    assert "Scanned Archive" not in epub_html

    pdf_html = authenticated_client.get("/books/formats/pdf").get_data(as_text=True)
    assert "<h1>Has PDF</h1>" in pdf_html
    assert "Scanned Archive" in pdf_html
    assert "Kindle First" not in pdf_html

    pdf_only_html = authenticated_client.get("/books/formats/pdf-only").get_data(
        as_text=True
    )
    assert "<h1>PDF Only</h1>" in pdf_only_html
    assert "Scanned Archive" in pdf_only_html
    assert "Kindle First" not in pdf_only_html

    no_digital_html = authenticated_client.get("/books/formats/no-digital").get_data(
        as_text=True
    )
    assert "<h1>No Digital Format</h1>" in no_digital_html
    assert "Review Queue" in no_digital_html
    assert "Archive Without ISBN" in no_digital_html
    assert "Scanned Archive" not in no_digital_html


def test_books_signal_direct_views(authenticated_client, app):
    ids = seed_filter_books(app)
    with app.app_context():
        kfx = db.session.get(Book, ids["kfx"])
        assert kfx is not None
        kfx.quotes.append(
            Quote(
                text="Signal quote for the notes lane.",
                note="Signal coverage",
            )
        )
        db.session.commit()

    highlights_html = authenticated_client.get("/books/signals/highlights").get_data(
        as_text=True
    )
    assert "<h1>Has Highlights</h1>" in highlights_html
    assert "Kindle First" in highlights_html
    assert "Portable Edition" in highlights_html
    assert "Scanned Archive" not in highlights_html
    assert 'select name="highlights" disabled' in highlights_html

    quotes_html = authenticated_client.get("/books/signals/quotes").get_data(
        as_text=True
    )
    assert "<h1>Has Quotes</h1>" in quotes_html
    assert "Portable Edition" in quotes_html
    assert "Kindle First" in quotes_html
    assert "Scanned Archive" not in quotes_html
    assert 'select name="quotes" disabled' in quotes_html

    notes_html = authenticated_client.get("/books/signals/notes").get_data(
        as_text=True
    )
    assert "<h1>Has Notes</h1>" in notes_html
    assert "Kindle First" in notes_html
    assert "Portable Edition" not in notes_html
    assert "Scanned Archive" not in notes_html
    assert 'select name="notes" disabled' in notes_html


def test_books_api_uses_knowledge_filters(authenticated_client, app):
    ids = seed_filter_books(app)

    response = authenticated_client.get("/api/v1/books?format=EPUB&review=no")
    payload = response.get_json()

    assert response.status_code == 200
    assert [item["id"] for item in payload["items"]] == [ids["epub"]]

    pdf_only_response = authenticated_client.get("/api/v1/books?format=pdf_only")
    pdf_only_payload = pdf_only_response.get_json()

    assert pdf_only_response.status_code == 200
    assert [item["id"] for item in pdf_only_payload["items"]] == [ids["pdf_only"]]

    no_digital_response = authenticated_client.get(
        "/api/v1/books?format=no_digital_format"
    )
    no_digital_payload = no_digital_response.get_json()

    assert no_digital_response.status_code == 200
    assert {item["id"] for item in no_digital_payload["items"]} == {
        ids["review"],
        ids["no_isbn"],
    }

    quote_response = authenticated_client.get("/api/v1/books?q=Private+marginalia")
    quote_payload = quote_response.get_json()

    assert quote_response.status_code == 200
    assert [item["id"] for item in quote_payload["items"]] == [ids["epub"]]

    language_response = authenticated_client.get("/api/v1/books?language=English")
    language_payload = language_response.get_json()

    assert language_response.status_code == 200
    assert {item["id"] for item in language_payload["items"]} == {
        ids["kfx"],
        ids["pdf_only"],
    }

    metadata_response = authenticated_client.get("/api/v1/books?metadata=no_isbn")
    metadata_payload = metadata_response.get_json()

    assert metadata_response.status_code == 200
    assert [item["id"] for item in metadata_payload["items"]] == [ids["no_isbn"]]

    collection_response = authenticated_client.get("/api/v1/books?collection=Archive")
    collection_payload = collection_response.get_json()

    assert collection_response.status_code == 200
    assert {item["id"] for item in collection_payload["items"]} == {
        ids["pdf_only"],
        ids["no_isbn"],
    }

    author_response = authenticated_client.get("/api/v1/books?author=Archive+Author")
    author_payload = author_response.get_json()

    assert author_response.status_code == 200
    assert {item["id"] for item in author_payload["items"]} == {
        ids["pdf_only"],
        ids["no_isbn"],
    }

    translator_response = authenticated_client.get(
        "/api/v1/books?translator=Edition+Translator"
    )
    translator_payload = translator_response.get_json()

    assert translator_response.status_code == 200
    assert [item["id"] for item in translator_payload["items"]] == [ids["epub"]]

    quotes_response = authenticated_client.get("/api/v1/books?quotes=yes")
    quotes_payload = quotes_response.get_json()

    assert quotes_response.status_code == 200
    assert [item["id"] for item in quotes_payload["items"]] == [ids["epub"]]

    notes_response = authenticated_client.get("/api/v1/books?notes=yes")
    notes_payload = notes_response.get_json()

    assert notes_response.status_code == 200
    assert [item["id"] for item in notes_payload["items"]] == [ids["kfx"]]

    highlights_response = authenticated_client.get("/api/v1/books?highlights=yes")
    highlights_payload = highlights_response.get_json()

    assert highlights_response.status_code == 200
    assert {item["id"] for item in highlights_payload["items"]} == {
        ids["kfx"],
        ids["epub"],
    }

    highlight_query_response = authenticated_client.get(
        "/api/v1/books?q=portable+constellations"
    )
    highlight_query_payload = highlight_query_response.get_json()

    assert highlight_query_response.status_code == 200
    assert [item["id"] for item in highlight_query_payload["items"]] == [ids["epub"]]
