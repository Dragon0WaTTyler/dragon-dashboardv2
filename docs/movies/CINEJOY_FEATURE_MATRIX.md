# Cinejoy → Dragon Movies V2 Feature Matrix

Status: Phase 28 final parity review on 2026-08-27. This is an evidence-backed
comparison of the implemented Dragon Movies V2 surface, not an authorization to
copy Cinejoy code or architecture.

## Evidence used

- Nineteen supplied Cinejoy screenshots, covering My Lists, Movies and TV browse,
  a movie detail, hero, Continue Watching, provider browse and home rails.
- Reference repository: `steveyout/cinejoy`, reviewed at `cc71dfc`.
  Relevant source includes `HomeView`, `TrendingHeroCarousel`, `MediaSection`,
  `TopRankedRow`, `MovieCard`, `DiscoverView`, `LibraryView`, `VideoPlayer`,
  `SettingsModal`, PWA components and Firebase/Firestore services.
- Dragon current-state evidence: `MOVIES_V2_CURRENT_STATE.md` in this directory.

The screenshots are the visual reference. The repository is an implementation
reference only and is explicitly not a 100% representation of the captured site.

## Visual vocabulary observed in screenshots

- Artwork-reactive dark backdrop, with blurred/colorized atmosphere behind content.
- Floating, rounded desktop navigation pill; a compact mobile-navigation idea in
  the codebase.
- Poster-first rails with large imagery, sparse labels, horizontal overflow and
  “View all” affordances.
- Dedicated browse grids for Movies and Shows with compact filter pills.
- Cinematic detail hero, action cluster, metadata, cast circles, trailer and
  similar-title rails.
- Home sections for Continue Watching, provider browse, editorial/award/seasonal
  collections, popularity and personal recommendations.

## Feature matrix

`Dragon target` states the agreed direction in the supplied roadmap. Final
status is one of `DONE`, `DRAGON_EQUIVALENT`, `INTENTIONALLY_DIFFERENT`,
`DEFERRED`, or `NOT_APPLICABLE`.

