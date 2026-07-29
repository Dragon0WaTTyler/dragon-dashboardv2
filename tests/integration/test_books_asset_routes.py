from html import escape
from zipfile import ZIP_STORED, ZipFile

from app.books.models import AudiobookAsset, Book, BookEdition, TextAsset
from app.extensions import db
from tests.conftest import csrf_from


def write_epub(path):
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr("META-INF/container.xml", "<container />")


def write_reader_epub(path, chapters: list[tuple[str, list[str]]]):
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            (
                "<?xml version='1.0'?>"
                "<container xmlns='urn:oasis:names:tc:opendocument:xmlns:container' "
                "version='1.0'><rootfiles><rootfile full-path='OEBPS/content.opf' "
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
                f"OEBPS/chapter{index}.xhtml",
                (
                    "<html xmlns='http://www.w3.org/1999/xhtml'><head>"
                    f"<title>{escape(title)}</title><script>bad()</script></head>"
                    f"<body><h1>{escape(title)}</h1>{body}</body></html>"
                ),
            )
        archive.writestr(
            "OEBPS/content.opf",
            (
                "<package xmlns='http://www.idpf.org/2007/opf' version='3.0'>"
                f"<manifest>{''.join(manifest_items)}</manifest>"
                f"<spine>{''.join(spine_items)}</spine></package>"
            ),
        )


def seed_book(app) -> str:
    with app.app_context():
        book = Book(
            title="Asset Book",
            normalized_title="asset book",
            authors=["Example Author"],
            status="wishlist",
        )
        db.session.add(book)
        db.session.commit()
        return book.id


def seed_book_with_text_asset(app) -> str:
    with app.app_context():
        book = Book(
            title="Audio Book",
            normalized_title="audio book",
            authors=["Example Author"],
            status="reading",
        )
        edition = BookEdition(book=book, title="Audio Book", primary=True)
        edition.text_assets.append(
            TextAsset(
                format="EPUB",
                source_type="local",
                filename="audio-book.epub",
                file_hash="existing-text-hash",
                verification_status="verified",
                preferred_for_kindle=True,
            )
        )
        db.session.add(book)
        db.session.commit()
        return book.id


def seed_book_with_runtime_assets(app, pdf_path, kfx_path) -> dict[str, str]:
    with app.app_context():
        book = Book(
            title="Runtime Text Book",
            normalized_title="runtime text book",
            authors=["Example Author"],
            status="reading",
        )
        edition = BookEdition(book=book, title="Runtime Text Book", primary=True)
        pdf_asset = TextAsset(
            format="PDF",
            source_type="local",
            local_path=str(pdf_path),
            source_reference=str(pdf_path),
            filename=pdf_path.name,
            file_size=pdf_path.stat().st_size,
            file_hash="runtime-pdf-hash",
            verification_status="verified",
        )
        kfx_asset = TextAsset(
            format="KFX",
            source_type="local",
            local_path=str(kfx_path),
            source_reference=str(kfx_path),
            filename=kfx_path.name,
            file_size=kfx_path.stat().st_size,
            file_hash="runtime-kfx-hash",
            verification_status="likely",
            preferred_for_kindle=True,
        )
        edition.text_assets.extend([pdf_asset, kfx_asset])
        db.session.add(book)
        db.session.commit()
        return {"book": book.id, "pdf": pdf_asset.id, "kfx": kfx_asset.id}


def seed_book_with_epub_reader_asset(app, epub_path) -> dict[str, str]:
    with app.app_context():
        book = Book(
            title="Reader Text Book",
            normalized_title="reader text book",
            authors=["Example Author"],
            status="reading",
        )
        edition = BookEdition(book=book, title="Reader Text Book", primary=True)
        asset = TextAsset(
            format="EPUB",
            source_type="local",
            local_path=str(epub_path),
            source_reference=str(epub_path),
            filename=epub_path.name,
            file_size=epub_path.stat().st_size,
            file_hash="reader-epub-hash",
            verification_status="verified",
        )
        edition.text_assets.append(asset)
        db.session.add(book)
        db.session.commit()
        return {"book": book.id, "epub": asset.id}


