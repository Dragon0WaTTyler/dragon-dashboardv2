---
target: my-tv section
total_score: 20
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 3
timestamp: 2026-08-15T23-11-59Z
slug: app-templates-mytv-index-html
---
# My TV Design Critique

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|---|---:|---|
| 1 | Visibility of System Status | 3 | Strong playback/sync feedback; list loading and persistent errors are weaker. |
| 2 | Match System / Real World | 2 | Bouquet, package, override, and source-copy terminology exposes implementation details. |
| 3 | User Control and Freedom | 2 | Bulk mutations have no undo. |
| 4 | Consistency and Standards | 2 | Theme, bouquet, and group terminology drifts. |
| 5 | Error Prevention | 1 | Broad changes apply without preview, saving lock, or undo. |
| 6 | Recognition Rather Than Recall | 3 | Inherited channel state is not resolved in context. |
| 7 | Flexibility and Efficiency | 2 | Recent channels, TV shortcuts, direct group navigation, and focus preservation are missing. |
| 8 | Aesthetic and Minimalist Design | 2 | The header and four metrics displace the watching task. |
| 9 | Error Recovery | 2 | Playback retry is good; catalogue/manage errors are transient. |
| 10 | Help and Documentation | 1 | Jargon and high-impact actions lack contextual explanation. |
| **Total** | | **20/40** | **Acceptable foundation; significant improvements needed.** |

## Design Specificity Verdict

The local-first promise, Dragon noir system, live-player states, and bouquet/source model feel specific to Dragon. The above-fold oversized title, four hero metrics, repeated eyebrows, and bordered containers still use generic premium-dashboard grammar. The deterministic markup scan returned zero findings, but CSS and runtime issues remain outside that scan. A stale long-running server showed an API-shape error; a fresh targeted browser test passed, so this is not treated as a current-code defect. Mutable overlay injection was unavailable, so no visual overlay exists.

## Overall Impression

The foundation is technically thoughtful and visually coherent. Its strongest moment is playback. The main opportunity is a fast Watch-first television surface with catalogue inventory and source administration progressively disclosed in Manage.

## What's Working

- Watch and Manage are clearly separated with semantic, keyboard-operable tabs.
- Playback covers empty, connecting, ready, timeout, offline, and retry states.
- Sync, health, and persistence behavior are transparent.

## Cognitive Load and Emotional Journey

Six of eight cognitive-load checks fail overall, driven mostly by Manage; Watch alone is closer to two failures. The title, maintenance actions, four metrics, source status, bouquet policy, bulk actions, and exceptions compete across one surface. Arrival feels polished but inventory-heavy. Playback success is the peak. The 15-second failure wait and unsafe bulk management are valleys. There is no continuity-oriented ending such as last channel or recently watched.

## Priority Issues

### P1 — Watching begins below a dashboard preamble

Open Watch directly into the player/list workspace. Use a compact 64–80px header, replace four metrics with “269 ready · checked 2h ago,” and move catalogue, bouquet, and source counts to Manage. Suggested command: `impeccable distill`.

### P1 — Bulk actions lack safety and recovery

Show affected-channel counts, lock the row while saving, provide undo, and require lightweight confirmation for large All off operations. Suggested command: `impeccable polish`.

### P1 — RTL support is incomplete

Replace physical left/right CSS with logical properties, test switch behavior in RTL, and localize TV vocabulary. Suggested command: `impeccable adapt`.

### P2 — Manage exposes the storage model

Organize it around My lineup, Active groups, and My exceptions. Put repository details behind disclosure, rename Update selected, and display inherited settings' resolved state. Suggested command: `impeccable clarify`.

### P2 — Dynamic lists and compact controls create accessibility friction

Provide 44x44 hit areas, preserve focus, update rows in place, and announce concise action results instead of whole lists. Suggested command: `impeccable polish`.

## Persona Red Flags

- Alex: no TV shortcuts, recent/last channel, direct group jump, or guaranteed focus preservation.
- Sam: sub-44px controls, whole-list live announcements, incomplete RTL behavior, and transient errors.
- Jordan: ambiguous Update selected, hidden outcome for Use bouquet default, technical vocabulary, and deceptively lightweight All off.

## Minor Observations

- Repeated eyebrows and hero metrics read as dashboard scaffolding.
- Completed operations leave no lasting last-checked trust signal.
- Infinite loading has no explicit fallback button.
- Light/dark native select appearance needs verification.

## Questions to Consider

- Why should catalogue administration own the first viewport if watching is the primary task?
- Is 21,254 total channels more reassuring than 269 ready to watch, checked two hours ago?
- Should Manage reveal groups and exceptions only after selection?
- Should continuity come from last channel, recent channels, favorites, or a now/next guide?
