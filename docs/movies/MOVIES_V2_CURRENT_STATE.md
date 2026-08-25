# Dragon Movies V2 — Current-State Audit

Status: Phase 0 baseline frozen on 2026-08-25; Phase 1 foundation applied on
2026-08-25 at Alembic revision `a9c4e1f7b2d6`. Sections explicitly labelled
“current” below describe the pre-Phase-1 baseline unless superseded by the
verified Phase 1 delta. This remains an evidence record, not a UI plan.

## Scope and evidence

- Audited application: the Flask/Jinja Dragon Movies surface only.
- Audited commit: `4510614 fix: compact mobile embedded player action`.
- Source reviewed: `app/movies/`, `app/playback/`, `app/api/v1/routes.py`,
  Movie templates/assets, migrations, focused tests, and the existing foundation
  and M10/M11 records.
- Focused baseline: `28 passed in 16.45s` from
  `.venv\\Scripts\\python.exe -m pytest -q tests/unit/test_movie_services.py tests/integration/test_movies.py`.
- “Confirmed working” below means implemented in the current code and covered by
  this focused baseline or a directly relevant existing browser test. It does not
  claim that every optional external integration is configured on every machine.

## Verified Phase 1 delta

The active database was migrated only after a SQLite backup and a representative
copy both verified preservation of Movies and Playback state. See
`MOVIES_V2_PHASE1_MIGRATION_AUDIT.md` for the exact counts.

| Contract area | Current Phase 1 state |
| --- | --- |
| Canonical title identity | `Movie.media_key` is typed as `movie:<tmdb_id>` / `tv:<tmdb_id>` when a reliable TMDB ID exists, otherwise Dragon-owned `local:movie:<movie_id>` / `local:tv:<movie_id>`. |
| Personal ownership | `MovieLibraryEntry` now owns V2 lifecycle, favorite, rating and label state, while legacy Movie fields are retained and mirrored for compatibility. |
| Progress invariant | `MovieProgress.scope_key` makes one movie slot (`movie`) or episode slot (`sNNeNN`) unique per Movie. A safe archive table exists for any discarded duplicate during migration. |
| Completion | Centralized rules are movie >=95%, normal/special episode >=90%, or an explicit trusted `ended` signal. Manual lifecycle timestamps prevent stale timestamped playback from immediately overriding a manual transition. |
| What Should I Watch | `GET /movies/api/what-should-i-watch` selects only an unwatched `MovieLibraryEntry`; it makes no TMDB or source-provider request. |
| Snapshot timing | No new Movies snapshot exporter/importer was added in Phase 1. |

SQLite cannot alter a referenced `movies` table without rebuilding it, which
would cascade-delete child source/progress rows. The migration therefore uses an
additive `media_key` column plus a unique index and non-empty SQLite triggers;
the ORM model also requires a media key. This is a deliberate safety boundary,
not an omission.

## Ownership map

```text
Movies blueprint (/movies)
  ├─ models.py                 persisted Movie and MovieProgress records
  ├─ repositories.py           local library queries, filters, projections
  ├─ services.py               item/detail/TV workspaces, statuses, progress,
  │                            recommendation scoring
  ├─ external_library.py       TMDB/Notion discovery, import and write-back
  ├─ integrations.py           provider adapters and normalized metadata
  ├─ providers.py              movie-facing provider adapters
  └─ templates/static          server-rendered Movies UI

Playback blueprint (/playback)
  ├─ models.py                 PlaybackSource, availability, provider preference,
  │                            import rows, local/magnet candidates
  ├─ services.py/runtime.py    source selection and isolated local runtime
  ├─ subtitles.py              track discovery, proxy and sync support
  └─ routes.py                 feature-gated player/source/local-runtime APIs

Shared infrastructure
  ├─ SQLite + Alembic          source of truth and schema evolution
  ├─ HistoryService            meaningful movie/status/progress events
  ├─ snapshots/                atomic, versioned generic snapshot store
  ├─ migration/legacy.py       approved legacy import path
  └─ api/v1                    read/write projections used by clients
```

