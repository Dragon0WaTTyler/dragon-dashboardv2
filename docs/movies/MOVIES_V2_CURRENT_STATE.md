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

## Verified Phase 2 visual-shell delta

The Movies home and detail templates now use a Dragon-native cinematic shell:
an ink-and-ember atmosphere, internal Movies navigation, a poster-led personal
hero, horizontal Continue Watching rail, adaptive 2:3 library cards, and a
more editorial detail hierarchy. This is CSS/template composition only:

- all existing URLs, form names, player IDs, data attributes, source controls,
  subtitle controls and Movies JavaScript hooks are preserved;
- ordinary Movies page load still makes no new provider/source request;
- the player remains a functional Playback-owned component; and
- the visual layer respects keyboard focus and `prefers-reduced-motion`.

## Verified Phase 3 personal-home delta

The Movies home now projects Dragon-owned state instead of treating a generic
recommendation as the primary experience: Continue Watching takes priority when
there is resumable progress; otherwise the hero selects from `MovieLibraryEntry`
rows that are not watched. Its shuffle control calls the existing local
`GET /movies/api/what-should-i-watch` contract only on an explicit click. A
separate Want to Watch rail uses the existing Watch Next repository projection.
This is presentation and routing composition only: it introduces no new external
catalog/provider request, no state transition, and no playback/source change.

## Verified Phase 4 discovery-rail delta

`app/movies/rails.py` now owns a declarative registry and a five-minute,
app-scoped cache for TMDB discovery rails: Trending, Popular, Top Rated,
Upcoming, Now in Theaters, and Top 10. The normalized catalog cards are
explicitly labelled as TMDB discovery and link to Dragon's existing `discover`
route; rendering them never creates a `Movie`, `MovieLibraryEntry`, source, or
progress record. A cache miss may make one TMDB request per distinct source
query, while repeated page loads within the TTL reuse normalized cards; Top 10
reuses the Trending Movies query. View All browse targets remain deferred to
the shared browse-engine phase.

## Verified Phase 5 shared browse delta

`/movies/browse/movie` and `/movies/browse/tv` now use one typed query contract
for `genre`, `year`, `sort`, and `page`; `/movies/shows` is a convenience alias
for the Series view. Every filter and pagination value remains in the URL, so a
browse result is shareable/restorable. `app/movies/browse.py` caches genre
metadata for a day and each normalized TMDB browse page for five minutes. Its
cards remain catalog previews and link to the existing Dragon `discover` route;
they do not mutate the personal library, playback state, or acquisition data.
Language, country, availability provider, rating, and runtime filters are
explicitly deferred until their metadata/source contracts are implemented.

## Verified Phase 6 multilingual-search delta

The existing `/movies/api/search` pipeline now normalizes Unicode and
punctuation only within its search path, leaving legacy catalog identity/import
normalization untouched. It ranks Dragon title, original title, locally retained
alternate/transliterated title metadata, year, type, and explicit `tmdb:<id>`
matches before remote popularity. TMDB text results are enriched with cached
alternate titles, then deduplicated against `media_key`/TMDB identity so a local
title is not rendered twice. The search UI adds debounced requests, cancellation
of stale requests, a lightweight loading skeleton, and session-local recent
searches. It intentionally makes no claim to actor/director/people search.

## Verified Phase 7 cached-detail delta

Movie detail pages remain cache-first. An authenticated, CSRF-protected
`POST /movies/<movie_id>/refresh-metadata` is the only new explicit refresh
path; it resolves a TMDB identity and stores normalized presentational metadata
under `Movie.metadata_state.tmdb_detail`. It never selects or resolves a source,
starts playback, writes `MovieProgress`, or changes a lifecycle state.

When that cache exists, the Dragon detail template renders only real TMDB data:
backdrop, tagline, original language, production countries, US movie
certification when supplied, TMDB rating, YouTube trailer links, cast/character
credits, member reviews, and similar/recommended title cards. A missing field
removes its section rather than producing filler. Trailers open as external
links and remain outside the Dragon player. Provider availability, favorites,
custom-list controls, and acquisition claims are intentionally not represented
by this metadata cache.

## Verified Phase 8 TV detail delta

