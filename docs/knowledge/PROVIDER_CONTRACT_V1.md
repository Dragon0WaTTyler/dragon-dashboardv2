# Provider Contract V1

Providers do not own books.

## Metadata Providers

Open Library is primary. Google Books is fallback.

They may propose:

- title
- author
- overview
- cover
- subjects
- ISBN
- publisher
- pages
- publication year
- edition details

They must not silently overwrite manual Notion corrections or personal state.

The local implementation currently exposes metadata preview/apply services:

- provider adapters return candidates
- preview separates fillable empty fields from conflicts
- preview is triggered by explicit POST, never normal page GET
- apply only writes the fill plan and keeps conflicts unchanged
- personal reading state is not part of metadata apply
- non-ISBN fallback matches must respect known edition language when providers
  expose it
- translated or language-sensitive books without a compatible provider language
  signal stay in review and must not fill ISBN fields from title-only evidence

## Availability Providers

Local files, Telegram, and Jackett produce candidates.

Provider result is not:

- a `Book`
- a `BookEdition`
- a confirmed `TextAsset`
- a verified `AudiobookEdition`

Promotion requires match confidence plus explicit review.
The current local UI supports manual candidate entry plus confirm/reject review
states. A confirmed candidate is still not a confirmed asset; it remains a
provider reference until a separate asset registration step exists for that file.

Audiobook availability is separate from text availability. Manual audiobook
candidates create `AudiobookEdition` rows with `needs_review` verification and
no `AudiobookAsset`. Confirming or rejecting an audiobook candidate updates only
that edition's verification status.

Registered local audiobook assets may stream through authenticated Dragon asset
routes for local playback. UI and API responses should reference Dragon asset
IDs and stream URLs, not raw local filesystem paths.

Registered local text assets follow the same path rule. PDF assets may open
inline for browser viewing; EPUB assets may open in the authenticated local
reader, which extracts safe text from the EPUB spine and saves local progress
by Dragon asset ID. KFX and AZW3 remain authenticated file delivery for
Kindle/inventory workflows. The manual Kindle export manifest may include
Dragon asset IDs, filenames, sizes, SHA-256 hashes, format priority, edition
labels, and verification status, but must not include raw local filesystem
paths or start any transfer process.

## Jackett V1 Boundary

Jackett remains read-only candidate discovery for books. No automatic torrent
session or acquisition belongs in the first Knowledge milestones.

Current local behavior:

- search runs only from an explicit book-detail POST action
- book results are ranked by `KFX -> AZW3 -> EPUB -> PDF`
- stored references are credential-safe and do not keep Jackett API keys
- results become `AvailabilityCandidate` rows with `review_required`
- confirmation still changes review state only; it does not register an asset

## Telegram V0 Boundary

Telegram starts as manual candidate input. Automatic monitoring only comes after
manual matching and review behavior is stable.

## Kindle Clippings Boundary

Kindle highlight parsing is deterministic and local. The parser may transform
`My Clippings.txt` blocks into Book Quotes-shaped payloads containing quote
text, title, author, page/location, clipping timestamp, source `Kindle`, and a
deduplication hash.

The hash contract follows the roadmap ingredients:

- normalized book title
- normalized clipping text
- normalized location
- normalized clipping timestamp

Current behavior is parser-only. It must not store Kindle or Notion tokens,
collect secrets through the UI, infer verified book relations, or read from a
connected Kindle device.

The local sync-state/outbox contract may track:

- `synced_hashes` already accepted by a future Book Quotes sync
- `pending` payloads waiting for upload
- per-item retry attempts and the last error

Queueing must be idempotent: a hash already synced, already pending, or repeated
in the same clipping import is not queued again. Marking an item uploaded moves
that hash to synced and removes it from pending; marking an item failed keeps it
pending for retry. This remains a local contract until a Notion client is added.
If the ignored local outbox JSON is unreadable or malformed, the state store may
quarantine that runtime file with a `.corrupt-*` suffix and return an empty
state. Recovery must not mark clippings synced, upload anything, or delete the
quarantined copy.

