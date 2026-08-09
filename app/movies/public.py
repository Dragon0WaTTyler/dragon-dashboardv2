from __future__ import annotations

from app.extensions import db
from app.movies.repositories import MovieRepository


def get_playback_context(movie_id: str) -> dict | None:
    movie = MovieRepository.get(movie_id)
    if movie is None:
        return None
    return {
        "id": movie.id,
        "title": movie.title,
        "year": movie.year,
        "poster_url": movie.poster_url,
        "media_type": movie.media_type,
        "external_ids": dict(movie.external_ids or {}),
    }


def save_playback_external_ids(movie_id: str, values: dict[str, str]) -> dict[str, str] | None:
    movie = MovieRepository.get(movie_id)
    if movie is None:
        return None
    merged = {**dict(movie.external_ids or {}), **values}
    movie.external_ids = merged
    db.session.commit()
    return merged


def tv_episode_exists(movie_id: str, *, season: int, episode: int) -> bool:
    movie = MovieRepository.get(movie_id)
    if movie is None or movie.media_type != "tv":
        return False
    episodes = dict(movie.metadata_state or {}).get("tv_episodes") or {}
    for row in episodes.get(str(season)) or []:
        try:
            if int(row.get("episode_number") or 0) == episode:
                return True
        except (AttributeError, TypeError, ValueError):
            continue
    return False
