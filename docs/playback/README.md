# Authorized Playback Catalog

Use [authorized-catalog.sample.json](authorized-catalog.sample.json) only as a
template. Replace every placeholder with identifiers from a catalog or account
that you are authorized to use; it is intentionally not importable unchanged.

Use **Provider settings → Authorized source catalog** to upload the CSV or JSON
and review each batch. The same authenticated API remains available at
`POST /playback/catalog/imports` as multipart field `catalog`, or with its
`rows` in an authenticated JSON request. Dragon accepts only exact IMDb/TMDb
matches. TV mappings additionally require an exact season and episode that
already exist in Dragon.

Use `provider_key` as the canonical catalog field (the legacy `provider` and
`server` aliases remain accepted). For example, `okru` is normalized to `ok`.

For indexed providers, prefer `provider_asset_id`. An allowlisted HTTPS embed
URL can be imported only to extract that ID. Dragon discards the full URL: it
stores the native asset ID and constructs the final embed URL from the local,
authorized provider template. A provider appears for a title only when all are
true:

- its provider config is enabled and has a valid HTTPS template;
- its preference is enabled;
- the title/episode has an enabled, authorized mapping.

Catalog imports deliberately create `catalog_authorized` mappings with
`enabled = false`. Activate each tested mapping explicitly from its catalog
batch, or with authenticated `POST /playback/movie/<movie_id>/sources/<source_id>/enabled`
and `enabled=true`; set `enabled=false` to withdraw it again. This never enables
a provider globally.

## StreamWish account library sync

Dragon can also create disabled source mappings from files in a configured
StreamWish account. Enable `DRAGON_STREAMWISH_LIBRARY_SYNC_ENABLED=true` and
put the account key in `instance/secrets/streamwish_api_key` (or inject
`DRAGON_STREAMWISH_API_KEY` through your deployment secret manager). The key is
used only by the server during an explicit **Sync StreamWish library** action;
it is never stored in an import row, asset cache, or browser response.

MixDrop can use the identical account-only flow. Enable
`DRAGON_MIXDROP_LIBRARY_SYNC_ENABLED=true`, keep the account email and key in
`instance/secrets/mixdrop_api_email` and `instance/secrets/mixdrop_api_key`,
then use **Sync MixDrop library**. Dragon inventories only the account's file
references and titles; direct URLs returned by the API are never stored. The
configured provider template creates the embed URL only after an explicitly
activated source is selected for playback.

StreamTape follows the same manual-review model. Set
`DRAGON_STREAMTAPE_LIBRARY_SYNC_ENABLED=true` and keep its API login/key in
`instance/secrets/streamtape_api_login` and
`instance/secrets/streamtape_api_key`. Dragon follows only folders in that
account and retains file IDs plus safe metadata, never account URLs.

DoodStream, FileLions/EarnVids, and LuluStream use the same account-library
contract: enable the matching `DRAGON_<PROVIDER>_LIBRARY_SYNC_ENABLED` flag,
put its API key in `instance/secrets/<provider>_api_key`, sync explicitly from
the catalog page, then review and activate exact mappings one by one. A sync
does not contact a provider while a movie detail page is being opened.

For automatic matching, put an exact identity marker in every account-file
title. Examples:

```text
Interstellar (2014) [tmdb-157336] [1080p]
Breaking Bad S01E05 [tmdb-1396] [720p]
```

TV assets require both `SxxExx` and an existing Dragon episode. A title/year
match without a TMDb or IMDb marker, and assets that the provider reports as
not playable, remain in the review batch without publishing a source. Account
sync sources have `source_type=account_catalog`,
`authorization_status=account_authorized`, and `enabled=false` until activated.

Check the local-only readiness report before a playback smoke test:

```text
GET /playback/movie/<movie_id>/activation-status
GET /playback/movie/<movie_id>/activation-status?season=1&episode=1
```

The report performs no request to providers and exposes no embed URL.

## VidLove identity embed

VidLove is an optional TMDb-backed provider. Enable it only for content and
provider use that you are authorized to access:

```text
DRAGON_PLAYBACK_ENABLED=true
DRAGON_VIDLOVE_ENABLED=true
```

Dragon resolves movies as `/embed/movie/{tmdb_id}` and exact TV episodes as
`/embed/tv/{tmdb_id}/{season}/{episode}`. The VidLove player owns its internal
server picker; Dragon embeds the one player inside the strict safe-playback
sandbox and does not accept undocumented provider messages. The same policy is
applied to the optional discovery preview. Popup and top-navigation
permissions are never granted. While a VidLove embed is playing, Dragon's
toolbar exposes an in-player **Reload player** action; the safe V0 surface does
not expose an external-open/new-tab action.
Providers without a declared internal-server capability keep Dragon's source
and recovery controls available below the embed instead of showing the
provider-server toolbar.

## Safe VidLove V0 manual smoke

Run this only with content and provider access you are authorized to use. With
`DRAGON_PLAYBACK_ENABLED=true` and `DRAGON_VIDLOVE_ENABLED=true`:

1. Open a Movie with a TMDb identity, choose VidLove, and press Play five
   times, including one player reload.
2. Use VidLove's own server picker to switch three times. Seek and request
   fullscreen from inside the player.
3. Repeat the same flow for a real TV episode and confirm the episode scope is
   preserved.
4. Confirm the result is zero popup windows, zero new tabs, and zero
   navigation away from the Dragon Movie page.

The local browser contract test also covers the no-confirmation case: when a
provider with declared lifecycle messages loads but never reports `play`, Auto
uses its bounded watchdog and moves to the next provider without looping.

