from __future__ import annotations

import runpy
from pathlib import Path


def test_pythonanywhere_package_contains_google_personal_vault_runtime_and_migration():
    root = Path(__file__).parents[2]
    module = runpy.run_path(root / "scripts" / "build_pythonanywhere_package.py")
    files = module["_files"]()
    included = {path.relative_to(root).as_posix() for path in files}

    assert {
        "app/vault/runtime.py",
        "app/vault/google.py",
        "app/vault/cli.py",
        "migrations/versions/c1a4d9e7b2f6_add_google_personal_workspaces.py",
        ".env.example",
    } <= included
    assert not any(path.startswith("instance/") for path in included)
