from __future__ import annotations

from dataclasses import dataclass

MODES = {
    "film_analysis": "Film Analysis",
    "movie_curation": "Movie Curation",
    "youtube_study": "YouTube Study",
}
CONTEXT_TYPES = {"movie", "youtube", "none"}


@dataclass(frozen=True, slots=True)
class AIWorkspace:
    mode: str
    label: str
    context_type: str
    context_id: str
    enabled: bool


class AIService:
    @staticmethod
    def workspace(
        *, mode: str, context_type: str, context_id: str, enabled: bool
    ) -> AIWorkspace:
        if mode not in MODES:
            raise ValueError("Unknown AI workspace mode.")
        if context_type not in CONTEXT_TYPES:
            raise ValueError("Unknown AI context type.")
        if context_type == "none":
            context_id = ""
        return AIWorkspace(
            mode=mode,
            label=MODES[mode],
            context_type=context_type,
            context_id=context_id[:64],
            enabled=enabled,
        )
