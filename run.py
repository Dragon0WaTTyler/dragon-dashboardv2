import os

from werkzeug.serving import is_running_from_reloader

from app import create_app
from app.shared.auto_sync import start_auto_sync

app = create_app()


if __name__ == "__main__":
    debug = str(os.getenv("DRAGON_DEBUG") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not debug or is_running_from_reloader():
        start_auto_sync(app)
    port = int(os.getenv("DRAGON_PORT") or "5053")
    app.run(host="127.0.0.1", port=port, debug=debug, threaded=True)
