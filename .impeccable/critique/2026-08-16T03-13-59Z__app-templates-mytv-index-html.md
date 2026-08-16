---
target: my-tv section
total_score: 25
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 3
timestamp: 2026-08-16T03-13-59Z
slug: app-templates-mytv-index-html
---
# My TV design critique

Method: dual-agent (A: `/root/mytv_design_review` · B: `/root/mytv_detector_evidence`)

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|---|---:|---|
| 1 | Visibility of system status | 3 | Trust summary, busy states, banners, playback status, and retry are strong; general errors disappear quickly. |
| 2 | Match system / real world | 3 | Watch language is natural; Manage leaks technical terms such as catalogue cache and repository. |
| 3 | User control and freedom | 3 | Cancel, retry, filters, native video controls, PiP, and undo are present. |
| 4 | Consistency and standards | 2 | Ready/enabled/availability and group/bouquet terminology drift; 20-second undo copy conflicts with an 18-second toast. |
| 5 | Error prevention | 2 | Broad changes are guarded, but first-load auto-sync can make an external request without explicit consent. |
| 6 | Recognition rather than recall | 2 | Main actions are visible, but empty-state copy references a missing Visibility control and Disabled exists only in a hidden select. |
| 7 | Flexibility and efficiency | 3 | Search, `/`, `F`, `M`, arrow navigation, filters, recent items, and bulk group actions are strong. |
| 8 | Aesthetic and minimalist design | 2 | Watch is disciplined; Manage becomes a nested-card dashboard with weak priority. |
| 9 | Error recovery | 3 | Persistent playback retry and inline destructive confirmation are good; transient toasts are weaker. |
| 10 | Help and documentation | 2 | Context copy and shortcut hints help, but source concepts have little contextual explanation. |
| **Total** |  | **25/40** | **Acceptable — strong foundation, significant refinement needed.** |

## Design Specificity Verdict

The Watch surface feels authored for Dragon: it is a private-TV cockpit built around a player, trusted lineup, favorites, recent channels, guide information, and recovery. It avoids the Netflix-clone trap. The Manage surface has visible generic-dashboard residue: repeated bordered cards, a four-metric strip, repeated eyebrow labels, and equal-weight maintenance sections.

The deterministic markup scan returned exit code 0 with `[]`: zero rules, locations, or false positives. This clean result is narrow, because the detector was correctly scoped to the stable markup file and did not constitute a CSS/runtime audit. The manual review found product-level and accessibility issues that a structural markup detector would not catch.

No reliable live overlay is available. A fresh in-app-browser tab redirected to the authentication screen, and mutable injection failed because the browser evaluation surface exposed a read-only document title. The fallback evidence was the stable template/CSS/JS plus the supplied screenshots; those screenshots predate the latest source edits and are not proof of the final rendered build.

## Overall Impression

The feature set is already mature: Watch/Manage separation, favorites, recent channels, EPG, health checks, retry, PiP, keyboard navigation, bulk actions, and undo are all present. The biggest opportunity is not adding controls; it is turning Watch into a stronger personal “what should I watch now?” surface while reducing Manage to a calm operational ledger.

## What’s Working

- Watch and Manage are separated cleanly, so everyday viewing does not inherit source-management complexity.
- System-state communication is unusually thoughtful: trust summary, sync/health banners, `aria-busy`, requested/loading/playing states, now/next guide, persistent playback failure, and retry.
- Accessibility foundations are real: semantic tabs, roving tabindex, keyboard shortcuts and arrow navigation, logical CSS properties, labelled icon buttons, live regions, 44px channel/favorite targets, lazy images, RTL layout coverage, and reduced-motion handling.

## Priority Issues

### [P1] Hidden first-load network behavior

`loadBootstrap()` can silently call `startSync("fetch", [], true)` when no repository files exist. That conflicts with Dragon’s local/private/deliberate-action promise.

**Fix:** never POST or fetch external source data on ordinary My TV rendering. Show a local first-run state that names the source, explains the effect, and offers one explicit “Import lineup” action.

