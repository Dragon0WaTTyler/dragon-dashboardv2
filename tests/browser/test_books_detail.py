from html import escape
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pytest

from app.books.book_quotes import BookQuotesSnapshotStore
from app.books.clippings import KindleClippingsStateStore
from app.books.models import (
    AudiobookAsset,
    AudiobookEdition,
    AvailabilityCandidate,
    Book,
    BookEdition,
    Quote,
    TextAsset,
)
from app.extensions import db

pytestmark = pytest.mark.browser


def write_reader_epub(path, chapters: list[tuple[str, list[str]]]):
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            (
                "<?xml version='1.0'?>"
                "<container xmlns='urn:oasis:names:tc:opendocument:xmlns:container' "
                "version='1.0'><rootfiles><rootfile full-path='OPS/content.opf' "
                "media-type='application/oebps-package+xml'/></rootfiles></container>"
            ),
        )
        manifest_items = []
        spine_items = []
        for index, (title, paragraphs) in enumerate(chapters, start=1):
            manifest_items.append(
                f"<item id='chapter{index}' href='chapter{index}.xhtml' "
                "media-type='application/xhtml+xml'/>"
            )
            spine_items.append(f"<itemref idref='chapter{index}'/>")
            body = "".join(f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs)
            archive.writestr(
                f"OPS/chapter{index}.xhtml",
                (
                    "<html xmlns='http://www.w3.org/1999/xhtml'><head>"
                    f"<title>{escape(title)}</title></head><body>"
                    f"<h1>{escape(title)}</h1>{body}</body></html>"
                ),
            )
        archive.writestr(
            "OPS/content.opf",
            (
                "<package xmlns='http://www.idpf.org/2007/opf' version='3.0'>"
                f"<manifest>{''.join(manifest_items)}</manifest>"
                f"<spine>{''.join(spine_items)}</spine></package>"
            ),
        )


def sign_in(page, base_url: str):
    page.goto(f"{base_url}/auth/login")
    page.get_by_label("Username").fill("walid")
    page.get_by_label("Password").fill("correct horse battery staple")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"{base_url}/")


def test_arabic_book_detail_shows_cover_and_rtl_layout(page, live_app, app):
    image = (
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
        "width='360' height='540'%3E%3Crect width='360' height='540' "
        "fill='%237d1725'/%3E%3C/svg%3E"
    )
    with app.app_context():
        book = Book(
            title="كويكول",
            normalized_title="كويكول",
            authors=["حنان لاشين"],
            description="رواية عربية محفوظة في المكتبة المحلية.",
            cover_url=image,
            status="reading",
            current_page=84,
            page_count=320,
            published_year=2021,
        )
        book.quotes.append(
            Quote(text="أحياناً نلتقي بقلوب كالصخور، بل هي أشد قسوة.", page=41)
        )
        db.session.add(book)
        db.session.commit()
        book_id = book.id

    page.set_viewport_size({"width": 1440, "height": 900})
    sign_in(page, live_app)
    page.goto(f"{live_app}/books/{book_id}")

    assert page.locator(".book-detail__cover img").is_visible()
    metrics = page.locator(".book-detail__hero").evaluate(
        "element => {"
        "const cover = element.querySelector('.book-detail__cover').getBoundingClientRect();"
        "const intro = element.querySelector('.book-detail__intro').getBoundingClientRect();"
        "const title = element.querySelector('h1');"
        "return {"
        "coverLeft: cover.left, introLeft: intro.left,"
        "direction: getComputedStyle(title).direction,"
        "textAlign: getComputedStyle(title).textAlign"
        "};"
        "}"
    )
    assert metrics["coverLeft"] > metrics["introLeft"]
    assert metrics["direction"] == "rtl"
    assert metrics["textAlign"] == "right"
    quote = page.locator(".quote-list blockquote").first
    assert quote.evaluate("element => getComputedStyle(element).direction") == "rtl"
    assert quote.evaluate("element => getComputedStyle(element).textAlign") == "right"

    page.set_viewport_size({"width": 390, "height": 844})
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow == 0


