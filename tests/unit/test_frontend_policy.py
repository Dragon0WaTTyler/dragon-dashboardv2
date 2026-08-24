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


def test_library_uses_logical_rtl_styles_and_global_auto_direction():
    library_css = (ROOT / "app" / "static" / "css" / "pages" / "library.css").read_text(
        encoding="utf-8"
    )
    core_js = (ROOT / "app" / "static" / "js" / "core.js").read_text(encoding="utf-8")

    assert "border-inline-start" in library_css
    assert 'setAttribute("dir", "auto")' in core_js


def test_iptv_uses_hls_load_policies_without_a_manual_reconnect_loop():
    mytv_js = (ROOT / "app" / "static" / "js" / "mytv.js").read_text(encoding="utf-8")

    assert "manifestLoadPolicy" in mytv_js
    assert "playlistLoadPolicy" in mytv_js
    assert "fragLoadPolicy" in mytv_js
    assert "lowLatencyMode: false" in mytv_js
    assert "hls.startLoad(" not in mytv_js
    assert "elements.videoPlayer.onerror = () => switchToBackup" in mytv_js
    assert "else switchToBackup(" in mytv_js
    assert "scheduleStallFailover();" in mytv_js
