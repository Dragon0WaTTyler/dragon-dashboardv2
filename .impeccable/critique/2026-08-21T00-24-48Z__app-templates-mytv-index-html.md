---
target: My TV advanced player final check
total_score: 24
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 4
timestamp: 2026-08-21T00-24-48Z
slug: app-templates-mytv-index-html
---
# My TV advanced-player final critique

Method: dual-agent (A: `/root/mytv_player_design_a` · B: `/root/mytv_player_evidence_b`)

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|---|---:|---|
| 1 | Visibility of system status | 3 | Startup and terminal error states are visible; buffering, fallback attempt, reconnecting, and autoplay rejection are opaque. |
| 2 | Match system / real world | 3 | Now, Next, Live, Favorites, Recent, and Resume are natural; “fallback sources” exposes implementation language. |
| 3 | User control and freedom | 2 | Retry, PiP, native controls, and channel switching exist; no coherent stop/theater/fullscreen lifecycle and Manage can hide an active stream. |
| 4 | Consistency and standards | 2 | Controls are split between browser-native chrome, an external PiP button, a separate Live badge, and global shortcuts. |
| 5 | Error prevention | 2 | Server fallback helps, but playback requests are not cancelled or token-guarded, so rapid channel changes can race. |
| 6 | Recognition rather than recall | 3 | Search, filters, Now/Next, Resume, and shortcut hints help; hints disappear below 980px. |
| 7 | Flexibility and efficiency | 2 | Search/mute/favorite/list shortcuts work; channel surfing, theater, remote navigation, and explicit fullscreen are absent. |
| 8 | Aesthetic and minimalist design | 3 | The player-and-rail composition is focused; the actual player is generic native chrome inside a more authored Dragon shell. |
| 9 | Error recovery | 3 | Retry preserves channel context; different backend failures collapse into generic messages. |
| 10 | Help and documentation | 1 | A terse desktop shortcut hint is the only player help. |
| **Total** |  | **24/40** | **Acceptable — the shell is credible, but the playback system is not advanced yet.** |

## Design Specificity Verdict

My TV is recognizably Dragon around the media: calm two-column composition, trusted lineup, local/private framing, Now/Next, Favorites, Recent, health and guide freshness. Inside the media surface it becomes category-interchangeable: a native `<video controls>` plus PiP, Live, and metadata placed outside the control system.

The deterministic markup detector returned exit code 0 with `[]`: zero findings, zero rules, zero locations, and no false positives. This proves only that the current markup avoids the detector’s structural anti-patterns; it does not validate CSS, runtime state, codecs, transport reliability, or real playback.

No reliable visual overlay exists. A fresh Browser tab redirected to the login screen, mutable injection was blocked, visibility remained off, no live detector server was started, and the temporary tab was closed. Current source and authenticated Playwright tests were used as fallback evidence.

## Overall Impression

The visible page is further along than the media engine. The correct next move is not to decorate the native player with a large toolbar. First create one truthful playback contract, then progressively enhance it with a Dragon control shell. The strongest product shortcut is to extract reusable primitives from the already-advanced Movies player instead of building a second player architecture from scratch.

## What’s Working

- Player-first desktop composition and sticky 16:9 mobile behavior are correct foundations.
- Empty, resume, connecting, requested, playing, Live, terminal error, retry, Now/Next, and channel-list states already exist.
- Same-origin playback hides upstream URLs; candidate fallback, health penalty, PiP, keyboard list navigation, RTL geometry, and responsive layout are covered at a basic level.

## Priority Issues

### [P1] Green browser tests do not prove that real video plays

The My TV browser fixture replaces `HTMLMediaElement.src` and stubs `load()`, `play()`, and `pause()`, immediately emitting `loadeddata`. It proves UI wiring, not decoding or transport. `tests/test_streaming.py` tests `app.services.streaming`, while the active My TV route uses the separate `app.mytv.streaming` module.

**Fix:** add real-media tests for the active route and module: tiny MP4, HLS/transport sample, actual FFmpeg first chunk, `videoWidth > 0`, startup failure, Range requests, semaphore cleanup, and late stream termination. Consolidate the two streaming modules or explicitly retire the disconnected implementation.

**Suggested command:** `$impeccable harden app/templates/mytv/index.html`

### [P1] Channel switching and fallback timing are racy and unbounded

`playChannel()` has no session token or AbortController. A slow result for channel A can arrive after channel B and attach the wrong URL/state. The client timeout begins only after metadata returns, while the server can try three candidates and spend up to roughly 12–15 seconds starting each.

**Fix:** introduce a playback `session_id`, cancel/invalidate the previous session, ignore stale media events, make the server authoritative for the total deadline, and expose `resolving → source 1/3 → switching source → playing/error`. Listen for `waiting`, `stalled`, `playing`, `ended`, and `error`; add bounded reconnect/backoff.

**Suggested command:** `$impeccable harden app/static/js/mytv.js`

### [P1] The player lacks one coherent Dragon control architecture

Native controls, PiP, Live status, Now/Next, and shortcuts live in separate layers. Manage can hide a still-playing stream, leaving invisible audio. PiP state is not reflected in its accessible label/state.

**Fix:** extract a shared `DragonMediaCore` from the Movies player: state machine, play/mute/volume, fullscreen, PiP, focus management, auto-hide, accessible announcements, reduced motion, and native-controls fallback. Add a TV adapter for Previous/Next channel, Live, Now/Next, theater, reconnect, and alternate source. Pause/stop on Manage or keep one compact persistent controller.

