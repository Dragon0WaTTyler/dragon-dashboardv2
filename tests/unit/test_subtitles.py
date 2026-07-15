import json
from io import BytesIO
from zipfile import ZipFile

import pytest

from app.playback.subtitles import (
    SubdlSubtitleProvider,
    SubtitleProviderError,
    to_webvtt,
)


class FakeResponse:
    def __init__(self, *, data=None, payload=b""):
        self._data = data
        self.content = json.dumps(data).encode() if data is not None else payload
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._data

    def iter_content(self, chunk_size):
        assert chunk_size == 64 * 1024
        yield self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def test_subdl_search_prioritizes_arabic_and_hides_download_query():
    data = {
        "subtitles": [
            {
                "language": "EN",
                "release_name": "English release",
                "url": "/subtitle/archive123-456.zip?api_key=must-not-leak",
                "unpack_files": [
                    {
                        "language": "EN",
                        "format": "srt",
                        "name": "movie.en.srt",
                        "url": "/subtitle/parent123/file456?api_key=must-not-leak",
                    }
                ],
            },
            {
                "language": "AR",
                "release_name": "Arabic release",
                "url": "/subtitle/archive789-012.zip?api_key=must-not-leak",
                "unpack_files": [
                    {
                        "language": "AR",
                        "format": "srt",
                        "name": "movie.ar.srt",
                        "url": "/subtitle/parent789/file012?api_key=must-not-leak",
                    }
                ],
            },
        ]
    }
    session = FakeSession([FakeResponse(data=data)])
    provider = SubdlSubtitleProvider("private-key", session=session)

    candidates = provider.search(
        {
            "title": "Arrival",
            "year": 2016,
            "media_type": "movie",
            "external_ids": {"imdb_id": "tt2543164"},
        }
    )

    assert [candidate.language for candidate in candidates] == ["ar", "en"]
    assert all("?" not in candidate.path for candidate in candidates)
    _, request = session.calls[0]
    assert request["params"]["imdb_id"] == "tt2543164"
    assert request["params"]["languages"] == "ar,en"
    assert request["headers"]["Authorization"] == "Bearer private-key"


def test_subdl_download_is_allowlisted_and_converted_to_webvtt():
    subtitle = "1\n00:00:01,250 --> 00:00:03,500\nمرحبا\n".encode("cp1256")
    payload = BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr("movie.ar.srt", subtitle)
    session = FakeSession([FakeResponse(payload=payload.getvalue())])
    provider = SubdlSubtitleProvider("private-key", session=session)

    result = provider.download(
        "/subtitle/archive123-456.zip",
        file_format="srt",
        member_name="movie.ar.srt",
    )

    assert result.startswith(b"WEBVTT\n\n")
    assert b"00:00:01.250 --> 00:00:03.500" in result
    assert "مرحبا" in result.decode()
    url, request = session.calls[0]
    assert url == "https://dl.subdl.com/subtitle/archive123-456.zip"
    assert request["headers"]["X-API-Key"] == "private-key"
    assert request["allow_redirects"] is False


def test_subtitle_conversion_rejects_non_caption_payloads():
    with pytest.raises(SubtitleProviderError, match="does not contain subtitle cues"):
        to_webvtt(b"not a subtitle", "srt")

    provider = SubdlSubtitleProvider("private-key", session=FakeSession([]))
    with pytest.raises(SubtitleProviderError, match="invalid subtitle path"):
        provider.download("https://attacker.example/subtitle.srt", file_format="srt")
