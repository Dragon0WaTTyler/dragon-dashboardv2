from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import click
from flask import current_app
from flask.cli import with_appcontext

from app.extensions import db
from app.migration.inventory import build_inventory, write_inventory
from app.shared.models import MigrationRun
from app.shared.time import utc_now


@click.group("migrate")
@with_appcontext
def migration_cli() -> None:
    """Inventory legacy data without changing the source project."""


def _run_inventory(source: Path, *, mode: str) -> tuple[MigrationRun, dict]:
    source_root = source.expanduser().resolve(strict=True)
    result = build_inventory(source_root)
    output_root = Path(current_app.instance_path) / "migration" / "manifests"
    written = write_inventory(result, output_root)
    run = MigrationRun(
        id=str(uuid4()),
        mode=mode,
        status="completed_with_warnings" if result.warnings else "completed",
        source_root=str(source_root),
        manifest_path=str(output_root / written["relative_path"]),
        report_path=str(output_root / written["markdown_path"]),
        counts=result.manifest["counts"],
        completed_at=utc_now(),
    )
    db.session.add(run)
    db.session.commit()
    return run, {"warnings": result.warnings, "written": written}


@migration_cli.command("inventory")
@click.option(
    "--source",
    type=click.Path(path_type=Path, exists=True, file_okay=False, resolve_path=True),
    required=True,
)
def inventory_command(source: Path) -> None:
    """Create a schema-only manifest. The source is never modified."""
    run, details = _run_inventory(source, mode="inventory")
    click.echo(
        json.dumps(
            {
                "ok": True,
                "run_id": run.id,
                "status": run.status,
                "counts": run.counts,
                "warnings": details["warnings"],
            },
            sort_keys=True,
        )
    )


@migration_cli.command("dry-run")
@click.option(
    "--source",
    type=click.Path(path_type=Path, exists=True, file_okay=False, resolve_path=True),
    required=True,
)
def dry_run_command(source: Path) -> None:
    """Validate the available legacy schemas without importing records."""
    run, details = _run_inventory(source, mode="dry_run")
    click.echo(
        json.dumps(
            {
                "ok": True,
                "run_id": run.id,
                "status": run.status,
                "counts": run.counts,
                "warnings": details["warnings"],
                "records_imported": 0,
            },
            sort_keys=True,
        )
    )
