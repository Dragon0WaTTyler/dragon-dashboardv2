# My TV + Media Library — Flask dashboard

A local Flask TV dashboard that discovers M3U playlist packages from
`mesbahikarim63-commits/hot-dodo`, imports selected packages, organises channels
by bouquet, and plays enabled streams inside the browser.

It also includes a Notion-backed movie and series library at `/media`. Notion is
the source of truth: existing rows form the visible library, TMDB discovers and
enriches missing titles, and Jackett supplies selectable releases only after a
title or episode is chosen.

## What is included

- GitHub catalogue refresh without downloading every large playlist.
- Background import for the latest, selected, or all source packages.
- SQLite persistence for sources, bouquets, channels, and overrides.
- Three control levels: source master switch, bouquet default, channel override.
- Search, filters, pagination, responsive layout, and accessible controls.
- HLS proxy/manifest rewriting and HLS.js playback.
- FFmpeg live transcoding for direct MPEG-TS and other browser-incompatible streams.
- Stream URLs remain server-side; the page works with channel IDs.
- Public-address validation blocks imported URLs that resolve to local/private networks.
- Notion read/write library with duplicate-safe TMDB ID upserts.
- TMDB movie/series discovery plus season and episode selection.
- Modular Jackett release provider with movie/TV category selection and seeder filtering.
- Browser WebTorrent playback or a configurable external-player adapter.

## Run it

```powershell
python -m pip install -r requirements.txt
$env:TMDB_API_TOKEN = "your-tmdb-read-token"
$env:JACKETT_API_KEY = "your-jackett-api-key"
$env:NOTION_TOKEN = "your-notion-integration-token"
$env:NOTION_DATABASE_ID = "your-notion-database-id"
$env:SECRET_KEY = "replace-this-with-a-long-random-value"
python run.py
```

Copy `.env.example` to `.env` for local development, then fill in the secrets.
The `.env` file is ignored by git. Open `http://127.0.0.1:5000/my-tv` for live
TV or `http://127.0.0.1:5000/media` for movies and series.

The first visit refreshes the lightweight repository catalogue. Click **Import
latest** to import the three newest packages, select specific packages in
**Manage**, or choose **Import all** when you intentionally want the full source.
The upstream repository can be hundreds of megabytes, so importing everything
can take several minutes and create a large local database.

## Command-line sync

```powershell
python -m flask --app run mytv sync --mode catalog
python -m flask --app run mytv sync --mode latest
python -m flask --app run mytv sync --mode all
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `SECRET_KEY` | development value | Session and signed playback tokens; change this outside local development. |
| `MYTV_GITHUB_OWNER` | `mesbahikarim63-commits` | Playlist repository owner. |
| `MYTV_GITHUB_REPO` | `hot-dodo` | Playlist repository name. |
| `MYTV_GITHUB_BRANCH` | `main` | Repository branch. |
| `MYTV_IMPORT_LIMIT` | `3` | Number of newest packages imported by **Import latest**. |
| `MYTV_MAX_CHANNELS_PER_PLAYLIST` | `0` | Optional per-playlist cap; `0` means no cap. |
| `MYTV_FFMPEG` | `ffmpeg` | FFmpeg executable name/path. |
| `MYTV_MAX_TRANSCODES` | `2` | Maximum simultaneous FFmpeg sessions. |
| `MYTV_ALLOW_PRIVATE_STREAMS` | `0` | Set to `1` only when intentionally playing trusted LAN sources. |

## Control behaviour

- Turning a **source** off is a master stop for everything in that package.
- Turning a **bouquet** off changes its default, while explicit channel overrides remain.
- Turning a **channel** on or off creates an explicit exception.
- **Use default** clears all exceptions in a bouquet.
- **All on / All off** creates explicit overrides for every channel in the bouquet.

Only use streams you own or are authorised to access. The dashboard does not
grant rights to third-party content, and upstream links can expire at any time.

## Media library flow

1. `/media` queries the configured Notion data source and shows those rows only.
2. Search checks those rows and TMDB. TMDB results already present in Notion are
   shown as library items; missing results can continue to release selection.
3. Movies search Jackett with category `2000`. Series use TMDB seasons/episodes
   and search category `5000` with an `SxxExx` query.
4. Jackett results without a magnet URI or with fewer than
   `JACKETT_MIN_SEEDERS` are removed.
5. **Add & play** fetches trusted metadata from TMDB on the backend, then creates
   or updates the Notion row before playback starts.
6. The first successful browser `playing` event sets `Watched` and `Date Watched`
   in Notion. A manual **Mark watched** action is also available.

For a series, its Notion row stores the latest selected season, episode, release
title, and magnet. TMDB remains responsible for the full current season and
episode catalogue, so the Notion database does not need one row per episode.

## Notion setup

Share the database with the integration using **Add connections**. The
integration needs read, insert, and update-content capabilities. The code accepts
a database ID and discovers its first modern Notion data source; if your database
has more than one data source, set `NOTION_DATA_SOURCE_ID` explicitly.

The title property's name is detected automatically. Create the remaining
properties below, or map their existing names with the matching environment
variables from `.env.example`.

| Default property | Recommended Notion type | Purpose |
| --- | --- | --- |
| `Title` | Title | Movie or series title |
| `TMDB ID` | Number | Stable duplicate check |
| `Type` | Select | `Movie` or `Series` |
| `Year` | Number | Release/first-air year |
| `Poster` | URL | TMDB poster URL |
| `Overview` | Text | TMDB overview |
| `Magnet` | Text | Selected magnet URI |
| `Release Title` | Text | Exact Jackett result selected |
| `Watched` | Checkbox | Watched state |
| `Date Watched` | Date | UTC timestamp of playback/marking |
| `Season` | Number | Latest selected series season |
| `Episode` | Number | Latest selected series episode |

Missing optional properties do not prevent reads. The `/media` page reports
which properties are missing so write-back can be completed safely without the
app silently changing your Notion schema.

## Jackett setup

Run Jackett locally and copy its API key from the Jackett dashboard:

```powershell
docker run -d --name=jackett -p 9117:9117 -v jackett-config:/config linuxserver/jackett
```

When Flask runs directly on the host, use `JACKETT_URL=http://127.0.0.1:9117`.
When both services run in Docker, put them on the same private Docker network and
use the service URL, for example `http://jackett:9117`. Do not expose Jackett or
its API key through the public reverse proxy on a VPS.

The release-provider interface lives in `app/services/releases.py`. A future
Prowlarr adapter only needs to implement the same `configured` property and
`search(query, media_type)` method; the routes and frontend do not depend on
Jackett-specific response fields.

## Playback notes

`MEDIA_PLAYER_MODE=webtorrent` uses a pinned WebTorrent browser bundle and a
same-origin service worker. Browser torrent clients need WebRTC-compatible peers,
and the selected file must use a browser-supported container and codec. On a VPS,
serve `/media` over HTTPS because service workers require a secure context
(`localhost` is allowed for development).

For broader torrent and codec support, set `MEDIA_PLAYER_MODE=external` and
configure `MEDIA_EXTERNAL_PLAYER_URL_TEMPLATE`; `${magnet}` is substituted on
the backend. Keep all torrent use limited to content you own or are authorised
to access.
