# DragonV2

DragonV2 is a private, local-first Flask workspace for movies, YouTube, reading, books and knowledge, chess, German learning, history, optional AI, and protected administration. It uses the Dragon Noir design system: near-black surfaces, crimson accents, warm typography, and responsive layouts that stay readable on desktop and mobile.

The app keeps personal data local. Normal page GET requests read from the local database and snapshots only. Anything external, such as sync, import, playback, or provider lookups, is explicit and feature-gated.

## Current State

- The M11 luxury redesign and approved private import are complete.
- Books and knowledge workflows are first-class parts of the app, including metadata review, local assets, audiobooks, highlights, quotes, and Kindle clippings.
- Runtime caches, snapshots, logs, OAuth material, secrets, and personal exports live under ignored `instance/` storage.
- There are no default admin credentials.

## What Lives Here

- **Today**: a combined start page for continue-watching/reading, movie picks, YouTube watch-later, current book, chess queue, and freshness warnings.
- **Movies**: local browsing, filters, details, status, score, TV seasons/episodes, TMDB discovery, Notion-backed library sync, Jackett release discovery, and explicit source selection.
- **Playback**: click-gated movie playback with VidSrc or the local WebTorrent runtime, range serving, subtitle support, and source caching.
- **YouTube**: Watch Later and PocketTube projections, playlist sync, detail views, shuffle flows, and watched/removal history.
- **Reading**: article lists/details, extraction state, source health, and explicit full-text adapters.
- **Books and Knowledge**: responsive library views, metadata inbox/review lanes, local text and audio assets, EPUB/KFX/AZW3/PDF handling, audiobook review, Kindle export, Book Quotes, Kindle clippings, diagnostics, and Notion snapshot workflows.
- **Chess**: imported games, puzzle attempts, review state, courses, and APIs.
- **German**: learning resources, lesson progress, and vocabulary review.
- **History**: a local progress timeline.
- **AI**: contextual workspaces that stay disabled unless configured.
- **Admin**: freshness, sync, repair, diagnostic, and operation-report tools.
- **API v1**: stable item and collection envelopes for the app surfaces above.

## Requirements

- Python 3.13 (`>=3.13,<3.14`)
- Node.js 24 and npm for local magnet playback and its tests
- Git
- A Chromium-based browser for browser tests

## Setup

From PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,production]"
npm install
flask --app app:create_app db upgrade
flask --app app:create_app admin create
flask --app app:create_app run
```

To rotate the administrator password later:

```powershell
flask --app app:create_app admin set-password
```

## Configuration

Copy `.env.example` to an ignored `.env` for local overrides. Development can create its own ignored instance secret; production requires `DRAGON_SECRET_KEY`.

Feature flags default to off:

- `DRAGON_AI_ENABLED`
- `DRAGON_PLAYBACK_ENABLED`
- `DRAGON_VIDSRC_ENABLED`
- `DRAGON_MAGNETS_ENABLED`
- `DRAGON_SUBTITLES_ENABLED`
- `DRAGON_EXTERNAL_SYNC_ENABLED`
- `DRAGON_NOTION_SYNC_ENABLED`
- `DRAGON_NOTION_WRITEBACK_ENABLED`
- `DRAGON_YOUTUBE_DELETE_ENABLED`
- `DRAGON_YOUTUBE_SYNC_ENABLED`
- `DRAGON_READING_TTS_ENABLED`

Common external settings include:

- `DRAGON_DATABASE_URL`
- `DRAGON_TMDB_API_KEY`
- `DRAGON_TMDB_READ_ACCESS_TOKEN`
- `DRAGON_JACKETT_URL`
- `DRAGON_JACKETT_API_KEY`
- `DRAGON_WYZIE_API_KEY`
- `DRAGON_WYZIE_BASE_URL`
- `DRAGON_SUBDL_API_KEY`
- `DRAGON_YOUTUBE_API_KEY`
- `DRAGON_YOUTUBE_WATCH_LATER_PLAYLIST_ID`
- `DRAGON_NOTION_TOKEN`
- `DRAGON_NOTION_DATABASE_ID`
- `DRAGON_NOTION_DATA_SOURCE_ID`
- `DRAGON_BOOK_NOTION_DATABASE_ID`
- `DRAGON_BOOK_NOTION_DATA_SOURCE_ID`
- `DRAGON_NOTION_TV_SHOW_DATABASE_ID`
- `DRAGON_NOTION_TV_SHOW_DATA_SOURCE_ID`
- `DRAGON_NOTION_TV_EPISODE_DATABASE_ID`
- `DRAGON_NOTION_TV_EPISODE_DATA_SOURCE_ID`

Secrets, tokens, runtime caches, and local exports should stay out of Git.

## Verification

```powershell
ruff check .
pytest -q
pytest -q --cov=app --cov-report=term-missing
flask --app app:create_app db upgrade
python scripts/check_tracked_secrets.py
npm run test:playback
```

## Documentation

- [Legacy audit and target architecture](docs/foundation/00-audit-and-architecture.md)
- [Product UX, design system, and wireframes](docs/foundation/01-ux-and-wireframes.md)
- [API v1 contracts](docs/foundation/02-api-contracts.md)
- [Migration safety and milestones](docs/foundation/03-migration-and-milestones.md)
- [M1 delivery record](docs/milestones/M1.md)
- [M2-M9 delivery record](docs/milestones/M2-M9.md)
- [M10 release report](docs/milestones/M10.md)
- [M11 luxury redesign and approved import](docs/milestones/M11.md)
