---
target: News section
total_score: 19
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 4
timestamp: 2026-08-20T14-28-53Z
slug: app-templates-reading-index-html
---
# News section design critique

Method: dual-agent (A: news_design_review · B: news_evidence_audit)

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|---|---:|---|
| 1 | Visibility of System Status | 2/4 | Sync feedback is good, but source failures lack cause, recency, and recovery; the active News view is visually weak. |
| 2 | Match System / Real World | 1/4 | Today and Recent behave identically; Saved is modeled as reading progress rather than a bookmark. |
| 3 | User Control and Freedom | 2/4 | No clear/reset flow, Back loses context, and opening can silently mutate Unread to Reading. |
| 4 | Consistency and Standards | 2/4 | The shell is coherent, but News-view links are an under-styled exception. |
| 5 | Error Prevention | 3/4 | CSRF, explicit sync, native forms, and preserved cached data are strong; automatic status mutation remains surprising. |
| 6 | Recognition Rather Than Recall | 2/4 | Labels are visible, but view semantics, extraction state, and source-health meaning must be inferred. |
| 7 | Flexibility and Efficiency | 2/4 | Useful filters exist, but there is no reset, preserved result context, paging, presets, or compact mobile disclosure. |
| 8 | Aesthetic and Minimalist Design | 2/4 | Dragon Noir is distinctive, but filters, health pills, repeated badges, and 50 equal cards bury editorial focus. |
| 9 | Error Recovery | 1/4 | No-match guidance points users toward Admin; source errors offer no reason/retry; return context is lost. |
| 10 | Help and Documentation | 2/4 | Local-first copy is clear, but status, source health, full-text behavior, and view definitions are unexplained. |
| **Total** |  | **19/40** | **Poor — the foundation is usable, but the primary information architecture needs correction.** |

## Design Specificity Verdict

Dragon Noir feels authored: near-black surfaces, crimson accent, warm typography, Arabic font support, restrained radii, and the 66ch reader give the product a recognizable voice. The index is less product-specific. It behaves like a generic database grid wearing an editorial skin: five filter controls, source diagnostics, and up to 50 equal-weight cards appear before Dragon offers an editorial next step.

The deterministic Impeccable scan returned three `side-tab` warnings in `app/static/css/pages/library.css` at lines 159, 297, and 327. All are false positives for News because those shared selectors are not rendered by `reading/index.html` or `reading/detail.html`. The automated scan therefore found no applicable News anti-pattern. Manual/browser evidence exposed the real issues that a static selector scan cannot detect: Today/Recent semantic duplication, undersized touch targets, low-contrast health text, misleading empty-state recovery, and information overload.

Both independent assessors inspected fresh local browser sessions. Desktop and 390×844 mobile layouts had no horizontal overflow, broken-image fallback worked, long titles wrapped, and Arabic detail content reflowed correctly. No reliable user-visible detector overlay was injected; browser and DOM measurements plus the CLI JSON are the evidence base.

## Overall Impression

The reader page is calmer and more successful than the inbox. The biggest opportunity is to make News an editorial decision surface—what matters now, what to continue, what was saved—instead of mixing reading, filtering, source diagnostics, and archive maintenance in one uninterrupted page.

## What’s Working

- The visual system is coherent and recognizable across English and Arabic content.
- Semantic foundations are solid: skip link, landmarks, labeled native controls, `aria-current`, `dir="auto"`, visible focus CSS, reduced-motion rules, and responsive reflow.
- The local-first failure philosophy is trustworthy: explicit sync, cached-data preservation, spinner/label feedback, full-text fallback copy, and access to the original source.

## Priority Issues

### [P1] The top-level views make a false promise

**Why it matters:** `feed` is validated in `app/reading/routes.py:28-35`, but Today and Recent call the same repository query at `routes.py:38-46`. Both browser audits confirmed identical titles and order. This makes the primary navigation untrustworthy.

**Fix:** Define explicit contracts: Today = items published since local midnight; Recent = reverse chronology beyond today; Saved = bookmarked items; Sources = diagnostics. Add a persistent current-view treatment and preserve current filters when switching views.

**Suggested command:** `$impeccable shape News views`

### [P1] Saved is incorrectly conflated with reading progress

**Why it matters:** `unread`, `reading`, `saved`, and `finished` are mutually exclusive. A user cannot save an article while continuing it or after finishing it; the interface exposes a data-model problem as a confusing status selector.

**Fix:** Split `reading_state: unread | reading | finished` from `is_saved`. Make Save a direct bookmark toggle and keep progress separate.

**Suggested command:** `$impeccable clarify News state model`

### [P1] The index overwhelms users before the first story

**Why it matters:** At 390×844, one assessor measured the first story at y=1,443px and the page at 22,014px. The filter block alone occupied 515px; up to 50 equal cards render with no pagination. The four mobile News-view links were only 23px high. This blocks quick scanning and hurts motor accessibility.

**Fix:** Lead with a compact Continue/Saved lane; move health diagnostics into Sources; collapse mobile filters behind a labeled control with active-filter count and Clear; use 15–20 items with paging or progressive loading; raise every view target to at least 44px.

**Suggested command:** `$impeccable layout News index`

### [P1] Source health is visible but not actionable or fully accessible

**Why it matters:** Health pills show raw state without cause, last success, or retry. The measured small status text contrast was about 4.44:1, just below WCAG AA 4.5:1. A trust signal that users cannot interpret or act on becomes noise.

**Fix:** Keep the summary compact on reading views and put details in Sources: last successful sync, failure reason, affected source, and Retry. Increase text size/contrast and use text/icon/state—not color alone.

**Suggested command:** `$impeccable audit News source health`

### [P2] Empty, loading, and return states do not close the loop

**Why it matters:** A no-match search says to configure sources and refresh from Admin. Opening can change Unread to Reading and begin full-text extraction with little visible local feedback. “Back to News” drops feed, filters, view, sort, and scroll context.

**Fix:** Separate first-run empty from no-match empty; offer Clear filters for no-match and source setup only for no-data. Show a visible “Loading article…” state, explain automatic progress behavior, and carry a safe return URL/context into detail.

**Suggested command:** `$impeccable harden News states`

## Persona Red Flags

**Morning scanner:** Today is not a real filter; 50 equal cards, raw feed boilerplate, and no read-time/topic hierarchy make a two-minute scan impossible.

**Arabic-first reader:** Content RTL is strong, but language is inferred from the title and interface chrome/actions remain English/LTR. Mixed source-author-date metadata is dense on mobile.

**Personal archivist:** Saved and Reading cannot coexist; source failures lack diagnosis/retry; returning from detail loses the working context; the visible article count is only the capped query slice.

## Minor Observations

- Raw `YYYY-MM-DD` dates feel technical rather than editorial.
- `aria-label="Reading results"` conflicts with the product-facing name News.
- Detail hero alt duplicates the adjacent headline; decorative duplicates should usually use empty alt text.
- The large detail hero delays article text on desktop.
- Raw excerpts can retain feed boilerplate such as “The post … appeared first on…”.
- Inline article images are lazy-loaded but lack intrinsic dimensions, creating some layout-shift risk.

## Questions to Consider

- Is News mainly a place to decide what to read, or an RSS administration console?
- If Today and Recent cannot be explained with different behaviors in one sentence each, should both exist?
- Should Arabic be a first-class interface locale, or only supported content direction?
- What editorial judgment should Dragon add beyond timestamp sorting?