The same explicit refresh path now hydrates a TV title's real TMDB season and
episode metadata into `tv_seasons` and `tv_episodes`. The TV show and season
workspaces render those cached season names, air dates, episode titles, stills,
runtime, overview, and explicit per-episode progress. They do not synthesize a
1–10 episode list.

Season 0 is preserved and labelled **Specials**. Its canonical `s00eNN`
progress record is shown only for that special and is not inferred from normal
series ordering. Specials are excluded from default resume/auto-next and normal
season-completion counts, as frozen in the V2 contract. Existing source and
player controls remain in the Playback boundary; no new source lookup is made
by TV page rendering or metadata refresh.

## Verified Phase 9 TV resume and next-episode delta

The local player retains an explicit Resume path and now exposes Start from
Beginning when an incomplete episode record exists. On a trusted native `ended`
event it saves completion before offering the next episode; a failed progress
write never triggers the transition. The server derives that target from the
cached normal-episode catalog, including a valid next season, rather than
incrementing an episode number. Season 0 is never auto-sequenced.

The ten-second next prompt provides Play now, Cancel, and Replay. Its default
autoplay behavior is a browser-local user preference; turning it off suppresses
the automatic transition. No `postMessage` event handling was added or trusted:
the feature depends only on Dragon's native local-video `ended` event and the
same-origin progress API.

## Verified Phase 10 Library delta

The Library view now has explicit lifecycle links for All, Want to Watch,
Watching, Watched, and an independent Favorites projection. Favorites are
stored on the existing `MovieLibraryEntry`, can be toggled from Movie and TV
detail pages, and are rendered as a separate card state rather than a lifecycle
status. Toggling a favorite does not write, remove, or reset MovieProgress.
Custom-list ownership remains the dedicated next milestone.

## Verified Phase 11 custom-list delta

`MovieCustomList` and `MovieCustomListItem` are now additive, owner-scoped
tables. A list has title, optional description, timestamps, ordered membership,
and a cascade-safe foreign key to its owner. A Movie can belong to many lists;
membership is never encoded in lifecycle, favorite, or progress state. The
Movies UI supports create, edit, delete, add, and remove operations, and every
mutation resolves the list through the current authenticated owner.

## Verified Phase 12 provider-availability delta

The shared TMDB browse contract now supports an optional provider ID and
two-letter region. Provider catalogs and filtered browse pages are cached and
shareable in the URL. Explicit detail refresh caches a title's TMDB availability
labels for the selected default region and labels them as availability only. No
availability record creates, enables, probes, or selects a Dragon Playback
source; absent TMDB data is omitted rather than guessed.

## Verified Phase 13 collections-engine delta

`app/movies/collections.py` is now the sole declarative registry for Dragon
Movie collections. It exposes only safe, reviewable editorial, seasonal, and
dynamic-query definitions; every collection resolves through the existing
cache-first TMDB browse engine and its cards remain discovery previews. The
collection index is local configuration only, so opening it does not call TMDB,
write a Movie or library row, or inspect Playback sources. A collection's first
catalog page can make the same bounded TMDB browse request as the existing
Browse surface; subsequent requests reuse that cache.

The registry's contract recognizes `award`, `festival`, and `provider` types,
but exposes none until Dragon has a reliable, reviewable source for the relevant
metadata. Therefore no “award-winning”, “Oscar”, “Cannes”, “based on a true
story”, provider, or playback claim is fabricated from a loose genre query.
`/movies/collections/<collection_id>` reuses the browse result surface with its
editorial query fixed and pagination preserved in the URL.

## Verified Phase 14 source-selector delta

The existing Player source select remains the control that drives the already
tested Playback routes. Its presentation now records the selected source's
display name, source type, enabled state, effective priority, and the last
known health only when one is already persisted. `UNKNOWN` means Dragon has no
fresh recorded check; rendering the selector never calls a provider probe.
Fresh `UNAVAILABLE` authorized embeds remain omitted by the pre-existing
Playback service policy, while stale checks remain selectable rather than being
misreported as a current outage. Local runtime sources expose their existing
release metadata and report health as unchecked unless a recorded availability
row exists. This is a selector UX/projection change only: source resolution,
selection persistence, acquisition, local runtime, and provider configuration
contracts are unchanged.

