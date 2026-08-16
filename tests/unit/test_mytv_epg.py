from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from sqlalchemy import select

from app.extensions import db
from app.mytv.epg import (
    EPGSyncError,
    EPGSyncService,
    FavoriteChannel,
    now_next_for_ids,
    parse_xmltv,
    status_payload,
)
from app.mytv.models import TVChannelPreference, TVEPGState, TVProgramme

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def guide_xml() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
    <tv>
      <channel id="source-doc">
        <display-name>Al Jazeera Documentary HD</display-name>
      </channel>
      <programme channel="source-doc" start="20260816113000 +0000" stop="20260816123000 +0000">
        <title>Wild Morocco</title>
        <sub-title>Atlas</sub-title>
        <desc>A journey through the Atlas mountains.</desc>
      </programme>
      <programme channel="source-doc" start="20260816123000 +0000" stop="20260816133000 +0000">
        <title>Ocean Stories</title>
      </programme>
      <programme channel="unrelated" start="20260816120000 +0000" stop="20260816130000 +0000">
        <title>Do not save</title>
      </programme>
    </tv>"""


def duplicate_guide_xml() -> bytes:
    slots = "".join(
        f"""
        <programme channel="{{channel}}" start="20260816{hour:02d}0000 +0000"
                   stop="20260816{hour + 1:02d}0000 +0000">
          <title>Shared programme {hour}</title>
        </programme>
        """
        for hour in range(11, 15)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <tv>
      <channel id="source-jazeera">
        <display-name>Al Jazeera Documentary HD</display-name>
      </channel>
      <channel id="source-asharq">
        <display-name>Asharq Documentary HD</display-name>
      </channel>
      {slots.format(channel="source-jazeera")}
      {slots.format(channel="source-asharq")}
    </tv>""".encode()


class FakeResponse:
    def __init__(self, body: bytes, status_code: int = 200):
        self.raw = BytesIO(body)
        self.raw.decode_content = False
        self.status_code = status_code
        self.headers = {"Content-Length": str(len(body))}

    def close(self):
        pass


class FakeSession:
    def __init__(self, body: bytes, status_code: int = 200):
        self.body = body
        self.status_code = status_code

    def get(self, *_args, **_kwargs):
        return FakeResponse(self.body, self.status_code)


def favorite() -> TVChannelPreference:
    return TVChannelPreference(
        preference_key="favorite-doc",
        theme_key="documentary",
        name="Al Jazeera Documentary (1080p) [Geo-blocked]",
        tvg_id="AlJazeeraDocumentary.qa@SD",
        favorite=True,
    )


def asharq_favorite() -> TVChannelPreference:
    return TVChannelPreference(
        preference_key="favorite-asharq",
        theme_key="documentary",
        name="Asharq Documentary (1080p)",
        tvg_id="AsharqDocumentary.sa@SD",
        favorite=True,
    )


def test_xmltv_parser_matches_favorite_name_and_keeps_only_its_window():
    rows, matched = parse_xmltv(
        BytesIO(guide_xml()),
        [FavoriteChannel(favorite().tvg_id, favorite().name)],
        source="test guide",
        now=NOW,
    )

    assert matched == {"AlJazeeraDocumentary.qa@SD"}
    assert [row.title for row in rows] == ["Wild Morocco", "Ocean Stories"]
    assert rows[0].starts_at == datetime(2026, 8, 16, 11, 30, tzinfo=UTC)
    assert rows[0].subtitle == "Atlas"


def test_epg_sync_persists_only_favorite_programmes(app, monkeypatch):
    monkeypatch.setattr("app.mytv.epg.validate_stream_url", lambda value: value)
    with app.app_context():
        app.config["DRAGON_TV_EPG_URLS"] = "https://guide.example/guide.xml"
        db.session.add(favorite())
        db.session.commit()

        result = EPGSyncService(session=FakeSession(guide_xml())).sync()

        assert result == {
            "favorites": 1,
            "matched": 1,
            "programmes": 2,
            "sources": 1,
            "status": "ready",
        }
        rows = list(db.session.scalars(select(TVProgramme).order_by(TVProgramme.starts_at)))
        assert [row.title for row in rows] == ["Wild Morocco", "Ocean Stories"]
        assert {row.tvg_id for row in rows} == {"AlJazeeraDocumentary.qa@SD"}
        state = db.session.get(TVEPGState, 1)
        assert state.status == "ready"
        assert state.matched_channels == 1


