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
| A–N | `A-home-hero-candidate-a.png`, `A-home-hero-candidate-b.png`, `A-home-hero-continue.png`, `G-want-to-watch.png`, `B-browse-by-provider.png`, `I-provider-selector-open.png`, `D-movies-on-provider.png`, `E-tv-on-provider.png`, `L-because-you-watched-changed.png`, `G-top-10.png` and existing detail captures | PASS; Because native select popup is marked PARTIAL for platform-owned popup pixels, behavior PASS |
| O–R | `O-library-top.png`, `P-library-filters.png`, `AG-library-mobile.png`, plus Home capture proving no `#movie-library` | PASS |
| S–X | `H-detail-hero.png`, `M-enrichment.png`, `U-preview-player-on-demand.png`, `N-watch-options.png`, `K-trailers.png`, `J-cast.png`, `L-reviews.png`, `M-more-like-this.png` | PASS |
| Y–AB | `Y-series-detail-hero.png`, `Z-series-seasons.png`, `AA-season-page.png`, `AB-episode-cards.png` | PASS |
| AC–AE | `AC-episode-context.png`, `AD-episode-player-playing.png`, browser `pageerror` collection is empty | PASS |
| AF–AI | `O-home-mobile.png`, `AG-library-mobile.png`, `AH-series-detail-mobile.png`, `AI-episode-mobile.png` | PASS |

## Phase 31 final width / rail correction — 2026-08-28

This pass is layout-only. It keeps the accepted Movies/TV routes, player/source
hooks, progress state, snapshots, and schema unchanged. Fresh screenshots were
captured from the disposable seeded browser fixtures at
`C:\Users\walid\Pictures\movies-v2-phase1`.

| ID | Surface | Viewport | Result | Evidence |
| --- | --- | --- | --- | --- |
| A | Home hero + global/local navigation | 1600 | PASS | `A-home-1600.png`; canvas starts at a 48px gutter and the hero fills it |
| B | Continue Watching / Home rails | 1600 | PASS | `B-home-rails-1600.png`; rails use the same wide left edge |
| C | Home after scroll | 1600 | PASS | `C-home-after-scroll-1600.png`; fixed local nav remains in the header-safe band |
| D | Library canvas | 1600 | PASS | `D-library-1600.png`; title, filters, and grid share the wide canvas |
| E | Library filters + grid | 1600 | PASS | `E-library-filters-1600.png`; no narrow centered strip |
| F | TV Series on provider rail | 1600 | PASS | `F-provider-tv-1600.png`; controls are left-middle/right-middle overlays |
| G | Same provider rail after horizontal scroll | 1600 | PASS | `G-provider-tv-scrolled-1600.png`; edge controls remain separated |
| H | Movie detail hero | 1600 | PASS | `H-detail-1600.png`; detail hero participates in the Movies canvas |
| I | Lower movie detail modules | 1600 | PASS | `I-detail-lower-1600.png`; lower content is full-width with readable inner copy |
| J | Series detail hero | 1600 | PASS | `J-series-detail-1600.png`; no narrow centered island |
| K | Season / episode workspace | 1600 | PASS | `K-season-page-1600.png`; episode area uses the same canvas |
| L | Episode player shell | 1600 | PASS | `L-episode-player-1600.png`; player behavior unchanged |
| M | Home | 1024 | PASS | `M-home-1024.png`; responsive gutter and no document overflow |
| N | Home | 390 | PASS | `N-home-390.png`; local nav can scroll horizontally without page overflow |
| O | Library | 390 | PASS | `O-library-390.png`; mobile gutters remain usable |
| P | Series detail | 390 | PASS | `P-series-390.png`; series layout remains stable on mobile |

Root cause: the shared `.page-frame` capped every Movies route at the global
`--content-width` (1320px) and contributed a 48px top padding, while detail
wrappers added their own max-widths. The correction is one scoped
`.page-frame:has(.movies-v2)` canvas rule with responsive gutters, reduced
Movies-only top padding, and explicit full-width detail wrappers. No global
Dragon layout rule was changed.

