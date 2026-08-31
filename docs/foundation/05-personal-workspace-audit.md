# Personal workspace audit

## Product result

When Google personal workspaces are enabled, Dragon becomes a user-owned service:
each Google identity gets an isolated cache that is synchronised through that
identity's Drive appData folder. A local installation and a PythonAnywhere
installation use the same workspace after the user signs into both with the same
Google account.

The central application database deliberately contains only authentication,
workspace discovery information, and an encrypted refresh credential. Content data
is not shared there.

## Feature coverage

| Area | User-owned data | Workspace behavior |
| --- | --- | --- |
| Movies and TV | Library state, progress, scores, custom lists, playback history | Isolated SQLite data; synchronised with Drive |
| YouTube | Cached videos, watched state, API key, selected playlist | User saves a playlist/API key in Personal workspace |
| PocketTube | Imported groups, channel memberships, cached uploads | User uploads the extension JSON export from PocketTube |
| News | RSS/Atom sources, article cache, saved/read state | User adds a source directly from News sources |
| Books | Library, reading state, Notion destinations, Book Quotes state | Data and supported Notion settings are synchronised |
| Kindle workflows | Clipping outbox, manual matching, and Book Quotes sync readiness | Queue and Notion sync settings are stored in the workspace cache; personal workspaces never read legacy shared Kindle credentials |
| Settings | Appearance, home layout, section choices, movie playback preferences | Stored in the workspace cache |

## Connected-user journey

1. Enable the three Google personal-workspace flags only after configuring a
   Google OAuth web client and its exact callback URL.
2. A new person chooses Google sign-in. Dragon creates a private Drive workspace.
3. The person visits Personal workspace to save their YouTube playlist/API key and
   optional Notion destinations.
4. They add RSS sources from News and import their PocketTube export from YouTube.
5. On another Dragon installation, they sign in with the same Google account. The
   newer Drive cache is restored before the request runs.

For the original single-owner installation, the existing local user first chooses
Connect Google Drive from Personal workspace. Dragon makes one legacy SQLite
import into Drive before all later changes use the personal cache.

## Cross-device proof

The Google cache integration test writes a movie marked want to watch, its
842-of-2400-second playback progress, a custom I want to watch list, a private
YouTube playlist setting, PocketTube channel/video watched data, an RSS source,
a Book reading position, and Movie playback preferences. It uploads the cache,
removes the local cache directory, then verifies that a new local cache restores
every record and setting from Drive.

## Deliberate boundaries

- Drive conflict detection protects the newer remote file with an ETag. An
  interactive merge tool is not available yet.
- Book, audiobook, subtitle, and playback files remain local device assets. Their
  catalog records synchronise, not the file bytes.
- Google Drive is the supported provider. GitHub backup/export and iCloud/CloudKit
  are future provider work, not hidden fallback behavior.
- PocketTube requires a user-selected JSON export; Dragon does not access the
  browser extension or a PocketTube account directly.