The application factory registers the Movies and Playback blueprints separately.
That separation is real and must be preserved: Movies owns catalog and personal
state; Playback owns source/runtime concerns.

## Persisted Movies data

### `Movie` — Phase 0 baseline, superseded in Phase 1

`app/movies/models.py` owns the current `movies` table. Its application-generated
primary key is `mov…`; it is **not** the target canonical media identity.

| Group | Current fields |
| --- | --- |
| Identity/catalog | `id`, `title`, `normalized_title`, `original_title`, `media_type`, `year`, `runtime_minutes` |
| Personal/library | `status`, `personal_score`, `category`, `source` |
| Presentation metadata | `overview`, `poster_url`, `trailer_url`, `genres`, `directors`, `cast` |
| Flexible/import metadata | `external_ids`, `metadata_state`, `watch_history` |
| Audit | `created_at`, `updated_at` |

Current status values validated by `MovieService` are
`want_to_watch`, `watching`, `finished`, `watched`, and `unknown`. A numeric
personal score is 0–5. The optional legacy-style score label is currently stored
inside `metadata_state.personal_score_label`, rather than as a first-class field.

`external_ids` carries TMDB and legacy/Notion identifiers. Phase 1 adds the
persisted `media_key` and a separate personal-state record; alternate-title
search and custom lists remain target-contract gaps.

### `MovieProgress` — Phase 0 baseline risk, resolved in Phase 1

`movie_progress` currently stores `movie_id`, nullable `season` and `episode`,
`current_seconds`, `duration_seconds`, `completed`, `client_updated_at`, and
`updated_at`. A null/null row represents movie-level progress; a populated pair
represents TV episode progress. `Movie.progress_entries` is the complete ordered
relationship, while `Movie.progress` is a view-only movie-level relationship.

The service validates non-negative positions, requires season and episode as a
pair, bounds a position to duration, rejects stale client timestamps for an
already selected row, and records an event. TV workspaces derive watched counts,
completion percentage, resume target, and exact/fallback local-source state from
the episode rows plus TMDB episode metadata.

**Historical integrity risk — confirmed by migration and model review:** migration
`1c7f96e2a4b8` initially made `movie_id` unique. Migration `e8b6c2a9f4d1`
removed that constraint, added nullable `season`/`episode`, and created only the
non-unique index `ix_movie_progress_scope(movie_id, season, episode)`. The model
declares the same non-unique index. Therefore the database currently permits
multiple rows for the same movie-level scope and for the same `(movie_id, season,
episode)` scope. `MovieService.get_progress()` masks this by selecting the most
recent row; equal timestamps and the view-only `uselist=False` relationship leave
duplicate state unsafe/ambiguous. Phase 1 audited the actual rows (zero duplicate
groups), then added `scope_key` and `UNIQUE(movie_id, scope_key)`. The migration
archives recoverable discarded duplicates and stops on the unsafe completed vs
newer-incomplete conflict. See the Phase 1 audit for the applied result.

### TV seasons and episodes — partial but substantial

TV catalog data is currently stored in `Movie.metadata_state` as `tv_total_seasons`,
`tv_total_episodes`, `tv_seasons`, and `tv_episodes`. `tv_show_workspace()` and
`tv_season_workspace()` build the rendered season/episode projections, including
episode title, runtime, air metadata when supplied, watched/progress state, and
resume target. TMDB endpoints can fetch season and episode data on demand.

This is operationally useful and covered by focused integration/browser tests,
but the season/episode catalog is JSON metadata rather than a canonical target
identity/data contract. No assertion in this audit treats it as the final V2
shape.

## Current routes and API surface

All Movies routes are login-protected. The main current routes are:

