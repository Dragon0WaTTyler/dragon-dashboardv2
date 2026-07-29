# Knowledge Current State

Status: initial local audit for Knowledge Identity V1 on 2026-07-19.

## Local Project Shape

DragonV2 is already a modular Flask app, so the Knowledge roadmap maps onto the
existing `app/books` package instead of a new `src/knowledge` tree.

Current public routes:

- `GET /books`
- `GET /books/reading`
- `GET /books/finished`
- `GET /books/wishlist`
- `GET /books/paused`
- `GET /books/dropped`
- `GET /books/reference`
- `GET /books/audiobooks`
- `GET /books/collections`
- `GET /books/needs-review`
- `GET /books/metadata/inbox`
- `GET /books/metadata/missing-isbn`
- `GET /books/metadata/candidate-found`
- `GET /books/metadata/needs-review`
- `GET /books/metadata/verified`
- `GET /books/metadata/no-isbn`
- `GET /books/metadata/errors`
- `GET /books/formats/kfx`
- `GET /books/formats/azw3`
- `GET /books/formats/epub`
- `GET /books/formats/pdf`
- `GET /books/formats/pdf-only`
- `GET /books/formats/no-digital`
- `GET /books/signals/highlights`
- `GET /books/signals/quotes`
- `GET /books/signals/notes`
- `GET /books/highlights`
- `GET /books/quotes`
- `GET /books/<book_id>`
- `POST /books/<book_id>/progress`
- `POST /books/<book_id>/quotes`
- `POST /books/<book_id>/metadata-preview`
- `POST /books/<book_id>/metadata-apply`
- `POST /books/<book_id>/assets/preview`
- `POST /books/<book_id>/assets/register`
- `GET /books/<book_id>/assets/<asset_id>/stream`
- `GET /books/<book_id>/kindle-export`
- `GET /books/<book_id>/kindle-export/manifest.json`
- `GET /books/<book_id>/assets/<asset_id>/reader`
- `POST /books/<book_id>/assets/<asset_id>/reader-progress`
- `POST /books/<book_id>/audiobooks/assets/preview`
- `POST /books/<book_id>/audiobooks/assets/register`
- `POST /books/<book_id>/audiobooks/candidates`
- `POST /books/<book_id>/audiobooks/<audiobook_id>/confirm`
- `POST /books/<book_id>/audiobooks/<audiobook_id>/reject`
- `GET /books/<book_id>/audiobooks/assets/<asset_id>/stream`
- `POST /books/<book_id>/audiobooks/<audiobook_id>/progress`
- `POST /books/<book_id>/availability-candidates`
- `POST /books/<book_id>/availability-candidates/parse`
- `POST /books/<book_id>/availability-candidates/jackett-search`
- `POST /books/<book_id>/availability-candidates/<candidate_id>/confirm`
- `POST /books/<book_id>/availability-candidates/<candidate_id>/reject`
- `GET /settings/knowledge/diagnostics`
- `GET /settings/knowledge/book-quotes`
- `POST /settings/knowledge/book-quotes/refresh`
- `POST /settings/knowledge/book-quotes/<item_key>/assign-book`
- `POST /settings/knowledge/book-quotes/<item_key>/clear-match`
- `GET /settings/knowledge/kindle-clippings`
- `POST /settings/knowledge/kindle-clippings/queue`
- `POST /settings/knowledge/kindle-clippings/clear`
- `POST /settings/knowledge/kindle-clippings/clear-credentials`
- `POST /settings/knowledge/kindle-clippings/validate-credentials`
- `POST /settings/knowledge/kindle-clippings/sync`
- `POST /settings/knowledge/kindle-clippings/reset-failures`
- `POST /settings/knowledge/kindle-clippings/<unique_hash>/assign-book`
- `POST /settings/knowledge/kindle-clippings/<unique_hash>/remove`
- `GET /api/v1/books`
- `GET /api/v1/books/<book_id>`

