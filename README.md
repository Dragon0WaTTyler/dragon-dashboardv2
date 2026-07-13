# DragonV2

DragonV2 is a private, local-first personal workspace for media, reading,
learning, training, history, and optional contextual AI.

## Current status

M0 is approved and M1 (production skeleton and guardrails) is complete. This is
a new Flask application, not a refactor of the legacy monolith. The legacy
project at `C:\Users\walid\Desktop\FlaskDashboard` remains read-only, and no
personal data or secrets have been copied into this repository.

The implemented surface is intentionally small: authentication, the protected
application shell, a protected production-component gallery, and health checks.
Feature domains, data migration, snapshots, external integrations, dark mode,
and API tokens remain deferred to later approved milestones.

## Requirements

- Python 3.13 (the supported baseline is `>=3.13,<3.14`)
- Git
- A local Chromium-based browser for browser smoke tests, or Playwright's
  bundled Chromium

## Local setup

From PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,production]"
flask --app app:create_app db upgrade
flask --app app:create_app admin create
flask --app app:create_app run
```

The admin command prompts interactively for a username and a password of at
least 12 characters. There is no default account or environment-based
credential bootstrap. Only a Werkzeug scrypt password hash is stored in the
ignored local SQLite database under `instance/`.

To rotate the password later:

```powershell
flask --app app:create_app admin set-password
```

## Routes delivered in M1

- `GET /healthz` — minimal deployment liveness response
- `GET /api/v1/health` — versioned JSON envelope with a request ID
- `GET|POST /auth/login` — local administrator login
- `POST /auth/logout` — authenticated, CSRF-protected logout
- `GET /` — protected Today shell
- `GET /admin/design-system` — protected production component gallery

Future feature links are visible as disabled placeholders; they are not partial
implementations.

## Configuration

Copy `.env.example` to an ignored `.env` only when local overrides are needed.
Development creates an ignored local secret key. Production fails fast unless
`DRAGON_SECRET_KEY` is supplied. All integration and mutation-related feature
flags default to off.

## Verification

```powershell
ruff check .
pytest -q
flask --app app:create_app db upgrade
python scripts/check_tracked_secrets.py
```

Browser smoke tests cover desktop and a 390 px mobile viewport. CI repeats
Ruff, pytest, a migration upgrade from an empty database, and the tracked-file
secret scan.

## Documentation

- [Legacy audit and target architecture](docs/foundation/00-audit-and-architecture.md)
- [Product UX, design system, and wireframes](docs/foundation/01-ux-and-wireframes.md)
- [Initial API v1 contracts](docs/foundation/02-api-contracts.md)
- [Migration safety and implementation milestones](docs/foundation/03-migration-and-milestones.md)
- [M1 delivery record](docs/milestones/M1.md)
