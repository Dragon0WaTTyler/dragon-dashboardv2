# Knowledge Schema V1

Status: initial local contract.

## Book Work

`Book` remains the local work row and now carries a stable `dragon_book_id`.
The existing `id` remains the database primary key for compatibility.

Core fields:

- `dragon_book_id`
- `title`
- `original_title`
- `authors`
- `additional_authors`
- `original_language`
- `edition_language`
- `translator`
- `publisher`
- `published_year`
- `isbn_10`
- `isbn_13`
- `series_name`
- `series_position`
- `subjects`
- `genres`
- `metadata_status`
- `metadata_confidence`
- `metadata_sources`

Personal fields stay on `Book` for the current local app:

- `status`
- `current_page`
- `page_count`
- `personal_score`
- `favorite`
- `personal_tags`
- `collections`
- `personal_notes`

Current local status contract:

- `wishlist`
- `reading`
- `finished`
- `paused`
- `dropped`
- `reference`

Legacy `want_to_read` rows remain readable as wishlist aliases until any future
Notion cleanup migrates them explicitly.

When those root primary-edition snapshot fields are empty, current local
projections may fall back to the primary `BookEdition` for read/query behavior.
That fallback is a compatibility layer, not a replacement for a later explicit
schema cleanup or Notion migration.

Current local interpretation:

- `Book` is still the canonical local work row
- root edition-like fields on `Book` are the selected primary-edition snapshot
- the primary `BookEdition` is the structured edition record that should mirror
  that snapshot, not compete with it as a separate source of truth

See `PRIMARY_EDITION_CONTRACT_V1.md` for the explicit local mirroring rules.

## Book Edition

`BookEdition` represents a language, translation, or publication edition.

Important fields:

- `book_id`
- `title`
- `subtitle`
- `language`
- `translator`
- `publisher`
- `publication_year`
- `page_count`
- `isbn_10`
- `isbn_13`
- `openlibrary_edition_id`
- `google_books_volume_id`
- `verification_status`
- `primary`

## Text Asset

`TextAsset` belongs to an edition, not directly to the work.

Supported V1 formats:

1. KFX
2. AZW3
3. EPUB
4. PDF

Fields:

- `edition_id`
- `format`
- `source_type`
- `source_reference`
- `local_path`
- `filename`
- `file_size`
- `file_hash`
- `availability_status`
- `verification_status`
- `preferred_for_kindle`

## Audiobook Edition

Audiobooks are parallel editions, not a fifth text format.

Fields:

- `book_id`
- `related_text_edition_id`
- `title`
- `language`
- `narrator`
- `publisher`
- `release_year`
- `duration_seconds`
- `chapter_count`
- `abridgement_type`
- `production_type`
- `verification_status`

## Availability Candidate

Provider results are temporary candidates.

Fields:

- `book_id`
- `edition_id`
- `provider`
- `title`
- `format_guess`
- `language_guess`
- `size_bytes`
- `match_confidence`
- `source_reference`
- `review_state`

Provider candidates are never canonical books, editions, or assets until a
reviewed action promotes them.
