# Asset Priority V1

Official text format order:

1. KFX
2. AZW3
3. EPUB
4. PDF

This order controls:

- preferred format badge
- read section display
- local asset sorting
- provider candidate ranking
- Kindle transfer recommendation

The order does not mean every format is browser-readable. KFX and AZW3 are
Kindle-first inventory assets in V1. EPUB and PDF are better browser runtime
candidates, but they do not outrank Kindle-optimized formats for acquisition or
availability.

Local Asset V0 follows an explicit preview/register flow:

- preview reads an existing local file path, detects the text format, calculates
  SHA-256, and shows the target edition
- register stores a local asset reference only after preview
- duplicate file hashes are rejected
- EPUB/PDF use basic container/header validation where possible
- KFX/AZW3 can be recorded with review status when only extension-level
  detection is available

Audiobooks are separate:

- M4B
- MP3
- AAC

They never alter the preferred text format.

Local Audiobook Asset V0 mirrors the text asset safety rules:

- preview reads an existing local audio path, detects M4B/MP3/AAC, calculates
  SHA-256, and shows the target audiobook edition
- register stores a local `AudiobookAsset` reference only after preview
- duplicate audiobook file hashes are rejected
- no transcoding or player runtime is included in this step
