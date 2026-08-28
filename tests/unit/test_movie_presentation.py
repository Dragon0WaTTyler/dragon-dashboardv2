from __future__ import annotations

from app.extensions import db
from app.auth.models import User
from app.movies.models import Movie
from app.movies.presentation import canonical_detail_presentation
from flask_login import login_user


def test_canonical_detail_contract_keeps_catalog_shared_and_personal_state_separate():
    local = {
        "id": "mov_local",
        "media_type": "movie",
        "title": "Shared Title",
        "original_title": "Original Shared Title",
        "year": 2024,
        "external_ids": {"tmdb_id": "44"},
        "poster_url": "https://image.example/poster.jpg",
        "backdrop_url": "https://image.example/backdrop.jpg",
        "overview": "A saved title.",
        "tmdb_rating": 8.4,
        "genres": [{"name": "Drama"}],
        "cast": [{"name": "Actor"}],
        "trailers": [{"name": "Trailer", "url": "https://www.youtube.com/watch?v=abc"}],
        "reviews": [{"author": "Member", "content": "Useful review"}],
        "related": [
            {"tmdb_id": 44, "media_type": "movie", "title": "Shared Title"},
            {"tmdb_id": 45, "media_type": "movie", "title": "Related"},
        ],
        "status": "watching",
        "is_favorite": True,
        "personal_score": 4.5,
        "progress": {"percent": 40},
    }
    discovery = {
        "tmdb_id": 44,
        "media_type": "movie",
        "title": "Shared Title",
        "original_title": "Original Shared Title",
        "year": 2024,
        "poster_url": "https://image.example/poster.jpg",
        "overview": "A saved title.",
        "rating": 8.4,
        "genres": [{"name": "Drama"}],
        "cast": [{"name": "Actor"}],
        "tmdb_detail": {
            "backdrop_url": "https://image.example/backdrop.jpg",
            "trailers": [{"name": "Trailer", "url": "https://www.youtube.com/watch?v=abc"}],
            "reviews": [{"author": "Member", "content": "Useful review"}],
            "similar": [{"tmdb_id": 45, "media_type": "movie", "title": "Related"}],
        },
    }

    saved = canonical_detail_presentation(
        local,
        is_saved=True,
        personal={"lists": [{"id": "list_1", "title": "Friday"}]},
        playback={"can_play": True, "configured_sources_present": True},
    )
    preview = canonical_detail_presentation(
        discovery,
        is_saved=False,
        playback={"can_preview": True},
    )

    assert saved["catalog"] == preview["catalog"]
    assert saved["catalog"]["trailers"][0]["thumbnail_url"].endswith("/abc/hqdefault.jpg")
    assert saved["catalog"]["related"] == [
        {"tmdb_id": 45, "media_type": "movie", "title": "Related"}
    ]
    assert saved["personal"] == {
        "is_saved": True,
        "status": "watching",
        "favorite": True,
        "personal_rating": 4.5,
        "lists": [{"id": "list_1", "title": "Friday"}],
        "progress": {"percent": 40},
    }
    assert preview["personal"] == {
        "is_saved": False,
        "status": None,
        "favorite": False,
        "personal_rating": None,
        "lists": [],
        "progress": None,
    }
    assert saved["playback"]["can_play"] is True
    assert preview["playback"] == {
        "can_play": False,
        "can_preview": True,
        "configured_sources_present": False,
    }


def test_saved_movie_detail_renders_the_shared_catalog_component(app, admin_user):
    with app.app_context():
        movie = Movie(
            title="Canonical Detail",
            normalized_title="canonical detail",
            media_type="movie",
            status="want_to_watch",
            external_ids={"tmdb_id": "611"},
            metadata_state={
                "tmdb_detail": {
                    "trailers": [
                        {"name": "Trailer", "url": "https://www.youtube.com/watch?v=canonical"}
                    ],
                    "reviews": [{"author": "Member", "content": "A review"}],
                    "similar": [
                        {"tmdb_id": 612, "media_type": "movie", "title": "Related detail"}
                    ],
                }
            },
            cast=[{"name": "Actor"}],
        )
        db.session.add(movie)
        db.session.commit()
        movie_id = movie.id

    with app.test_request_context(f"/movies/{movie_id}"):
        login_user(db.session.get(User, 1))
        page = app.view_functions["movies.detail"](movie_id)

    assert page.count('data-detail-catalog-identity') == 1
    assert page.count('data-detail-catalog-modules') == 1
    assert "Related detail" in page