def seed_book_with_kindle_export_assets(app, kfx_path, azw3_path, pdf_path) -> dict[str, str]:
    with app.app_context():
        book = Book(
            title="Kindle Export Book",
            normalized_title="kindle export book",
            authors=["Example Author"],
            status="reading",
        )
        edition = BookEdition(
            book=book,
            title="Kindle Export Book",
            language="en",
            primary=True,
        )
        kfx_asset = TextAsset(
            format="KFX",
            source_type="local",
            local_path=str(kfx_path),
            source_reference=str(kfx_path),
            filename=kfx_path.name,
            file_size=kfx_path.stat().st_size,
            file_hash="kindle-export-kfx-hash",
            verification_status="likely",
        )
        azw3_asset = TextAsset(
            format="AZW3",
            source_type="local",
            local_path=str(azw3_path),
            source_reference=str(azw3_path),
            filename=azw3_path.name,
            file_size=azw3_path.stat().st_size,
            file_hash="kindle-export-azw3-hash",
            verification_status="verified",
        )
        rejected_pdf = TextAsset(
            format="PDF",
            source_type="local",
            local_path=str(pdf_path),
            source_reference=str(pdf_path),
            filename=pdf_path.name,
            file_size=pdf_path.stat().st_size,
            file_hash="kindle-export-pdf-hash",
            availability_status="rejected",
            verification_status="verified",
        )
        edition.text_assets.extend([azw3_asset, rejected_pdf, kfx_asset])
        db.session.add(book)
        db.session.commit()
        return {
            "book": book.id,
            "kfx": kfx_asset.id,
            "azw3": azw3_asset.id,
            "pdf": rejected_pdf.id,
        }


def test_local_asset_preview_registers_existing_file_once(
    authenticated_client, app, tmp_path
):
    book_id = seed_book(app)
    epub_path = tmp_path / "asset-book.epub"
    write_epub(epub_path)

    page = authenticated_client.get(f"/books/{book_id}")
    preview_response = authenticated_client.post(
        f"/books/{book_id}/assets/preview",
        data={"csrf_token": csrf_from(page), "local_path": str(epub_path)},
        follow_redirects=True,
    )
    preview_html = preview_response.get_data(as_text=True)

    assert "Local asset ready for review." in preview_html
    assert "asset-book.epub" in preview_html
    assert "Verified Container" in preview_html
    assert "Register asset" in preview_html

    with app.app_context():
        book = db.session.get(Book, book_id)
        assert book.editions == []
        assert db.session.scalars(db.select(TextAsset)).all() == []
        assert book.metadata_state["local_text_asset_preview"]["format"] == "EPUB"

    register_response = authenticated_client.post(
        f"/books/{book_id}/assets/register",
        data={"csrf_token": csrf_from(preview_response)},
        follow_redirects=True,
    )
    register_html = register_response.get_data(as_text=True)

    assert "EPUB asset registered." in register_html
    assert "Best available: EPUB" in register_html
    assert "asset-book.epub" in register_html

    with app.app_context():
        book = db.session.get(Book, book_id)
        assert len(book.editions) == 1
        asset = book.editions[0].text_assets[0]
        assert asset.format == "EPUB"
        assert asset.filename == "asset-book.epub"
        assert asset.local_path == str(epub_path.resolve())
        assert asset.source_type == "local"
        assert asset.verification_status == "verified"
        assert asset.preferred_for_kindle is True
        assert "local_text_asset_preview" not in book.metadata_state
        assert book.metadata_state["last_local_text_asset"]["registered_asset_id"] == asset.id

    duplicate_response = authenticated_client.post(
        f"/books/{book_id}/assets/preview",
        data={"csrf_token": csrf_from(register_response), "local_path": str(epub_path)},
        follow_redirects=True,
    )
    duplicate_html = duplicate_response.get_data(as_text=True)

    assert "Duplicate" in duplicate_html
    assert "Register asset" not in duplicate_html

    blocked_response = authenticated_client.post(
        f"/books/{book_id}/assets/register",
        data={"csrf_token": csrf_from(duplicate_response)},
        follow_redirects=True,
    )
    assert "This file hash is already registered." in blocked_response.get_data(as_text=True)

    with app.app_context():
        assets = db.session.scalars(db.select(TextAsset)).all()
        assert len(assets) == 1


