# Product UX, design system, and wireframes

Status: approved as the M0 design brief on 2026-07-14. These remain low-fidelity
planning artifacts; the M1 production shell implements the approved direction.

## Feature summary

Dragon is a single-user personal operating workspace for deciding what to do
next across media, reading, books, chess, and learning. It is used frequently,
often for a short focused check-in, so the interface must make the next action
obvious while keeping library depth and administration available without visual
noise.

The primary action is: resume or choose one meaningful item, with enough local
freshness context to trust the choice.

## Design direction

- Color strategy: **Restrained**. Warm neutral surfaces carry almost all of the
  interface; blue is reserved for selection, progress, links, and primary action.
- Scene sentence: one person at a quiet desk in soft daylight, checking a
  well-kept personal index before settling into the next activity.
- Anchor references: Linear for operational clarity and compact controls,
  Readwise Reader for editorial reading density, and Things 3 for calm daily
  prioritization. These are behavioral references, not layouts to copy.
- Fidelity: low-fi wireframes now; high-fi and production implementation only
  after this foundation is approved.
- Breadth: global shell plus Today, Movies, and Movie Detail across desktop and
  mobile.
- Interactivity: flows and states are specified now; no prototype is implemented.

The direction is intentionally unrelated to the legacy black/red Cinema Prive
interface: no permanent sidebar, cinematic hero, glass surface, red glow,
decorative serif typography, floating AI button, or oversized decorative cards.

## Information architecture

Desktop primary navigation is a second, stable row under the app bar:

`Today · Movies · YouTube · Reading · Books · Chess · More`

`More` contains German, History, AI workspaces, Admin, and Design System. AI is
also available from the command menu and eligible detail-page actions.

Mobile bottom navigation contains Today, Movies, YouTube, Reading, and More.
Books, Chess, German, History, AI, and Admin live in More. The compact top bar
contains the Dragon mark, search/command trigger, and status/account menu.

## Layout rules

- Desktop content width: maximum 1,200px with 24–32px page gutters.
- Reading/detail prose width: 68–76 characters.
- Main rhythm: 8px base spacing scale, with 24px between related sections and
  40–48px between major page regions.
- The desktop shell is flat. Page sections use whitespace or a hairline divider;
  primary containers are used only when they clarify grouping.
- Context panels are closed by default and open as a right drawer or dialog.
- At 900px, dense two-column arrangements collapse intentionally.
- At 720px and below, the desktop module row disappears and bottom navigation
  appears. No horizontal nav or page-level horizontal scrolling is allowed.
- Touch targets are at least 44×44px. Tables become labeled record rows or an
  explicitly scrollable table region with a visible cue; they never silently clip.

## Design tokens

### Color

| Token | Light value | Use |
|---|---:|---|
| `--color-bg` | `#F7F7F2` | Page canvas |
| `--color-surface` | `#FFFFFF` | Primary controls and grouped content |
| `--color-surface-muted` | `#F0F0EA` | Subtle selected/secondary region |
| `--color-text` | `#171714` | Primary text |
| `--color-text-muted` | `#68685F` | Secondary text |
| `--color-border` | `#E2E2DA` | Hairline borders |
| `--color-accent` | `#315CF5` | Primary action, focus, selected state |
| `--color-accent-soft` | `#E8EDFF` | Subtle selection and progress track |
| `--color-success` | `#218358` | Healthy/completed |
| `--color-warning` | `#B7791F` | Stale/requires attention |
| `--color-error` | `#C93C37` | Failure/destructive action |

Dark mode is a later token substitution, not the default identity. It must use
opaque surfaces and the same hierarchy; no glow, blur, or translucent glass.

### Typography

- Interface: IBM Plex Sans with system sans-serif fallback.
- Technical metadata only: IBM Plex Mono.
- Display 32/40, page title 26/34, section title 18/26, body 15/23, compact body
  14/20, label 12/16. Weight, spacing, and scale establish hierarchy; headings
  are not decorative.
- Dates and sync IDs use the mono face only when their technical form matters.

### Spacing, radii, borders, and motion

- Spacing: 4, 8, 12, 16, 24, 32, 40, 48, 64px.
- Buttons/inputs: 8px radius. Primary grouped containers: 12px radius. Status
  badges and avatars may be fully rounded.
- Border: 1px hairline. Shadows are absent by default; dialogs may use one quiet
  elevation shadow.
