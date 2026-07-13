from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_NAMES = {
    ".env",
    "client_secret.json",
    "youtube_token.json",
    "oauth.json",
    "token.json",
}
SECRET_PATTERN = re.compile(
    r"(?im)^(?:DRAGON_SECRET_KEY|API_KEY|CLIENT_SECRET|ACCESS_TOKEN|PASSWORD)"
    r"[ \t]*=[ \t]*[^\s#][^\r\n]*$"
)


def tracked_files() -> list[Path]:
    git_path = shutil.which("git")
    if git_path is None:
        raise RuntimeError("Git is required for the tracked-file scan.")
    result = subprocess.run(  # noqa: S603 - executable is resolved by shutil.which
        [git_path, "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        relative = path.relative_to(ROOT).as_posix()
        if path.name.lower() in BLOCKED_NAMES or path.suffix.lower() in {".db", ".sqlite3"}:
            findings.append(f"blocked tracked file: {relative}")
            continue
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if SECRET_PATTERN.search(content):
            findings.append(f"possible secret value: {relative}")

    if findings:
        print("\n".join(findings))
        return 1
    print("Tracked-file secret scan passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
