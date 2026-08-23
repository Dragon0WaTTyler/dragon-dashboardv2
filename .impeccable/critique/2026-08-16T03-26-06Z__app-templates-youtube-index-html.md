---
p0_count: 0
total_score: 23
na_heuristics: 
max_score: 40
target: YouTube section (index + detail flow)
p1_count: 4
timestamp: 2026-08-16T03-26-06Z
slug: app-templates-youtube-index-html
---
Method: dual-agent (A: `/root/youtube_design_review` · B: `/root/youtube_detector_review`)

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|---|---:|---|
| 1 | Visibility of system status | 2/4 | Sync lacks last-refresh/progress feedback; player lacks a failure/retry state. |
| 2 | Match system / real world | 3/4 | Watch Later is familiar, but “Every GET,” “snapshot,” “Normal,” and “Pick one” are technical or ambiguous. |
| 3 | User control and freedom | 2/4 | Returning from detail loses query/group/order/page/seed/scroll; local removal has no undo. |
| 4 | Consistency and standards | 2/4 | Mobile “Grid” visually becomes a row list. |
| 5 | Error prevention | 2/4 | Sync and removal lack clear scope confirmation and recovery. |
| 6 | Recognition rather than recall | 3/4 | Controls are labelled, but duplicate links and lost browsing context add memory work. |
| 7 | Flexibility and efficiency | 3/4 | Shuffle, resume, chapters, and focus mode are strong; filtering still needs Apply and lacks bulk actions. |
| 8 | Aesthetic and minimalist design | 2/4 | Hero, halo, repeated eyebrows, and shadows outrank the library. |
| 9 | Error recovery | 2/4 | YouTube API/script failures have no timeout, retry, or in-page fallback state. |
| 10 | Help and documentation | 2/4 | Privacy copy helps, but freshness, order modes, and action scope remain unexplained. |
| **Total** | | **23/40** | **Acceptable — significant UX improvement needed** |

## Design Specificity Verdict

The surface scores 6/10 for specificity. It is not a generic YouTube clone: the privacy-gated player, Dragon Noir styling, local resume, RTL/Arabic handling, chapters, and focus mode are product-specific. The oversized editorial hero, halo, repeated uppercase eyebrows, and glow are familiar “generated luxury” patterns that distract from the practical watching task.

The deterministic detector scanned `app/templates/youtube/index.html` and `app/templates/youtube/detail.html` and returned zero findings for both. That indicates no explicit markup anti-patterns covered by the detector; it does not contradict the visual hierarchy, cognitive-load, and contrast findings. No false positives were present.

Browser overlay injection was unavailable because mutable `javascript:` navigation was blocked and the available evaluate surface is read-only. No user-visible overlay exists. Authenticated browser review by Assessment A used an isolated seeded app at desktop and mobile sizes. Assessment B's fresh browser tabs were redirected to sign-in, so its responsive evidence was source-level only.

## Overall Impression

The detail/player experience is the strongest surface. The library landing is the main opportunity: it behaves like source maintenance before it behaves like a watching surface. On mobile, the first viewport contains hero, source, sync, and filters but no video.

## What’s Working

- Privacy is expressed through interaction: YouTube only loads after deliberate play.
- The detail flow is useful and calm: resume, focus mode, Escape, chapters, queue, related videos, and an external fallback.
- Accessibility foundations are thoughtful: semantic landmarks, labelled fields, `dir="auto"`, 44px targets, reduced motion, and Arabic font handling.

## Priority Issues

1. **[P1] Mobile prioritizes administration before watching.** At 390px, the hero, sync, and filters consume the first viewport. Compress the header, keep source and search visible, move Group/Order/View into a mobile Filters disclosure, demote Sync, and show the first video above the fold. Preserve a true grid or rename the mobile mode. Suggested command: `$impeccable adapt`.

2. **[P1] The local/external boundary is ambiguous at action level.** Sync lacks freshness and scope; “Remove from Watch Later” implies an external YouTube mutation while the implementation is local. Show “Last refreshed…”, source health, and loading/result states. Rename to “Hide from local Watch Later” unless external removal is intentionally implemented. Suggested command: `$impeccable clarify`.

3. **[P1] Browse context is lost in list → detail → back.** Preserve query, group, order, view, page, shuffle seed, and scroll using a validated `return_to` or explicit state parameters, then restore the originating card anchor. Suggested command: `$impeccable harden`.

4. **[P1] Light-mode semantic badges fail WCAG AA.** Success text is approximately 2.43:1 and accent/error text approximately 3.23:1 on their soft backgrounds. Define darker light-theme semantic foreground tokens and test every badge state. Suggested command: `$impeccable audit`.

5. **[P2] The visual grammar is louder than the task.** Reduce repeated eyebrow labels, heading scale, halo, glow, and broad shadows. Let thumbnail, title, and state carry hierarchy. Replace technical copy with “Stored locally · refreshes only when you ask.” Suggested command: `$impeccable quieter`.

## Persona Red Flags

**Alex / power user:** Shuffle, resume, and chapters are strong, but every filter change requires Apply, collection-level actions are absent, and returning from detail destroys browse context.

**Sam / accessibility-dependent:** Labels and semantics are good, but badge contrast is weak, each card exposes duplicate links to one destination, and `.visually-hidden` appears scoped to `today.css`, risking a visible “Player ready” status on detail.

**Casey / distracted mobile user:** No video is visible in the first viewport, filters demand sustained attention, bottom navigation competes with the filter runway, and Grid visually becoming List undermines confidence.

## Minor Observations

- Empty Watch Later copy points to Admin even though the page has a sync button.
- Replace “Page 1” with “1–50 of N”.
- Rename “Normal” to “Playlist order” and “Pick one” to “Choose one at random”.
- Add player timeout, Retry, and Open on YouTube fallback.
- Clarify whether the count badge is source total or filtered total.
- Apply a detail-level RTL modifier so title, metadata, and rail share one reading axis.

## Questions to Consider

- Is YouTube fundamentally a watching surface or a source-maintenance surface?
- Should removal change the real YouTube playlist or only Dragon's local view?
- Does Grid/List need to stay user-controlled, or should density persist per device?