- Motion: 160ms for control feedback, 200ms for drawers/dialogs. Animate opacity
  and transform only. Under `prefers-reduced-motion`, remove nonessential motion
  and make transitions effectively immediate.
- Focus: 2px accent outline with 2px offset, always visible on keyboard focus.

## Reusable component inventory

### Shell and navigation

- `app_bar`: brand, command trigger, refresh/status, theme, account.
- `module_nav` and `mobile_bottom_nav`: stable selected states and badges only
  for meaningful warnings.
- `page_header`: one H1, optional supporting sentence, primary action cluster.
- `command_dialog`: searchable actions/content, focus trap, Escape, restored focus.
- `context_drawer`: optional detail/AI/admin context, never permanently open.

### Actions and forms

- Buttons: primary, secondary, quiet, destructive, icon-only with accessible name.
- Input, search input, select, checkbox, radio, switch, segmented control.
- `filter_bar`: query, compact selects, active filter summary, reset.
- `pagination`: first/previous/page/next with result range.
- `confirm_dialog`: explicit consequence, cancel-first tab order, no ambiguous copy.

### Content and feedback

- `content_row`: title, supporting metadata, optional thumbnail, progress, action.
- `movie_tile`: poster, title, year, status, score, optional progress only.
- `progress_bar`: value plus visible text; color is not the sole signal.
- `status_badge`: neutral/success/warning/error with text label.
- `freshness_notice`: source, last successful update, state, action.
- `operation_report`: totals, changed/skipped/failed, warnings, report ID.
- Empty, loading, skeleton, unavailable, malformed-data, and permission states.
- Toasts for reversible confirmations; persistent inline errors for failed actions.
- `data_table` and mobile `record_list` with the same semantic fields.
- `poster`, `thumbnail`, and `cover` image macros with width/height, lazy loading,
  fallback art, and useful alt rules.

### Domain components

- Today: resume row, recommendation row, daily training row, freshness digest.
- Movies: view switcher, movie result grid/list, rating control, status control,
  cast/crew list, watch progress, trailer disclosure.
- YouTube: source switcher, group/channel navigation, shuffle control, watched action.
- Reading: source health row, article row, extraction state, reader typography.
- Books: book row, quote block, reading progress, metadata candidate comparison.
- Chess: board shell, move list, training prompt, attempt feedback, session summary.

## Desktop wireframes

### Today — 1440×900 reference

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Dragon                 [ Search or run a command…  ⌘K ]   ↻  Up to date  ◐ W│
├──────────────────────────────────────────────────────────────────────────────┤
│ Today   Movies   YouTube   Reading   Books   Chess   More                    │
└──────────────────────────────────────────────────────────────────────────────┘

        ┌──────────────────────────── max 1200px ──────────────────────────┐
        │ MONDAY, 13 JULY                                                  │
        │ Today                                                            │
        │ Pick up where you left off or choose one useful next step.       │
        │                                                                  │
        │ ⚠ Reading snapshot is 2 days old. Last good sync …   [Review]    │
        │──────────────────────────────────────────────────────────────────│
        │ CONTINUE                                                        │
        │ [poster] Movie title        48 min left      ━━━━━━━━── [Resume]│
        │ [cover ] Current book       page 142 / 280   ━━━━━───── [Open]  │
        │ [image ] Saved article      8 min read                   [Read]  │
        │──────────────────────────────────────────────────────────────────│
        │ RECOMMENDED MOVIE                                                │
        │ [poster] Title · Year · short reason derived from local library  │
        │                                      [View details] [Watch next] │
        │──────────────────────────────────────────────────────────────────│
        │ LATEST FROM YOUTUBE                                              │
        │ [thumb] Title / channel / saved 2h ago                    [Open]  │
        │ [thumb] Title / channel / saved 5h ago                    [Open]  │
        │──────────────────────────────────────────────────────────────────│
        │ TODAY'S CHESS                                                    │
        │ 12-minute review · 3 due positions             [Start training]  │
        │                                                                  │
        │ Library: 3 compact facts only          Sources: 8 healthy, 1 old │
        └──────────────────────────────────────────────────────────────────┘