**Suggested command:** `$impeccable harden app/templates/mytv/index.html`

### [P1] High-frequency accessibility defects

Watch tabs are 40px and the view switch is 36px, below the project’s 44px target. Manual token checks found dark-theme contrast failures in accent and toast actions, several labels sit around `.62–.70rem`, the media play triangle mirrors in RTL, and tab arrow-key behavior is not direction-aware.

**Fix:** raise high-frequency targets to 44px, increase small-label size/contrast, repair semantic dark tokens, keep media controls direction-neutral, and verify Arabic + 200% zoom + keyboard-only behavior.

**Suggested command:** `$impeccable audit app/templates/mytv/index.html`

### [P1] Manage is a nested-card dashboard

The bordered toolbar, metric strip, source card, manage-section cards, and row cards give every block the same weight. Operational priority is buried and the surface drifts toward generic SaaS.

**Fix:** flatten Manage into an operational ledger: one maintenance header, one compact status/trust row, divider-led Groups and Channel exceptions sections, and flatter rows. Keep source internals inside progressive disclosure or move deep source administration to Settings.

**Suggested command:** `$impeccable distill app/templates/mytv/index.html`

### [P2] Recovery copy and control vocabulary are stale

The empty state says “change Visibility,” but no visible control has that name. Disabled exists only in a hidden select. “Bouquets” survives in one empty state while the rest of the UI says Groups. The 20-second undo promise conflicts with the 18-second actionable toast.

**Fix:** standardize on Ready / Favorites / Recent / All, route disabled-channel work explicitly to Manage, replace Bouquet with Group, make undo timing truthful, and keep important errors until dismissal or recovery.

**Suggested command:** `$impeccable clarify app/templates/mytv/index.html`

## Product Roadmap

1. **Trust and accessibility first:** remove auto-sync, repair touch targets/contrast/RTL semantics, and make recovery persistent.
2. **Reshape Manage:** reduce card chrome, separate routine lineup choices from source internals, and add sorting/batch editing for very large catalogues.
3. **Make Watch more personal:** prioritize Resume last channel, On now from favorites, recent channels, favorite guide freshness, and reliability—not generic catalogue totals.
4. **Mobile viewing mode:** collapse the sticky player to a mini-player after scrolling, keep channel search/views thumb-accessible, and preserve selected channel/view on interruption.
5. **Operational intelligence later:** surface per-channel reliability, last successful playback, source alternative used, and guide freshness only when they help choose or recover a stream.

## Persona Red Flags

- **Alex (power user):** excellent shortcuts and group bulk actions, but channel exceptions remain one-at-a-time, no visible sort exists for collections reaching tens of thousands, and shortcut help disappears below 980px.
- **Sam (accessibility-dependent):** 36/40px controls, very small technical labels, failing dark-theme contrast, polite auto-dismissed error toasts, mirrored RTL play icon, and non-direction-aware tab arrows are concrete barriers.
- **Casey (mobile):** the sticky 16:9 player can occupy much of the viewport while the actionable channel list moves below it; Manage’s three actions per group become thumb-heavy.

## Minor Observations

- The product register recommends fixed UI type scales, but the page H1 uses `clamp()`.
- The repeated “Lineup maintenance / My lineup / My exceptions” eyebrows feel like scaffold rather than product voice.
- The toast combines a border, a 3px side stripe, and a very wide shadow; it is visually louder than the action it confirms.
- The permanent red dot beside My TV can imply recording or live playback before a channel is selected.
- The screenshots are stale relative to the current template/CSS/JS, so a new authenticated visual QA pass is still needed before shipping layout changes.

## Questions to Consider

- Is My TV primarily “watch my trusted lineup” or “administer a 21,000-channel source”? Deep source administration may belong in Settings.
- Should catalogue totals earn more visual weight than personal signals such as last watched, favorite programs currently live, guide freshness, and channel reliability?
- If external work should happen only after deliberate action, should any My TV page render be allowed to make a POST automatically?
