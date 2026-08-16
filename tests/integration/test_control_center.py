from pathlib import Path

from app.extensions import db
from app.movies.models import Movie
from tests.conftest import csrf_from


def test_control_center_reports_sections_without_rendering_secrets(authenticated_client, app):
    app.config.update(
        DRAGON_YOUTUBE_API_KEY="never-render-this-key",
        DRAGON_TMDB_API_KEY="never-render-this-token",
    )
    response = authenticated_client.get("/admin")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Settings" in body
    assert "What do you want to change?" in body
    assert "Movies" in body
    assert "never-render-this-key" not in body
    assert "never-render-this-token" not in body


def test_section_preferences_change_navigation_today_and_module_features(
    authenticated_client,
):
    page = authenticated_client.get("/admin/sections/movies")
    assert page.status_code == 200
    assert "Access &amp; placement" in page.get_data(as_text=True)

    response = authenticated_client.post(
        "/admin/sections/movies/preferences",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Movies preferences saved" in response.get_data(as_text=True)

    home = authenticated_client.get("/").get_data(as_text=True)
    movies = authenticated_client.get("/movies").get_data(as_text=True)
    assert ">Movies</a>" not in home
    assert "Recommended movie" not in home
    assert "What should I watch?" not in movies

    detail = authenticated_client.get("/admin/sections/movies")
    restored = authenticated_client.post(
        "/admin/sections/movies/preferences",
        data={
            "csrf_token": csrf_from(detail),
            "enabled": "on",
            "show_in_navigation": "on",
            "show_on_home": "on",
            "default_view": "watching",
            "default_sort": "recent",
            "feature_recommendation": "on",
        },
        follow_redirects=False,
    )
    assert restored.status_code == 302
    assert "Recommended movie" in authenticated_client.get("/").get_data(as_text=True)
    assert ">Movies</a>" in authenticated_client.get("/").get_data(as_text=True)


def test_unknown_section_and_unsafe_operation_return_are_rejected(authenticated_client):
    assert authenticated_client.get("/admin/sections/not-a-module").status_code == 404
    page = authenticated_client.get("/admin")
    response = authenticated_client.post(
        "/admin/run",
        data={
            "csrf_token": csrf_from(page),
            "kind": "diagnose",
            "domain": "movies",
            "next": "https://evil.example/steal",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/admin/operations/")


def test_general_and_home_preferences_are_saved_and_rendered(authenticated_client):
    page = authenticated_client.get("/admin/general")
    token = csrf_from(page)
    general = authenticated_client.post(
        "/admin/general/preferences",
        data={
            "csrf_token": token,
            "appearance": "light",
            "layout_density": "compact",
            "language": "ar",
            "start_destination": "last_section",
            "remember_filters": "on",
        },
        follow_redirects=True,
    )
    assert 'lang="ar"' in general.get_data(as_text=True)
    assert 'data-appearance="light"' in general.get_data(as_text=True)
    assert 'data-density="compact"' in general.get_data(as_text=True)

    home_page = authenticated_client.get("/admin/home")
    home = authenticated_client.post(
        "/admin/home/preferences",
        data={
            "csrf_token": csrf_from(home_page),
            "layout_order": "favorite_iptv,recommended_movie",
            "home_favorite_iptv_enabled": "on",
            "home_recommended_movie_enabled": "on",
        },
        follow_redirects=True,
    )
    body = home.get_data(as_text=True)
    assert 'value="favorite_iptv,recommended_movie,continue_watching' in body


def test_news_settings_only_render_news_related_cards(authenticated_client):
    response = authenticated_client.get("/admin/sections/reading")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "News reading" in body
    assert "Source &amp; refresh" in body
    assert "Torrent cache" not in body
    assert "Favorites first" not in body


def test_movies_news_and_iptv_defaults_persist_and_drive_their_pages(authenticated_client, app):
    with app.app_context():
        db.session.add_all(
            [
                Movie(
                    title="Zulu wishlist", normalized_title="zulu wishlist", status="want_to_watch"
                ),
                Movie(
                    title="Alpha wishlist",
                    normalized_title="alpha wishlist",
                    status="want_to_watch",
                ),
                Movie(title="Active title", normalized_title="active title", status="watching"),
            ]
        )
        db.session.commit()
    movies_page = authenticated_client.get("/admin/sections/movies")
    movies_saved = authenticated_client.post(
        "/admin/sections/movies/preferences",
        data={
            "csrf_token": csrf_from(movies_page),
            "enabled": "on",
            "show_in_navigation": "on",
            "show_on_home": "on",
            "default_view": "wishlist",
            "default_sort": "title",
            "feature_recommendation": "on",
            "feature_progress": "on",
            "feature_personal_score": "on",
        },
        follow_redirects=True,
    )
    assert 'value="wishlist" selected' in movies_saved.get_data(as_text=True)
    movies = authenticated_client.get("/movies").get_data(as_text=True)
    assert 'value="want_to_watch" selected' in movies
    assert 'value="title_asc" selected' in movies
    assert "Alpha wishlist" in movies
    assert "Zulu wishlist" in movies
    assert "Active title" not in movies
    assert movies.index("Alpha wishlist") < movies.index("Zulu wishlist")

    news_page = authenticated_client.get("/admin/sections/reading")
    news_saved = authenticated_client.post(
        "/admin/sections/reading/preferences",
        data={
            "csrf_token": csrf_from(news_page),
            "enabled": "on",
            "show_in_navigation": "on",
            "show_on_home": "on",
            "default_view": "saved",
            "default_sort": "title",
            "feature_source_health": "on",
            "feature_reader_mode": "on",
            "feature_images": "on",
            "feature_source": "on",
            "feature_publication_date": "on",
            "feature_mark_read_automatically": "on",
        },
        follow_redirects=True,
    )
    assert 'value="saved" selected' in news_saved.get_data(as_text=True)
    news = authenticated_client.get("/reading").get_data(as_text=True)
    assert 'name="feed" value="saved"' in news
    assert 'value="title" selected' in news

    tv_page = authenticated_client.get("/admin/sections/mytv")
    tv_saved = authenticated_client.post(
        "/admin/sections/mytv/preferences",
        data={
            "csrf_token": csrf_from(tv_page),
            "enabled": "on",
            "show_in_navigation": "on",
            "show_on_home": "on",
            "default_view": "favorites",
            "default_sort": "recent",
            "favorites_first": "on",
        },
        follow_redirects=True,
    )
    assert 'value="favorites" selected' in tv_saved.get_data(as_text=True)
    tv = authenticated_client.get("/my-tv").get_data(as_text=True)
    assert 'data-default-view="favorites"' in tv
    assert 'data-default-sort="recent"' in tv
    assert 'data-favorites-first="true"' in tv


def test_movies_control_center_reports_and_clears_inactive_playback_cache(
    authenticated_client, app
):
    page = authenticated_client.get("/admin/sections/movies")
    assert "Torrent cache" in page.get_data(as_text=True)
    cache_file = (
        Path(app.instance_path) / "playback-cache" / "torrents" / ("a" * 40) / "fixture.mp4"
    )
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(b"inactive-cache")

    response = authenticated_client.post(
        "/admin/sections/movies/playback-cache/clear",
        data={"csrf_token": csrf_from(page)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "inactive playback cache" in response.get_data(as_text=True)
    assert not cache_file.exists()