## Verified Phase 15 Jackett/local-runtime boundary

Jackett release lookup remains an explicit action through the release API,
manual release browser, or deliberate TV “Find Best Source” action. Movies
Home, library/detail rendering, personal state, cached TMDB discovery, and the
new collection index do not invoke it. The cinematic Home contains no Jackett
configuration or runtime controls. When a source is explicitly selected, the
existing Playback boundary owns local runtime sessions and their transient
engine/buffer state; neither the Movie catalog nor the V2 snapshot contract
receives those fields. Existing focused tests verify that a direct embed skips
automatic source search and that normal pages do not trigger a release lookup.

## Verified Phase 16 subtitle-preservation checkpoint

No subtitle implementation was replaced. The post-selector focused baseline
passes the full Movies player browser suite, covering subtitle retrieval and
track selection, a failed-track fallback, subtitle style/offset persistence,
TV episode-specific subtitle requests, local runtime/transcode, and saved
resume behavior. The Player still owns subtitle rendering, Subtitle Rescue,
fine adjustments, drift correction, segmented resync, reset, fullscreen
controls, and source/episode-specific persistence identity; Movies V2 only
composes that tested Playback component.

## Verified Phase 17 personal-recommendations delta

`What Should I Watch` remains constrained to `MovieLibraryEntry` rows that are
not watched. Its API now accepts optional local filters for type, genre, maximum
runtime, original language when cached, decade, and random/oldest/recent sort.
The response explains only the concrete eligibility filters that were applied;
it neither queries TMDB nor invents a behavioral rationale.

The cache-only “Because you watched” rail chooses a personal watched,
high-rated, or favorited anchor, then projects only already-cached TMDB
recommendation/similar cards. It removes all identities already in the local
library and labels its signal truthfully. A missing cached detail simply omits
the rail: Home does not refresh TMDB, add a Movie, or alter personal state to
make a recommendation appear.

## Verified Phase 18 compact-settings delta

Movies V2 preferences are now persisted through the existing local
`PreferenceStore` (schema version 3) and deliberately remain separate from
Playback provider/runtime administration. The active preferences are:

- `autoplay_next`: the default for a new player-local auto-next choice; an
  already-saved browser choice still takes precedence;
- `automatic_resume`: passes a saved local position to an explicit local-player
  launch only when enabled;
- `default_subtitle_language`: first chooses a matching usable subtitle track,
  then safely falls back to any usable track when that language is unavailable;
- `preferred_source`: a default only when no remembered selected source exists;
- `preferred_region`: the default region for TMDB availability browse; and
- `reduced_effects` and `ambient_level`: persisted display choices reserved for
  the following ambient/reduced-effects phase.

`/admin/sections/movies` is the intentionally compact settings surface. It also
offers an explicit disposable-cache action that removes only the app-scoped
Movies discovery-rails, browse, and alternate-title caches. It does not touch
library entries, custom lists, personal state, progress, Playback sources, or
runtime cache. Trailer autoplay and hiding watched discovery cards are not
exposed because no truthful/current behavior exists for them yet.

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
- `integrations.py` normalizes TMDB movie/TV details, credits, actual YouTube
  trailers, member reviews, similar/recommendation candidates, and can request
  TMDB alternative titles for matching/search ranking.
- The current `/movies/api/search` path ranks normalized title, original title,
  retained localized/transliterated aliases, year/type, and explicit TMDB IDs.
  This search-only normalization does not alter legacy import identity.
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
| Partial / requires a contract | canonical Movies snapshot; custom-list ownership; provider-availability discovery; TV season/episode cache/detail; source-selector UX and next-episode policy |
| Legacy / preserve during migration | app-generated Movie IDs, JSON metadata containers, existing status vocabulary (`finished` and `watched`), score label in `metadata_state`, `watch_history`, imported Notion identifiers and historical import records |

## Historical Phase 0 boundary

The initial audit itself made no code, schema, route, provider, Jackett,
playback, source, or existing-state change. Subsequent sections record the
separately verified, incremental V2 milestones above; they do not authorize the
remaining milestones.
