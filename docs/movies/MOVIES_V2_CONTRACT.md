# Dragon Movies V2 — Target Contracts

Status: Phase 0 contract freeze on 2026-08-25. This document defines target
invariants for a later implementation. It makes no schema, migration, route,
runtime, source or existing-data change.

The governing rule is:

```text
Dragon personal state is the source of truth.
TMDB supplies metadata/discovery.
Cinejoy supplies UX reference only.
Playback and acquisition are separate from catalog and personal state.
```

## Contract status legend

- **FROZEN**: a later implementation must conform unless this document is
  explicitly amended.
- **OPEN — approval required**: an intentionally unresolved policy. Phase 1 may
  prepare evidence but must not silently choose it.

## 1. Canonical identity

### Media key — FROZEN

Every canonical title has a typed, stable `media_key`:

```text
movie:<tmdb_id>
tv:<tmdb_id>
```

The type prefix is mandatory. A numeric TMDB identifier by itself is never a
Dragon identity and a Movie and a TV show with equal numeric IDs are different
items.

An episode has a typed child identity:

```text
tv:<tmdb_id>:s<season_number>:e<episode_number>
```

The canonical serialized form uses zero-padded two-digit season/episode numbers
where that remains representable (for example `tv:1399:s01:e05`); the parsed
identity is numeric and must not depend on display padding.

### Identity edge cases — FROZEN

1. A title without a trustworthy TMDB ID uses Dragon-owned stable identity:
   `local:movie:<movie_id>` or `local:tv:<movie_id>`. It does not receive a
   fabricated TMDB ID. Later TMDB reconciliation must be explicit and preserve
   the title's library state, progress, rating, labels, favorites, lists and
   history.
2. Specials (`season 0`) are canonical first-class episodes and may carry
   progress/manual watched state. They are excluded from default auto-next and
   normal series-completion calculations unless a later focused contract says
   otherwise.
3. TMDB is the only current external authority allowed to issue typed catalog
   identities. Other external IDs remain metadata, not canonical identity.

## 2. Canonical media metadata — FROZEN

A media record is catalog metadata, not personal state. The target contract
includes:

```text
media_key, media_type, tmdb_id
title, original_title, localized_titles[], alternative_titles[]
year, release_date
poster, backdrop, overview, genres[], runtime
original_language, spoken_languages[], country_codes[]
rating_tmdb, rating_count, status, external_ids
```

TV additionally includes real season/episode metadata, total seasons/episodes,
last aired episode and next aired episode when available. The implementation may
cache this metadata, but cache expiry cannot change personal state.

## 3. Personal library — FROZEN

`LibraryEntry` is the owner of a person’s relationship to one `media_key`.
Catalog data must not be overloaded to express this state.

```text
LibraryEntry
  media_key
  lifecycle_status
  is_favorite
  personal_rating
  personal_label
  added_at
  first_watched_at
  last_watched_at
  completed_at
```

### Lifecycle status — FROZEN

The V2 lifecycle vocabulary is exactly:

```text
want_to_watch | watching | watched
```

`watched` does not remove a title from the library. Legacy `finished` maps to
`watched` during migration. A title may be favorite at any lifecycle state.

### Favorites, rating and labels — FROZEN

- `is_favorite` is independent of lifecycle status.
- `personal_rating` is a Dragon-owned optional numeric rating; it is never a
  replacement for TMDB/external scores.
- `personal_label` preserves existing categorical labels such as `godmode`,
  `great movie` or `favorite movie`. It is independent of both `is_favorite` and
  `personal_rating`.
- Current `metadata_state.personal_score_label` migrates to `personal_label`;
  current `personal_score` migrates to `personal_rating` without rounding.

### Custom lists — FROZEN

A personal list is separate from lifecycle and favorites:

```text
List: id, slug, title, created_at, updated_at
ListMembership: list_id, media_key, added_at, position (later optional)
```

One title may belong to zero or many lists. Deleting a list never deletes the
title, library entry, progress or history.

## 4. Progress contracts

### `MovieProgress` — FROZEN

Movie progress applies only to `movie:<tmdb_id>` and contains:

```text
media_key
position_seconds
duration_seconds
percent (derived, never independently authoritative)
started_at
last_watched_at
completed_at
completed
```

