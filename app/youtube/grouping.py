from __future__ import annotations

import re
from collections.abc import Iterable

FAVORITE_GROUP = "my favoret"
ARCHIVE_GROUP = "Archive / Review Later"

MY_TV_GROUP_ORDER = (
    FAVORITE_GROUP,
    "Books & Literature",
    "Science & Knowledge",
    "Tech & AI",
    "Faith & Islamic Thought",
    "News & Geopolitics",
    "Music",
    "Culture & Commentary",
    "Documentary & History",
    "Film, TV & Animation",
    "Podcasts & Long-form",
    "Sports",
    "Language Learning",
    "Travel & Lifestyle",
)

THEME_GROUPS = {
    "Books & Literature": "Books & Literature",
    "Science & Ideas": "Science & Knowledge",
    "Education & Study": "Science & Knowledge",
    "Technology & AI": "Tech & AI",
    "Faith & Islamic Studies": "Faith & Islamic Thought",
    "News & Geopolitics": "News & Geopolitics",
    "Music": "Music",
    "Culture & Entertainment": "Culture & Commentary",
    "Documentary & History": "Documentary & History",
    "Film & TV": "Film, TV & Animation",
    "Podcasts & Interviews": "Podcasts & Long-form",
    "Sports": "Sports",
    "Language Learning": "Language Learning",
    "Travel & Adventure": "Travel & Lifestyle",
    "Lifestyle & Personal Growth": "Travel & Lifestyle",
    "Archive": ARCHIVE_GROUP,
}

_LEGACY_GROUPS = {
    "booktube": "Books & Literature",
    "knowledge": "Science & Knowledge",
    "tech": "Tech & AI",
    "islamic knowledge": "Faith & Islamic Thought",
    "news": "News & Geopolitics",
    "musics": "Music",
    "entertainment": "Culture & Commentary",
    "entertainment ysm 1": "Travel & Lifestyle",
    "documentary": "Documentary & History",
    "movise": "Film, TV & Animation",
    "podcasts": "Podcasts & Long-form",
    "sports": "Sports",
    "language": "Language Learning",
    "poetry": "Books & Literature",
    "school": "Science & Knowledge",
    "archive": ARCHIVE_GROUP,
    "archive review later": ARCHIVE_GROUP,
}


def group_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def canonical_group(value: str) -> str:
    """Return the approved group label while accepting the previous PocketTube labels."""
    clean = str(value or "").strip()
    if not clean:
        return ""
    key = group_key(clean)
    if key in {"favo", "favorite", "my favoret"}:
        return FAVORITE_GROUP
    for group in (*MY_TV_GROUP_ORDER, ARCHIVE_GROUP):
        if group_key(group) == key:
            return group
    return _LEGACY_GROUPS.get(key, clean)


def is_favorite_group(value: str) -> bool:
    return canonical_group(value) == FAVORITE_GROUP


def is_archive_group(value: str) -> bool:
    return canonical_group(value) == ARCHIVE_GROUP


def is_my_tv_group(value: str) -> bool:
    return bool(canonical_group(value)) and not is_archive_group(value)


def ordered_groups(groups: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    order = {name: index for index, name in enumerate(MY_TV_GROUP_ORDER)}
    return sorted(
        groups,
        key=lambda item: (
            order.get(canonical_group(str(item.get("name") or "")), len(order)),
            str(item.get("name") or "").casefold(),
        ),
    )