def test_audiobook_asset_registers_separately_from_text_formats(
    authenticated_client, app, tmp_path
):
    book_id = seed_book_with_text_asset(app)
    mp3_path = tmp_path / "audio-book.mp3"
    mp3_path.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x10audio bytes")

    page = authenticated_client.get(f"/books/{book_id}")
    preview_response = authenticated_client.post(
        f"/books/{book_id}/audiobooks/assets/preview",
        data={"csrf_token": csrf_from(page), "local_path": str(mp3_path)},
        follow_redirects=True,
    )
    preview_html = preview_response.get_data(as_text=True)

    assert "Audiobook asset ready for review." in preview_html
    assert "audio-book.mp3" in preview_html
    assert "Verified Header" in preview_html
    assert "Register audio" in preview_html

    with app.app_context():
        book = db.session.get(Book, book_id)
        assert book.audiobooks == []
        assert db.session.scalars(db.select(AudiobookAsset)).all() == []
        assert book.metadata_state["local_audio_asset_preview"]["format"] == "MP3"

    register_response = authenticated_client.post(
        f"/books/{book_id}/audiobooks/assets/register",
        data={"csrf_token": csrf_from(preview_response)},
        follow_redirects=True,
    )
    register_html = register_response.get_data(as_text=True)

    assert "MP3 audiobook asset registered." in register_html
    assert "Best available: EPUB" in register_html
    assert "audio-book.mp3" in register_html

    with app.app_context():
        book = db.session.get(Book, book_id)
        assert len(book.audiobooks) == 1
        audiobook = book.audiobooks[0]
        asset = audiobook.assets[0]
        assert audiobook.title == "Audio Book"
        assert asset.format == "MP3"
        assert asset.filename == "audio-book.mp3"
        assert asset.local_path == str(mp3_path.resolve())
        assert "local_audio_asset_preview" not in book.metadata_state
        assert book.metadata_state["last_local_audio_asset"]["registered_asset_id"] == asset.id

    duplicate_response = authenticated_client.post(
        f"/books/{book_id}/audiobooks/assets/preview",
        data={"csrf_token": csrf_from(register_response), "local_path": str(mp3_path)},
        follow_redirects=True,
    )
    duplicate_html = duplicate_response.get_data(as_text=True)

    assert "Duplicate" in duplicate_html
    assert "Register audio" not in duplicate_html

    blocked_response = authenticated_client.post(
        f"/books/{book_id}/audiobooks/assets/register",
        data={"csrf_token": csrf_from(duplicate_response)},
        follow_redirects=True,
    )
    assert "This audiobook file hash is already registered." in blocked_response.get_data(
        as_text=True
    )

    with app.app_context():
        assets = db.session.scalars(db.select(AudiobookAsset)).all()
        assert len(assets) == 1


def test_text_asset_streams_by_id_without_rendering_local_path(
    authenticated_client, app, tmp_path
):
    pdf_path = tmp_path / "runtime-book.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\nruntime pdf")
    kfx_path = tmp_path / "runtime-book.kfx"
    kfx_path.write_bytes(b"CONTBOUNDARY runtime kfx")
    ids = seed_book_with_runtime_assets(app, pdf_path.resolve(), kfx_path.resolve())

    page = authenticated_client.get(f"/books/{ids['book']}")
    html = page.get_data(as_text=True)

    assert str(pdf_path.resolve()) not in html
    assert str(kfx_path.resolve()) not in html
    assert f"/books/{ids['book']}/assets/{ids['pdf']}/stream" not in html
    assert f"/books/{ids['book']}/assets/{ids['kfx']}/stream" not in html
    assert "Open PDF" not in html
    assert "Kindle file" not in html

    pdf_response = authenticated_client.get(
        f"/books/{ids['book']}/assets/{ids['pdf']}/stream",
        headers={"Range": "bytes=0-3"},
    )
    assert pdf_response.status_code in {200, 206}
    assert pdf_response.headers["Content-Type"].startswith("application/pdf")
    assert "attachment" not in pdf_response.headers.get("Content-Disposition", "")
    assert pdf_response.get_data().startswith(b"%PDF")

    kfx_response = authenticated_client.get(
        f"/books/{ids['book']}/assets/{ids['kfx']}/stream"
    )
    assert kfx_response.status_code == 200
    assert kfx_response.headers["Content-Type"].startswith("application/octet-stream")
    assert "attachment" in kfx_response.headers["Content-Disposition"]
    assert kfx_response.get_data().startswith(b"CONTBOUNDARY")


