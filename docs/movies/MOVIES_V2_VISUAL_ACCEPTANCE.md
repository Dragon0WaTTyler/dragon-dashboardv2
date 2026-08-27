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

## Final correction audit — 2026-08-27

The following fresh captures were inspected in a separate disposable local
fixture after the final correction pass. The fixture populated existing UI
paths only; it did not alter the application database or runtime contracts.

| Capture | Result | Rendered finding |
| --- | --- | --- |
| A. Home hero | PASS | `TV · 2019 · 61 min · Drama · History` renders as human-readable text; no Python dict/list representation is visible. |
| B. Standard discovery rail | PASS | The populated poster rail shows seven full cards plus horizontal continuation at the desktop capture size; artwork is dominant and the rating overlay remains compact. |
| C. Top 10 | PASS | Large translucent ranks remain legible behind the poster cards while the posters stay primary. |
| D. Home Add title area | PASS | The home flow shows only the `+ Add title` trigger. Its dialog opens a focused search surface and closes with Escape; the importer is not embedded in the canvas. |
| E. Discover movie detail hero | PASS | The first viewport is backdrop-led with layered gradients, title, year, certification, runtime, rating, genres, actions, synopsis, and a secondary poster. |
| F. Detail lower modules | PASS | Overview, collapsed `Watch options & sources`, trailer, cast, review, and related-title modules were all rendered from populated existing metadata. |

The existing local movie-detail path was also captured after the correction:
its hero now uses the same backdrop-first composition while retaining Resume,
status/score, favorite, trailer, player, and source controls.

## Phase 29 A–Q evidence — 2026-08-27

Fresh rendered captures from the browser smoke test are stored outside the
repository at `C:\Users\walid\Pictures\movies-v2-phase1` (the test fixture is
disposable and does not touch the working database).

| ID | Rendered surface | Viewport | Result |
| --- | --- | --- | --- |
| A | Home hero + Continue Watching | 1280 | PASS |
| B | Browse by Provider tiles | 1280 | PASS |
| C | Because You Watched selector | 1280 | PARTIAL: behavior is exercised; native OS popup is not portable in screenshot capture |
| D | Movies on selected provider | 1280 | PASS |
| E | TV Series on selected provider | 1280 | PASS |
| F | Generic discovery rail | 1280 | PASS |
| G | Top 10 ranked rail | 1280 | PASS |
| H | Detail hero | 1280 | PASS |
| I | Detail metadata transition below hero | 1280 | PASS |
| J | Cast rail | 1280 | PASS |
| K | Trailer visual cards | 1280 | PASS |
| L | Compact review card | 1280 | PASS |
| M | More Like This rail | 1280 | PASS |
| N | Watch Options / Jackett disclosure | 1280 | PASS |
| O | Home responsive composition | 390 | PASS |
| P | Detail responsive composition | 390 | PASS |
| Q | Detail lower rail on mobile | 390 | PASS |

The same test checks that the mobile provider rail can scroll, the detail page
has no horizontal document overflow, and the selector preserves its URL state.

## Phase 30 structural completion evidence — 2026-08-28

| Surface / behavior | Verification | Result |
| --- | --- | --- |
| Dedicated Library route | `tests/integration/test_movies.py` checks `/movies/library`, heading `My Library`, and the absence of the old Home grid | PASS |
| Persistent Movies navigation | Server-rendered nav added to Home, browse, discover, detail, TV, lists, and Watch Next templates; sticky CSS is shared | PASS |
| Dynamic Home hero | Server-projected candidate deck, client dots/previous/next/auto-rotation when at least two real candidates exist; the browser fixture captures `A-home-hero-candidate-a.png` and `A-home-hero-candidate-b.png` as distinct titles | PASS |
| Inline availability provider selector | Existing provider URLs and selected state are retained; selector is visible in the shared Home rail heading | PASS |
| TV series hierarchy | Series hero metadata, season/episode counts, compact season cards, inline selected-season episode browser, and explicit secondary Jackett disclosure | PASS |
| Episode-picker null guard | `tests/browser/test_movie_player.py` season-pack flow passes with the secondary disclosure opened deliberately | PASS |
| Focused regression suites | `tests/integration/test_movies.py` (33 passed), `tests/browser/test_movies_phase1.py` (1 passed), `tests/browser/test_movie_player.py` (9 passed), `tests/unit/test_movie_services.py` (22 passed), Movies API contracts included; combined run 72 passed | PASS |

These checks are structural and behavioral evidence, not a claim that optional
external providers are configured or that PWA/offline playback is complete.

## A–AI evidence index

The live browser fixtures write the following real UI captures outside the
repository under `C:\Users\walid\Pictures\movies-v2-phase1`:

| IDs | Capture files / surface | Result |
| --- | --- | --- |
| A–N | `A-home-hero-candidate-a.png`, `A-home-hero-candidate-b.png`, `A-home-hero-continue.png`, `B-browse-by-provider.png`, `I-provider-selector-open.png`, `D-movies-on-provider.png`, `E-tv-on-provider.png`, `L-because-you-watched-changed.png`, `G-top-10.png` and existing detail captures | PASS; Because native select popup is marked PARTIAL for platform-owned popup pixels, behavior PASS |
| O–R | `O-library-top.png`, `P-library-filters.png`, `AG-library-mobile.png`, plus Home capture proving no `#movie-library` | PASS |
| S–X | `H-detail-hero.png`, `M-enrichment.png`, `N-watch-options.png`, `K-trailers.png`, `J-cast.png`, `L-reviews.png`, `M-more-like-this.png` | PASS |
| Y–AB | `Y-series-detail-hero.png`, `Z-series-seasons.png`, `AA-season-page.png`, `AB-episode-cards.png` | PASS |
| AC–AE | `AC-episode-context.png`, `AD-episode-player-playing.png`, browser `pageerror` collection is empty | PASS |
| AF–AI | `O-home-mobile.png`, `AG-library-mobile.png`, `AH-series-detail-mobile.png`, `AI-episode-mobile.png` | PASS |
