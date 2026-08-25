# Dragon Movies V2 — Phase 1 Migration Audit

Status: applied successfully on 2026-08-25 at Alembic revision
`a9c4e1f7b2d6`.

## Pre-migration inventory

The active SQLite database was backed up with SQLite's backup API before the
schema migration. The exact backup remains ignored under `instance/backups/`.

| Item | Count |
| --- | ---: |
| Movies | 688 |
| Movies | 642 movie / 46 TV |
| Lifecycle status | 494 Want to Watch / 11 Watching / 183 Watched |
| Personal scores | 123 |
| MovieProgress rows | 46 (11 movie / 35 episode) |
| Duplicate progress scopes | 0 |
| Malformed or orphan progress | 0 |
| Reliable TMDB IDs | 34 (30 movie / 4 TV) |
| Dragon local identities | 654 |
| Playback sources | 2,446 |
| History events | 724 |

## Migration behavior

- Backfilled typed TMDB media keys and Dragon-owned local keys.
- Created one `MovieLibraryEntry` per existing Movie, mapping legacy `finished`
  to `watched` and copying score/label values without conflating labels with
  favorites.
- Added a unique progress slot key: `movie` for a movie, `sNNeNN` for an
  episode (including season 0).
- Archives discarded duplicate candidates in
  `movie_progress_duplicate_archive`; none existed in this database.
- Stops before deleting a duplicate when the newest row is incomplete but an
  older duplicate is completed, because that needs human reconciliation.

## Safety verification

The migration first failed its representative safety check because SQLite table
rebuild of `movies` cascaded to child rows. That version was never applied to
the active database. The migration was corrected to avoid rebuilding `movies`;
the final representative migration and active migration both preserved all
progress and playback-source rows.

| Verification | Result |
| --- | --- |
| Fresh migration path | exercised by the isolated test database fixtures |
| Representative copy | 688 Movies, 688 entries, 46 progress, 2,446 sources preserved |
| Active post-migration | 688 Movies, 688 entries, 46 progress, 2,446 sources, 724 history events |
| Progress duplicate scopes after migration | 0 |
| Archived duplicate records | 0 |

No known personal Movies state was lost. Do not downgrade this migration against
a real database merely to remove its additive `movies.media_key` column: SQLite
would rebuild a referenced parent table. The downgrade removes the new V2 tables
and constraints while safely retaining that ignored legacy-compatible column.