def test_knowledge_diagnostics_layout_has_no_mobile_overflow(page, live_app, app):
    with app.app_context():
        book = Book(
            title="Diagnostics Book",
            normalized_title="diagnostics book",
            authors=["Example Author"],
            metadata_status="needs_review",
        )
        edition = BookEdition(book=book, title="Diagnostics Book", primary=True)
        edition.text_assets.append(
            TextAsset(
                format="AZW3",
                filename="diagnostics.azw3",
                file_hash="diagnostics-hash",
                verification_status="likely",
            )
        )
        book.availability_candidates.append(
            AvailabilityCandidate(
                provider="telegram",
                title="Diagnostics Book KFX",
                format_guess="KFX",
                review_state="review_required",
            )
        )
        db.session.add(book)
        db.session.commit()

    page.set_viewport_size({"width": 1360, "height": 900})
    sign_in(page, live_app)
    page.goto(f"{live_app}/settings/knowledge/diagnostics")

    assert page.get_by_role("heading", name="Diagnostics").is_visible()
    assert page.get_by_text("Diagnostics Book KFX").is_visible()
    assert page.locator(".diagnostics-metrics").is_visible()

    page.set_viewport_size({"width": 390, "height": 844})
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow == 0


def test_kindle_clippings_outbox_layout_has_no_mobile_overflow(page, live_app, app):
    raw_text = """Layout Book (Example Author)
- Your Highlight on page 20 | Location 244 | Added on Monday, July 20, 2026 9:30:00 PM

A compact clipping row that should wrap cleanly on mobile screens.
=========="""
    with app.app_context():
        state_path = Path(app.instance_path) / "knowledge" / "kindle_clippings_sync.json"
        state_path.unlink(missing_ok=True)
        store = KindleClippingsStateStore(state_path)
        store.queue_raw(raw_text)

    sign_in(page, live_app)
    page.set_viewport_size({"width": 1360, "height": 900})
    page.goto(f"{live_app}/settings/knowledge/kindle-clippings")

    assert page.get_by_role("heading", name="Kindle clippings outbox").is_visible()
    assert page.locator(".kindle-clippings__actions").get_by_text("pending").first.is_visible()
    assert page.get_by_role("button", name="Queue clippings").is_visible()

    page.set_viewport_size({"width": 390, "height": 844})
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow == 0


def test_book_quotes_review_layout_has_no_mobile_overflow(page, live_app, app):
    with app.app_context():
        book = Book(
            title="Review Surface Book",
            normalized_title="review surface book",
            authors=["Known Author"],
            metadata_status="verified",
        )
        db.session.add(book)
        db.session.commit()

        snapshot_path = Path(app.instance_path) / "knowledge" / "book_quotes_snapshot.json"
        snapshot_path.unlink(missing_ok=True)
        BookQuotesSnapshotStore(snapshot_path).save(
            {
                "refreshed_at": "2026-07-21T13:20:00Z",
                "last_checked_at": "2026-07-21T13:20:00Z",
                "last_error": "",
                "items": [
                    {
                        "notion_page_id": "review-surface-row",
                        "payload": {
                            "quote": "A synced highlight waiting for a local match.",
                            "book_id": book.id,
                            "dragon_book_id": book.dragon_book_id,
                            "book_title": book.title,
                            "author": "Known Author",
                            "source": "Kindle",
                            "kind": "highlight",
                        },
                    }
                ],
            }
        )

    sign_in(page, live_app)
    page.set_viewport_size({"width": 1360, "height": 900})
    page.goto(f"{live_app}/settings/knowledge/book-quotes")

    assert page.get_by_role("heading", name="Book Quotes review").is_visible()
    assert page.get_by_role(
        "heading", name="Move between clean matches and review work"
    ).is_visible()

    page.set_viewport_size({"width": 390, "height": 844})
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow == 0


