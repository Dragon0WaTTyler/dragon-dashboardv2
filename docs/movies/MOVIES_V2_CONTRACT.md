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

### Identity edge cases — OPEN — approval required

1. The policy for a legacy/local title with no trustworthy TMDB ID: provisional
   `legacy:` key, a user-selected manual identity, or ineligible until matched.
2. Whether specials (`season 0`) are canonical first-class episodes or are
   excluded from normal completion/auto-next by default.
3. Whether non-TMDB catalog authorities may ever issue canonical keys. Phase 1
   assumes no unless explicitly approved.

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

### Completion rules — OPEN — approval required

The following are frozen behavioral constraints, while the exact thresholds need
approval:

- Completion is either an explicit user action or a configured threshold/end
  event, never “recently opened.”
- Manual “mark watched” sets `completed_at` and lifecycle `watched` but retains
  the last position for replay.
- Trailer playback never changes title progress.
- Completion rules are configured separately for films and episodes.

Candidate default thresholds from the roadmap are movie 90–95% and episode 90%.
The current code has display logic around 92%; it is not the approved V2 policy.
Choose exact values before implementation.

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

## Approval gates before Phase 1

The owner must approve these open decisions before the smallest stable
implementation begins:

1. no-TMDB legacy/local identity policy;
2. treatment of TV specials/season zero;
3. exact movie and episode automatic-completion thresholds; and
4. whether the first Phase 1 scope includes only schema/contract migration and
   What Should I Watch eligibility, or also a snapshot exporter.

Phase 1 must remain foundation-only: audit/backup, canonical identity, library and
progress migration path, duplicate-progress handling, What Should I Watch against
canonical unwatched entries, playback smoke proof, and a clean checkpoint. It
does not include Cinejoy-like UI implementation.
