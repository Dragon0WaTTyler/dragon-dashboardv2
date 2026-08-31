import hashlib
from collections import Counter

from flask.sessions import SecureCookieSessionInterface
from playwright.sync_api import sync_playwright

from app import create_app
from app.auth.models import User
from app.extensions import db


BASE_URL = "http://127.0.0.1:5053"
USER_AGENT = "Dragon playback verification"
identifier = hashlib.sha512(
    f"b'127.0.0.1'|{USER_AGENT.encode()!r}".encode()
).hexdigest()
app = create_app()
with app.app_context():
    user = db.session.query(User).first()
    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    session_value = serializer.dumps(
        {"_user_id": str(user.id), "_fresh": True, "_id": identifier}
    )
    cookie_name = app.config["SESSION_COOKIE_NAME"]

media, failed, console = [], [], []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    )
    context = browser.new_context(user_agent=USER_AGENT)
    context.add_cookies(
        [{"name": cookie_name, "value": session_value, "url": BASE_URL}]
    )
    page = context.new_page()
    page.on(
        "response",
        lambda response: media.append((response.status, response.url.split("?")[0]))
        if "/iptv/play/" in response.url or "/iptv/resource/" in response.url
        else None,
    )
    page.on(
        "requestfailed",
        lambda request: failed.append((request.url.split("?")[0], request.failure)),
    )
    page.on("console", lambda message: console.append((message.type, message.text)))
    page.goto(f"{BASE_URL}/iptv", wait_until="networkidle", timeout=30_000)
    page.locator("[data-play-channel]").filter(has_text="AR|DOCU: DW ARABIC").first.click()
    # Run beyond the point where this provider normally refreshes the playlist,
    # leaving time for a bounded client recovery if that refresh is inconsistent.
    page.wait_for_timeout(110_000)
    video = page.locator("#videoPlayer").evaluate(
        "(video) => ({readyState: video.readyState, currentTime: video.currentTime, paused: video.paused, hidden: video.hidden})"
    )
    print(
        {
            "video": video,
            "status": page.locator("#playerLoadingText").text_content(),
            "media_statuses": dict(Counter(status for status, _ in media)),
            "media_failures": [(status, url) for status, url in media if status >= 400][-20:],
            "failed": failed[-20:],
            "console_errors": [text for kind, text in console if kind == "error"][-20:],
        }
    )
    browser.close()