There is at most one canonical progress state for a movie `media_key`.

### `EpisodeProgress` — FROZEN

Episode progress applies only to a canonical episode key and contains the same
fields as MovieProgress, plus its parent TV `media_key` is derivable from the
episode key. There is at most one canonical progress state for each episode key.
Series-level progress is a projection of episode rows, never the only stored
truth.

### Current uniqueness risk and target invariant — FROZEN

The current database **does not enforce** one row per movie or episode scope:
`e8b6c2a9f4d1` removed `UNIQUE(movie_id)` and introduced a non-unique
`INDEX(movie_id, season, episode)`. Therefore duplicate `(movie_id, NULL, NULL)`
and duplicate `(movie_id, season, episode)` rows are legal today. A future
migration must:

1. audit and report duplicates before modifying data;
2. choose/merge a deterministic winning record without losing meaningful history;
3. enforce the V2 one-canonical-state invariant at the persistence layer; and
4. test concurrent/upsert behavior and null/movie scopes explicitly.

No migration, duplicate cleanup or data modification is authorized by this
document.

### Completion rules — FROZEN

- Completion is either an explicit user action or a configured threshold/end
  event, never “recently opened.”
- Manual “mark watched” sets `completed_at` and lifecycle `watched` but retains
  the last position for replay.
- Trailer playback never changes title progress.
- Completion rules are configured separately for films and episodes.
- Movies complete at **>=95%**; normal episodes complete at **>=90%**; a trusted
  explicit `ended` event completes either scope even when duration is unknown.
- Season 0 uses the episode threshold for its own record but remains excluded
  from default auto-next/series completion.
- A stale timestamped playback update cannot immediately overwrite a newer
  manual lifecycle transition.

### Continue Watching — FROZEN

A title is eligible only when it has canonical progress satisfying:

```text
position_seconds > 0
AND completed is false
AND position_seconds is below the applicable completion threshold
AND its LibraryEntry lifecycle is not watched
```

It is ordered by `last_watched_at DESC`. A movie card displays elapsed/total; an
episode card displays `Sxx Exx`, elapsed/total and series title. Actions are
Resume, Details, Mark watched and Remove progress. It must never be populated
from a click/open event alone.

### What Should I Watch? — FROZEN

Default eligibility is deliberately narrow:

```text
LibraryEntry exists
AND lifecycle_status != watched
AND title is eligible/playable under the chosen rule
```

It chooses only from the owner’s personal library by default. Discovery-mode
recommendation, if ever added, is a different explicit mode. The result gives a
reason, Watch, Shuffle again and Details; displaying a result never marks it
watched.

## 5. Search, rails and collections

### Multilingual search — FROZEN

Search normalizes the query and merges/deduplicates candidates by `media_key`.
It searches, in order appropriate to ranking:

```text
local Dragon library
title and original_title
localized and alternate titles
TMDB candidates / alternative-title data
year and typed TMDB ID disambiguation
```

Results reveal title, original title when distinct, year and media type. Ranking
prefers exact title/original/alias, then year/prefix/fuzzy/popularity. Local
library search remains instant and visibly distinct from global catalog search.

### Collection and rail contract — FROZEN

`Collection` is catalog/editorial state with `id`, `slug`, `title`,
`description`, `artwork`, `collection_type`, ordered `media_key` items, source
and `updated_at`. Types are `editorial`, `dynamic`, `seasonal`, `award`,
`provider` and `personal`.

`MediaRail` is a reusable projection with title, optional subtitle/badge, source
label, ordered items, View All target, loading state and empty state. Rails are
configuration/data-driven, not duplicated page HTML. A “Top 10” rail must state
whether it is TMDB/trending Movies/TV; it must not claim Dragon-wide viewing
statistics without those facts.

## 6. Provider and playback boundaries — FROZEN

```text
Provider availability metadata
  = catalog/discovery information such as Netflix/Prime availability.
  != Dragon playback source.

Dragon playback source
  = configured/authorized local file, direct HTTPS/HLS, authorized embed,
    or another explicit Dragon source.
```

Catalog pages may show availability metadata, expiry and region/source context.
They may not imply that a subscription/provider is the selected Dragon stream.