def test_epub_reader_extracts_safe_text_and_saves_progress(
    authenticated_client, app, tmp_path
):
    epub_path = tmp_path / "reader-book.epub"
    write_reader_epub(
        epub_path,
        [
            ("Opening", ["First reader paragraph.", "Second reader paragraph."]),
            ("Notes", ["Another chapter paragraph."]),
        ],
    )
    ids = seed_book_with_epub_reader_asset(app, epub_path.resolve())

    detail = authenticated_client.get(f"/books/{ids['book']}")
    detail_html = detail.get_data(as_text=True)
    assert str(epub_path.resolve()) not in detail_html
    assert "Read EPUB" not in detail_html
    assert f"/books/{ids['book']}/assets/{ids['epub']}/reader" not in detail_html

    reader = authenticated_client.get(
        f"/books/{ids['book']}/assets/{ids['epub']}/reader"
    )
    reader_html = reader.get_data(as_text=True)
    assert reader.status_code == 200
    assert "Local EPUB reader" in reader_html
    assert "Read the local EPUB without leaving Dragon" in reader_html
    assert "Opening" in reader_html
    assert "First reader paragraph." in reader_html
    assert "Another chapter paragraph." in reader_html
    assert "bad()" not in reader_html
    assert str(epub_path.resolve()) not in reader_html

    progress = authenticated_client.post(
        f"/books/{ids['book']}/assets/{ids['epub']}/reader-progress",
        json={"chapter_index": 1, "scroll_percent": 42.25},
        headers={"X-CSRFToken": csrf_from(detail)},
    )
    assert progress.status_code == 200
    assert progress.json["progress"]["chapter_index"] == 1
    assert progress.json["progress"]["scroll_percent"] == 42.25

    with app.app_context():
        book = db.session.get(Book, ids["book"])
        saved = book.metadata_state["text_reading_progress"][ids["epub"]]
        assert saved["chapter_index"] == 1
        assert saved["scroll_percent"] == 42.25


def test_kindle_export_manifest_prioritizes_transfer_assets_without_paths(
    authenticated_client, app, tmp_path
):
    kfx_path = tmp_path / "kindle-book.kfx"
    kfx_path.write_bytes(b"CONTBOUNDARY kindle export")
    azw3_path = tmp_path / "kindle-book.azw3"
    azw3_path.write_bytes(b"BOOKMOBI kindle export")
    pdf_path = tmp_path / "kindle-book.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\nrejected")
    ids = seed_book_with_kindle_export_assets(
        app, kfx_path.resolve(), azw3_path.resolve(), pdf_path.resolve()
    )

    detail = authenticated_client.get(f"/books/{ids['book']}")
    detail_html = detail.get_data(as_text=True)
    assert "Kindle export" not in detail_html
    assert str(kfx_path.resolve()) not in detail_html

    page = authenticated_client.get(f"/books/{ids['book']}/kindle-export")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "Manual Kindle transfer" in html
    assert "Prepare the local file you actually want to send" in html
    assert "Download recommended" in html
    assert "kindle-book.kfx" in html
    assert "kindle-book.azw3" in html
    assert "kindle-book.pdf" not in html
    assert str(kfx_path.resolve()) not in html
    assert str(azw3_path.resolve()) not in html

    manifest_response = authenticated_client.get(
        f"/books/{ids['book']}/kindle-export/manifest.json"
    )
    manifest = manifest_response.get_json()
    assert manifest_response.status_code == 200
    assert manifest["preferred_format"] == "KFX"
    assert manifest["format_priority"] == ["KFX", "AZW3", "EPUB", "PDF"]
    assert [asset["format"] for asset in manifest["assets"]] == ["KFX", "AZW3"]
    assert manifest["assets"][0]["preferred"] is True
    assert "local_path" not in str(manifest)
    assert str(kfx_path.resolve()) not in str(manifest)

    download = authenticated_client.get(
        f"/books/{ids['book']}/assets/{ids['kfx']}/stream"
    )
    assert download.status_code == 200
    assert download.get_data().startswith(b"CONTBOUNDARY")