```

Hierarchy: resume rows come first, followed by one recommendation, recent saved
content, and the daily training task. Statistics are a quiet footer. A warning is
shown only when the user can understand or act on it.

### Movies — 1440×900 reference

```text
┌─ global app bar and module nav; Movies selected ─────────────────────────────┐
└──────────────────────────────────────────────────────────────────────────────┘

        ┌──────────────────────────── max 1200px ──────────────────────────┐
        │ Movies                                      [＋ Add] [Sync ▾]    │
        │ 371 titles · local library updated 18 min ago                    │
        │                                                                  │
        │ [Search titles…________________] [Status ▾] [Genre ▾] [More]     │
        │ Active: Watching ×  2020–2026 ×          [Grid | List] [Sort ▾]  │
        │──────────────────────────────────────────────────────────────────│
        │ [poster]  [poster]  [poster]  [poster]  [poster]                 │
        │ Title     Title     Title     Title     Title                    │
        │ 2024      1999      2018      2021      1972                     │
        │ Watching  Finished  Want      Watched   Watching                 │
        │ ★ 4.5     ★ 5.0     —         ★ 4.0     ★ 4.0                   │
        │ ━━━━━──                                            ━━━━━━━──    │
        │                                                                  │
        │ [poster]  [poster]  [poster]  [poster]  [poster]                 │
        │ …                                                                │
        │──────────────────────────────────────────────────────────────────│
        │ Showing 1–50 of 371                  [Previous] 1 2 3 … [Next]   │
        └──────────────────────────────────────────────────────────────────┘
```

Grid cards contain only the approved six data roles. Hover does not reveal
essential actions. List view adds columns for category/source/last activity, with
the same filtering URL and preserved pagination.

### Movie detail — 1440×900 reference

```text
┌─ global app bar and module nav ───────────────────────────────────────────────┐
└──────────────────────────────────────────────────────────────────────────────┘

        ┌──────────────────────────── max 1080px ──────────────────────────┐
        │ ← Movies                                                         │
        │                                                                  │
        │ ┌──────────────┐  THE GODFATHER                                  │
        │ │              │  1972 · Crime, Drama · 2h 55m                   │
        │ │    poster    │  Directed by Francis Ford Coppola               │
        │ │              │                                                  │
        │ │              │  [Want to watch ▾]  [Rate]  [Ask AI]            │
        │ │              │  ━━━━━━━━━━━━━━━──────── 1h 42m / 2h 55m        │
        │ └──────────────┘  [Resume] [Trailer] [More ▾]                    │
        │                                                                  │
        │                    A clean, readable synopsis in a bounded line  │
        │                    length. No backdrop or overlaid hero text.     │
        │                                                                  │
        │──────────────────────────────────────────────────────────────────│
        │ DETAILS                         CAST                              │
        │ Personal score  4.5             Name · role                      │
        │ Source          Notion          Name · role                      │
        │ Last watched    …               [View all cast]                   │
        │──────────────────────────────────────────────────────────────────│
        │ WATCH HISTORY                  METADATA                           │
        │ Simple dated rows              TMDB match · last enriched …      │
        │                                 [Report metadata issue]           │
        └──────────────────────────────────────────────────────────────────┘
