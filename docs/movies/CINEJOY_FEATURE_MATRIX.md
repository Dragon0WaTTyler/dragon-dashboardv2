# Cinejoy → Dragon Movies V2 Feature Matrix

Status: Phase 0 reference matrix frozen on 2026-08-25. It identifies what may
influence Dragon’s future UX; it does not authorize copying Cinejoy code or
changing Dragon behavior.

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

`Dragon target` states the agreed direction in the supplied roadmap. “Dragon
current” records only audited evidence, not a promise of runtime availability.

| Feature | Cinejoy screenshot | Cinejoy code | Dragon current | Dragon target | Action |
| --- | --- | --- | --- | --- | --- |
| Hero | Full-bleed featured artwork, title, facts, Play/Add/Details and dots | `TrendingHeroCarousel` | No equivalent cinematic home hero | Feature-rich Dragon hero with real title state/actions | PORT_UX |
| Continue Watching | Landscape cards, time-left labels | Home derives history entries | Persisted-progress projection and Resume link | Only real incomplete progress; clear movie/episode context | KEEP_DRAGON |
| Top 10 | Poster rail / ranking treatment | `TopRankedRow`, ranking overlay | No named Top 10 projection | Explicit source-labelled trending Movies/TV Top 10 | PORT_UX |
| Reusable rails | Many horizontal poster sections | `MediaSection` | Declarative TMDB rails are cache-first, retain stale cards on refresh failure, and never create personal state | Config-driven `MediaRail` with skeleton/loading contract | BUILD_NEW |
| Provider browse | Provider-logo strip and provider-scoped rails | TMDB/provider-oriented discovery | Playback provider/source data exists; no catalog provider browsing | Availability metadata only, separate from playback | ADAPT_IDEA |
| Editorial collections | Cannes, Oscars, psychological thrillers, seasonal rows | Curated data and home sections | No canonical collection model | Editorial/dynamic/seasonal/award/provider/personal collections | BUILD_NEW |
| Because You Watched | Title-specific recommendation rail | History and TMDB recommendation composition | Local recommendation scoring exists | Explainable Dragon behavior, separate from Similar and watch-next | ADAPT_IDEA |
| Movies browse | Poster grid, Genre/Year/Popular/Provider/Country filters | `DiscoverView` | Local library filter/pagination plus discovery endpoint | Dedicated catalog browse with query-state/infinite pagination | PORT_UX |
| TV browse | Equivalent TV grid/filters | `DiscoverView` with media type | TV records share Movie model and TV workspaces | Dedicated TV browse with airing/season/network filters | PORT_UX |
| Search | Navigation search affordance | `SearchView`, TMDB service | Local normalized/original-title search; discovery search API | Local-first multilingual merged search + keyboard flow | BUILD_NEW |
| Library | “My List” / watchlist surface | `LibraryView`, Firestore watchlist | Local Movie statuses, Watch Next and filters | Library tabs: All, Want, Watching, Watched, Favorites, Lists | KEEP_DRAGON |
| Custom lists | My Lists empty state and New List action | Watchlist/collection UI, not Dragon semantics | No custom-list persistence | Multi-membership personal lists with clear ownership | BUILD_NEW |
| Movie/TV cards | Poster-first cards; hover/overlay variants | `MovieCard` | `movie_tile` grid/list and progress presentation | Unified card with state badges and mobile-safe actions | PORT_UX |
| Detail page | Cinematic backdrop, poster/actions/facts | `DetailModal`, TMDB detail data | Server-rendered detail/TV detail/player workspace | Rich detail with separate personal/catalog/playback information | PORT_UX |
| Cast | Circular cast rail with actor/character | TMDB credits mapping | `cast` JSON is rendered on detail | Preview rail + full Cast surface when data exists | PORT_UX |
| Reviews | External score badges, screenshot critic labels | TMDB detail requests reviews | No confirmed review presentation | Labelled TMDB/authorized metadata reviews, separate from Dragon rating | BUILD_NEW |
| Trailers | Trailer card in detail | TMDB videos and player components | `trailer_url` and detail action | Explicit user-controlled trailer, no progress side effect | ADAPT_IDEA |
| Similar titles | “You Might Also Like” rail | TMDB similar/recommendation mapping | Integrations retrieve similar/recommendation candidates | Content-similar rail, distinct from personal recommendation | PORT_UX |
| Source selector | Player/provider settings concept | `VideoPlayer`, provider config | Isolated source records, priorities, availability and selection | Dragon engine + Cinejoy-style selector only | PORT_UX |
| Progress / resume | Basic history/time-left display | Firestore history | Real persisted seconds/duration/completed, Resume flow | Canonical progress with completion and activity rules | KEEP_DRAGON |
| Seasons / episodes | Shows are browsable; player configuration carries season/episode | TV URLs include numeric season/episode | Real TMDB-backed season/episode workspaces and scoped progress | Canonical episode identity and derived series state | KEEP_DRAGON |
| Auto-next | Settings describes a ten-second next-episode countdown | Player event handler | No confirmed Dragon auto-next implementation | Actual next episode only, after real episode metadata/model | LATER |
| Skeletons | Implied loading polish | `Skeletons` components | Discovery search renders six non-interactive card skeletons while its request is pending | Hero/card/rail/detail/episode skeleton family | ADAPT_IDEA |
| Toasts | Interaction feedback style | `ToastContainer` | Movies has dismissible, source-aware transient toast feedback; Player keeps detailed inline states | Reusable Dragon toast only for reversible confirmations | ADAPT_IDEA |
| Responsive/mobile nav | Desktop screenshots; mobile nav components in repo | `BottomNav`, `MobileDrawer` | Movies V2 has verified no-overflow responsive surfaces, labelled internal navigation, 44px controls, and native dialog focus handling | Movie-specific navigation and rail/detail behavior | PORT_UX |
| Ambient light | Artwork colors influence background | `ambientLight`, theme utilities | Dragon samples already-rendered artwork once with a session cache and static/CORS-safe fallback; it respects off/reduced settings | Optional subtle dynamic movie atmosphere | ADAPT_IDEA |
| PWA | Install-oriented code/components | `usePWAInstall`, `InstallBanner` | Not confirmed for Movies | Post-runtime-stabilization app shell/cache policy | LATER |
| Settings | Top-nav settings control | `SettingsModal` | Compact Dragon Movies settings now persist playback defaults, availability region and display preferences; provider/runtime administration remains separate | Small Movies preferences with advanced disclosure | ADAPT_IDEA |