def test_books_index_filters_have_no_mobile_overflow(page, live_app, app):
    with app.app_context():
        book = Book(
            title="Filter Surface",
            normalized_title="filter surface",
            authors=["Example Author"],
            status="reading",
            metadata_status="verified",
        )
        edition = BookEdition(book=book, title="Filter Surface", primary=True)
        edition.text_assets.append(
            TextAsset(
                format="KFX",
                filename="filter-surface.kfx",
                file_hash="filter-surface-hash",
                verification_status="verified",
            )
        )
        book.audiobooks.append(
            AudiobookEdition(title="Filter Surface", narrator="Example Narrator")
        )
        db.session.add(book)
        db.session.commit()

    sign_in(page, live_app)
    page.set_viewport_size({"width": 1360, "height": 900})
    page.goto(f"{live_app}/books?format=KFX&audiobook=yes&review=no&view=list")

    assert page.get_by_label("Book results").is_visible()
    assert page.get_by_role("button", name="Apply").is_visible()

    page.set_viewport_size({"width": 390, "height": 844})
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow == 0


def test_audiobook_player_layout_has_no_mobile_overflow(page, live_app, app, tmp_path):
    audio_file = tmp_path / "player.mp3"
    audio_file.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x21audio-payload")
    with app.app_context():
        book = Book(
            title="Player Layout",
            normalized_title="player layout",
            authors=["Example Author"],
            status="reading",
        )
        audiobook = AudiobookEdition(
            book=book,
            title="Player Layout",
            narrator="Example Narrator",
            verification_status="verified",
        )
        audiobook.assets.append(
            AudiobookAsset(
                format="MP3",
                source_type="local",
                local_path=str(audio_file),
                source_reference=str(audio_file),
                filename=audio_file.name,
                file_hash="player-layout-hash",
            )
        )
        db.session.add(book)
        db.session.commit()
        book_id = book.id

    sign_in(page, live_app)
    page.set_viewport_size({"width": 1360, "height": 900})
    page.goto(f"{live_app}/books/{book_id}")

    assert page.locator("[data-book-audio-player]").is_visible()
    assert page.locator("audio").is_visible()

    page.set_viewport_size({"width": 390, "height": 844})
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow == 0


def test_text_asset_runtime_actions_have_no_mobile_overflow(
    page, live_app, app, tmp_path
):
    pdf_file = tmp_path / "text-runtime.pdf"
    pdf_file.write_bytes(b"%PDF-1.7\nbrowser runtime pdf")
    kfx_file = tmp_path / "text-runtime.kfx"
    kfx_file.write_bytes(b"CONTBOUNDARY browser runtime kfx")
    with app.app_context():
        book = Book(
            title="Text Runtime",
            normalized_title="text runtime",
            authors=["Example Author"],
            status="reading",
        )
        edition = BookEdition(book=book, title="Text Runtime", primary=True)
        edition.text_assets.extend(
            [
                TextAsset(
                    format="PDF",
                    source_type="local",
                    local_path=str(pdf_file),
                    source_reference=str(pdf_file),
                    filename=pdf_file.name,
                    file_hash="browser-runtime-pdf-hash",
                    verification_status="verified",
                ),
                TextAsset(
                    format="KFX",
                    source_type="local",
                    local_path=str(kfx_file),
                    source_reference=str(kfx_file),
                    filename=kfx_file.name,
                    file_hash="browser-runtime-kfx-hash",
                    verification_status="likely",
                    preferred_for_kindle=True,
                ),
            ]
        )
        db.session.add(book)
        db.session.commit()
        book_id = book.id

    sign_in(page, live_app)
    page.set_viewport_size({"width": 1360, "height": 900})
    page.goto(f"{live_app}/books/{book_id}")

    assert page.get_by_role("link", name="Open PDF").is_visible()
    assert page.get_by_role("link", name="Kindle file").is_visible()
    html = page.content()
    assert str(pdf_file) not in html
    assert str(kfx_file) not in html

    page.set_viewport_size({"width": 390, "height": 844})
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow == 0


