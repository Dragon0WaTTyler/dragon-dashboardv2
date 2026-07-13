# Migration safety and implementation milestones

Status: M0 approved on 2026-07-14; M1 authorized and delivered. No personal data
has been copied.

## Safety invariants

1. The legacy directory is always opened read-only by migration code. Importers
   never rename, delete, truncate, normalize in place, or write reports there.
2. A migration starts with a manifest containing relative path, byte size,
   modified time, SHA-256 checksum, detected format, schema version when present,
   and sensitivity class. Credentials are recorded as `excluded_sensitive`
   without reading their values.
3. Dry-run is the default. Apply requires `--apply`, an approved dry-run report,
   and a fresh backup of the DragonV2 instance database.
4. Every importer validates before persistence and commits one domain in a single
   transaction. A failed domain rolls back without leaving partial records.
5. Stable source IDs and deterministic fingerprints make repeated runs
   idempotent. The report distinguishes created, updated, unchanged, skipped,
   conflicted, orphaned, and failed records.
6. Raw source artifacts used for an import are copied only into an encrypted or
   access-restricted migration staging directory outside Git, after explicit user
   approval. The initial scaffold never copies them.
7. Secrets, OAuth tokens, `.env`, caches that can be rebuilt, logs, generated
   reports, virtual environments, `node_modules`, and binaries are never committed.
8. A post-import reconciliation compares source counts, target counts, relation
   integrity, representative checksums, and rejected records before the new app is
   allowed to become primary.

## Migration workspace

```text
instance/
├── dragon.sqlite3
├── backups/
│   └── dragon-before-import-<timestamp>.sqlite3
├── migration/
│   ├── manifests/
│   ├── staging/          # ignored; optional approved copies
│   └── reports/
└── snapshots/
```

All of `instance/` is ignored except a documented `.gitkeep` if needed.

## Import phases and dependency order

### Phase 0 — inventory only

- Discover supported legacy files without following symlinks out of the source.
- Exclude `._*`, `.git`, `.venv`, `node_modules`, `__pycache__`, pytest caches,
  logs, and executables from import candidates while listing them as ignored.
- Mark `.env`, OAuth/token/client-secret files, and personal DBs as sensitive.
- Parse supported JSON/CSV/SQLite schemas without echoing record values.
- Produce `inventory.json` and a human-readable `inventory.md` in DragonV2.

### Phase 1 — reference and taxonomy

- Import stable source records: integration types, reading sources, YouTube
  sections/groups/channels, genres, directors, tags, and chess profiles.
- Build a legacy-ID map table containing source system, source ID, DragonV2 ID,
  source checksum, and imported timestamp.

### Phase 2 — core content

- Movies from the Notion backup/export and normalized movie export, reconciled by
  Notion page ID first, TMDB ID second, then a reviewed title/year fingerprint.
- Books before quotes; unresolved book relations become reportable orphans and do
  not cause quote loss.
- Articles and RSS sources from `reading_data.json`; content HTML is sanitized and
  state fields are normalized separately from content.
- YouTube Watch Later/PocketTube items from local cache/snapshots with explicit
  source provenance.
- Chess games using source game IDs; PGN is validated before storage.

### Phase 3 — user state and history

- Movie watch progress after movie ID mapping.
- Book progress/status/history and quote favorites.
- Article read/saved/starred state.
- YouTube watched/deleted history, merging both legacy deletion stores by
  deterministic video/date fingerprint.
- Chess review queue, puzzle attempts, Lichess progress, and training history.
- German resources and playlist progress.
- Optional AI history only after a separate opt-in confirmation.

### Phase 4 — derived and optional artifacts

- Successful full-text article cache, TTS metadata/audio, poster/cover cache, and
  YouTube durations may be copied with checksums when the user chooses a faster
  warm start.
- Magnet preferences and saved sources may be imported only when the isolated
  playback feature is enabled.