| Feature | Cinejoy screenshot | Cinejoy code | Dragon current | Dragon target | Action | Final status |
| --- | --- | --- | --- | --- | --- | --- |
| Hero | Full-bleed featured artwork, title, facts, Play/Add/Details and dots | `TrendingHeroCarousel` | Cinematic personal-first hero with real Resume/Watch/Details actions | Feature-rich Dragon hero with real title state/actions | PORT_UX | DONE |
| Continue Watching | Landscape cards, time-left labels | Home derives history entries | Persisted incomplete movie/episode progress, exact scope and Resume | Only real incomplete progress; clear movie/episode context | KEEP_DRAGON | DRAGON_EQUIVALENT |
| Top 10 | Poster rail / ranking treatment | `TopRankedRow`, ranking overlay | Ranked TMDB trending Top 10 rail, explicitly source-labelled | Explicit source-labelled trending Movies/TV Top 10 | PORT_UX | DONE |
| Reusable rails | Many horizontal poster sections | `MediaSection` | Declarative cache-first rails, stale fallback, no personal-state writes | Config-driven `MediaRail` with skeleton/loading contract | BUILD_NEW | DONE |
| Provider browse | Provider-logo strip and provider-scoped rails | TMDB/provider-oriented discovery | Region-aware TMDB availability browse, kept separate from playback | Availability metadata only, separate from playback | ADAPT_IDEA | DONE |
| Editorial collections | Cannes, Oscars, psychological thrillers, seasonal rows | Curated data and home sections | Declarative Dragon collection registry; unverified award claims are not fabricated | Editorial/dynamic/seasonal/award/provider/personal collections | BUILD_NEW | DRAGON_EQUIVALENT |
| Because You Watched | Title-specific recommendation rail | History and TMDB recommendation composition | Cache-only, explainable local recommendation projection | Explainable Dragon behavior, separate from Similar and watch-next | ADAPT_IDEA | DONE |
| Movies browse | Poster grid, Genre/Year/Popular/Provider/Country filters | `DiscoverView` | Shared poster grid with URL state, genre/year/provider/region/sort and bounded pagination | Dedicated catalog browse with query-state/infinite pagination | PORT_UX | DRAGON_EQUIVALENT |
| TV browse | Equivalent TV grid/filters | `DiscoverView` with media type | Same shared browse engine with typed TV results and season workspace links | Dedicated TV browse with reliable filters | PORT_UX | DRAGON_EQUIVALENT |
| Search | Navigation search affordance | `SearchView`, TMDB service | Local-first merged multilingual/original/alternate-title search; debounce and cancellation | Local-first multilingual merged search + keyboard flow | BUILD_NEW | DONE |
| Library | “My List” / watchlist surface | `LibraryView`, Firestore watchlist | All, Want, Watching, Watched, Favorites and list entry points | Library tabs: All, Want, Watching, Watched, Favorites, Lists | KEEP_DRAGON | DONE |
| Custom lists | My Lists empty state and New List action | Watchlist/collection UI, not Dragon semantics | Owner-scoped lists with ordered memberships and CRUD | Multi-membership personal lists with clear ownership | BUILD_NEW | DONE |
| Movie/TV cards | Poster-first cards; hover/overlay variants | `MovieCard` | Shared poster/landscape card treatment with real state/progress and touch-safe actions | Unified card with state badges and mobile-safe actions | PORT_UX | DONE |
| Detail page | Cinematic backdrop, poster/actions/facts | `DetailModal`, TMDB detail data | Server-rendered cinematic detail with separated catalog, personal and playback areas | Rich detail with separate personal/catalog/playback information | PORT_UX | DONE |
| Cast | Circular cast rail with actor/character | TMDB credits mapping | Cached real TMDB cast, character and image data | Preview rail + full Cast surface when data exists | PORT_UX | DONE |
| Reviews | External score badges, screenshot critic labels | TMDB detail requests reviews | Cached, labelled TMDB review metadata; never Dragon personal ratings | Labelled TMDB/authorized metadata reviews, separate from Dragon rating | BUILD_NEW | DONE |
| Trailers | Trailer card in detail | TMDB videos and player components | User-controlled trailer action; it cannot write progress | Explicit user-controlled trailer, no progress side effect | ADAPT_IDEA | DONE |
| Similar titles | “You Might Also Like” rail | TMDB similar/recommendation mapping | Cached TMDB Similar and separate personal recommendation rail | Content-similar rail, distinct from personal recommendation | PORT_UX | DONE |
| Source selector | Player/provider settings concept | `VideoPlayer`, provider config | Explicit, configured Dragon source selector with actual status/priority only | Dragon engine + Cinejoy-style selector only | PORT_UX | DRAGON_EQUIVALENT |
| Progress / resume | Basic history/time-left display | Firestore history | Canonical scope-keyed seconds/duration/completed progress and completion rules | Canonical progress with completion and activity rules | KEEP_DRAGON | DRAGON_EQUIVALENT |
| Seasons / episodes | Shows are browsable; player configuration carries season/episode | TV URLs include numeric season/episode | Real cached TMDB seasons/episodes, season 0 and scoped progress | Canonical episode identity and derived series state | KEEP_DRAGON | DRAGON_EQUIVALENT |
| Auto-next | Settings describes a ten-second next-episode countdown | Player event handler | Actual trusted-ended TV next episode with user setting and specials boundary | Actual next episode only, after real episode metadata/model | LATER | DONE |
| Skeletons | Implied loading polish | `Skeletons` components | Non-interactive search, rail, grid/detail and episode loading states | Hero/card/rail/detail/episode skeleton family | ADAPT_IDEA | DRAGON_EQUIVALENT |
| Toasts | Interaction feedback style | `ToastContainer` | Accessible transient Movies feedback plus detailed player inline errors | Reusable Dragon toast only for reversible confirmations | ADAPT_IDEA | DONE |
| Responsive/mobile nav | Desktop screenshots; mobile nav components in repo | `BottomNav`, `MobileDrawer` | Internal nav, rail/grid/detail adaptation, 44px controls and native-dialog focus behaviour | Movie-specific navigation and rail/detail behavior | PORT_UX | DONE |
| Ambient light | Artwork colors influence background | `ambientLight`, theme utilities | Restrained artwork sampling with session fallback, reduced effects and intensity settings | Optional subtle dynamic movie atmosphere | ADAPT_IDEA | DONE |
| PWA | Install-oriented code/components | `usePWAInstall`, `InstallBanner` | No app-wide manifest/worker/cache policy; isolated `/media/` worker is not reused | Post-runtime-stabilization app shell/cache policy | LATER | DEFERRED |
| Settings | Top-nav settings control | `SettingsModal` | Compact Movies preferences for playback, availability region and display effects; administration stays global | Small Movies preferences with advanced disclosure | ADAPT_IDEA | DONE |

