from pathlib import Path

from tests.conftest import csrf_from


def test_control_center_reports_sections_without_rendering_secrets(authenticated_client, app):
    app.config.update(
        DRAGON_YOUTUBE_API_KEY="never-render-this-key",
        DRAGON_TMDB_API_KEY="never-render-this-token",
    )
    response = authenticated_client.get("/admin")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Control Center" in body
    assert "Section registry" in body
    assert "Movies" in body
    assert "never-render-this-key" not in body
    assert "never-render-this-token" not in body


def test_section_preferences_change_navigation_today_and_module_features(
    authenticated_client,
):
    page = authenticated_client.get("/admin/sections/movies")
    assert page.status_code == 200
    assert "Shape this section" in page.get_data(as_text=True)

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
            "show_in_navigation": "on",
            "show_on_today": "on",
            "feature_recommendation": "on",
        },
        follow_redirects=False,
    )
    assert restored.status_code == 302
    assert "Recommended movie" in authenticated_client.get("/").get_data(as_text=True)
    assert "What should I watch?" in authenticated_client.get("/movies").get_data(as_text=True)


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


def test_movies_control_center_reports_and_clears_inactive_playback_cache(
    authenticated_client, app
):
    page = authenticated_client.get("/admin/sections/movies")
    assert "Torrent cache" in page.get_data(as_text=True)
    cache_file = (
        Path(app.instance_path)
        / "playback-cache"
        / "torrents"
        / ("a" * 40)
        / "fixture.mp4"
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
