# DragonV2

Dragon is a private, local-first personal workspace for movies, YouTube,
reading, books, chess, German learning, history, optional AI, and protected
administration. It is a new Flask application with a black-and-crimson luxury interface;
it does not reuse the legacy Cinema Prive frontend or monolithic architecture.

## Release status

The M1–M11 application surface, approved local import, and release hardening are complete.
The application includes normalized local persistence, atomic snapshots,
freshness and operation reports, versioned APIs, responsive primary pages, and
disabled-by-default integration/playback boundaries.

The legacy project at `C:\Users\walid\Desktop\FlaskDashboard` remains read-only.
After an inventory and dry run, the approved importer populated supported Dragon
models and archived the remaining private source files under ignored instance
storage. Credential values and personal records never enter Git.

## Requirements and setup

- Python 3.13 (`>=3.13,<3.14`)
- Node.js 24 and npm (required only for local magnet playback)
- Git
- A Chromium-based browser for browser tests

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

The administrator command prompts for a username and a password of at least 12
characters. There are no default credentials. To rotate the password:

```powershell
flask --app app:create_app admin set-password
```

## Product surface

- **Today** — continue watching/reading, a local movie recommendation, latest
  Watch Later videos, current book, chess queue, and freshness warnings.
- **Movies** — search, filters, sorting, pagination, grid/list views, details,
  status, score, and conflict-aware playback progress.
- **YouTube** — separate Watch Later and PocketTube projections, paginated
  playlists, thumbnails, explicit public-playlist sync, shuffle modes, details,
  related cached videos, and watched/removal history.
- **Reading** — source health, thumbnail-backed article list/detail, progress, read-only
  extraction status, and explicit adapter-backed full-text extraction.
- **Books** — responsive grid/list library, details, progress, linked quotes,
  and local metadata state.
- **Chess** — imported games, puzzle attempts/review state, courses, and APIs.
- **German** — extensible resources, lesson progress, and vocabulary review.
- **History** — a local unified progress timeline with no external analytics.
- **AI** — lazy contextual workspaces that stay disabled without configuration.
- **Admin** — protected explicit refresh/sync/repair/diagnostic actions,
  freshness, source health, snapshot inspection, and operation reports.
- **Playback** — one click-gated movie player with a source switcher for VidSrc
  or the local WebTorrent runtime, plus an isolated source review registry. The
  local runtime selects the main browser-compatible MP4 and serves browser range
  requests directly from a loopback-only Node/WebTorrent server. Media bytes do
  not pass through Flask or JSON. It never waits for a complete movie and never
  launches a torrent client automatically.

Normal page GET requests use the local database/snapshots and make no external
calls. External-facing operations are explicit, CSRF-protected, feature-gated,
and return a report when no provider adapter is configured.

## API

The protected `/api/v1` surface provides consistent item or paginated envelopes
for home, movies, playback progress, YouTube/sections, articles, books, chess,
German, history, freshness, operations, and health.

Collection envelopes contain `ok`, `api_version`, `items`, `count`, `total`,
`limit`, `offset`, `has_more`, and `next_offset`. Mutations require the current
authenticated session and CSRF token; a future native-client token scheme can be
added without changing these resource contracts.

## Configuration and safety

Copy `.env.example` to an ignored `.env` only for local overrides. Development
creates an ignored instance secret; production fails fast without
`DRAGON_SECRET_KEY`. These flags default to off:

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

The **Movies** section can use Notion as its visible library and TMDB plus
Jackett as discovery providers. Configure `DRAGON_NOTION_TOKEN`, either
`DRAGON_NOTION_DATABASE_ID` or `DRAGON_NOTION_DATA_SOURCE_ID`,
`DRAGON_TMDB_API_KEY` (or the TMDB read token), `DRAGON_JACKETT_URL`, and
`DRAGON_JACKETT_API_KEY`. When Notion credentials are present, sync and
write-back are enabled unless their flags explicitly disable them. Jackett
results are magnet-only, combine movie category `2000` and series category
`5000`, and default to at least five seeders through
`DRAGON_JACKETT_MIN_SEEDERS`.

Search checks the synced Notion collection before TMDB. A missing movie opens a
Jackett release picker; a missing series first opens TMDB season and episode
selectors. The selected release is written to Notion with its TMDB metadata and
then opened through Dragon's existing local player. Playback start and a later
Finished/Watched status write the corresponding dates back to Notion. New
write-back fields are added to the configured Notion data source on the first
import, while existing Name, Year, poster, overview, status, and magnet fields
remain compatible.

