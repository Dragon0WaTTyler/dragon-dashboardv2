# Initial API v1 contracts

Status: approved as the M0 contract baseline on 2026-07-14. M1 implements and
tests the common envelopes and health contract only.

## Principles

- Prefix every endpoint with `/api/v1`.
- Normal reads use normalized local persistence and validated local snapshots
  only. A GET endpoint never refreshes, syncs, extracts, enriches, or mutates.
- JSON uses `snake_case`, UTF-8, ISO 8601 UTC timestamps with `Z`, stable string
  IDs, and explicit `null` for unavailable optional values.
- Collection endpoints use offset pagination. Default `limit` is 20; maximum is
  100. Invalid filters return `400`, not silent coercion.
- Unknown resources return a stable `404` error contract. Missing/malformed local
  data is represented as freshness or availability metadata when the request can
  still succeed.
- Browser sessions and future iOS API tokens are separate authentication modes.
  State-changing API endpoints require a scoped token or an authenticated browser
  session plus CSRF.

## Common envelopes

### Paginated success

```json
{
  "ok": true,
  "api_version": "v1",
  "items": [],
  "count": 0,
  "total": 0,
  "limit": 20,
  "offset": 0,
  "has_more": false,
  "next_offset": null
}
```

`count` is the number of returned items. `total` is the count after filters but
before pagination. `next_offset` is `null` when `has_more` is false.

### Single-resource success

```json
{
  "ok": true,
  "api_version": "v1",
  "item": {}
}
```

### Error

```json
{
  "ok": false,
  "api_version": "v1",
  "error": {
    "code": "validation_error",
    "message": "One or more request values are invalid.",
    "fields": {"limit": "Must be between 1 and 100."},
    "request_id": "req_01..."
  }
}
```

Allowed baseline error codes: `authentication_required`, `forbidden`,
`not_found`, `validation_error`, `conflict`, `feature_disabled`,
`local_data_unavailable`, `operation_failed`, and `internal_error`. Safe public
messages never contain token values, local absolute paths, upstream response
bodies, or tracebacks.

## Shared types

### Freshness

```json
{
  "domain": "movies",
  "state": "fresh",
  "snapshot_version": "movies.v1",
  "generated_at": "2026-07-13T20:00:00Z",
  "last_success_at": "2026-07-13T20:00:00Z",
  "age_seconds": 1080,
  "stale_after_seconds": 21600,
  "is_stale": false,
  "source": "local_snapshot",
  "message": "Using the latest local movie snapshot.",
  "active_operation_id": null
}
```

`state` is one of `fresh`, `stale`, `missing`, `malformed`, `refreshing`, or
`failed`. A failed refresh does not replace a valid older snapshot.

### Operation summary

```json
{
  "id": "op_01...",
  "kind": "sync",
  "domain": "reading",
  "scope": "all_sources",
  "status": "completed_with_warnings",
  "started_at": "2026-07-13T20:00:00Z",
  "completed_at": "2026-07-13T20:00:08Z",
  "counts": {"seen": 120, "created": 8, "updated": 12, "skipped": 100, "failed": 0},
  "warnings": ["One source used its fallback URL."],
  "report_url": "/admin/operations/op_01..."
}
```

Operation status is `queued`, `running`, `completed`,
`completed_with_warnings`, or `failed`.

