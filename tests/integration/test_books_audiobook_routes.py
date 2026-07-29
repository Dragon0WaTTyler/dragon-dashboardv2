from app.books.models import AudiobookAsset, AudiobookEdition, Book, BookEdition, TextAsset
from app.extensions import db
from tests.conftest import csrf_from


def seed_audio_candidate_book(app) -> str:
    with app.app_context():
        book = Book(
            title="Audio Candidate Book",
            normalized_title="audio candidate book",
            authors=["Example Author"],
            status="wishlist",
        )
        edition = BookEdition(book=book, title="Audio Candidate Book", primary=True)
        edition.text_assets.append(
            TextAsset(
                format="KFX",
                filename="audio-candidate.kfx",
                file_hash="audio-candidate-text-hash",
                verification_status="verified",
            )
        )
        db.session.add(book)
        db.session.commit()
        return book.id


def test_audiobook_candidate_review_does_not_create_assets_or_change_text_format(
    authenticated_client, app
):
    book_id = seed_audio_candidate_book(app)
    page = authenticated_client.get(f"/books/{book_id}")

    add_response = authenticated_client.post(
        f"/books/{book_id}/audiobooks/candidates",
        data={
            "csrf_token": csrf_from(page),
            "title": "Audio Candidate Book",
            "language": "English",
            "narrator": "Example Narrator",
            "publisher": "Audio Press",
            "release_year": "2024",
            "duration_minutes": "615",
            "chapter_count": "18",
            "abridgement_type": "unabridged",
            "production_type": "single_narrator",
        },
        follow_redirects=True,
    )
    add_html = add_response.get_data(as_text=True)

    assert "Audiobook candidate saved for review." in add_html
    assert "Example Narrator" in add_html
    assert "Needs Review" in add_html
    assert "10h 15m" in add_html
    assert "Preferred KFX" in add_html

    with app.app_context():
        audiobook = db.session.scalar(db.select(AudiobookEdition))
        assert audiobook is not None
        assert audiobook.title == "Audio Candidate Book"
        assert audiobook.narrator == "Example Narrator"
        assert audiobook.verification_status == "needs_review"
        assert audiobook.duration_seconds == 36_900
        assert db.session.scalars(db.select(AudiobookAsset)).all() == []
        assert len(db.session.scalars(db.select(TextAsset)).all()) == 1
        audiobook_id = audiobook.id

    confirm_response = authenticated_client.post(
        f"/books/{book_id}/audiobooks/{audiobook_id}/confirm",
        data={"csrf_token": csrf_from(add_response)},
        follow_redirects=True,
    )
    confirm_html = confirm_response.get_data(as_text=True)

    assert "Audiobook candidate confirmed." in confirm_html
    assert "Verified" in confirm_html
    assert f"/audiobooks/{audiobook_id}/confirm" not in confirm_html

    with app.app_context():
        audiobook = db.session.get(AudiobookEdition, audiobook_id)
        assert audiobook.verification_status == "verified"
        assert db.session.scalars(db.select(AudiobookAsset)).all() == []


def test_audiobook_candidate_rejects_duplicates(authenticated_client, app):
    book_id = seed_audio_candidate_book(app)
    page = authenticated_client.get(f"/books/{book_id}")
    data = {
        "csrf_token": csrf_from(page),
        "title": "Audio Candidate Book",
        "language": "English",
        "narrator": "Example Narrator",
        "publisher": "Audio Press",
    }

    first = authenticated_client.post(
        f"/books/{book_id}/audiobooks/candidates",
        data=data,
        follow_redirects=True,
    )
    duplicate = authenticated_client.post(
        f"/books/{book_id}/audiobooks/candidates",
        data={**data, "csrf_token": csrf_from(first)},
        follow_redirects=True,
    )

    assert "This audiobook candidate already exists." in duplicate.get_data(as_text=True)
    with app.app_context():
        assert len(db.session.scalars(db.select(AudiobookEdition)).all()) == 1


def test_local_audiobook_asset_streams_by_id_and_saves_progress(
    authenticated_client, app, tmp_path
):
    audio_file = tmp_path / "sample.mp3"
    audio_file.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x21audio-payload")
    with app.app_context():
        book = Book(
            title="Runtime Audio Book",
            normalized_title="runtime audio book",
            authors=["Example Author"],
            status="reading",
        )
        audiobook = AudiobookEdition(
            book=book,
            title="Runtime Audio Book",
            narrator="Runtime Narrator",
            duration_seconds=1200,
            verification_status="verified",
        )
        asset = AudiobookAsset(
            audiobook=audiobook,
            format="MP3",
            source_type="local",
            local_path=str(audio_file),
            source_reference=str(audio_file),
            filename=audio_file.name,
            file_size=audio_file.stat().st_size,
            file_hash="runtime-audio-hash",
            availability_status="available",
        )
        db.session.add(book)
        db.session.commit()
        book_id = book.id
        audiobook_id = audiobook.id
        asset_id = asset.id

    page = authenticated_client.get(f"/books/{book_id}")
    html = page.get_data(as_text=True)
    assert str(audio_file) not in html
    assert f"/books/{book_id}/audiobooks/assets/{asset_id}/stream" not in html
    assert "book-audio.js" not in html

    stream = authenticated_client.get(
        f"/books/{book_id}/audiobooks/assets/{asset_id}/stream",
        headers={"Range": "bytes=0-2"},
    )
    assert stream.status_code in {200, 206}
    assert stream.headers["Content-Type"].startswith("audio/mpeg")
    assert stream.get_data().startswith(b"ID3")

    progress = authenticated_client.post(
        f"/books/{book_id}/audiobooks/{audiobook_id}/progress",
        json={
            "position_seconds": 615,
            "duration_seconds": 1200,
            "current_chapter": 4,
            "playback_speed": 1.25,
            "completed": False,
        },
        headers={"X-CSRFToken": csrf_from(page)},
    )
    assert progress.status_code == 200
    assert progress.get_json()["progress"]["position_seconds"] == 615

    with app.app_context():
        book = db.session.get(Book, book_id)
        saved = book.metadata_state["listening_progress"][audiobook_id]
        assert saved["position_seconds"] == 615
        assert saved["duration_seconds"] == 1200
        assert saved["current_chapter"] == 4
        assert saved["playback_speed"] == 1.25
        assert saved["completed"] is False

    refreshed = authenticated_client.get(f"/books/{book_id}").get_data(as_text=True)
    assert "Resume 10m" not in refreshed
