import re
from datetime import UTC, datetime

from app.extensions import db
from app.personal_tv.services import PersonalTVService
from app.youtube.models import YouTubeVideo


def csrf_header(client):
    page = client.get("/my-tv")
    match = re.search(r'<meta name="csrf-token" content="([^"]+)">', page.get_data(as_text=True))
    assert match is not None
    token = match.group(1)
    return {"X-CSRFToken": token}


def seed_video(index, duration=1200, group="Science"):
    return YouTubeVideo(
        external_id=f"video-{index}",
        source="pockettube",
        group_name=group,
        channel_title=f"Creator {index}",
        title=f"Video {index}",
        duration_seconds=duration,
        published_at=datetime(2026, 8, 20, tzinfo=UTC),
    )


def test_personal_tv_builds_resumable_youtube_session(authenticated_client, app):
    with app.app_context():
        db.session.add_all(
            [seed_video(1, 1800), seed_video(2, 1500), seed_video(3, 1200, "History")]
        )
        db.session.commit()
    page = authenticated_client.get("/my-tv")
    assert page.status_code == 200
    assert "Start My TV" in page.get_data(as_text=True)
    response = authenticated_client.post(
        "/my-tv/api/sessions",
        json={
            "duration_minutes": 60,
            "groups": ["Science"],
            "avoid_watched": True,
            "no_shorts": True,
        },
        headers=csrf_header(authenticated_client),
    )
    assert response.status_code == 201
    session = response.get_json()["session"]
    assert session["state"] == "playing"
    assert session["items"] and all(item["source"] == "youtube" for item in session["items"])
    skipped = authenticated_client.post(
        f"/my-tv/api/sessions/{session['id']}/skip",
        json={},
        headers=csrf_header(authenticated_client),
    ).get_json()["session"]
    assert skipped["items"][0]["state"] == "skipped"
    active = authenticated_client.get("/my-tv/api/bootstrap").get_json()["active_session"]
    assert active["id"] == session["id"]
    finished = authenticated_client.post(
        f"/my-tv/api/sessions/{session['id']}/complete_item",
        json={},
        headers=csrf_header(authenticated_client),
    ).get_json()["session"]
    completed_id = finished["items"][finished["current_item_index"]]["candidate_id"]
    with app.app_context():
        assert db.session.get(YouTubeVideo, completed_id).watched is True


def test_personal_tv_recovers_and_keeps_explicit_feedback(authenticated_client, app):
    with app.app_context():
        db.session.add_all(
            [
                seed_video(10, 1500, "Science"),
                seed_video(11, 1320, "Science"),
                seed_video(12, 1260, "History"),
                seed_video(13, 1200, "Science"),
                seed_video(14, 1140, "History"),
            ]
        )
        db.session.commit()
    headers = csrf_header(authenticated_client)
    created = authenticated_client.post(
        "/my-tv/api/sessions",
        json={"duration_minutes": 60, "groups": ["Science"]},
        headers=headers,
    ).get_json()["session"]
    replaced = authenticated_client.post(
        f"/my-tv/api/sessions/{created['id']}/replace",
        json={"reason": "unavailable"},
        headers=headers,
    )
    assert replaced.status_code == 200
    replacement = replaced.get_json()["session"]
    assert replacement["state"] == "playing"
    assert replacement["items"][0]["candidate_id"] != created["items"][0]["candidate_id"]

    feedback = authenticated_client.post(
        f"/my-tv/api/sessions/{created['id']}/feedback",
        json={"kind": "hide_channel"},
        headers=headers,
    )
    assert feedback.status_code == 200
    profile = feedback.get_json()["profile"]
    assert profile["explicit"]["blocked_creators"]

    preference = authenticated_client.patch(
        "/my-tv/api/preferences",
        json={
            "preferred_topics": ["Science"],
            "preferred_languages": ["en", "ar"],
            "discovery_level": "low",
        },
        headers=headers,
    )
    assert preference.status_code == 200
    assert preference.get_json()["preferences"]["discovery_level"] == "low"

    intent = authenticated_client.post(
        "/my-tv/api/intent",
        json={"text": "90 minutes of calm science, no Shorts"},
        headers=headers,
    )
    assert intent.status_code == 200
    assert intent.get_json()["intent"]["duration_minutes"] == 90
    assert intent.get_json()["intent"]["no_shorts"] is True

    synced = authenticated_client.put(
        "/my-tv/api/sync-state",
        json={
            "state": {
                "preferences": {"source_quality": {"youtube": 12, "iptv": -5}},
                "feedback": [
                    {
                        "candidate_id": "remote-item",
                        "creator": "Remote channel",
                        "kind": "more_like_this",
                        "reason": "",
                    }
                ],
            }
        },
        headers=headers,
    )
    assert synced.status_code == 200
    assert synced.get_json()["state"]["preferences"]["source_quality"]["youtube"] == 12


def test_personal_tv_prepared_programme_starts_as_a_new_session(authenticated_client, app):
    with app.app_context():
        db.session.add_all([seed_video(20, 1800), seed_video(21, 1500, "History")])
        db.session.commit()
    headers = csrf_header(authenticated_client)
    prepared = authenticated_client.post(
        "/my-tv/api/programs",
        json={
            "name": "Tonight on My TV",
            "starts_at": "2026-08-23T19:00:00Z",
            "request": {"duration_minutes": 60, "groups": ["Science"]},
        },
        headers=headers,
    )
    assert prepared.status_code == 201
    program_id = prepared.get_json()["program"]["id"]
    started = authenticated_client.post(
        f"/my-tv/api/programs/{program_id}/start",
        json={},
        headers=headers,
    )
    assert started.status_code == 200
    assert started.get_json()["session"]["state"] == "playing"


def test_personal_tv_can_prepare_a_daypart_channel(authenticated_client, app):
    headers = csrf_header(authenticated_client)
    saved = authenticated_client.patch(
        "/my-tv/api/preferences",
        json={
            "daypart_profiles": {
                "evening": {
                    "name": "Evening Science",
                    "start": "23:59",
                    "duration_minutes": 60,
                    "groups": ["Science"],
                }
            }
        },
        headers=headers,
    )
    assert saved.status_code == 200
    with app.app_context():
        programs = PersonalTVService.generate_daypart_programs(
            datetime(2026, 8, 23, 18, 0, tzinfo=UTC)
        )
    assert programs
