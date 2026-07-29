import os

from app import create_app
from app.shared.auto_sync import start_auto_sync
from werkzeug.serving import is_running_from_reloader


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
    app.run(host="127.0.0.1", port=5053, debug=debug, threaded=True)
