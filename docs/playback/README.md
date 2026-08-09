# Authorized Playback Catalog

Use [authorized-catalog.sample.json](authorized-catalog.sample.json) only as a
template. Replace every placeholder with identifiers from a catalog or account
that you are authorized to use; it is intentionally not importable unchanged.

Submit the JSON file to `POST /playback/catalog/imports` as multipart field
`catalog`, or send its `rows` in an authenticated JSON request. Dragon accepts
only exact IMDb/TMDb matches. TV mappings additionally require an exact season
and episode that already exist in Dragon.

For indexed providers, prefer `provider_asset_id`. An allowlisted HTTPS embed
URL can be imported only to extract that ID. Dragon discards the full URL: it
stores the native asset ID and constructs the final embed URL from the local,
authorized provider template. A provider appears for a title only when all are
true:

- its provider config is enabled and has a valid HTTPS template;
- its preference is enabled;
- the title/episode has an enabled, authorized mapping.

Check the local-only readiness report before a playback smoke test:

```text
GET /playback/movie/<movie_id>/activation-status
GET /playback/movie/<movie_id>/activation-status?season=1&episode=1
```

The report performs no request to providers and exposes no embed URL.
