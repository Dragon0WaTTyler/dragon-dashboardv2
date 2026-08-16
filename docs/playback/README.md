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