Dragon does not probe VidLove in the background and does not treat VidLove's
internal server aliases as Dragon provider keys. Record any provider-side
failure separately from the Dragon iframe safety result.

## Provider contract

Every registered playback provider exposes a stable contract:
`id`, `display_name`, `supported_content`, `build_embed(...)`, and static
capability metadata for internal-server support, fullscreen, subtitles (or
`unknown`), documented lifecycle messages, and reliable server/language/quality
metadata support. `resolve(...)` remains only as a compatibility alias; Dragon
uses `build_embed(...)` for its provider boundary. Every embed provider resolves through the
Dragon safe-playback sandbox; a provider that needs popup or top-navigation
permissions is incompatible with this policy. The existing
`probe` operation is the provider health hook; it remains explicit and is not
called while a Movie page is loading. VidLove declares its server picker as
provider-owned rather than exposing Thunder, Wave, or other aliases as Dragon
providers. A resolver receives a last-good opaque server preference only when
its provider declares `supports_server_identity`; it remains the provider's
responsibility to accept, ignore, or reject that value.

## Playback health memory (M4)

Dragon stores explicit player lifecycle observations in the separate
`playback_attempts` table. These records are runtime/diagnostics state, not
movie metadata or source canonicalization. Each attempt is scoped to the
authenticated user, Movie, episode scope, provider, optional source, and an
opaque browser device/attempt ID. It can retain provider-owned `server_id`,
startup milliseconds, known quality/language, and a bounded failure reason.
`movie_id` is the relational Movie foreign key; `content_id` stores that
Movie's canonical `media_key`, with `scope_key` carrying the episode scope.

The player reports only after the user presses Play (or explicitly reloads the
player). `started` means Dragon began the attempt; `embed_ready` means the
iframe document loaded; `success` and `failure` are reserved for explicit
playback lifecycle signals. An embed load is not presented as confirmed video
playback, and Dragon does not infer server aliases from the iframe. For a
provider-documented lifecycle message such as VidLove's `play`, Dragon accepts
only messages from the exact iframe origin and source window; this can mark a
confirmed playback success, but it cannot select or identify an internal
server. The authenticated attempt-report endpoint performs no provider probe
and failures in telemetry never interrupt playback.

## Auto selection V1 (M5)

When local attempt history exists, the player scores configured providers using
final success/failure observations, success rate, title/episode successes,
startup time, recent successful playback, and optional user audio/quality
preferences. Language and quality bonuses are applied only to providers that
declare the corresponding reliable metadata capability. The highest-scoring known embed
is placed first and is also available through the explicit `Auto · Best
available` player option. When a provider has no history yet, the same
capability-gated preferences may use explicit metadata already attached to
the current source, so a cold-start choice is still deterministic. Auto changes only the Dragon-side provider choice;
it does not contact every provider, inspect hidden provider APIs, or probe
servers in the background. With no usable history, configured provider
priority remains the deterministic fallback. Provider-owned server aliases are
not scored as Dragon providers until the provider supplies a supported opaque
server identity.

## Automatic fallback V1 (M6)

Automatic fallback is an explicit `Auto`-mode behavior only. If the selected
provider's same-origin Dragon resolver returns a non-success response or no
usable embed URL, Dragon records that failed attempt and tries the next
configured embed provider in the current local ranking. A single Play action
uses at most three provider attempts; it never loops indefinitely. A manually
selected provider never triggers this automatic fallback.

An iframe `load` event is not treated as provider playback success or failure
because it only proves that a document loaded. For a provider that explicitly
declares lifecycle messages, Auto keeps a bounded post-load watchdog and falls
back if documented `play` confirmation never arrives; a native iframe error is
handled through the same bounded path. Dragon does not infer failure from
provider internals, aliases, or undocumented `postMessage` events. If Auto
exhausts its bounded resolver/playback attempts, the player asks the user to
choose a source manually. No provider is contacted during page load or
background health probing.

## Provider-owned metadata boundary (M7-M9)

The attempt schema stores opaque provider `server_id` values and exposes a
user/movie/scope-scoped last-good lookup, but Dragon does not manufacture any
of them. M7 now passes that scoped memory to a resolver only when the provider
declares support for opaque server identities; M8 and M9 can rank language or quality only after the
provider/source metadata is reliable. Current providers declare no opaque
server identity or reliable language/quality metadata. VidLove's visible aliases are not
converted into those identities, and no language or quality truth is inferred
from a server name. Until that contract exists, Auto remains provider-level
and the provider owns its internal server, language, and quality controls.
VidLove's public embed documentation exposes a `server=auto`/preferred-server
option, but it does not provide Dragon with a stable server list or opaque
server-change identity; Dragon therefore leaves that choice inside the VidLove
player until such a contract is available.

The attempt-report endpoint enforces the same boundary server-side: external
`server_id`, language, and quality values are discarded unless the registered
provider explicitly declares the corresponding capability. Client-side
metadata fields are therefore telemetry hints only, never a way to promote an
alias into Dragon state.

## Provider diagnostics V1 (M10)

Playback Settings shows a local, user-scoped health summary for each configured
provider: confirmed successes, failures, average startup, and last confirmed
success. `Healthy` and `Degraded` are derived only from explicit lifecycle
reports; an iframe load alone cannot make a provider healthy. Popup protection
is shown as active only when the provider declares the Dragon safe embed
policy. Resetting a provider's health history is an explicit local action and
does not contact the provider. The explicit Test action requires selecting a
local Movie with a known identity; it runs only on POST and uses the provider's
health hook, so settings GETs still make no provider requests.
