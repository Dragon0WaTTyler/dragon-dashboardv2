"""Build a clean PythonAnywhere upload archive."""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
INCLUDED_ROOTS = ("app", "migrations")
INCLUDED_FILES = (
    ".env.example",
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    "requirements.lock",
    "wsgi.py",
)
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "instance",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def _is_excluded(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return bool(set(relative.parts) & EXCLUDED_PARTS) or path.suffix in EXCLUDED_SUFFIXES


def _files() -> list[Path]:
    paths: list[Path] = []
    for root_name in INCLUDED_ROOTS:
        root = ROOT / root_name
        paths.extend(path for path in root.rglob("*") if path.is_file() and not _is_excluded(path))
    paths.extend(ROOT / name for name in INCLUDED_FILES if (ROOT / name).is_file())
    return sorted(paths)


def build(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = _files()
    with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    print(f"Wrote {destination} ({len(files)} files)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "dragonv2-pythonanywhere-clean.zip",
    )
    args = parser.parse_args()
    build(args.output if args.output.is_absolute() else ROOT / args.output)
