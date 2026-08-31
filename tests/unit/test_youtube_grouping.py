import json
from datetime import UTC, datetime

from app.extensions import db
from app.personal_tv.providers import YouTubeCandidateProvider
from app.youtube.cli import build_pockettube_payload
from app.youtube.models import PocketTubeChannelMembership, YouTubeVideo
from app.youtube.services import YouTubeService


def test_pockettube_export_keeps_favorites_as_an_overlay():
    payload = build_pockettube_payload(
        [
            {"Channel ID": "UCscience", "Theme": "Science & Ideas", "Favorite": "Yes"},
            {"Channel ID": "UCmusic", "Theme": "Music", "Favorite": "No"},
        ]
    )

    assert payload["my favoret"] == ["UCscience"]
    assert payload["Science & Knowledge"] == ["UCscience"]
    assert payload["Music"] == ["UCmusic"]
    assert "ysc_collection" in payload and "ysc_meta" in payload


def test_personal_tv_keeps_all_pockettube_memberships_and_prioritises_favo(app):
    with app.app_context():
        db.session.add_all(
            [
                YouTubeVideo(
                    external_id="shared-video::pt:Science & Knowledge",
                    source="pockettube",
                    group_name="Science & Knowledge",
                    channel_title="Trusted channel",
                    title="A science programme",
                    duration_seconds=1800,
                    published_at=datetime(2026, 8, 20, tzinfo=UTC),
                ),
                YouTubeVideo(
                    external_id="shared-video::pt:my favoret",
                    source="pockettube",
                    group_name="my favoret",
                    channel_title="Trusted channel",
                    title="A science programme",
                    duration_seconds=1800,
                    published_at=datetime(2026, 8, 20, tzinfo=UTC),
                ),
                YouTubeVideo(
                    external_id="archived-video::pt:Archive / Review Later",
                    source="pockettube",
                    group_name="Archive / Review Later",
                    channel_title="Old channel",
                    title="An old programme",
                    duration_seconds=1800,
                    published_at=datetime(2026, 8, 20, tzinfo=UTC),
                ),
            ]
        )
        db.session.commit()

        candidates = YouTubeCandidateProvider.candidates()
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.favorite is True
        assert set(candidate.groups) == {"Science & Knowledge", "my favoret"}
        assert candidate.quality_score == 12

        groups = YouTubeCandidateProvider.groups()
        assert [group["name"] for group in groups] == [
            "my favoret",
            "Science & Knowledge",
        ]
        assert groups[0]["favorite"] is True


def test_group_map_relabels_cached_pockettube_videos_without_network(app, tmp_path):
    export_path = tmp_path / "pockettube.json"
    export_path.write_text(
        json.dumps(
            {
                "my favoret": ["UCtrusted"],
                "Science & Knowledge": ["UCtrusted"],
                "ysc_collection": {},
            }
        ),
        encoding="utf-8",
    )
    with app.app_context():
        db.session.add(
            YouTubeVideo(
                external_id="cached-video::pt:legacy",
                source="pockettube",
                group_name="legacy",
                channel_id="UCtrusted",
                channel_title="Trusted channel",
                title="A trusted programme",
                duration_seconds=1800,
                published_at=datetime(2026, 8, 20, tzinfo=UTC),
            )
        )
        db.session.commit()

        counts = YouTubeService.apply_pockettube_group_map(export_path)
        active = list(
            db.session.scalars(
                db.select(YouTubeVideo)
                .where(
                    YouTubeVideo.source == "pockettube",
                    YouTubeVideo.removed_from_source.is_(False),
                )
                .order_by(YouTubeVideo.group_name)
            )
        )
        assert counts["videos"] == 2
        assert {video.group_name for video in active} == {"Science & Knowledge", "my favoret"}
        memberships = list(db.session.scalars(db.select(PocketTubeChannelMembership)))
        assert {(item.group_name, item.channel_id) for item in memberships} == {
            ("Science & Knowledge", "UCtrusted"),
            ("my favoret", "UCtrusted"),
        }

        class FakeYouTubeClient:
            def fetch_channel_uploads(self, channel_limits, *, maximum):
                assert channel_limits == {"UCtrusted": 12}
                assert maximum == 288
                return {
                    "UCtrusted": [
                        {
                            "id": "playlist-item",
                            "snippet": {
                                "resourceId": {"videoId": "fresh-video"},
                                "title": "Fresh science programme",
                                "description": "A useful long-form programme.",
                                "publishedAt": "2026-08-24T12:00:00Z",
                                "channelTitle": "Trusted channel",
                            },
                        }
                    ]
                }

            def fetch_durations(self, video_ids, *, maximum):
                assert video_ids == ["fresh-video"]
                assert maximum == 1
                return {"fresh-video": 1200}

        hydrated = YouTubeService.hydrate_pockettube_groups(
            FakeYouTubeClient(), ("Science & Knowledge",)
        )
        assert hydrated["channels"] == 1
        fresh = list(
            db.session.scalars(
                db.select(YouTubeVideo).where(YouTubeVideo.external_id.like("fresh-video%"))
            )
        )
        assert {video.group_name for video in fresh} == {"Science & Knowledge", "my favoret"}
        assert all(item.last_hydrated_at is not None for item in memberships)


def test_pockettube_hydration_caps_each_group_at_200_videos(app):
    with app.app_context():
        membership = PocketTubeChannelMembership(
            group_name="Science & Knowledge",
            channel_id="UCcap0001",
        )
        db.session.add(membership)
        db.session.add_all(
            [
                YouTubeVideo(
                    external_id=f"cached-{index}",
                    source="pockettube",
                    group_name="Science & Knowledge",
                    channel_id="UCcap0001",
                    title=f"Cached {index}",
                    position=index,
                    duration_seconds=600,
                )
                for index in range(199)
            ]
        )
        db.session.commit()

        class FakeYouTubeClient:
            def fetch_channel_uploads(self, channel_limits, *, maximum):
                assert channel_limits == {"UCcap0001": 12}
                assert maximum == 288
                return {
                    "UCcap0001": [
                        {
                            "id": "upload-new-1",
                            "snippet": {
                                "resourceId": {"videoId": "new-1"},
                                "title": "New one",
                                "publishedAt": "2026-08-24T12:00:00Z",
                            },
                        },
                        {
                            "id": "upload-new-2",
                            "snippet": {
                                "resourceId": {"videoId": "new-2"},
                                "title": "New two",
                                "publishedAt": "2026-08-24T11:00:00Z",
                            },
                        },
                    ]
                }

            def fetch_durations(self, video_ids, *, maximum):
                assert video_ids == ["new-1", "new-2"]
                assert maximum == 2
                return {"new-1": 600, "new-2": 600}

        counts = YouTubeService.hydrate_pockettube_groups(
            FakeYouTubeClient(), ("Science & Knowledge",)
        )
        feed = YouTubeService.feed(
            source="pockettube", group="Science & Knowledge", limit=None
        )

        assert counts["videos"] == 1
        assert feed["total"] == 200
        assert {item["external_id"] for item in feed["items"]} == {
            *(f"cached-{index}" for index in range(199)),
            "new-1",
        }