def test_epub_reader_layout_has_no_mobile_overflow(page, live_app, app, tmp_path):
    epub_file = tmp_path / "reader-layout.epub"
    write_reader_epub(
        epub_file,
        [
            ("Quiet Opening", ["A local reader paragraph for the browser test."]),
            ("Second Passage", ["More extracted chapter text for layout checks."]),
        ],
    )
    with app.app_context():
        book = Book(
            title="Reader Layout",
            normalized_title="reader layout",
            authors=["Example Author"],
            status="reading",
        )
        edition = BookEdition(book=book, title="Reader Layout", primary=True)
        asset = TextAsset(
            format="EPUB",
            source_type="local",
            local_path=str(epub_file),
            source_reference=str(epub_file),
            filename=epub_file.name,
            file_hash="reader-layout-epub-hash",
            verification_status="verified",
        )
        edition.text_assets.append(asset)
        db.session.add(book)
        db.session.commit()
        book_id = book.id
        asset_id = asset.id

    sign_in(page, live_app)
    page.set_viewport_size({"width": 1360, "height": 900})
    page.goto(f"{live_app}/books/{book_id}")

    assert page.get_by_role("link", name="Read EPUB").is_visible()
    page.get_by_role("link", name="Read EPUB").click()
    page.wait_for_url(f"{live_app}/books/{book_id}/assets/{asset_id}/reader")

    assert page.get_by_role("heading", name="Reader Layout").is_visible()
    assert page.get_by_role("heading", name="Read the local EPUB without leaving Dragon").is_visible()
    assert page.get_by_role("link", name="1. Quiet Opening").is_visible()
    assert page.get_by_text("A local reader paragraph for the browser test.").is_visible()
    html = page.content()
    assert str(epub_file) not in html

    page.set_viewport_size({"width": 390, "height": 844})
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow == 0


def test_kindle_export_layout_has_no_mobile_overflow(page, live_app, app, tmp_path):
    kfx_file = tmp_path / "layout-export.kfx"
    kfx_file.write_bytes(b"CONTBOUNDARY layout export")
    azw3_file = tmp_path / "layout-export.azw3"
    azw3_file.write_bytes(b"BOOKMOBI layout export")
    with app.app_context():
        book = Book(
            title="Kindle Layout",
            normalized_title="kindle layout",
            authors=["Example Author"],
            status="reading",
        )
        edition = BookEdition(book=book, title="Kindle Layout", language="en", primary=True)
        kfx_asset = TextAsset(
            format="KFX",
            source_type="local",
            local_path=str(kfx_file),
            source_reference=str(kfx_file),
            filename=kfx_file.name,
            file_hash="layout-export-kfx-hash",
            verification_status="likely",
        )
        azw3_asset = TextAsset(
            format="AZW3",
            source_type="local",
            local_path=str(azw3_file),
            source_reference=str(azw3_file),
            filename=azw3_file.name,
            file_hash="layout-export-azw3-hash",
            verification_status="verified",
        )
        edition.text_assets.extend([azw3_asset, kfx_asset])
        db.session.add(book)
        db.session.commit()
        book_id = book.id

    sign_in(page, live_app)
    page.set_viewport_size({"width": 1360, "height": 900})
    page.goto(f"{live_app}/books/{book_id}")

    assert page.get_by_role("link", name="Kindle export").is_visible()
    page.get_by_role("link", name="Kindle export").click()
    page.wait_for_url(f"{live_app}/books/{book_id}/kindle-export")

    assert page.get_by_role("heading", name="Kindle Layout").is_visible()
    assert page.get_by_role("heading", name="Prepare the local file you actually want to send").is_visible()
    assert page.get_by_role("link", name="Download recommended").is_visible()
    assert page.get_by_role("heading", name="KFX · layout-export.kfx").is_visible()
    html = page.content()
    assert str(kfx_file) not in html
    assert str(azw3_file) not in html

    page.set_viewport_size({"width": 390, "height": 844})
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow == 0