**Suggested command:** `$impeccable shape advanced My TV player`

### [P1] Advanced controls have no backend capability contract

Every non-file stream is transcoded to one fragmented H.264/AAC MP4 using only the first video and first audio stream. There is no adaptive ladder, subtitles, multiple audio tracks, DVR window, live-edge data, or DASH/HLS client engine. The fixed transcode limit is two sessions.

**Fix:** return a capability object with transport, live status, seekability, DVR window, qualities, audio tracks, text tracks, PiP, candidate count, and active attempt. Render controls only when the capability is real. Consolidate HLS manifest proxying with the active route and make transcode limits/configuration observable.

**Suggested command:** `$impeccable craft playback capability contract`

### [P2] Accessibility, mobile, RTL, and remote behavior stop short of an advanced player

Tabs are 40px and view controls 36px, metadata falls to 0.66–0.78rem, the video lacks a channel-specific accessible name, horizontal tab keys are not RTL-aware, and there is no five-way remote focus model.

**Fix:** use 44px targets, 56px in TV mode; dynamic media naming; truthful PiP/fullscreen/theater states; `?` shortcut help; RTL-aware horizontal navigation; universal media icons that do not mirror; explicit focus zones for player, channel rail, and filters.

**Suggested command:** `$impeccable adapt app/templates/mytv/index.html`

## Recommended Architecture

```text
Channel rail / user intent
        ↓
TV playback controller (session_id + finite-state machine)
        ↓
Backend capability + attempt-status contract
        ↓
Native video engine / HLS-DASH adapter
        ↕
Shared accessible Dragon media controls
```

Reuse from Movies:

- Player state-machine patterns.
- Custom controls and focus management.
- Volume, fullscreen, PiP, auto-hide, accessibility, RTL-safe captions, and browser fallbacks.

Do not reuse from Movies for linear live TV:

- VOD timeline/seek controls without DVR.
- Playback speed.
- Intro/recap markers, bookmarks, and next-episode behavior.
- Subtitle/audio menus when the backend exposes only the first audio and no text track.

TV-specific layer:

- Previous/next channel and remote Channel Up/Down.
- Truthful Live/Paused/Buffering/Reconnecting/Offline states.
- Now/Next and EPG progress as programme context, not a fake seek bar.
- Attempt progress and “Try alternate source.”
- Theater mode and one compact controller when leaving Watch, if continuous playback is intended.

## Roadmap

### Phase 0 — Prove and stabilize playback

- Real-media end-to-end fixture against the active My TV route.
- Consolidate streaming modules.
- Session ID, cancellation, stale-event protection, total startup deadline.
- Actual playing/autoplay rejection handling and categorized errors.

### Phase 1 — Advanced Dragon player MVP

- Shared MediaCore extracted from Movies.
- Custom progressive-enhancement controls with native fallback.
- Mute/volume, previous/next channel, PiP, theater, fullscreen, Live state, Now/Next, shortcut help.
- Buffering/reconnect states, alternate-source action, Manage lifecycle policy.
- Desktop, mobile, keyboard, RTL, and 44px accessibility coverage.

### Phase 2 — Real media capabilities

- Adaptive HLS/DASH with Auto/manual quality only when genuine variants exist.
- Multiple audio tracks and subtitles with remembered language preference.
- Local QoE telemetry: startup time, attempts, stalls, reconnects, terminal category, session duration; never raw URLs.
- Configurable transcode capacity, output resolution/bitrate policy, and capacity feedback.

### Phase 3 — Optional live-TV depth

- DVR/ring buffer, pause live, seekable window, and Go Live.
- Remote/gamepad adapter and 10-foot TV mode if the app is actually used from a couch.
- Programme details/history drawer, without turning My TV into a streaming-service clone.

## Do Not Build Yet

- Fake Quality settings over one MP4 rendition.
- Playback speed for linear live TV.
- A draggable seek bar that is merely EPG progress.
- Subtitle/audio menus before tracks are preserved and exposed.
- A second desktop mini-player when PiP + theater + the mobile sticky frame cover the need.
- Autoplay with sound, decorative equalizers, cinematic hero chrome, or cloud analytics.

## Persona Red Flags

- **Alex:** rapid channel switches can race; `F` means Favorite instead of the common fullscreen shortcut; no channel next/previous or theater shortcuts.
- **Sam:** media has no channel-specific name; PiP state is not announced; small controls/text, polite terminal errors, hidden shortcut help, and incomplete RTL keyboard semantics remain barriers.
- **Casey:** mobile view buttons are 36px; Now/Next and PiP require extra thumb travel; autoplay rejection is swallowed; Manage can hide an active stream.
- **Living-room viewer:** dense text/rows, no spatial focus system, no remote-safe focus ring, and two focusable actions on every row make channel surfing expensive.

## Minor Observations

- The header’s permanent red dot should become stateful or disappear; the truthful Live badge already exists.
- “fallback sources” should become actual attempt progress or be removed.
- The empty-state reference to “Visibility” does not match the visible Ready/Favorites/Recent/All controls.
- Source security remains good in principle, but the legacy tokenized resource route should be login-protected or clearly retired, and URL fetching needs DNS-rebinding-safe resolution.

## Questions to Consider

- Which daily job matters most: fast channel surfing, finding a programme through Now/Next, or resilient playback from unstable sources?
- Is continuous audio while opening Manage intentional? If not, stopping visibly is calmer than inventing a mini-player.
- Which backend capability earns Phase 2 first: adaptive quality, subtitles/audio, or DVR/live pause?