def test_epg_sync_rejects_identical_schedules_for_distinct_channels(
    app, monkeypatch
):
    monkeypatch.setattr("app.mytv.epg.validate_stream_url", lambda value: value)
    monkeypatch.setattr("app.mytv.epg.utc_now", lambda: NOW)
    with app.app_context():
        app.config["DRAGON_TV_EPG_URLS"] = "https://guide.example/guide.xml"
        db.session.add_all([favorite(), asharq_favorite()])
        db.session.commit()

        result = EPGSyncService(session=FakeSession(duplicate_guide_xml())).sync()

        assert result["matched"] == 0
        assert result["programmes"] == 0
        assert result["status"] == "partial"
        assert db.session.scalar(select(TVProgramme)) is None
        state = db.session.get(TVEPGState, 1)
        assert state.matched_channels == 0
        assert "duplicated schedules for 2 channels" in state.last_error


def test_epg_failure_preserves_last_saved_schedule(app, monkeypatch):
    monkeypatch.setattr("app.mytv.epg.validate_stream_url", lambda value: value)
    with app.app_context():
        app.config["DRAGON_TV_EPG_URLS"] = "https://guide.example/guide.xml"
        db.session.add(favorite())
        db.session.add(
            TVProgramme(
                tvg_id="AlJazeeraDocumentary.qa@SD",
                title="Saved programme",
                starts_at=NOW,
                ends_at=NOW + timedelta(hours=1),
                source="saved",
                fetched_at=NOW,
            )
        )
        db.session.commit()

        with pytest.raises(EPGSyncError):
            EPGSyncService(session=FakeSession(b"", status_code=503)).sync()

        assert db.session.scalar(select(TVProgramme)).title == "Saved programme"
        assert db.session.get(TVEPGState, 1).status == "error"
        assert EPGSyncService.is_due() is False


def test_targeted_epg_sync_keeps_other_favorite_schedules(app, monkeypatch):
    monkeypatch.setattr("app.mytv.epg.validate_stream_url", lambda value: value)
    with app.app_context():
        app.config["DRAGON_TV_EPG_URLS"] = "https://guide.example/guide.xml"
        db.session.add(favorite())
        db.session.add(
            TVChannelPreference(
                preference_key="other-favorite",
                theme_key="documentary",
                name="Other Channel",
                tvg_id="other.channel",
                favorite=True,
            )
        )
        db.session.add(
            TVProgramme(
                tvg_id="other.channel",
                title="Keep this slot",
                starts_at=NOW,
                ends_at=NOW + timedelta(hours=1),
                source="saved",
                fetched_at=NOW,
            )
        )
        db.session.commit()

        EPGSyncService(session=FakeSession(guide_xml())).sync(
            tvg_ids={"AlJazeeraDocumentary.qa@SD"}
        )

        titles = {
            row.title
            for row in db.session.scalars(select(TVProgramme).order_by(TVProgramme.title))
        }
        assert titles == {"Keep this slot", "Ocean Stories", "Wild Morocco"}
        state = db.session.get(TVEPGState, 1)
        assert state.matched_channels == 2
        assert state.programme_count == 3
        assert state.last_success_at is None
        assert state.source_count == 0
        assert EPGSyncService.is_due() is True


def test_now_next_returns_current_and_upcoming_slots(app):
    with app.app_context():
        db.session.add_all(
            [
                TVProgramme(
                    tvg_id="channel.one",
                    title="Current",
                    starts_at=NOW - timedelta(minutes=20),
                    ends_at=NOW + timedelta(minutes=20),
                    source="test",
                    fetched_at=NOW,
                ),
                TVProgramme(
                    tvg_id="channel.one",
                    title="Next",
                    starts_at=NOW + timedelta(minutes=20),
                    ends_at=NOW + timedelta(hours=1),
                    source="test",
                    fetched_at=NOW,
                ),
            ]
        )
        db.session.commit()

        payload = now_next_for_ids({"channel.one"}, now=NOW)["channel.one"]

        assert payload["now"]["title"] == "Current"
        assert payload["next"]["title"] == "Next"


def test_now_next_hides_existing_ambiguous_duplicate_schedules(app):
    with app.app_context():
        db.session.add_all([favorite(), asharq_favorite()])
        for tvg_id in ("AlJazeeraDocumentary.qa@SD", "AsharqDocumentary.sa@SD"):
            db.session.add_all(
                TVProgramme(
                    tvg_id=tvg_id,
                    title=f"Shared programme {index}",
                    starts_at=NOW + timedelta(hours=index - 1),
                    ends_at=NOW + timedelta(hours=index),
                    source="bad guide",
                    fetched_at=NOW,
                )
                for index in range(5)
            )
        db.session.commit()

        assert (
            now_next_for_ids(
                {"AlJazeeraDocumentary.qa@SD", "AsharqDocumentary.sa@SD"}, now=NOW
            )
            == {}
        )


def test_epg_status_marks_saved_guide_stale(app, monkeypatch):
    monkeypatch.setattr("app.mytv.epg.utc_now", lambda: NOW)
    with app.app_context():
        db.session.add(
            TVEPGState(
                id=1,
                status="ready",
                message="Saved guide",
                last_success_at=NOW - timedelta(hours=13),
            )
        )
        db.session.commit()

        assert status_payload()["stale"] is True