## Endpoint inventory

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Process and database health; no private counts |
| GET | `/home` | Today projection from local domains |
| GET | `/movies` | Filtered movie collection |
| GET | `/movies/{movie_id}` | Movie editorial detail |
| GET | `/books` | Book collection |
| GET | `/books/{book_id}` | Book detail with quote summary |
| GET | `/articles` | Filtered article collection |
| GET | `/articles/{article_id}` | Cached article detail |
| GET | `/youtube/videos` | Videos across a selected source/section/group |
| GET | `/youtube/sections` | Watch Later and PocketTube navigation |
| GET | `/youtube/sections/{section_id}` | Section/group detail |
| GET | `/chess/home` | Chess dashboard projection |
| GET | `/chess/games` | Imported games |
| GET | `/chess/games/{game_id}` | Game detail |
| GET | `/chess/train-today` | Current training recommendation |
| GET | `/chess/openings` | Opening collection |
| GET | `/chess/courses` | Course collection |
| GET | `/chess/progress` | Progress projection |
| GET | `/playback-progress/{media_type}/{item_id}` | Current local progress |
| PUT | `/playback-progress/{media_type}/{item_id}` | Idempotent progress update |
| GET | `/freshness` | All-domain freshness |
| GET | `/freshness/{domain}` | One-domain freshness |
| GET | `/operations/{operation_id}` | Status/report for an explicit operation |

The existing legacy aliases `/api/v1/youtube`, `/api/v1/me`, and
`/api/v1/articles/{id}` can be supported during migration, but the contracts
above are the canonical surface.

## First contract: Home

`GET /api/v1/home`

```json
{
  "ok": true,
  "api_version": "v1",
  "item": {
    "date": "2026-07-13",
    "continue_items": [
      {
        "kind": "movie",
        "id": "mov_01...",
        "title": "Example title",
        "subtitle": "48 minutes left",
        "image_url": "/media/posters/mov_01...",
        "progress_percent": 63,
        "href": "/movies/mov_01..."
      }
    ],
    "recommended_movie": {
      "id": "mov_02...",
      "title": "Example title",
      "year": 2024,
      "reason": "From your local watch-next list.",
      "poster_url": "/media/posters/mov_02..."
    },
    "latest_youtube": [],
    "chess_training": {
      "due_count": 3,
      "estimated_minutes": 12,
      "href": "/chess/train"
    },
    "freshness_warnings": [],
    "compact_stats": {
      "watching_movies": 2,
      "unread_articles": 18,
      "books_in_progress": 1
    }
  }
}
```

Every nested section may be empty or `null` without failing the whole endpoint.
Ordering is determined by the Today service, not the API route.

## First contract: Movies collection

`GET /api/v1/movies`

Query parameters:

- `q`: title/director text search.
- `status`: repeatable canonical status.
- `genre`, `category`, `source`: repeatable stable slugs.
- `score_min`, `score_max`: decimal values on the canonical 0–5 scale.
- `year_min`, `year_max`: four-digit years.
- `sort`: `title_asc`, `title_desc`, `score_desc`, `year_desc`,
  `recently_watched`, or `recently_updated`.
- `limit`, `offset`.

Movie list item:

```json
{
  "id": "mov_01...",
  "title": "Example title",
  "year": 2024,
  "status": "watching",
  "personal_score": 4.5,
  "poster_url": "/media/posters/mov_01...",
  "progress": {
    "current_seconds": 4200,
    "duration_seconds": 7200,
    "percent": 58,
    "completed": false,
    "updated_at": "2026-07-13T20:00:00Z"
  }
}
```

Allowed status values are `want_to_watch`, `watching`, `finished`, `watched`, and
`unknown`. `progress` is `null` when not applicable.

## First contract: Movie detail

`GET /api/v1/movies/{movie_id}` returns:

```json
{
  "ok": true,
  "api_version": "v1",
  "item": {
    "id": "mov_01...",
    "title": "Example title",
    "original_title": null,
    "media_type": "movie",
    "year": 2024,
    "runtime_minutes": 120,
    "status": "watching",
    "personal_score": 4.5,
    "overview": "Locally cached synopsis.",
    "poster_url": "/media/posters/mov_01...",
    "trailer_url": null,
    "genres": [{"id": "genre_drama", "name": "Drama", "slug": "drama"}],
    "directors": [{"id": "person_01...", "name": "Example director"}],
    "cast": [{"id": "person_02...", "name": "Example actor", "role": "Role"}],
    "progress": null,
    "watch_history": [],
    "external_ids": {"tmdb": "123", "notion": null},
    "metadata_state": {
      "review_required": false,
      "last_enriched_at": "2026-07-12T20:00:00Z"
    },
    "updated_at": "2026-07-13T20:00:00Z"
  }
}
```