```text
Metadata/control: TMDB + LibraryEntry + lists + progress
Playback runtime: player session + subtitle tracks + local process/buffer
Acquisition: authorized source lookup + local worker + optional Jackett boundary
```

The web catalog requests a source only on an explicit source/play action; it does
not fan out to providers on detail-page load. Jackett/magnet internals stay behind
the local/desktop acquisition boundary. Any future embed `postMessage` protocol
validates event origin, source frame and message schema.

### Movies preferences and disposable cache — FROZEN

Movies preferences are owner-local display/control defaults, not provider
configuration, credentials, or runtime state. The initial compact set is:

```text
autoplay_next
automatic_resume
default_subtitle_language
preferred_source
preferred_region
reduced_effects
ambient_level
```

`preferred_source` is only a fallback when no safe remembered Dragon source
selection exists. `preferred_region` scopes catalog availability metadata only;
it never selects or authorizes a playback source. A browser-local player choice
may override the account-local auto-next default. Unsupported preferences must
fail closed to established Dragon behavior.

Discovery cache ownership is frozen as follows:

| Cache | Key / boundary | Current clear action |
| --- | --- | --- |
| Rails | source, media type, query | disposable app memory |
| Browse | type, genre, year, availability provider, region, sort, page | disposable app memory |
| Alternate titles | TMDB media type + numeric ID | disposable TMDB-adapter memory |
| Collections | declarative local definition; pages reuse Browse keys | no separate mutable cache |
| Detail/provider availability | persisted presentational metadata on `Movie` | **not** included in discovery clear; explicit detail refresh only |

A fresh cache hit must not make a remote request. An expired Browse/rail entry
may revalidate for the request that needs it; if that request fails, Dragon must
retain the last cached content rather than replace it with an empty result.
No background revalidation worker is frozen by this phase. The clear action is
explicit and may clear only the disposable rows above; it must never delete or
rewrite `LibraryEntry`, lists, ratings, favorites, progress, Playback sources,
or active/runtime playback data.

Ambient artwork is presentation-only. It may sample artwork already rendered in
the browser and retain a bounded browser-session palette cache keyed by artwork
URL; it must not fetch an image solely to derive a color. A canvas/CORS failure
must keep the static Dragon fallback with no user-visible error. Ambient output,
palette cache, and reduced-motion state never enter a Movies snapshot. `off` and
reduced-effects settings must suppress the dynamic treatment; operating-system
reduced-motion remains an independent safety override.

### Feedback, loading, empty, and error states — FROZEN

UI feedback is transient presentation state and never changes a lifecycle,
favorite, list, rating, progress, source, or snapshot field by itself. A toast
may report only an action that succeeded, a selected source that has not yet
started playback, or a browser-local setting change. It must be dismissible and
must not conceal the Player's more specific inline runtime/subtitle errors.

Async search must expose a non-interactive loading state, then distinguish no
match from unavailable TMDB, unavailable network, metadata failure, source
failure, playback failure, and subtitle failure. It must not call all of those
errors “Something went wrong,” and it must not imply a catalog failure changed
Dragon personal state.

### Responsive and accessibility baseline — FROZEN

Movies surfaces must remain keyboard-operable at the supported responsive
widths (375, 390, 430, 768, 1024, 1280, and 1440+ pixels) without creating
document-level horizontal overflow. Horizontal rails may scroll within their
own labelled containers; no action may depend on hover alone. Primary touch
controls require a 44px minimum target where the platform does not provide a
larger native target.

Native dialogs retain focus, support Escape, and restore focus to their opener.
Controls that reveal/close an in-page region or dialog must keep
`aria-expanded` synchronized. Reduced-motion mode removes nonessential motion
but keeps focus, status, and essential loading/error information perceivable.

## 7. Snapshot contract

### Canonical Movies snapshot — FROZEN

`movies.snapshot.json` is portable, versioned (`schema_version`) and contains:

```text
library entries
movie progress
episode progress
personal ratings and labels
favorites
custom lists and memberships
movie preferences
personal collection state when introduced
```

It contains canonical keys and data sufficient to restore Dragon personal Movies
state. Cached TMDB metadata may be exported separately only with freshness/source
metadata; it cannot override personal state on import.

