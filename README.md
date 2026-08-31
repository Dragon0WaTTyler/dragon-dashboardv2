# DragonV2

**DragonV2 is a private, local-first personal workspace for organising what you watch, read, learn, and return to next.** It brings movies and TV, live TV, YouTube, articles, books, chess, language learning, and personal history into one calm dashboard—without turning your personal data into a hosted service.

It is designed for one owner running it on their own machine or private server. The default experience is deliberately local: ordinary pages read from the local database and saved snapshots; network activity only happens when you explicitly configure and enable an integration.

> [!IMPORTANT]
> DragonV2 is a personal workspace, not a hosted streaming service. It does not include media or subscriptions. Configure playback only with content and providers you are authorised to access.

## Why DragonV2?

Personal media and learning tools usually live in disconnected apps: a watchlist here, bookmarks there, book highlights somewhere else, and no useful answer to “what should I do next?”. DragonV2 provides one private home for that context.

The **Today** page is the starting point: it surfaces unfinished films and shows, Watch Later videos, your current book, reading queue, chess work, and freshness warnings. The rest of the workspace gives each area enough depth without making the daily view feel like a dashboard for its own sake.

## What it includes

| Area | What you can do |
| --- | --- |
| **Today** | Pick up where you left off across media, reading, books, chess, and learning. |
| **Movies & TV** | Maintain a library, track status and scores, browse details and seasons, and optionally discover titles with TMDB. |
| **My TV** | Organise live-TV sources, favourite channels, and programme-guide data. |
| **YouTube** | Keep a local view of Watch Later and PocketTube groups, then review or shuffle your queue. |
| **Reading** | Manage articles, their extraction state, source health, and optional full-text retrieval. |
| **Books & knowledge** | Maintain a library, review metadata, read local EPUB/PDF/KFX/AZW3 files, listen to audiobooks, and preserve highlights, quotes, and Kindle clippings. |
| **Chess, German & history** | Track games, puzzles and courses; continue vocabulary and lessons; keep a personal progress timeline. |
| **Admin & API** | See data freshness, run deliberate sync/repair operations, and use the authenticated `/api/v1` endpoints. |

## Key features

- A single **Today** view that brings your next media, reading, book, and training action together.
- A **local database** by default, with local snapshots so normal page loads stay fast and do not silently contact third parties.
- **Notion synchronisation** for organising movie/TV and book libraries in Notion while still using Dragon as the daily workspace. Movie watch state can optionally be written back after you explicitly enable write-back.
- **Deliberate external integrations** for TMDB, YouTube, RSS/Atom, IPTV/XMLTV, subtitles, and approved playback sources. Every integration is disabled until you configure it.
- A protected **admin control centre** for source management, freshness, diagnostics, and explicit sync or repair operations.

## Guide to every section

### Today

Your daily starting page. It combines the most relevant local items from the other sections—unfinished movies or episodes, Watch Later videos, current books, articles, chess practice, and freshness warnings—so you can decide what to continue without opening every library.

### Movies

Your personal film and series library. Use it to browse, search, filter, score, and update the status of titles; series have seasons and episodes. You can organise films and shows in a connected **Notion** database, then synchronise that library to Dragon; optional write-back can keep viewing state aligned after you explicitly turn it on. TMDB discovery is available only after you add your own credentials.

For playback, Dragon supports configured, allowlisted iframe providers and an explicit authorised-source catalog—not arbitrary iframe URLs. It can also query a configured Jackett instance for release discovery. Neither feature supplies content, verifies rights, nor makes a source lawful: you are responsible for ensuring every source, file, stream, and use complies with applicable law and the provider's terms. Playback and Jackett are disabled by default.

### YouTube

A local working view of YouTube rather than a replacement for YouTube. It can keep Watch Later and PocketTube groups in local snapshots, help you find a video, shuffle a queue, and remember what you watched. Synchronisation and removing an item from the real Watch Later playlist are both optional, explicit actions.

### IPTV

The live-channel library. Add authorised M3U playlists, local playlist files, or approved GitHub sources; organise their channels into themes and categories; mark favourites; and use XMLTV programme-guide data when configured. Dragon keeps sources separate from your channel preferences and reports when a channel or guide needs attention.

### My TV

Your deliberately prepared viewing session, separate from IPTV channels. Choose a duration, topics, languages, formats, mood, and discovery level; Dragon builds a personal programme from the available YouTube collections, while accounting for preferences such as avoiding watched videos or short-form content.

### News

Your private reading queue. Add RSS or Atom sources, group them into categories, refresh a local snapshot, and review each article’s extraction state and source health. Full-text retrieval and text-to-speech are optional features rather than background activity.

### Books

Your reading and knowledge library. Keep book metadata and reading status in one place, attach local EPUB, PDF, KFX, or AZW3 files and audiobooks, then preserve highlights, quotes, and Kindle clippings. You can also organise books and reading progress in a connected **Notion** database, then synchronise that collection into Dragon. Metadata review and Kindle/Notion workflows run only when you choose to configure and trigger them.