## Cinejoy weaknesses Dragon must not inherit

| Weakness / constraint | Dragon decision | Action |
| --- | --- | --- |
| Firebase/Firestore is the personal-library/history/settings owner | SQLite + Dragon snapshots remain Dragon truth; remote sync follows Dragon contracts | DO_NOT_COPY |
| Firebase/Firestore analytics and user telemetry | No third-party telemetry architecture; any analytics is local/private and derived from meaningful state | DO_NOT_COPY |
| Client-configured provider/embed URLs | Providers remain Dragon server-side/configured and authorized; no raw URLs in Movies UI | DO_NOT_COPY |
| Quality/download labels that may not be verified | Render capability/quality/download labels only when the Dragon source/runtime establishes them | DO_NOT_COPY |
| Hardcoded or URL-derived episode assumptions | Use real Dragon/TMDB season and episode metadata, including specials and boundaries | DO_NOT_COPY |
| Weak history-style progress model | Retain exact Dragon seconds/duration/completion and strengthen the target invariant | KEEP_DRAGON |
| Numeric-ID-only media identity | Use typed `media_key` and episode identity; never conflate movie and TV numeric IDs | DO_NOT_COPY |
| Player `postMessage` assumptions across embeds | Every future message protocol needs explicit origin, source-frame and schema validation | DO_NOT_COPY |
| Multi-brand/domain implementation and copied brand assets | Preserve Dragon identity; do not clone Cinejoy name, logo, artwork or multi-branding | DO_NOT_COPY |

## Resulting design boundary

Dragon may adopt the *composition* of a cinematic hero, poster rails, browse
filters, detail hierarchy and responsive navigation. It must not adopt Cinejoy’s
data ownership, telemetry, embed configuration, identifiers or unverified feature
claims. The first V2 implementation remains the contract/migration foundation,
not the visual shell.
