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
| Home discovery rails | 1280 | PASS | Populated cached discovery rails verify the poster-first composition, ratings, view-all affordance, and cross-rail rhythm. |
| Top 10 | 1280 | PASS | A populated Top 10 Movies rail verifies the rank-behind-poster treatment without changing discovery behavior. |
| Movies browse | 1280 and 390 | PASS | Poster-first catalog with compact Genre/Year/Country/Provider/Sort controls and shareable URL controls retained. |
| Shows browse | 1280 | PASS | Same shared browse treatment, using the explicit Shows destination rather than Series. |
| Search | 1280 | PASS | Library-first/global search surface remains a deliberate, bounded card and no longer leads the screen. |
| Movie detail first viewport | 1280 and 390 | PASS | Backdrop-first visual hierarchy with poster as a secondary element and existing actions intact. |
| Movie detail cast/trailer | 1280 | PASS | A rich, fixture-only movie record verifies populated trailer, cast, reviews, and similar-title modules. |
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

## Evidence note

The populated discovery and rich-detail records used for the complete captures
were created in a disposable SQLite file outside the repository. They exercise
existing rendering paths only; no fallback labels, runtime fixtures, catalog
records, or cache data were added to Dragon itself.
