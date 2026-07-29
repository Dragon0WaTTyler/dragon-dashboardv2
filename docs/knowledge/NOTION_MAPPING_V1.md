# Notion Mapping V1

Status: target mapping from the attached Knowledge cleanup plan. Live Notion
schema audit is still required before writeback.

## Knowledge Owns

- selected books
- status
- rating
- progress
- favorite
- collections
- tags
- personal notes
- manual corrections
- primary edition choice

## Dragon Local Owns

- `Dragon Book ID`
- normalized work, edition, asset, and audiobook models
- metadata cache
- matching confidence
- availability candidates
- search indexes

## Target Properties

- Name
- Dragon Book ID
- Original Title
- Authors
- Additional Authors
- Status
- Rating
- Reading Progress
- Favorite
- Collections
- Tags
- My Notes
- Primary ISBN-13
- ISBN-10
- Edition Language
- Original Language
- Translator
- Publisher
- Publication Year
- Pages
- Edition Name
- Edition Notes
- Open Library Work ID
- Open Library Edition ID
- Google Books Volume ID
- Overview
- Subjects
- Genres
- Series
- Series Position
- Cover
- Metadata Status
- Metadata Confidence
- Metadata Source
- Last Metadata Refresh
- Formats Available
- Preferred Format
- Audiobook Available
- Audiobook Languages

## Legacy Field Rules

- `Author` becomes a legacy migration source; `Authors` relation is canonical.
- `Decision` migrates to `Formats Available`.
- `kinde` becomes `Content Type`.
- `Summary` becomes `Overview`.
- `Checkbox` must be audited before renaming.

No personal field is overwritten by external metadata without explicit review.