`GET /books` and `GET /api/v1/books` support local Knowledge filters for
search query, status, text format, edition/audio language, metadata view,
audiobook presence, synced highlights, local quotes, personal notes, author,
translator, collection, and needs-review state. Metadata views include inbox,
missing ISBN, specific metadata statuses, verified, no-ISBN, and errors.
Search spans local identity fields, authors, languages, translators, publishers,
ISBNs, subjects, genres, collections, personal notes, audiobooks, availability
candidates, locally stored quote text/notes, and matched cached Book Quotes
highlight text after an explicit refresh.
`GET /books/highlights` now provides a dedicated library-wide synced highlights
surface with local search plus optional book filtering, while unmatched or
ambiguous rows stay in the separate review queue.
`GET /books/quotes` now provides a separate library-wide local notebook view
for manually saved quote rows, with local search plus optional book filtering
and no dependency on Book Quotes refresh state.
`GET /books/reading`, `GET /books/finished`, `GET /books/wishlist`,
`GET /books/paused`, `GET /books/dropped`, `GET /books/reference`, and
`GET /books/needs-review` now promote the main personal-library status lanes
into direct views, while still reusing the same local filter surface for
secondary slicing.
`GET /books/audiobooks` now locks the library to books with local audiobook
availability, while `GET /books/collections` adds a grouped shelf view that can
jump into one collection at a time without leaving the books area.
The books surface now also exposes direct metadata lanes for inbox, missing
ISBN, candidate-found, needs-review, verified, no-ISBN, and explicit error
states, so the metadata cleanup workflow no longer depends only on the generic
metadata filter dropdown.
The same shared surface now also exposes direct format lanes for KFX, AZW3,
EPUB, PDF, PDF-only, and no-digital-format books, so asset triage no longer
depends only on the generic format dropdown.
It now also exposes direct knowledge-signal lanes for books with synced
highlights, local quotes, and personal notes. The existing `/books/audiobooks`
lane remains the direct `Has Audiobook` view from the roadmap.

Current local persistence is SQLite through SQLAlchemy and Alembic migrations.
Runtime local data lives under the ignored `instance/` directory.

## Existing Books Boundary

Before Knowledge Identity V1, `app/books` contained:

- `Book`
- `Quote`
- thin routes
- repository-backed list/detail reads
- service projections for UI/API

The old model was enough for progress and manual quotes, but not enough for:

- stable DragonBookID
- primary edition metadata
- text assets ordered by Kindle priority
- audiobook editions
- provider candidates
- metadata review state

## Provider Boundaries

The existing Jackett integration is scoped to media releases and playback. Books
should reuse the same philosophy, not the same movie-specific runtime:

- provider result is a candidate
- no hidden acquisition
- explicit review before attaching to a book

Open Library and Google Books now have book-specific provider adapters for
metadata preview. They produce `MetadataCandidate` values and feed a merge
proposal service; they do not write to Notion or overwrite personal state.
Book detail pages can request and store a preview through an explicit POST, then
apply only the fill plan through a second explicit POST.
Today that fill path writes selected-edition snapshot fields on `Book`. The
current local contract is that the selected primary `BookEdition` should mirror
that root snapshot, while read/query fallback may still use the primary edition
when older rows leave the root snapshot empty.
Non-ISBN fallback matching now treats edition language as a safety signal:
provider candidates with a conflicting language are rejected, and translated or
language-sensitive books without compatible provider language stay in
`needs_review` without filling ISBN fields from title-only evidence.

Local text assets can be previewed from an existing absolute file path and then
registered through a second explicit POST. Registration stores local references,
format, size, hash, and verification status; it does not copy book files into
the repository.
Registered local text assets can stream through authenticated asset-id routes.
PDF assets open inline for browser viewing; KFX and AZW3 are delivered as
authenticated downloads for Kindle/inventory use. A manual Kindle export page
now selects the best local transfer asset by `KFX -> AZW3 -> EPUB -> PDF`,
shows a safe manifest with filenames, sizes, hashes, editions, and verification
state, and links to authenticated downloads. It does not copy files, convert
formats, or initiate device transfer. EPUB assets can open in a local reader
route that extracts safe spine text from the archive and caches reader progress
locally by asset ID. The original EPUB stream route remains available for
authenticated file delivery. Registered local paths are not rendered into the
UI or export manifest.

Local audiobook assets use the same preview/register pattern, but they attach to
`AudiobookEdition` and `AudiobookAsset` records instead of text editions.
Audiobook availability candidates can also be entered manually with language,
narrator, publisher, duration, chapter count, abridgement, and production
signals. Confirming or rejecting a candidate changes only the audiobook
edition verification status; it does not create an audio asset and does not
affect preferred text format.

Registered local audiobook assets can now be played from the book detail page
through authenticated asset-id stream routes. The UI does not render registered
local file paths. Listening progress is cached locally in book metadata state
with position, duration, chapter, speed, completion, and update timestamp.

Availability candidates can now be entered manually and reviewed on the book
detail page. Confirming a candidate changes only its review state; it does not
create a text asset or start any provider acquisition.

Pasted Telegram, Jackett, or local result text can also be parsed into a
review-only candidate. The parser extracts a supported text format, a likely
title, language hints, size hints, and a bounded source reference, but still
requires human review before any follow-up.