### Chess

A focused practice area for imported games, puzzle attempts, opening courses, and scheduled review. It uses local data to show what is due, let you record puzzle attempts, and revisit the details of past games.

### More

The overflow menu for supporting parts of the workspace:

- **German** keeps learning resources, lesson progress, and vocabulary review together.
- **History** is a local timeline of personal progress.
- **AI workspaces** are contextual helpers that stay disabled until you provide and enable a provider.
- **Settings / Admin** manages visible sections, data sources, freshness, diagnostics, sync and repair operations, and account-level preferences.
- **Design system** is an internal reference for the interface components and visual language.

## Privacy and control by default

- **Local-first:** SQLite and runtime data live in your local `instance/` directory by default.
- **Authenticated:** there are no shipped administrator credentials; you create the first account yourself.
- **Opt-in integrations:** AI, external synchronisation, playback, subtitles, Notion, YouTube, TMDB, Jackett, and write-back actions start disabled.
- **Explicit external work:** rendering a page does not silently trigger imports, syncs, or provider calls.
- **Git-safe storage:** secrets, tokens, caches, logs, and personal exports are excluded from version control.

For a multi-user deployment, Google Drive personal workspaces are available now.
The [cloud-provider options](docs/foundation/06-cloud-provider-options.md)
document explains the safe future paths for GitHub and iCloud.

## Quick start

### Prerequisites

- Python **3.13**
- Node.js and npm (only needed for the optional local magnet-playback runtime and its tests)
- Git

From PowerShell, clone the repository and run:

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

Open [http://127.0.0.1:5000](http://127.0.0.1:5000), then sign in with the account you just created.

For the lightweight local runner instead, use `python run.py`; it listens on `http://127.0.0.1:5053` by default.

To change an administrator password later:

```powershell
flask --app app:create_app admin set-password
```

## Configure only what you need

The workspace runs without third-party credentials. When you want an integration, copy `.env.example` to `.env` and enable only the relevant flags and credentials.

```powershell
Copy-Item .env.example .env
```

Typical optional integrations are:

- **TMDB** for movie and TV discovery
- **YouTube** for Watch Later synchronisation
- **Notion** for media and book snapshots or approved write-back
- **IPTV/XMLTV** sources for My TV and programme guides
- **Local or authorised playback** and subtitle providers
- **AI** features, when explicitly enabled

All `DRAGON_*` flags are documented in [.env.example](.env.example). Keep `.env`, `instance/`, exported data, OAuth tokens, and API keys out of Git.

For the lightweight PythonAnywhere setup, see [docs/deployment/pythonanywhere.md](docs/deployment/pythonanywhere.md).

## How the project is organised

```text
app/
  admin/          # control centre, operations, diagnostics
  auth/           # local administrator authentication and CLI commands
  books/          # library, reader, audio, highlights, Kindle workflows
  movies/         # films, shows, library and discovery
  mytv/           # live-TV sources, channels and EPG
  playback/       # explicitly enabled playback and subtitles
  reading/        # articles and extraction workflows
  youtube/        # Watch Later and PocketTube projections
  shared/         # snapshots, freshness, operations and common utilities
  templates/      # server-rendered UI
  static/         # Dragon Noir styles and browser behaviour
migrations/       # database schema migrations
tests/            # unit, integration and browser coverage
docs/             # architecture, API contracts, UX and milestone records
instance/         # ignored local database, secrets, caches and exports
```

The application is a Flask monolith with feature-oriented modules. It uses Flask-Login, Flask-SQLAlchemy, Flask-Migrate, server-rendered templates, and a small amount of progressive browser-side JavaScript.

## Verification

Run the checks relevant to your change:

```powershell
ruff check .
pytest -q
pytest -q --cov=app --cov-report=term-missing
flask --app app:create_app db upgrade
python scripts/check_tracked_secrets.py
pytest -q tests/browser/test_movie_player.py
```

Browser tests require a Chromium-based browser and the Playwright setup used by this repository.

## Documentation

- [Architecture and legacy audit](docs/foundation/00-audit-and-architecture.md)
- [Product UX, design system, and wireframes](docs/foundation/01-ux-and-wireframes.md)
- [API v1 contracts](docs/foundation/02-api-contracts.md)
- [Migration safety and milestones](docs/foundation/03-migration-and-milestones.md)
- [Google personal vault foundation](docs/foundation/04-google-personal-vault.md)
- [Personal workspace audit](docs/foundation/05-personal-workspace-audit.md)
- [M11 redesign and approved import record](docs/milestones/M11.md)

## Development note

This is an evolving personal project. It supports feature-gated Google personal
workspaces so a user can keep their own data and supported integrations portable
between local Dragon and PythonAnywhere. Large local media assets and alternative
storage providers remain deliberate follow-up work.