The shared `data-movie-rail` primitive now wraps each scroller in a stable
`.movie-rail-shell`; its controls are siblings of the scroller, centered on the
card viewport, and anchored to its left and right edges. Controls still disable
at the true ends and retain touch, keyboard, reduced-motion, and chunked-scroll
behavior.

## Phase 32 fixed local navigation / stable rail controls — 2026-08-28

This pass is presentation-only. The local Movies navigation is moved to a
viewport overlay so the cinematic shell cannot establish a scrolling containing
block; it stays below the unchanged global header and contributes no document
flow row. Every shared rail now owns a stable shell, with controls outside the
scrolling track. No backend, playback, provider, snapshot, or schema behavior
was changed.

| ID | Surface / assertion | Viewport | Result | Evidence |
| --- | --- | --- | --- | --- |
| A | Home top: hero plus local overlay nav | 1600 | PASS | `A-home-1600.png` |
| B | Home after document scroll | 1600 | PASS | `B-home-after-scroll-1600.png` |
| C | Movie detail top | 1600 | PASS | `C-movie-detail-top-1600.png` |
| D | Series detail top | 1600 | PASS | `J-series-detail-1600.png` |
| E | TV provider rail at start | 1600 | PASS | `E-provider-tv-start-1600.png` |
| F | Same rail after one next click | 1600 | PASS | `F-provider-tv-after-one-1600.png` |
| G | Same rail after repeated next clicks | 1600 | PASS | `G-provider-tv-after-several-1600.png` |
| H | True rail end: next disabled | 1600 | PASS | `H-provider-tv-end-1600.png` |
| I | Returned rail start: previous disabled | 1600 | PASS | `I-provider-tv-back-start-1600.png` |
| J | Generic discovery rail | 1600 | PASS | `J-generic-rail-1600.png` |
| K | Cast / related detail surface | 1600 | PASS | `K-cast-more-like-this-1600.png` |
| L | Compact mobile home nav and hero | 390 | PASS | `L-home-mobile-390.png` |

The browser assertions verify the nav has `position: fixed`, stays at the same
viewport coordinates after document scrolling, and does not occupy a separate
flow band. They also verify rail controls are siblings of the scroller, remain
at stable edge coordinates through multiple clicks, and reach disabled states at
both true ends. The focused Movies suite completed with 72 passing tests; the
browser fixture collected no page errors. Existing baseline console noise (the
known favicon 404 and CSP warnings from unrelated legacy hooks) remains outside
this presentation-only pass.

## Phase 33 unified detail and true full-bleed canvas — 2026-08-28

This pass is limited to Movies/TV presentation. It keeps the global Dragon
header, routes, data model, playback/source boundaries, progress semantics,
Jackett integration, snapshots, and database unchanged. The shared page frame
is now edge-to-edge only when its direct child is `.movies-v2`; inner rails use
an explicit readable safe area. The local Movies nav remains a fixed overlay
below the global header and contributes no flow height.

Local library movies, stateless TMDB previews, and local TV details now opt into
the same `movie-cinematic-hero` primitive. Local actions remain personal
(resume/watch, status, favorite, lists, trailer, refresh), while discovery keeps
its stateless Add to library and preview actions. The TV hero has a compact
resume CTA, centered poster, bounded height, compact season cards, and a 16:9
episode grid that preserves real progress and deep-link routes.

The browser fixtures write a focused A–P matrix outside the repository at
`C:\Users\walid\Pictures\movies-v2-unified-detail`:

| ID | Surface | Viewport | Result |
| --- | --- | --- | --- |
| A–C | Local movie hero, personal actions, lower modules | 1600 | PASS |
| D–H | Local series hero/resume, season selector, episodes, season page | 1600 | PASS |
| I–J | Stateless discovery movie hero and lower modules | 1600 | PASS |
| K–L | Stateless discovery TV hero and preview surface | 1600 | PASS |
| M–O | Full-bleed Home, local Movie, local Series | 1600 | PASS |
| P | Local Series responsive detail | 390 | PASS |