Jackett book fallback is available as an explicit book-detail POST action. It
uses the shared local Jackett credentials, searches book categories, ranks
results by `KFX -> AZW3 -> EPUB -> PDF`, strips API keys from stored references,
and saves only review candidates. It does not start playback, torrents, or file
registration.

Knowledge diagnostics are available at `/settings/knowledge/diagnostics`. The
page reports local counts, format coverage, review queues, integrity guards, and
provider boundaries. Local counts include
verified metadata, missing ISBN, explicit no-ISBN, and needs-review status
breakdowns, plus a PDF-only count for books whose only registered text format is
PDF. They also include unmatched local books with no registered text asset and
no reviewable availability candidate, plus unmatched Kindle highlights from the ignored local
clippings outbox; this is a local matching signal only and does not read from or
write to Notion `Book Quotes`. Integrity guards include DragonBookID
presence/uniqueness, asset hash duplicates, duplicate availability candidates,
provider automation boundaries, and ISBN-10/13 checksum validation for populated
book and edition ISBN fields. Explicit no-ISBN books are treated as legitimate;
malformed populated ISBNs are flagged.
The diagnostics also flag missing canonical authors, edition language,
publisher, and cover coverage from local book/edition/audiobook fields. Open
queues now surface local Kindle outbox items that still need review and route
them back to `/settings/knowledge/kindle-clippings`. The same page can also run
an explicit `Book Quotes` refresh action that reads the canonical Notion
database into an ignored local snapshot cache. The summary also exposes
the latest local metadata refresh timestamp stored on books and a local storage
estimate based on registered local text/audio asset sizes, plus the last local
`Book Quotes` refresh. When pending Kindle
items carry retry errors, diagnostics also expose the latest local outbox error
message and failure timestamp. Refreshed `Book Quotes` rows also contribute
matched/review counts and a small synced-highlight queue for rows that still do
not map cleanly to a local book.

Kindle `My Clippings.txt` parsing now has a local deterministic foundation in
`app/books/clippings.py`. It can parse Kindle highlights, notes, and bookmarks
from exported clipping text, normalize the roadmap deduplication ingredients
(`book title + clipping text + location + clipping timestamp`), and produce a
Book Quotes-shaped payload with source `Kindle` and a stable SHA-256 unique
hash. The same module also defines a serializable sync-state/outbox primitive:
new clippings are queued unless their hash is already synced, already pending,
or duplicated in the same import; uploaded hashes move from pending to synced;
failed hashes keep retry metadata. The local settings page at
`/settings/knowledge/kindle-clippings` can now
persist that outbox under the ignored `instance/knowledge/` runtime directory
from an explicit paste action. The page also projects pending items through a
local match review pass: existing Dragon relation fields are honored if present,
known Kindle title aliases can match, and otherwise normalized title plus
author can identify a single Dragon book. Unknown, ambiguous, or author-mismatch
items stay in review state. Retry attempts and the latest local sync error now
surface directly on the outbox page from the same ignored state file. The same
page now supports local filter views for review, matched, ambiguous, and failed
items, and diagnostics queue links can jump directly into the matching filtered
outbox view. This projection does not create Notion relations or write local
quote rows. Book detail pages now expose explicit local add/remove
controls for Kindle title aliases; aliases are stored in the book's ignored
local metadata state and feed only the matching projection. Pending clipping
rows can also be assigned to an existing local book through an explicit settings
page POST action; that stores local relation fields in the outbox payload for
review and does not create a `Quote`, call Notion, or mark the hash synced.
Pending clipping rows may also be removed explicitly from the local outbox when
they are unwanted or malformed; removal clears only that pending runtime item
and does not touch synced hashes, quote rows, or Notion state.
When the current filter is `matched` or `failed`, the same page may also clear
all currently shown rows through an explicit POST action. Bulk clear remains a
local queue cleanup only: it removes those pending runtime items and leaves
review-state rows, synced hashes, quote rows, and Notion state untouched.
When the current filter is `failed`, the page may also reset those failure
flags through an explicit POST action. Resetting a failed row clears only the
stored error marker and timestamp so the item can rejoin the normal pending
queue for a future retry; it keeps retry counts, synced hashes, quote rows, and
Notion state unchanged.
If the ignored local Kindle clippings state file becomes unreadable or contains
invalid JSON, the state store quarantines that runtime file beside the original
with a `.corrupt-*` suffix before returning an empty state. Later explicit paste
imports can then write a fresh outbox without marking any clipping synced.
The same settings route now also surfaces a local sync-readiness boundary for
Kindle manual sync credentials. It checks only a dedicated ignored
secret file at `instance/secrets/kindle_book_quotes_token` plus optional local
metadata at `instance/knowledge/kindle_sync_credentials.json`, never renders
the secret value, and can clear those local files through an explicit POST.
When a local token and Book Quotes target ID are already present, the same page
can also validate that target through an explicit POST-only Notion read. That
validation updates only local readiness metadata and does not collect
credentials in the UI or read Kindle hardware. The same page can now also run
an explicit manual sync POST that uploads pending outbox items to the canonical
Notion `Book Quotes` target. That sync path stays local-first and retry-safe:
it checks the dedicated target schema, requires a mappable `Unique Hash`
property for deduplication, queries the target before create, marks remote
duplicates as synced locally, and leaves failed rows in the local outbox with
retry metadata. Normal page GET routes still remain local-only, and there is
still no background sync loop or Kindle device read.

