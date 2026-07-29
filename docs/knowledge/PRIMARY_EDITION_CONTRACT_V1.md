# Primary Edition Contract V1

Status: current local decision note for Dragon Knowledge V2.

## Purpose

The current local app already stores edition-like metadata in two places:

- root snapshot fields on `Book`
- structured fields on `BookEdition`

This document makes the intended contract explicit so current behavior stays
coherent while Notion normalization and any later schema cleanup remain pending.

## Contract

For the current local app:

- `Book` remains the canonical local work row
- root edition-like fields on `Book` represent the selected primary-edition
  snapshot for that work
- `BookEdition(primary=True)` is the structured edition row for that selected
  edition and should mirror the root snapshot

This is intentionally not a "pick one and ignore the other" model.

## Root Snapshot Fields

The current local root snapshot includes:

- `cover_url`
- `edition_language`
- `translator`
- `publisher`
- `published_year`
- `page_count`
- `isbn_10`
- `isbn_13`

These fields exist on `Book` because the current routes, projections, metadata
preview/apply flow, and future Notion mapping still need one direct canonical
surface for the selected edition attached to the work row.

## Primary Edition Row

The primary `BookEdition` keeps the same edition identity in structured form,
along with edition-specific provider identifiers and verification state.

It exists so Dragon can also support:

- multiple editions for one work
- format assets attached to a specific edition
- edition-level verification and provider matching
- future explicit primary-edition switching

## Mirroring Rule

When a book has a selected primary edition, the root snapshot and
`BookEdition(primary=True)` should describe the same edition.

In practice:

- metadata fill to selected-edition fields should not leave the primary edition
  stale
- creating an implicit primary edition from a root-only book should seed it from
  the root snapshot
- future explicit primary-edition switching should refresh the root snapshot from
  the newly selected primary edition

## Fallback Rule

Current local read/query projections may fall back from root snapshot fields to
the primary `BookEdition` only when the root value is empty.

That fallback is:

- a compatibility guard for partially normalized local data
- useful for search, metadata lookup, and detail rendering
- not the ownership rule

Fallback must not be treated as proof that drift is acceptable.

## Drift Is a Bug

If root snapshot fields and the selected primary edition disagree for the same
book, that is local drift and should be resolved by explicit synchronization,
not preserved as a legitimate steady state.

## Mutation Guidance

Current and future mutation paths should follow this bias:

1. keep personal state on `Book`
2. treat selected-edition metadata on `Book` as the canonical snapshot surface
3. keep the primary `BookEdition` mirrored with that snapshot
4. use fallback reads only as a bridge for incomplete older rows

## Notion Mapping Implication

This contract matches the attached roadmap's intended shape:

- one canonical personal-library row
- one selected primary edition for that row
- edition ISBNs belonging to the edition, not the abstract work

For the current local app, that roadmap translates to:

- one `Book` work row with a selected-edition snapshot
- one primary `BookEdition` row that mirrors that selected edition
- additional non-primary editions when they are actually distinct
