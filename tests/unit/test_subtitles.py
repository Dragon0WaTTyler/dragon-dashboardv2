import json
from io import BytesIO
from zipfile import ZipFile

import pytest

from app.playback.subtitles import (
    SubdlSubtitleProvider,
    SubtitleProviderError,
    WyzieSubtitleProvider,
    to_webvtt,
)


class FakeResponse:
    def __init__(self, *, data=None, payload=b"", status_code=200):
        self._data = data
        self.content = json.dumps(data).encode() if data is not None else payload
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")
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
    assert candidates[0].path == "/subtitle/parent789/file012"
    assert candidates[0].member_name == ""
    _, request = session.calls[0]
    assert request["params"]["imdb_id"] == "tt2543164"
    assert request["params"]["languages"] == "ar,en"
    assert request["headers"]["Authorization"] == "Bearer private-key"


def test_wyzie_search_uses_tmdb_tv_episode_filters_and_prioritizes_arabic():
    data = [
        {
            "id": "1399",
            "url": "https://cdn.example/en/the.sopranos.s01e02.en.srt",
            "format": "srt",
            "encoding": "utf-8",
            "isHearingImpaired": False,
            "display": "English",
            "language": "en",
            "release": "The Sopranos S01E02 BluRay",
            "fileName": "The.Sopranos.S01E02.46.Long.en.srt",
        },
        {
            "id": "1399",
            "url": "https://cdn.example/ar/the.sopranos.s01e02.ar.srt",
            "format": "srt",
            "encoding": "utf-8",
            "isHearingImpaired": False,
            "display": "Arabic",
            "language": "ar",
            "release": "The Sopranos S01E02 BluRay",
            "fileName": "The.Sopranos.S01E02.46.Long.ar.srt",
        },
        {
            "id": "1399",
            "url": "https://cdn.example/ar/the.sopranos.s01e03.ar.srt",
            "format": "srt",
            "encoding": "utf-8",
            "isHearingImpaired": False,
            "display": "Arabic",
            "language": "ar",
            "release": "The Sopranos S01E03 BluRay",
            "fileName": "The.Sopranos.S01E03.Denial.ar.srt",
        },
    ]
    session = FakeSession([FakeResponse(data=data)])
    provider = WyzieSubtitleProvider("wyzie-key", session=session)

    candidates = provider.search(
        {
            "title": "The Sopranos",
            "year": 1999,
            "media_type": "tv",
            "external_ids": {"tmdb_id": "1399"},
        },
        season=1,
        episode=2,
        episode_title="46 Long",
    )

    assert [candidate.language for candidate in candidates] == ["ar", "en"]
    assert all("s01e03" not in candidate.path for candidate in candidates)
    _, request = session.calls[0]
    assert request["params"]["id"] == "1399"
    assert request["params"]["season"] == 1
    assert request["params"]["episode"] == 2
    assert request["params"]["language"] == "ar,en"
    assert request["params"]["format"] == "srt,vtt"
    assert request["params"]["key"] == "wyzie-key"


def test_wyzie_download_converts_remote_srt_to_webvtt():
    subtitle = "1\n00:00:01,000 --> 00:00:03,000\nHello\n".encode("utf-8")
    session = FakeSession([FakeResponse(payload=subtitle)])
    provider = WyzieSubtitleProvider("wyzie-key", session=session)

    result = provider.download(
        "https://cdn.example/subs/the.sopranos.s01e01.en.srt",
        file_format="srt",
    )

    assert result.startswith(b"WEBVTT\n\n")
    assert b"00:00:01.000 --> 00:00:03.000" in result
    url, request = session.calls[0]
    assert url == "https://cdn.example/subs/the.sopranos.s01e01.en.srt"
    assert request["allow_redirects"] is True


def test_subdl_search_passes_tv_season_and_episode_filters():
    data = {"subtitles": []}
    session = FakeSession([FakeResponse(data=data)])
    provider = SubdlSubtitleProvider("private-key", session=session)

    provider.search(
        {
            "title": "The Sopranos",
            "year": 1999,
            "media_type": "tv",
            "external_ids": {"tmdb_id": "1399"},
        },
        season=1,
        episode=2,
    )

    _, request = session.calls[0]
    assert request["params"]["tmdb_id"] == "1399"
    assert request["params"]["type"] == "tv"
    assert request["params"]["season"] == 1
    assert "episode" not in request["params"]


def test_subdl_unpack_files_are_filtered_to_requested_episode():
    data = {
        "subtitles": [
            {
                "language": "AR",
                "release_name": "The Sopranos S01",
                "url": "/subtitle/archive123-456.zip",
                "unpack_files": [
                    {
                        "language": "AR",
                        "format": "srt",
                        "name": "The.Sopranos.S01E01.Pilot.ar.srt",
                        "release_name": "The Sopranos S01E01",
                        "season": 1,
                        "episode": 1,
                        "url": "/subtitle/parent123/episode01",
                    },
                    {
                        "language": "AR",
                        "format": "srt",
                        "name": "The.Sopranos.S01E02.46.Long.ar.srt",
                        "release_name": "The Sopranos S01E02",
                        "season": 1,
                        "episode": 2,
                        "url": "/subtitle/parent123/episode02",
                    },
                ],
            }
        ]
    }
    session = FakeSession([FakeResponse(data=data)])
    provider = SubdlSubtitleProvider("private-key", session=session)

    candidates = provider.search(
        {
            "title": "The Sopranos",
            "year": 1999,
            "media_type": "tv",
            "external_ids": {"tmdb_id": "1399"},
        },
        season=1,
        episode=2,
    )

    assert len(candidates) == 1
    assert candidates[0].label == "The Sopranos S01E02"
    assert candidates[0].path == "/subtitle/parent123/episode02"