## Phase 28 outcome

The implemented outcome is Dragon-native rather than a Cinejoy clone. Where the
status is `DRAGON_EQUIVALENT`, the behavior deliberately has a stronger Dragon
contract (real progress, source selection, episode metadata, or explicit
server-owned state) instead of a visual/code port. Browse uses a bounded,
shareable pagination contract rather than unbounded donor-style scrolling; its
region is a real provider-availability filter, while broader catalog language,
airing-status and network filters remain future enhancements rather than fake
controls.

Only the PWA shell is deliberately `DEFERRED`: no secure authenticated cache
policy or app-wide worker exists yet, and Dragon does not claim offline
playback. Separately, the Phase 27 security audit recorded that the legacy
library/progress/preference records are not multi-account-owner scoped. That is
not a Cinejoy-parity feature and must receive an approved data migration before
Dragon can claim per-account snapshot isolation.

## Cinejoy weaknesses Dragon must not inherit

| Weakness / constraint | Dragon decision | Action | Final status |
| --- | --- | --- | --- |
| Firebase/Firestore is the personal-library/history/settings owner | SQLite + Dragon snapshots remain Dragon truth; remote sync follows Dragon contracts | DO_NOT_COPY | INTENTIONALLY_DIFFERENT |
| Firebase/Firestore analytics and user telemetry | No third-party telemetry architecture; local History is meaningful-state-only | DO_NOT_COPY | INTENTIONALLY_DIFFERENT |
| Client-configured provider/embed URLs | Providers remain server-configured; Movies receives same-origin resolver endpoints, not raw configuration | DO_NOT_COPY | INTENTIONALLY_DIFFERENT |
| Quality/download labels that may not be verified | Render capability labels only when the Dragon source/runtime establishes them | DO_NOT_COPY | INTENTIONALLY_DIFFERENT |
| Hardcoded or URL-derived episode assumptions | Use real Dragon/TMDB season and episode metadata, including specials and boundaries | DO_NOT_COPY | INTENTIONALLY_DIFFERENT |
| Weak history-style progress model | Retain exact Dragon seconds/duration/completion and the scoped progress invariant | KEEP_DRAGON | DRAGON_EQUIVALENT |
| Numeric-ID-only media identity | Use typed `media_key` and episode identity; never conflate movie and TV numeric IDs | DO_NOT_COPY | INTENTIONALLY_DIFFERENT |
| Player `postMessage` assumptions across embeds | Movies has no message listener; any future protocol requires origin/source/schema validation | DO_NOT_COPY | INTENTIONALLY_DIFFERENT |
| Multi-brand/domain implementation and copied brand assets | Preserve Dragon identity; do not clone Cinejoy name, logo, artwork or multi-branding | DO_NOT_COPY | INTENTIONALLY_DIFFERENT |

## Resulting design boundary

Dragon may adopt the *composition* of a cinematic hero, poster rails, browse
filters, detail hierarchy and responsive navigation. It must not adopt Cinejoy’s
data ownership, telemetry, embed configuration, identifiers or unverified feature
claims. The completed V2 implementation keeps those ownership and playback
boundaries intact while adapting only the approved cinematic UX ideas.