- Experimental magnet runtime memory, sessions, analytics, and derived forecasts
  are not imported by default.

## Proposed migration commands

Commands are designs for the later implementation, not currently available.

```powershell
flask --app app:create_app migrate inventory `
  --source "C:\Users\walid\Desktop\FlaskDashboard"

flask --app app:create_app migrate dry-run `
  --source "C:\Users\walid\Desktop\FlaskDashboard" `
  --domains movies,books,reading,youtube,chess

flask --app app:create_app migrate apply `
  --source "C:\Users\walid\Desktop\FlaskDashboard" `
  --report-id migration_01... `
  --apply

flask --app app:create_app migrate verify --migration-id migration_01...
```

The source path is always explicit. There is no command that defaults to scanning
the user's Desktop.

## Validation and reconciliation rules

| Domain | Required validation | Reconciliation |
|---|---|---|
| Movies | title, canonical status, score range, valid year, external-ID form | source totals, duplicate map, status/score distributions, unresolved TMDB/Notion IDs |
| Books | title, authors list, status/rating range | source totals, cover/external-ID presence, relation map |
| Quotes | non-empty quote, optional page/chapter, relation list | imported/orphan/duplicate totals; no silent drops |
| Reading sources | unique stable ID, valid HTTP(S) URL, enabled state | source health fields preserved as history, not trusted current health |
| Articles | stable ID/fingerprint, title, source, safe URLs, UTC dates | totals by source/state; sanitized-content differences reported |
| YouTube | valid video/channel IDs, explicit source, section/group mappings | totals by source/group; duplicate membership retained without duplicate videos |
| Chess | valid source ID, PGN parse where present, valid attempt state | game/profile/attempt totals, orphan queue items, due-date normalization |
| Progress | mapped parent ID, finite non-negative values, UTC timestamp | latest-write selection and conflicts reported |

Source records that fail validation are written to a rejected-record report using
safe field summaries and source row IDs. Full personal content is not duplicated
into logs.

## Rollback and recovery

- Before apply: SQLite online backup plus checksum and schema revision.
- During apply: one transaction per domain and a migration run record.
- After apply: keep the backup until the user signs off on verification.
- Rollback restores only the DragonV2 instance database/snapshots. It never
  touches the legacy directory.
- Snapshot writes use temp file, flush/fsync where supported, checksum validation,
  and atomic replace. Keep the previous valid generation until the new one passes
  validation.

## Milestone plan

### M0 — foundation approval

Deliverables: this audit, target architecture, visual direction, wireframes,
component inventory, API contracts, migration plan, and milestone plan.

Gate: explicit user approval. No application code before approval.

### M1 — production skeleton and guardrails

Deliverables:

- Flask application factory with configuration override support and Blueprint
  registration.
- Unbound database, migration, login, and CSRF extensions.
- Typed settings, safe feature-flag defaults, structured logging, request IDs.
- Instance paths and complete `.gitignore`; no secrets/data in Git.
- Base shell, design tokens, reusable primitives, and protected design-system page.
- API envelope schemas and contract tests before feature endpoints.
- Health endpoint and minimal protected login/logout.

Required tests:

- multiple isolated app instances;
- missing required production secrets fail fast;
- password hashing, login/logout, authorization, session renewal;
- CSRF rejection for form and fetch mutations;
- API envelope contract;
- no external call from base GET routes;
- initial keyboard/accessibility smoke.

### M2 — local persistence, snapshots, operations, and migration inventory

Deliverables:

- shared repository/session transaction pattern;
- versioned atomic snapshot store with last-known-good fallback;
- freshness and operation-report models/services;
- read-only inventory and dry-run migration commands;
- admin operation list/detail.

Required tests: atomic write failure, missing/malformed snapshot, fallback,
timezone-aware UTC, idempotent dry run, read-only source enforcement, and secret
redaction.

### M3 — Movies and Today vertical slice

Deliverables:

