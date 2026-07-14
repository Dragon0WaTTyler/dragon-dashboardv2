import io
import json

import pytest

from app.youtube.providers import YouTubePlaylistClient, YouTubeProviderError


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