The next local-web slice now has a first concrete implementation for synced
highlights too. An explicit diagnostics action can refresh `Book Quotes` into
an ignored local snapshot file under `instance/knowledge/`, using the same
dedicated Book Quotes target and token boundary as Kindle sync. Snapshot rows
are matched back to local books with the existing priority order
(`DragonBookID`, stored relation evidence, known Kindle aliases, then
normalized title plus author). Matched rows now surface read-only in the book
detail page under a `Highlights` panel. The synced side now also has a
dedicated review page at `/settings/knowledge/book-quotes` with local filter
views, lightweight text search, and explicit manual book assignment for rows
that still need review. Those manual assignments are stored only in the ignored
local snapshot as review hints, survive future refreshes when Notion still
lacks canonical relation evidence, and yield automatically if a later refresh
returns a real Book Quotes relation or `DragonBookID`. This remains a
cache/projection layer: it does not write back to Notion Knowledge and does not
mutate local quote rows. A dedicated `/books/highlights` page now surfaces only
matched synced highlights across the library, keeps search/filter local to the
cached snapshot, and routes unresolved rows back to the review queue instead of
mixing review actions into the read-only library view.
Local `Quote` rows now also have a dedicated `/books/quotes` page. That view is
intentionally separate from synced highlights: it lists only local notebook
quotes saved from book detail pages, supports local search and per-book
filtering, and does not depend on Notion refresh state or mutate Book Quotes.
The main books surface now also exposes direct local pages for `Reading`,
`Finished`, `Wishlist`, and `Needs Review`, so the core roadmap lanes no longer
depend entirely on query-string filters.
The same shared navigation now also includes direct `Audiobooks` and
`Collections` pages. The audiobook lane reuses the main books surface with the
audio filter locked on, while the collections lane layers grouped personal
shelf chips on top of the same local book-card projection.
The current local app now treats `wishlist` as the canonical personal-library
status for books you plan to read later. Older `want_to_read` rows remain
supported as a legacy alias in local filters and direct wishlist views, but new
progress updates normalize that status back to `wishlist`.
Metadata review now has its own secondary navigation inside the books surface.
Those direct metadata pages still render through the same local books template,
but each route locks one metadata state so cleanup work can move lane by lane.
Format triage now follows the same pattern with a dedicated secondary
navigation inside the books surface, locking one format state per route while
still reusing the shared local filter form and card layout.
Knowledge-signal triage now follows the same pattern too: synced highlights,
local quotes, and personal notes each have a direct book-card lane inside the
shared books surface, while the separate `/books/highlights` and `/books/quotes`
pages remain content-first views instead of book-filter lanes.
Local projections and provider queries now also fall back to the primary
`BookEdition` when root book fields such as edition language, translator,
publisher, ISBN, page count, or cover are still empty. That keeps book detail,
API projections, metadata queries, and Jackett query language aligned with the
primary-edition contract even before a deeper persistence sync exists.

## Notion State

The attached roadmap defines the target Notion shape:

- `Knowledge` is canonical for the personal library and primary edition choice.
- `Book Quotes` is canonical for highlights and quotes.
- Dragon local mirrors and normalizes, but never silently overwrites personal
  fields.

Live Notion schema inspection is still required before any Notion writeback or
bulk cleanup. Until that audit is done, local code must preserve legacy fields
and treat Notion mappings as contracts, not confirmed live state.

## Safety Notes

- No book files, audiobook files, provider keys, local paths, or Notion tokens
  belong in git.
- Normal page GET routes must render from local data only.
- All external sync/enrichment work should be explicit operations.
