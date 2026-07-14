from __future__ import annotations

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
    }
