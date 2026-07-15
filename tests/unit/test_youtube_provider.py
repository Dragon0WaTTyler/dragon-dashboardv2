import io
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from app.youtube.providers import (
    YouTubePlaylistClient,
    YouTubeProviderError,
    duration_seconds,
)


def test_playlist_client_paginates_without_exposing_configuration():
    responses = [
        {"items": [{"id": "one"}], "nextPageToken": "next"},
        {"items": [{"id": "two"}]},
    ]
    requests = []

    def opener(request, *, timeout):
        requests.append((request, timeout))
        return io.BytesIO(json.dumps(responses.pop(0)).encode())

    client = YouTubePlaylistClient("private-key", opener=opener)
    items = client.fetch_playlist("PL-test-playlist-123")

    assert [item["id"] for item in items] == ["one", "two"]
    assert len(requests) == 2
    assert requests[0][1] == 20


def test_playlist_client_rejects_invalid_ids_before_network_access():
    client = YouTubePlaylistClient("private-key", opener=lambda *_args, **_kwargs: None)

    with pytest.raises(YouTubeProviderError, match="playlist ID is invalid"):
        client.fetch_playlist("https://example.test/not-a-playlist")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("PT12M47S", 767),
        ("PT1H8M32S", 4112),
        ("P1DT2H3M4S", 93_784),
        ("not-a-duration", 0),
    ],
)
def test_youtube_duration_parser(value, expected):
    assert duration_seconds(value) == expected


def test_duration_client_batches_fifty_video_ids_per_request():
    requests = []

    def opener(request, *, timeout):
        requests.append((request, timeout))
        query = parse_qs(urlsplit(request.full_url).query)
        items = [
            {"id": video_id, "contentDetails": {"duration": "PT1M5S"}}
            for video_id in query["id"][0].split(",")
        ]
        return io.BytesIO(json.dumps({"items": items}).encode())

    client = YouTubePlaylistClient("private-key", opener=opener)
    durations = client.fetch_durations([f"video-{index}" for index in range(51)])

    assert len(requests) == 2
    assert len(parse_qs(urlsplit(requests[0][0].full_url).query)["id"][0].split(",")) == 50
    assert durations["video-0"] == 65
    assert durations["video-50"] == 65
