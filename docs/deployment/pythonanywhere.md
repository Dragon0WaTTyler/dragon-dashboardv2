# PythonAnywhere deployment

This deployment keeps Dragon lightweight on PythonAnywhere while leaving the
local installation unchanged.

## Environment

Set these in the PythonAnywhere web app environment (or its private `.env`):

```ini
DRAGON_ENV=production
DRAGON_PYTHONANYWHERE_LITE=true
DRAGON_PLAYBACK_ENABLED=true
DRAGON_MAGNETS_ENABLED=false
DRAGON_JACKETT_ENABLED=false
DRAGON_AI_ENABLED=false
DRAGON_TV_EPG_ENABLED=false
DRAGON_GOOGLE_OAUTH_ENABLED=true
DRAGON_GOOGLE_PERSONAL_VAULT_LOGIN_ENABLED=true
DRAGON_GOOGLE_PERSONAL_VAULT_SYNC_ENABLED=true
DRAGON_GOOGLE_OAUTH_CLIENT_ID=...
DRAGON_GOOGLE_OAUTH_CLIENT_SECRET=...
DRAGON_GOOGLE_OAUTH_REDIRECT_URI=https://YOUR-USERNAME.pythonanywhere.com/auth/google/callback
```

The `DRAGON_PYTHONANYWHERE_LITE` flag enables eager movie relation loading and
caps the `/movies` recommendation JSON at 24 items. When false, local behavior
is unchanged.

Playback on this deployment is provider/embed based. Magnet/local-player
routes are disabled, so PythonAnywhere does not need torrent state or a local
FFmpeg playback path.

For portable personal data, configure the Google OAuth callback exactly as shown
in the Google Cloud client and keep all three Google flags enabled together. A
user who signs in with the same Google account locally and on PythonAnywhere gets
the same private Drive workspace; their watch progress, lists, RSS sources, and
supported integration settings restore automatically.

Before enabling sign-in for users, run this in the deployed virtualenv:

```text
flask --app app:create_app vault-preflight
```

It confirms the six required flags and values without printing the client ID or
secret. It cannot check Google Cloud for you, so also confirm that its Authorized
redirect URI exactly matches the configured callback URL.

## Upload

From the project root, run:

```text
python scripts/build_pythonanywhere_package.py
```

Upload `dist/dragonv2-pythonanywhere-clean.zip` and extract it into the app
directory. Do not upload `instance/`, local SQLite data, playback/subtitle
caches, backups, `.venv/`, `node_modules/`, or logs.

## Web tab

Set the WSGI file to:

```python
import sys
sys.path.insert(0, "/home/USERNAME/DragonV2")
from wsgi import app
```

Replace `USERNAME` and the path with the actual PythonAnywhere location. Use
the project virtualenv with `requirements.txt`, run migrations once with
`flask --app app:create_app db upgrade`, then reload the web app. Do not run
`run.py` or `app.run()` on PythonAnywhere.

## Static files mapping

In the Web tab add:

| URL | Directory |
| --- | --- |
| `/static/` | `/home/USERNAME/DragonV2/app/static` |

After saving the mapping, reload the web app and verify that `/static/css/...`
and `/static/js/...` return directly without passing through Flask.
