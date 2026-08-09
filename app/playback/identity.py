from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

IMDB_ID_PATTERN = re.compile(r"^tt\d{5,12}$", re.IGNORECASE)


def _optional_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


@dataclass(frozen=True, slots=True)
class PlaybackIdentity:
    """The canonical, scoped identity passed to playback providers."""

    movie_id: str
    tmdb_id: str = ""
    imdb_id: str = ""
    media_type: str = "movie"
    title: str = ""
    year: int | None = None
    season: int | None = None
    episode: int | None = None

    @classmethod
    def from_context(
        cls,
        context: dict[str, Any],
        *,
        season: Any = None,
        episode: Any = None,
    ) -> PlaybackIdentity:
        external_ids = dict(context.get("external_ids") or {})
        imdb_id = str(external_ids.get("imdb_id") or external_ids.get("imdb") or "").strip()
        if imdb_id and not IMDB_ID_PATTERN.fullmatch(imdb_id):
            imdb_id = ""
        tmdb_id = str(external_ids.get("tmdb_id") or "").strip()
        if not tmdb_id.isdigit():
            tmdb_id = ""

        selected_season = _optional_positive_int(season)
        selected_episode = _optional_positive_int(episode)
        if (selected_season is None) != (selected_episode is None):
            raise ValueError("TV playback requires both a season and an episode.")

        return cls(
            movie_id=str(context.get("id") or "").strip(),
            tmdb_id=tmdb_id,
            imdb_id=imdb_id.lower(),
            media_type=str(context.get("media_type") or "movie").strip().lower(),
            title=str(context.get("title") or "").strip(),
            year=_optional_positive_int(context.get("year")),
            season=selected_season,
            episode=selected_episode,
        )

    @property
    def is_tv(self) -> bool:
        return self.media_type in {"tv", "series", "show"}

    @property
    def scope_key(self) -> str:
        if self.season is None or self.episode is None:
            return "movie"
        return f"s{self.season:02d}e{self.episode:02d}"

    def provider_id(self) -> tuple[str, str]:
        if self.imdb_id:
            return "imdb", self.imdb_id
        if self.tmdb_id:
            return "tmdb", self.tmdb_id
        raise ValueError("An IMDb ID or TMDB ID is required for playback.")