```

The top region is an editorial two-column composition, not a cinematic hero.
Trailer, full cast, AI, and metadata diagnostics open only when requested.

## Mobile wireframes

### Today — 390×844 reference

```text
┌──────────────────────────────────┐
│ Dragon             [⌕] [Status] │
├──────────────────────────────────┤
│ MONDAY, 13 JULY                  │
│ Today                            │
│ Choose one useful next step.     │
│                                  │
│ ⚠ Reading is 2 days old [Review] │
│──────────────────────────────────│
│ CONTINUE                         │
│ [img] Movie title                │
│       48 min left  ━━━━━──       │
│                         [Resume] │
│ [img] Current book · 51%  [Open] │
│ [img] Saved article       [Read] │
│──────────────────────────────────│
│ RECOMMENDED MOVIE                │
│ [poster] Title · 2024            │
│          one-line reason         │
│          [View details]          │
│──────────────────────────────────│
│ TODAY'S CHESS                    │
│ 3 positions due [Start training] │
│                                  │
├──────────────────────────────────┤
│ Today  Movies  YouTube  Reading  More│
└──────────────────────────────────┘
```

### Movies — 390×844 reference

```text
┌──────────────────────────────────┐
│ Dragon             [⌕] [Status] │
├──────────────────────────────────┤
│ Movies                     [＋]  │
│ 371 titles · local 18m ago       │
│ [Search titles…_______________]  │
│ [Filters · 2] [Grid|List] [Sort] │
│ Watching ×  2020–2026 ×         │
│──────────────────────────────────│
│ [poster]          [poster]       │
│ Title             Title          │
│ 2024 · Watching   1999 · Finished│
│ ★4.5  ━━━━━──     ★5.0           │
│                                  │
│ [poster]          [poster]       │
│ …                                │
│──────────────────────────────────│
│ 1–20 of 371        [‹] 1/19 [›]  │
├──────────────────────────────────┤
│ Today  Movies  YouTube  Reading  More│
└──────────────────────────────────┘
```

Filters open an accessible full-height sheet with Apply and Reset fixed at the
bottom. The grid never falls below a readable poster width; the list view becomes
one labeled record per row.

### Movie detail — 390×844 reference

```text
┌──────────────────────────────────┐
│ ‹ Movies            [More]       │
├──────────────────────────────────┤
│ [poster]  THE GODFATHER          │
│           1972 · Crime, Drama    │
│           2h 55m                 │
│                                  │
│ [Want to watch ▾] [Rate]         │
│ ━━━━━━━━━━━━━──────── 1h42 / 2h55│
│ [Resume] [Trailer] [Ask AI]      │
│──────────────────────────────────│
│ Synopsis text with comfortable   │
│ measure and a Read more control. │
│──────────────────────────────────│
│ Details                          │
│ Director      Francis F. Coppola │
│ Personal score             4.5   │
│ Source                  Notion   │
│──────────────────────────────────│
│ Cast                         [›]  │
│ Watch history                [›]  │
│ Metadata                     [›]  │
├──────────────────────────────────┤
│ Today  Movies  YouTube  Reading  More│
└──────────────────────────────────┘
```

The poster and title share the first row to avoid a tall media hero. Secondary
sections disclose progressively. The bottom navigation remains present unless a
modal player intentionally takes over the screen.

## Key states and interaction model

| State | Required behavior |
|---|---|
| Loading | Server pages render structural content immediately; only explicit async actions use localized skeletons/spinners |
| Empty | Explain what belongs here and provide one relevant setup/import action |
| Missing snapshot | Show the page shell and a safe empty state; never auto-refresh |
| Stale snapshot | Continue rendering local content with last-success time and an explicit refresh action |
| Malformed snapshot | Fall back to the last valid snapshot when available and link to diagnostics |
| Offline/external failure | Preserve local content, report the failed operation without leaking secrets, and offer retry |
| Action success | Update the relevant row/progress and show a concise confirmation |
| Partial sync | Report changed/skipped/failed counts and keep the last valid domain snapshot active |
| Destructive action | Require confirmation, describe local/remote effects separately, and produce an operation report |
| AI unavailable | Hide or disable AI actions with configuration guidance; core tasks remain unchanged |

Search and filters update URL query parameters so views are linkable and browser
navigation works. Primary row/card activation opens detail. Explicit inline
buttons perform status, progress, or resume actions. Keyboard users can reach the
same actions without hover. Dialogs trap focus, close with Escape, and restore
focus to the opener.

## Content requirements

- Use task labels such as “Resume”, “Start training”, “Refresh snapshot”, and
  “Review metadata”; avoid generic “Go” or “Submit”.
- Freshness copy includes source, last successful update, current operation state,
  and consequence: “Showing cached results” is more useful than “Stale”.
- Empty states do not invent statistics or recommendations.
- Movie posters, book covers, article images, video thumbnails, avatars, and chess
  boards are content assets. All images have explicit dimensions and fallbacks.
- Poster alt is the title plus “poster” only when the adjacent text does not
  already provide the same accessible name; decorative duplicates use empty alt.
- Technical IDs and operation timestamps may use IBM Plex Mono; human-facing
  dates remain in IBM Plex Sans.

## Design-system preview route

The first UI milestone includes protected route `/admin/design-system` showing
every component in default, hover/focus, disabled, loading, empty, success,
warning, error, long-text, and narrow-width states. It uses production macros and
styles, not duplicate demo-only components.

## Open decision for review

The brief assumes the restrained productivity/editorial lane and low-fi
wireframes are correct. Confirm or override that direction before high-fidelity
visual exploration or frontend implementation begins.