| Area | Current routes |
| --- | --- |
| Library/index | `GET /movies`, `GET /movies/watch-next`, `GET /movies/<movie_id>` |
| Discovery | `GET /movies/discover/<media_type>/<tmdb_id>`, `GET /movies/api/search`, `GET /movies/api/tv/<tmdb_id>/seasons`, `GET /movies/api/tv/<tmdb_id>/seasons/<season>/episodes`, `GET /movies/api/releases` |
| Library mutations | `POST /movies/api/library`, `POST /movies/api/import`, `POST /movies/<movie_id>/watch`, `POST /movies/<movie_id>/status`, `POST /movies/<movie_id>/score`, `GET /movies/api/what-should-i-watch` |
| TV workspace | `GET /movies/<movie_id>/seasons/<season>`, `GET /movies/<movie_id>/seasons/<season>/episodes/<episode>`, `GET /movies/api/library/<movie_id>/seasons/<season>`, `POST /movies/<movie_id>/seasons/<season>/episodes/<episode>/resolve-source` |
| API v1 projection | `GET /api/v1/movies`, `GET /api/v1/movies/recommendations`, `GET /api/v1/movies/<movie_id>`, `GET|PUT /api/v1/playback-progress/movie/<movie_id>` |

Playback adds the separate `/playback/movie/<movie_id>/…` source, embed,
subtitle, local-runtime, catalog-import, local-source and magnet routes. Their
existence does not make them part of the Movies ownership boundary.

## Rendered UI ownership

| Layer | Current owner |
| --- | --- |
| Library, filters, pagination, recommendation and continue card | `app/templates/movies/index.html` |
| Watch-next collection | `app/templates/movies/watch_next.html` |
| TMDB discovery detail | `app/templates/movies/discover.html` |
| Movie detail and player shell | `app/templates/movies/detail.html` |
| TV show / season / episode workspaces | `app/templates/movies/tv_show.html`, `tv_season.html` |
| Browser behavior | `app/static/js/movies.js`, `app/static/js/movie-detail.js` |
| Styles | `app/static/css/pages/movies.css`, shared layout/components/tokens |
| Cross-application navigation | `app/templates/layouts/app.html` |

The current visual lane is Dragon Noir, documented in M11: near-black surfaces,
crimson actions, warm typography, restrained grain, responsive mobile navigation,
and reduced-motion support. The existing foundation wireframes intentionally use
a restrained editorial Movies page rather than a cinematic hero; that is a
documented prior design direction, not an excuse to change it in this phase.

## Catalog, TMDB, search and library flows

- `external_library.py` orchestrates TMDB catalog search/detail and Notion library
  import/synchronization/write-back adapters.
- `integrations.py` normalizes TMDB movie/TV details, credits, videos, similar and
  recommendation candidates, and can request TMDB alternative titles for release
  matching.
- The current local `MovieRepository.list()` search matches only normalized title
  and original title. It does not persist or query the full alternate/localized/
  transliterated-title target contract.
- Discovery and release search are external/explicit flows. Normal library GETs
  operate on local persisted Movies; they should not become a hidden refresh path.

## Current personal projections

### Continue Watching — confirmed working

`MovieRepository.continue_watching()` and `MovieService.continue_watching()`
select records with a positive, non-completed `MovieProgress` and exclude
`finished`/`watched` movie statuses. They order by progress `updated_at`
descending. The index page renders the resulting “continue” card and Resume
links. This is a real persisted-progress projection, although its target ordering
will later be formalized as `last_watched_at`.

### Watch Next / recommendation — confirmed working, target differs

`MovieRepository.watch_next()` is a local-library query for
`status == want_to_watch`, ordered by personal score, shortest runtime, then
recent update. `MovieService.recommended()` and the index rotation operate on
that same intent with local metadata scoring/explanations. This is not yet the
target explicitly bounded “What Should I Watch?” contract with eligibility,
filters and a result interaction.

## Playback, local runtime, subtitles and Jackett

### Source resolution — confirmed and feature-gated

`PlaybackSource` owns configured local, magnet and authorized/indexed embed
records, scoped to movie or season/episode. It has source status, selection,
provider, authorization, enabled/priority and non-secret provenance metadata.
Its existing unique constraint is `(movie_id, scope_key, provider,
provider_asset_id)`. Provider availability and per-provider preferences are
separate Playback records.