VidSrc requires both `DRAGON_PLAYBACK_ENABLED=true` and
`DRAGON_VIDSRC_ENABLED=true`. `DRAGON_VIDSRC_EMBED_URL` defaults to the single
VidSrc v2 base used by the legacy integration. The movie detail response
contains no embed URL; the protected playback endpoint resolves it only after
the signed-in user presses Play. When a movie has no stored IMDb ID, that
explicit action uses configured TMDB credentials to resolve and cache
`tmdb_id`, `tmdb_type`, and `imdb_id` before constructing the VidSrc URL.
VidSrc rejects sandboxed iframes, so enabling its off-by-default feature permits
the provider's scripts inside the click-loaded frame. Use **Open separately**
when stronger browser isolation is preferred.

Local magnet playback requires both `DRAGON_PLAYBACK_ENABLED=true` and
`DRAGON_MAGNETS_ENABLED=true`. Dragon keeps magnet and paired `.torrent`
locators server-side, starts WebTorrent only after an authenticated click, and
returns a secret, process-scoped URL on a random `127.0.0.1` port. That server
validates the exact Host and application Origin and supports GET/HEAD, prefix,
suffix, and seek ranges directly. Only browser-compatible MP4/M4V/WebM files are
selected; sample and trailer files are rejected. The runtime warms the first
8 MB and final 1 MB of MP4 files in parallel so browser metadata can become
available sooner. Imported YTS metadata may follow only the explicit `yts.bz`
to `yts.gg` redirect; other hosts are rejected.

Reusable torrent pieces and validated `.torrent` metadata are stored by info
hash. `DRAGON_PLAYBACK_CACHE_GB` defaults to `10`, and
`DRAGON_PLAYBACK_CACHE_TTL_HOURS` defaults to `168` (seven days). Cleanup is LRU,
never removes a running torrent, and is available from **More → Movies → Torrent
cache**. Switching sources or pressing **Stop local stream** disconnects peers
but keeps reusable cached pieces. VidSrc remains the explicit fallback for a
torrent with no peers or a codec that Chrome/Edge cannot decode.

Run the direct range/security fixture with `npm run test:playback`.

Local subtitles require `DRAGON_SUBTITLES_ENABLED=true` and a private
`DRAGON_SUBDL_API_KEY`. Dragon searches SubDL only after Local playback is
started, ranks Arabic before English, keeps provider URLs and credentials on
the server, and converts supported SRT/VTT files to a same-origin WebVTT track.
VidSrc is a cross-origin iframe, so Dragon cannot synchronize an external track
with it; use VidSrc's own captions or switch the player source to Local.

Public YouTube playlist synchronization also requires
`DRAGON_YOUTUBE_API_KEY` and `DRAGON_YOUTUBE_WATCH_LATER_PLAYLIST_ID`. It runs
only from the protected Admin operation; normal YouTube page requests remain
local-only.

Runtime databases, snapshots, reports, OAuth files, secrets, caches, and
personal exports are ignored by Git.

## Safe legacy migration

The available commands inspect schemas and write reports only under ignored
Dragon instance storage:

```powershell
flask --app app:create_app migrate inventory `
  --source "C:\Users\walid\Desktop\FlaskDashboard"

flask --app app:create_app migrate dry-run `
  --source "C:\Users\walid\Desktop\FlaskDashboard"
```

Sensitive files are classified without hashing or parsing their contents. These
commands never write to the source and import zero records.

After reviewing the dry-run report and explicitly approving a private local copy:

```powershell
flask --app app:create_app migrate apply `
  --source "C:\Users\walid\Desktop\FlaskDashboard" `
  --confirm-private-import
```

The apply step is idempotent. It maps supported movie, PocketTube, reading, books,
quotes, chess, and learning records into SQLAlchemy models; archives unsupported raw datasets under
`instance/legacy-import`; merges environment entries into the ignored local `.env`;
and copies OAuth/YouTube configuration into `instance/secrets`. Its safe, value-free report is written
to `instance/migration/legacy-import-report.json`.

## Verification

```powershell
ruff check .
pytest -q
pytest -q --cov=app --cov-report=term-missing
flask --app app:create_app db upgrade
python scripts/check_tracked_secrets.py
```

The current release gate is recorded in
[`docs/milestones/M11.md`](docs/milestones/M11.md).

## Documentation

- [Legacy audit and target architecture](docs/foundation/00-audit-and-architecture.md)
- [Product UX, design system, and wireframes](docs/foundation/01-ux-and-wireframes.md)
- [API v1 contracts](docs/foundation/02-api-contracts.md)
- [Migration safety and milestones](docs/foundation/03-migration-and-milestones.md)
- [M1 delivery record](docs/milestones/M1.md)
- [M2–M9 delivery record](docs/milestones/M2-M9.md)
- [M10 release report](docs/milestones/M10.md)
- [M11 luxury redesign and approved import](docs/milestones/M11.md)