- movie models/repository/service, importer, search/filter/sort/pagination;
- movie grid/list and editorial detail page;
- local playback progress and Continue Watching;
- Today projections for movies plus safe empty placeholders for later domains;
- movie API contracts/endpoints;
- TMDB/Notion adapters for explicit preview/apply operations only.

Required tests: normalization, filters, pagination, detail, progress conflict and
idempotency, metadata preview/apply, cache fallback, local-only GET, responsive
browser checks, WCAG smoke, and no legacy visual assets.

### M4 — YouTube and PocketTube

Deliverables: separate source projections, Watch Later, groups/channels, video
detail, related videos, shuffle modes, freshness, explicit sync, deletion with
preserved local history, APIs, and Today contribution.

Required tests: dedupe/membership, stable shuffle pagination, stale/missing
snapshot, failed sync retains last good data, remote delete ordering and rollback,
local-only page GET, mobile filters/nav, and accessibility.

### M5 — Reading

Deliverables: source registry/health, article list/detail, local reader, explicit
full-text extraction, state/history, recipe of the day, diagnostics, APIs, and
Today contribution.

Required tests: malformed feeds/snapshots, retention, extraction queue, HTML
sanitization, GET status makes zero network/mutation calls, targeted sync,
fallback, responsive reader, and accessibility.

### M6 — Books and quotes

Deliverables: book/quote import, library/detail, progress, metadata preview/apply,
Notion sync reports, APIs, and Today contribution.

Required tests: relation/orphan handling, metadata provider fallback/confidence,
network failure, snapshot fallback, idempotent sync, local-only GET, responsive
pages, and accessibility.

### M7 — Chess

Deliverables: game import/detail, Lichess puzzles, sessions/review, openings,
branches/lines/courses, progress, Stockfish service, APIs, and Today contribution.

Required tests: PGN normalization, attempt scheduling, due items, service timeouts,
engine process cleanup, no engine/network call on dashboard GET, keyboard board
alternatives, responsive training UI, and accessibility.

### M8 — German, AI, history, and admin completion

Deliverables: extensible German resources/vocabulary/lesson progress; unified
history; lazy contextual AI workspaces; complete admin refresh/sync/repair/source
health/snapshot inspection; global search/command menu.

Required tests: AI-disabled core app, no key leakage, explicit AI loading, protected
admin actions, confirmations, operation reports, command-menu keyboard behavior,
focus trap/Escape/restore, and all primary page smoke tests.

### M9 — optional playback isolation

Deliverables: a separately enabled package for source discovery, magnet selection,
runtime capability, player handoff, and cleanup. It may be omitted without changing
movies, progress, Today, or APIs.

Required tests: feature-disabled absence, hard resource/time limits, process and
file cleanup, path safety, no runtime work on movie GET, and failure isolation.

### M10 — release hardening and migration apply

Deliverables: full reviewed import, reconciliation report, backup/restore drill,
security review, performance budgets, production configuration guide, full API
contract suite, browser matrix, and deployment smoke.

Gate: every required test passes, no credentials/personal artifacts are tracked,
the old project checksum manifest is unchanged, and the user accepts migration
reports before DragonV2 becomes primary.

## Definition of done for every milestone

- Scope-specific unit, integration, route, contract, browser, and accessibility
  tests pass.
- New page GETs pass a network-denial test.
- Empty, loading, stale, unavailable, malformed, success, and failure states are
  represented where applicable.
- Desktop, tablet, and mobile have no page-level horizontal overflow.
- No inline style/script, unexplained `!important`, or copied legacy UI code.
- Configuration, feature flags, data changes, and operation reports are documented.
- A milestone summary lists assumptions, verification performed, and known deferred
  work before the next milestone starts.

## Review gate

Approval of this plan authorizes M1 only. Later milestones begin one at a time
after the previous milestone passes its gate; approval does not authorize copying
or mutating any legacy personal data.
