import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)", re.IGNORECASE)
INLINE_STYLE = re.compile(r"\sstyle\s*=", re.IGNORECASE)


def test_frontend_has_no_inline_styles_scripts_or_important_rules():
    for path in (ROOT / "app" / "templates").rglob("*.html"):
        content = path.read_text(encoding="utf-8")
        assert INLINE_STYLE.search(content) is None, path
        assert INLINE_SCRIPT.search(content) is None, path
    for path in (ROOT / "app" / "static" / "css").rglob("*.css"):
        content = path.read_text(encoding="utf-8")
        assert "!important" not in content, path
        assert "http://" not in content and "https://" not in content, path
