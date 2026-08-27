# Movies V2 visual acceptance record

Reviewed against the supplied Cinejoy screenshots and the composition guidance in
`CINEJOY_FEATURE_MATRIX.md`. Screenshots were captured from local Dragon runs on
2026-08-27: the real local app where its data was suitable, and a disposable,
seeded SQLite fixture where rich artwork/progress was required. The fixture was
outside the repository and never touched the working database.

| Surface | Viewport | Result | Evidence / finding |
| --- | --- | --- | --- |
| Home top / hero | 1280 | PASS | Artwork-led hero, readable left/bottom treatment, metadata and real state actions. |
| Home Continue Watching | 1280 | PASS | 16:9 artwork card with SxxExx, remaining time, progress, and Resume. |
| Home discovery rails | 1280 | PARTIAL | Poster rail composition is verified; the fixture has no populated cached discovery rails, so provider/editorial density needs a populated-runtime recheck. |
| Top 10 | 1280 | PARTIAL | Rank-behind-poster treatment is in the rendered rail code; no populated Top 10 cache was available in the isolated fixture. |
| Movies browse | 1280 and 390 | PASS | Poster-first catalog with compact Genre/Year/Country/Provider/Sort controls and shareable URL controls retained. |
| Shows browse | 1280 | PASS | Same shared browse treatment, using the explicit Shows destination rather than Series. |
| Search | 1280 | PASS | Library-first/global search surface remains a deliberate, bounded card and no longer leads the screen. |
| Movie detail first viewport | 1280 and 390 | PASS | Backdrop-first visual hierarchy with poster as a secondary element and existing actions intact. |
| Movie detail cast/trailer | 1280 | PARTIAL | The existing rail components are retained and styled; no rich movie record was safely available in the local fixture for a visual data-filled capture. |
| TV detail and episode area | 1280 | PASS | Backdrop-led TV hero, real resume state, compact season card, and episode route verified. |
| Library | 1280 | PASS | Personal filters are compacted into controls rather than a dominant dashboard panel. |
| Mobile Home | 390 | PASS | Hero, local nav, CTAs and rail clipping were inspected; no page overflow observed. |
| Mobile detail | 390 | PASS | Backdrop, compact poster, title, and action area appear in the first screen; no hover-only dependency. |

## Fixed during audit

- Removed the abstract home masthead and decorative hero circles from the primary
  Movies canvas.
- Converted Continue Watching to landscape artwork cards and Want to Watch to a
  poster rail.
- Corrected the TV secondary grid row, which had created a dead gap before the
  season browser, and bounded season cards so a single season cannot fill the
  page width.

## Remaining evidence limitation

`PARTIAL` items are evidence limitations, not known visual failures: the
production local database did not offer safe, populated cache records for every
provider/editorial/Top 10/cast combination. They should be rechecked during the
next normal cache-populated runtime session; no fallback labels or fabricated
catalog data were added merely to make the screenshots look populated.