The existing smoke checks continue to assert no document overflow at mobile
widths, fixed-nav stability, rail-control ownership/end states, selected-season
deep links, player/source selection, subtitles, autoplay-next, and real progress
resume behavior. `pageerror` remains empty; the known favicon/CSP console noise
is pre-existing and not introduced by this pass.

## Phase 34 library detail closure — 2026-08-28

This pass closes the local-library detail gap without changing routes, schema,
playback, providers, Jackett, snapshots, or progress semantics. A local Movie
or Series detail now performs one bounded server-side TMDB detail hydration only
when its cached detail bundle is missing or older than 24 hours. Complete warm
cache entries render without a network call; provider failure rolls back the
attempt and leaves the local page usable. The existing manual Refresh action is
still available for an explicit forced refresh.

The Chernobyl fixture also exposed the final series geometry issue: a no-player
TV show inherited the movie detail `grid-row: 3`, creating an empty implicit row
and a large gap before Seasons. TV shows now place the secondary content in row
2, use a compact section rhythm, and render the episode browser as an actual
responsive grid. Season-page and episode deep-link screenshots assert that the
surrounding browser remains full-width and connected to the player.

The closure evidence is written outside the repository at
`C:\Users\walid\Pictures\movies-v2-library-closure`:

| ID | Surface | Result |
| --- | --- | --- |
| A–F | Local Movie detail: hero, cast, trailers, related, metadata, personal state | PASS |
| G–K | Chernobyl Series: hero, resume, seasons, episode browser, lower rails | PASS |
| L–O | Season page and episode deep-link: browser, source/player, episode context | PASS |
| P–Q | Stateless external Movie and TV detail | PASS |

The browser checks cover warm/missing/failure hydration behavior, no Chernobyl
dead space, five compact episode cards, no horizontal overflow, full-width
episode deep-link context, and an empty `pageerror` collection.

## Phase 35 unified local/discovery TV detail — 2026-08-28

The remaining local-vs-discovery split was structural, not a spacing defect.
The local TV template used a legacy `.movie-detail` grid whose hero and all
secondary modules shared one grid container. Discovery uses a standalone
`.movie-discover-hero` followed by a separate detail flow. The shared contract
is now explicit: local TV keeps the same discovery hero composition, backdrop
art, poster treatment, title scale, metadata row, overview clamp, and action
hierarchy, while adding Dragon-only status, favorite, resume, list, watch
options, and playback actions.

Local catalog metadata now renders in the same `About this series` / Overview
module as discovery. Resume is represented twice only as a compact context: a
hero-line `Resume SxxExx · percent watched · remaining` hint and the existing
lower Dragon resume action strip. The old primary `Refresh series details`
button is retained only inside collapsed `Catalog tools`.

Single-season series use a deliberate selected-season summary rather than a
large one-card rail. Multi-season titles retain the season-card selector and
deep-link routes. Episodes, cast, trailers, reviews, and More Like This use the
same rail/card primitives and order as discovery; availability remains labeled
metadata and never implies Dragon playback.

Equivalent comparison evidence is written to
`C:\Users\walid\Pictures\movies-v2-library-closure`:

| ID | Comparison surface | Result |
| --- | --- | --- |
| A | The Blacklist discovery hero | PASS |
| B | Chernobyl local hero | PASS |
| C | Discovery metadata/modules | PASS |
| D | Local metadata/modules | PASS |
| E | Chernobyl season selector | PASS |
| F | Chernobyl episode cards | PASS |
| G | Chernobyl cast rail | PASS |
| H | Chernobyl trailer rail | PASS |
| I | Chernobyl More Like This rail | PASS |
| J | Local season/episode player deep link | PASS |

The TV browser fixture verifies no accidental blank hero/season areas, an
intentional one-season presentation, compact 16:9 episode cards, responsive
no-overflow behavior, and no browser page errors. Discovery preview tests still
assert stateless behavior; no library, source, progress, or schema contracts
were changed.