### Snapshot V1 transport — FROZEN

The implemented portable envelope is `schema_version: 1` with:

```text
exported_at
media[]                 # minimal typed identity/title seed, never a metadata cache
library_entries[]       # lifecycle, favorite, rating, label and lifecycle timestamps
progress[]              # movie and episode scopes, seconds/duration/completion/timestamps
custom_lists[]          # current owner's list key, fields and media-key memberships
preferences             # compact Movies preferences only
```

The web flow is explicit: export is authenticated; import first validates and
previews with no writes; apply requires the digest of the exact previewed JSON.
Unsupported schemas, malformed identities, duplicate media/progress/list scopes,
invalid timestamps, or invalid preference values are rejected before a database
write. V0 compatibility accepts the same basic shape when optional progress,
lists and preferences are absent; it normalizes to V1 defaults. No speculative
converter exists for an unknown schema.

Apply is a confirmed, non-deleting merge. It may restore an existing canonical
personal entry/progress/list or add a missing one, but it must not remove local
titles, list memberships, source configuration, cache data or runtime state.
List keys are owner-scoped: a key owned by a different local account rejects the
restore. The current `MovieLibraryEntry` table is still single-local-library
rather than owner-keyed; therefore its export/import scope remains the existing
Dragon local library until a separately approved ownership migration.

## 9. Activity facts — FROZEN

Canonical Movies state remains separate from the local History/profile
projection. A fact may be emitted only for a meaningful transition: movie or
episode completed, lifecycle changed, rating changed, favorite changed, or a
new list membership. Progress saves below completion, duplicate requests, card
views, search, discovery and cache refreshes emit no fact. Completion facts use
the typed media key and, when applicable, season/episode scope; they never
include a playback source, runtime session, path, subtitle, credential or
provider token.

Watch-time totals remain absent until Dragon has an append-only, reliable watch
duration ledger. A current playhead or completed duration alone must not be
presented as historical time watched.

## 10. PWA/offline shell — DEFERRED

No Movies service worker, manifest or install claim is authorized until Dragon
has an app-wide authenticated-cache policy, explicit cache invalidation, and a
reviewed rule that excludes Playback runtime/source responses and personal JSON
from public/shared caches. Offline playback is not a V2 claim. The isolated
legacy `/media/` WebTorrent worker is not a reusable Movies PWA foundation.

## 11. Performance baseline — FROZEN

Personal-library and Browse rendering must remain bounded and paginated; a
Movies page may never materialize an unbounded library just to render a grid.
Related personal/progress rows must be loaded in bounded batches rather than
per-card queries. Artwork below the primary hero uses lazy loading. Search must
debounce input and cancel stale remote requests. Virtualization, infinite
scroll, new indexes, and background work require a measured problem and a
separate review; they are not defaults to add speculatively.

### Runtime-only fields excluded from snapshots — FROZEN

Never serialize API keys, credentials, passwords, auth cookies, provider tokens,
active torrent/local-runtime sessions, process IDs, temporary file paths, buffers,
logs, transient source probes, or raw provider embed credentials. A remembered
selected-source preference may be canonical only as a safe source identifier,
never as its active runtime session.

## 8. Migration requirements — FROZEN

Before any V2 data change:

1. create and verify database and snapshot backups;
2. inventory existing Movies, `external_ids`, statuses, scores/labels, history,
   progress rows, TV metadata and playback source references;
3. report unmapped/ambiguous identities and progress duplicates without changing
   them;
4. map current `Movie` identity to canonical media identity; map `finished` to
   `watched`; preserve all legacy personal labels separately; map progress to its
   correct movie/episode key;
5. retain legacy IDs in an explicit migration mapping for rollback/reconciliation;
6. prove playback sources still resolve after canonical identity mapping; and
7. make migration idempotent, transactional where possible, and test with a copy
   of real-shape data before applying to a personal database.

## Phase 1 implementation boundary

Phase 1 is foundation-only: audit/backup, canonical identity, library and
progress migration path, duplicate-progress handling, centralized completion,
and What Should I Watch against canonical unwatched entries. It deliberately
does not include Cinejoy-like UI implementation or a snapshot exporter.