The settings page at `/settings/knowledge/kindle-clippings` may persist the
outbox as ignored local runtime JSON after an explicit paste/import action. That
page must not ask for credentials, read from a connected Kindle, or render
local filesystem paths.
That same page may also read the presence of a dedicated ignored local secret at
`instance/secrets/kindle_book_quotes_token` plus optional local metadata at
`instance/knowledge/kindle_sync_credentials.json` in order to report sync
readiness and support explicit clear-credentials and manual sync POST actions.
It must never render the token value and must not treat the presence of those
files as proof that a Book Quotes upload succeeded.
If a dedicated local Book Quotes target ID is already present in that metadata,
the same page may also issue an explicit validation-only Notion read through a
separate POST action. That validation may update only the ignored local
readiness metadata with timestamps or safe errors, and it must not by itself
infer sync success or render token values.
The same page may also issue an explicit manual sync POST for pending outbox
rows. That sync may call the Notion API only against the dedicated canonical
`Book Quotes` target, may create pages only for rows not already present by
`Unique Hash`, and must preserve retry-safe local outbox behavior when a create
fails or the target is incomplete.

Pending clipping rows may be projected through local match review before any
sync exists. The current local priority is:

- existing relation fields in the payload, when present
- DragonBookID in the payload, when present
- known Kindle title aliases stored on the local book
- normalized clipping title plus author against local Knowledge books
- review state for missing, ambiguous, or author-mismatched rows

This projection is evidence for review only. It must not silently create a
Notion relation, write a `Quote`, or mark a clipping synced.
Manual unmatched handling may store explicit local relation fields on a pending
outbox item after a settings-page POST chooses an existing local book. That is a
local review annotation only: it must keep the item pending, must not create a
Dragon quote row, and must not write to `Book Quotes`.
Pending outbox items may also be removed through an explicit settings-page POST
when the local review queue needs cleanup. Removal must delete only that
pending runtime item, must not change `synced_hashes`, and must not create or
delete any local quote row or `Book Quotes` relation.
Bulk clear may exist only for explicitly safe local cleanup scopes such as
currently shown `matched` or `failed` rows. It must remain an explicit
settings-page POST, must not clear review-state rows by default, and must only
remove pending runtime items without changing `synced_hashes` or any quote
relation state.
Failure reset may also exist for currently shown `failed` rows. It must remain
an explicit settings-page POST, clear only the stored error/timestamp markers,
preserve retry counts for diagnostics, and keep `synced_hashes`, pending quote
payload contents, and any quote relation state unchanged.
Credential clear may also exist as an explicit settings-page POST. It must
delete only the ignored local Kindle sync secret and optional local metadata
files, and it must not touch the clipping outbox, `synced_hashes`, quote rows,
or any `Book Quotes` relation state.
Credential validation may also exist as an explicit settings-page POST. It must
read only the dedicated local Kindle token plus configured Book Quotes target,
must remain read-only against Notion, and must write only local readiness
timestamps or safe validation errors back to the ignored metadata file.
Manual sync may also exist as an explicit settings-page POST. It must remain
outbox-first, must deduplicate against `Book Quotes` by `Unique Hash`, must
scope writes to the dedicated canonical target only, and must keep failed rows
pending with retry metadata instead of dropping them.

An explicit `Book Quotes` refresh may also exist as a separate local-only
operation. It may read the canonical `Book Quotes` target through the same
dedicated token boundary, cache normalized rows into ignored local runtime
storage, and project those rows back onto local books for read-only UI
surfacing. That refresh must not mutate Notion Knowledge, must not create local
quote rows automatically, must not treat the local cache as canonical, and must
keep normal page GET routes free of background refresh behavior.
Matched cached Book Quotes rows may also participate in local Dragon search and
simple library filters such as "has highlights" after an explicit refresh, but
that search surface must still treat the cached projection as read-only and
non-canonical.
The local web may also expose a dedicated library highlights page for matched
cached rows. That page must stay backed by the local snapshot cache, must not
mutate Notion or local quote rows, and must keep unresolved rows flowing to the
separate review queue.
The local web may also expose a dedicated synced review page for those cached
rows. That page may offer local filter views, lightweight search, and explicit
manual local match actions for rows that still need review. Any such manual
match must stay in ignored local runtime storage only, must not write back to
Notion, and must not be treated as canonical when a later refresh returns a
real Book Quotes relation or `DragonBookID`.

Kindle title aliases are a local reliability aid. They may be added or removed
only through explicit local book-detail POST actions and are stored in local book
metadata state. They are not external metadata provider values, must not
overwrite canonical Notion title fields, and must not by themselves create a
Book Quotes relation.
