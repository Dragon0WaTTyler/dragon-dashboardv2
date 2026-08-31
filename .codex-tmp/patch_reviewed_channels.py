from __future__ import annotations

import csv
import os
from pathlib import Path


CSV_PATH = Path(r"C:\Users\walid\Desktop\DragonV2\outputs\my-tv-youtube-subscriptions-organized.csv")
OUTPUT_PATH = Path(r"C:\Users\walid\Desktop\DragonV2\outputs\my-tv-youtube-subscriptions-organized-reviewed.csv")

UPDATES = {
    "UC_RoRoYeLA_xtOYu5IJ7dRA": {
        "Theme": "News & Geopolitics",
        "Tags": "Journalism; Media; Arabic content; Social media",
        "Classification Basis": "Verified web research: broadcaster, journalism, and social-media media analysis",
        "Needs Review": "No",
    },
    "UC0qw9m7rxmT_ajCwzPQwq3g": {
        "Tags": "Culture; Entertainment; Unresolved",
        "Classification Basis": "No reliable public channel metadata found; retained the best available collection context",
    },
    "UC5v5S5DxGx6ozyOL6aNK7IQ": {
        "Theme": "Sports",
        "Tags": "Boxing; Technique; Fight analysis",
        "Classification Basis": "Verified web research: boxing technique and fight analysis",
        "Needs Review": "No",
    },
    "UC8zcPIQGZMZfMh0Bgu7E2oA": {
        "Tags": "Archive; Unresolved",
        "Classification Basis": "No reliable public channel metadata found",
    },
    "UCash6vxr1eNi5r_JsihPD_g": {
        "Theme": "News & Geopolitics",
        "Tags": "Social commentary; Gender; Politics; Video essays",
        "Classification Basis": "Verified web research: social and political commentary video essays",
        "Needs Review": "No",
    },
    "UCduD22OSc9f98Fg4NuJHU3Q": {
        "Tags": "Islam; Faith; Unresolved",
        "Classification Basis": "No reliable public channel metadata found; retained Islamic Studies collection context",
    },
    "UCGwu0nbY2wSkW8N-cghnLpA": {
        "Theme": "Culture & Entertainment",
        "Tags": "Animation; Storytelling; Gaming; Comedy",
        "Classification Basis": "Verified web research: animated storytelling and entertainment",
        "Needs Review": "No",
    },
    "UCmAlw1XDI-pRS8ZsHCWnfcw": {
        "Tags": "Archive; Unresolved",
        "Classification Basis": "No reliable public channel metadata found",
    },
    "UCp24iCen1UdEJr4ZSMyYfKA": {
        "Tags": "Knowledge; Education; Unresolved",
        "Classification Basis": "No reliable public channel metadata found; retained Knowledge collection context",
    },
    "UCG7E24xqPnCcKSTKM1NYmWw": {
        "Tags": "Knowledge; Education; Unresolved",
        "Classification Basis": "No reliable public channel metadata found; retained Knowledge collection context",
    },
    "UChUC06lcICzF_jBEhMSkiMg": {
        "Channel Name": "نشر الآن بالمغرب",
        "Theme": "News & Geopolitics",
        "Tags": "Morocco; News; Live coverage",
        "Classification Basis": "Verified web research: Moroccan news and live coverage",
        "Needs Review": "No",
    },
    "UCHZ5aiT4AuuqKLAGefojfNg": {
        "Channel Name": "خواطر بالدارجة - Khawater Bdarija",
        "Theme": "Faith & Islamic Studies",
        "Tags": "Islam; Moroccan Arabic; Reflections",
        "Classification Basis": "Verified web research: Moroccan Arabic faith and reflections",
        "Needs Review": "No",
    },
    "UCqF93nkibhEA1Sz8nZuqrVQ": {
        "Tags": "Islam; Faith; Unresolved",
        "Classification Basis": "No reliable public channel metadata found; retained Islamic Studies collection context",
    },
    "UCTxhd-f3WmraKfCQSambCxA": {
        "Channel Name": "Orange83",
        "Theme": "Technology & AI",
        "Tags": "Video editing; Premiere Pro; Creative tools",
        "Classification Basis": "Verified web research: video-editing presets and creative tools",
        "Needs Review": "No",
    },
    "UCUz6CXO5XIYD_7wmlK8mZsA": {
        "Channel Name": "Umm Kulthum | أم كلثوم",
        "Theme": "Music",
        "Tags": "Music; Arabic classics; Egyptian music",
        "Classification Basis": "Verified web research: official Umm Kulthum music channel",
        "Needs Review": "No",
    },
    "UCzmNyFIqGyVquE93gxRjQdw": {
        "Tags": "Knowledge; Education; Unresolved",
        "Classification Basis": "No reliable public channel metadata found; retained Knowledge collection context",
    },
}


def main() -> None:
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = reader.fieldnames
    if not fieldnames:
        raise ValueError("CSV header is missing")

    found: set[str] = set()
    for row in rows:
        channel_id = row["Channel ID"]
        update = UPDATES.get(channel_id)
        if update is not None:
            row.update(update)
            found.add(channel_id)
    missing = sorted(set(UPDATES) - found)
    if missing:
        raise ValueError(f"Channel IDs missing from CSV: {', '.join(missing)}")

    temporary = OUTPUT_PATH.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, OUTPUT_PATH)
    print(f"Updated {len(found)} reviewed channel records.")


if __name__ == "__main__":
    main()