No magnet, stream, token, or private provider payload is embedded in movie detail.
The optional playback subsystem exposes a separate protected capability.

## Books and articles

`GET /books` supports `q`, `status`, `tag`, `sort`, `limit`, and `offset`. Book
items include `id`, `title`, `authors`, `status`, `progress_percent`,
`personal_rating`, `cover_url`, `pinned`, and `updated_at`.

`GET /articles` supports `q`, `source`, `topic`, `state`, `starred`, `sort`,
`limit`, and `offset`. Article items include `id`, `title`, `source`,
`published_at`, `excerpt`, `image_url`, `read`, `saved`, `starred`,
`extraction_status`, and `reading_minutes`.

`GET /articles/{article_id}` returns cached content only. Its content object is:

```json
{
  "status": "available",
  "html": "<p>Sanitized cached HTML.</p>",
  "text": "Cached plain text.",
  "word_count": 820,
  "cached_at": "2026-07-13T20:00:00Z",
  "error": null
}
```

`status` is `not_requested`, `queued`, `extracting`, `available`, or `failed`.
This GET must never change the status.

## YouTube

`GET /youtube/sections` returns a paginated list of section items:

```json
{
  "id": "yt_watch_later",
  "source": "watch_later",
  "name": "Watch Later",
  "kind": "playlist",
  "video_count": 42,
  "channel_count": null,
  "freshness": {"state": "fresh", "last_success_at": "2026-07-13T20:00:00Z"}
}
```

`source` is `watch_later` or `pockettube`. `GET /youtube/videos` accepts
`source`, `section_id`, `group_id`, `channel_id`, `watched`, `order`, `limit`, and
`offset`. `order` is `normal`, `shuffle`, or `shuffle_stable`; stable shuffle
requires a `seed` and remains deterministic across pages.

Video items include `id`, `video_id`, `title`, `channel_id`, `channel_title`,
`thumbnail_url`, `published_at`, `duration_seconds`, `watched`, `source`,
`section_ids`, and `group_ids`. Playlist item IDs are returned only when needed by
an authorized removal capability.

## Playback progress

`PUT /playback-progress/movie/{movie_id}` request:

```json
{
  "current_seconds": 4200,
  "duration_seconds": 7200,
  "completed": false,
  "client_updated_at": "2026-07-13T20:00:00Z"
}
```

The response is the canonical saved progress. Values must be finite and
non-negative; current time is clamped to duration only after validation. A stale
`client_updated_at` returns `409 conflict` with the current server item instead of
silently overwriting newer progress. Repeating the same request is idempotent.

## Freshness and operations

`GET /freshness` returns a paginated collection of shared Freshness items for
`movies`, `youtube_watch_later`, `youtube_pockettube`, `reading`, `books`,
`chess`, and optional integrations. It never starts an operation.

`GET /operations/{operation_id}` returns the shared Operation summary and may add
domain-safe details. Full diagnostic tracebacks remain local admin logs and are
not API output.

## Contract test matrix

Every collection contract tests:

- exact required envelope fields and types;
- default, minimum, maximum, and invalid `limit`/`offset`;
- stable sort and pagination without duplicates;
- empty, missing-snapshot, malformed-snapshot, and stale-snapshot behavior;
- unknown filters and resource IDs;
- JSON content type and UTF-8;
- UTC timestamp form;
- no secret/local-path leakage;
- a network-denial fixture proving GET performs no external call.

Mutation contracts additionally test authentication, authorization scope, CSRF
for browser sessions, idempotency, validation, conflict handling, atomic rollback,
and operation-report creation.