def test_subdl_prefers_raw_episode_files_over_season_archives():
    data = {
        "subtitles": [
            {
                "language": "AR",
                "release_name": "The Sopranos S01 Complete",
                "url": "/subtitle/archive123-456.zip",
            },
            {
                "language": "AR",
                "release_name": "The Sopranos S01",
                "url": "/subtitle/archive789-012.zip",
                "unpack_files": [
                    {
                        "language": "AR",
                        "format": "srt",
                        "name": "The.Sopranos.S01E02.46.Long.ar.srt",
                        "release_name": "The Sopranos S01E02",
                        "season": 1,
                        "episode": 2,
                        "url": "/subtitle/parent789/episode02",
                    },
                ],
            },
        ]
    }
    session = FakeSession([FakeResponse(data=data)])
    provider = SubdlSubtitleProvider("private-key", session=session)

    candidates = provider.search(
        {
            "title": "The Sopranos",
            "year": 1999,
            "media_type": "tv",
            "external_ids": {"tmdb_id": "1399"},
        },
        season=1,
        episode=2,
    )

    assert candidates[0].path == "/subtitle/parent789/episode02"


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


def test_subdl_download_extracts_requested_episode_from_archive_pack():
    episode_1 = "1\n00:00:01,000 --> 00:00:02,000\nحلقة 1\n".encode("utf-8")
    episode_2 = "1\n00:00:01,000 --> 00:00:02,000\nحلقة 2\n".encode("utf-8")
    payload = BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr("The.Sopranos.S01E01.Pilot.ar.srt", episode_1)
        archive.writestr("The.Sopranos.S01E02.46.Long.ar.srt", episode_2)
    session = FakeSession([FakeResponse(payload=payload.getvalue())])
    provider = SubdlSubtitleProvider("private-key", session=session)

    result = provider.download(
        "/subtitle/archive123-456.zip",
        file_format="auto",
        season=1,
        episode=2,
    )

    text = result.decode()
    assert "حلقة 2" in text
    assert "حلقة 1" not in text


def test_subdl_download_ignores_wrong_member_and_extracts_episode_title_match():
    payload = BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr(
            "The.Sopranos.Complete.Season.01.The.Legend.of.Tennessee.Moltisanti.ar.srt",
            "1\n00:00:01,000 --> 00:00:02,000\nحلقة غلط\n".encode("utf-8"),
        )
        archive.writestr(
            "The.Sopranos.Season.01.Pilot.ar.srt",
            "1\n00:00:01,000 --> 00:00:02,000\nحلقة بايلوت\n".encode("utf-8"),
        )
    session = FakeSession([FakeResponse(payload=payload.getvalue())])
    provider = SubdlSubtitleProvider("private-key", session=session)

    result = provider.download(
        "/subtitle/archive123-456.zip",
        file_format="auto",
        member_name="The.Sopranos.Complete.Season.01.The.Legend.of.Tennessee.Moltisanti.ar.srt",
        season=1,
        episode=1,
        episode_title="Pilot",
    )

    text = result.decode()
    assert "حلقة بايلوت" in text
    assert "حلقة غلط" not in text


def test_subdl_download_rejects_archive_pack_without_requested_episode():
    payload = BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr(
            "The.Sopranos.S01E03.Denial.ar.srt",
            "1\n00:00:01,000 --> 00:00:02,000\nحلقة 3\n".encode("utf-8"),
        )
    session = FakeSession([FakeResponse(payload=payload.getvalue())])
    provider = SubdlSubtitleProvider("private-key", session=session)

    with pytest.raises(SubtitleProviderError, match="requested episode"):
        provider.download(
            "/subtitle/archive123-456.zip",
            file_format="auto",
            season=1,
            episode=2,
        )


def test_subdl_download_reuses_cached_archive_payload_for_other_episodes():
    payload = BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr(
            "The.Sopranos.S01E01.Pilot.ar.srt",
            "1\n00:00:01,000 --> 00:00:02,000\nحلقة 1\n".encode("utf-8"),
        )
        archive.writestr(
            "The.Sopranos.S01E02.46.Long.ar.srt",
            "1\n00:00:01,000 --> 00:00:02,000\nحلقة 2\n".encode("utf-8"),
        )
    session = FakeSession([FakeResponse(payload=payload.getvalue())])
    provider = SubdlSubtitleProvider("private-key", session=session)

    provider.download("/subtitle/archive123-456.zip", file_format="auto", season=1, episode=1)
    provider.download("/subtitle/archive123-456.zip", file_format="auto", season=1, episode=2)

    assert len(session.calls) == 1


def test_subtitle_conversion_rejects_non_caption_payloads():
    with pytest.raises(SubtitleProviderError, match="does not contain subtitle cues"):
        to_webvtt(b"not a subtitle", "srt")

    provider = SubdlSubtitleProvider("private-key", session=FakeSession([]))
    with pytest.raises(SubtitleProviderError, match="invalid subtitle path"):
        provider.download("https://attacker.example/subtitle.srt", file_format="srt")
