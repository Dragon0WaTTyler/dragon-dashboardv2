from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import click
from flask import current_app

from app.youtube.grouping import ARCHIVE_GROUP, FAVORITE_GROUP, MY_TV_GROUP_ORDER, THEME_GROUPS
from app.youtube.services import YouTubeService


def _load_base_metadata(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"Could not read PocketTube base export: {path.name}") from exc
    if not isinstance(value, dict):
        raise click.ClickException("PocketTube base export must contain a JSON object.")
    return {key: item for key, item in value.items() if str(key).startswith("ysc_")}


def build_pockettube_payload(
    rows: list[dict[str, str]], metadata: dict[str, object] | None = None
) -> dict:
    """Build the group-array format used by PocketTube's subscription-manager export."""
    grouped: dict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()
    for row in rows:
        channel_id = str(row.get("Channel ID") or "").strip()
        if not channel_id.startswith("UC") or channel_id in seen:
            continue
        seen.add(channel_id)
        theme = str(row.get("Theme") or "").strip()
        group = THEME_GROUPS.get(theme, ARCHIVE_GROUP)
        grouped[group].append(channel_id)
        if str(row.get("Favorite") or "").strip().casefold() == "yes":
            grouped[FAVORITE_GROUP].append(channel_id)

    ordered_names = [FAVORITE_GROUP, *MY_TV_GROUP_ORDER[1:], ARCHIVE_GROUP]
    payload: dict[str, object] = {
        name: grouped[name]
        for name in ordered_names
        if grouped.get(name)
    }
    preserved = dict(metadata or {})
    payload.update(
        {
            "ysc_collection": {name: name for name in payload},
            "ysc_meta": {
                name: {"position": position}
                for position, name in enumerate(payload)
            },
        }
    )
    for key, value in preserved.items():
        if key not in {"ysc_collection", "ysc_meta"}:
            payload[key] = value
    return payload


@click.command("export-pockettube-groups")
@click.option(
    "--csv-file",
    "csv_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    required=True,
    help="Reviewed subscriptions CSV.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path, dir_okay=False),
    required=True,
    help="PocketTube-compatible JSON export destination.",
)
@click.option(
    "--base-export",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    help="Optional existing PocketTube export whose ysc settings should be retained.",
)
def export_pockettube_groups(
    csv_path: Path, output_path: Path, base_export: Path | None
) -> None:
    """Export Dragon's approved group map in PocketTube's JSON shape."""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise click.ClickException("The reviewed subscriptions CSV is empty.")
    payload = build_pockettube_payload(rows, _load_base_metadata(base_export))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    group_count = len(
        [
            key
            for key, value in payload.items()
            if not key.startswith("ysc_") and isinstance(value, list)
        ]
    )
    click.echo(f"Wrote {group_count} groups for {len(rows)} subscriptions to {output_path}.")
    current_app.logger.info("PocketTube group export written to %s", output_path)


@click.command("apply-pockettube-group-map")
@click.option(
    "--input",
    "input_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    required=True,
    help="PocketTube group export to apply to Dragon's cached catalog.",
)
def apply_pockettube_group_map(input_path: Path) -> None:
    """Apply a reviewed PocketTube grouping to Dragon without a YouTube network refresh."""
    try:
        counts = YouTubeService.apply_pockettube_group_map(input_path)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Applied PocketTube groups to {counts['videos']} cached videos: "
        f"{counts['created']} memberships created, {counts['updated']} retained."
    )