`PlaybackService` resolves sources and makes exact-episode vs season-pack fallback
decisions. The player only exposes optional behavior when the corresponding
server-side flags permit it. A Movie detail opening is not itself a mandate to
probe every provider.

### Local playback and subtitles — confirmed for the tested paths

The Playback runtime is isolated behind `/playback/runtime/<session_id>` and
start/stop endpoints. Browser tests cover source selection, local runtime status,
resume refresh, subtitles, subtitle fallback, and season-pack episode selection.
`app/playback/subtitles.py` owns track discovery/proxy and the browser player
exposes the resulting track options; subtitle correction belongs to the playback
layer, not Movie metadata.

### Jackett/magnets — partial and intentionally isolated

Movies can request releases and route an approved candidate to `MagnetCandidate`
and `PlaybackSource`. The runtime code handles the heavy local session rather
than making the catalog page a torrent runtime. This boundary is correct in
principle but remains an optional configured path; Phase 0 does not make any
claim that every Jackett/provider setup is available locally.

## Snapshots, sync and migration

- SQLite remains the current source of truth. `SnapshotStore` is a generic atomic
  store with validation and last-valid fallback.
- The current Movies tables are included in the approved legacy importer and
  Notion/TMDB flows, but this audit found no dedicated canonical
  `movies.snapshot.json` V2 export/import contract yet.
- M10 records an earlier non-destructive migration dry run; M11 records an
  approved local legacy import. Those reports are historical evidence, not a
  substitute for a V2 migration plan.
- `Movie.watch_history` and `HistoryService` coexist. The target contract must
  distinguish state from meaningful activity events.

## Relevant migrations

| Migration | Effect | Status |
| --- | --- | --- |
| `1c7f96e2a4b8_create_movies_and_progress` | Introduced `movies` and single-row-per-movie progress | historical baseline |
| `e8b6c2a9f4d1_scope_movie_progress_by_episode` | Added nullable season/episode; removed unique `movie_id`; added non-unique scope index | active risk documented above |
| `1f6c4b8d9e72_add_episode_scoped_playback_sources` | Added episode-scoped playback-source support | active playback foundation |
| `af6c42e9b831_add_isolated_playback_sources` | Isolated source and magnet persistence | active playback foundation |
| `d4a8f2c9e731_add_playback_provider_foundation` | Added provider/source scope and a source uniqueness invariant | active playback foundation |
| `e5b9d3a0f842_add_provider_availability_cache` | Added provider availability cache | active playback foundation |
| `f6c0e4b1a953_add_playback_provider_preferences` | Added provider preferences | active playback foundation |

## Relevant tests

| Test area | Evidence |
| --- | --- |
| Movie model/service/progress/filter/recommendation | `tests/unit/test_movie_services.py` |
| Movies routes, discovery/library mutations, TV workspace, release/source behavior | `tests/integration/test_movies.py` |
| Player, resume, subtitles, local runtime and TV season-pack behavior | `tests/browser/test_movie_player.py` |
| API envelope/progress contracts | `tests/contracts/test_movies_api.py`, `tests/contracts/test_content_api.py` |
| TMDB adapter behavior | `tests/unit/test_tmdb_provider.py`, `tests/unit/test_movie_integrations.py` |

## Readiness classification

| Status | Current capability |
| --- | --- |
| Confirmed working | local Movie/status/score records; persisted progress; library filtering; watch-next; TMDB discovery; TV workspace; source selection; feature-gated local player; subtitle/browser flows covered by tests |
| Partial / requires a contract | canonical identity; multilingual local search; separate library entry/favorite/list models; canonical Movies snapshot; deterministic progress uniqueness; target collections/rails/reviews/provider-availability discovery |
| Legacy / preserve during migration | app-generated Movie IDs, JSON metadata containers, existing status vocabulary (`finished` and `watched`), score label in `metadata_state`, `watch_history`, imported Notion identifiers and historical import records |

## Phase 0 non-goals observed

This audit made no code, schema, route, provider, Jackett, playback, source, or
existing-state change. It does not authorize Phase 1.
