# Google personal vault

This document records Dragon's feature-gated personal-workspace model. Google
Drive is the portable source of truth for a connected user's Dragon data; a
local computer and a PythonAnywhere deployment each keep only a working cache.

## What is stored where

| Location | Stored there | Not stored there |
| --- | --- | --- |
| User's Google Drive appDataFolder | Their Dragon workspace cache, personal progress, lists, RSS sources, PocketTube data, and integration settings | Another Dragon user's data |
| Dragon application database | Login identity, a pointer to the vault file, and an encrypted refresh credential used to reach that user's Drive | Personal content, watch progress, RSS sources, PocketTube groups, or Notion data |
| Local/PythonAnywhere runtime | A separate SQLite cache for that workspace only | The source of truth for a connected Google personal workspace |

The vault uses one stable workspace_id. A second Dragon installation that signs
into the same Google account discovers the existing vault and adopts that same ID,
which is what makes local and PythonAnywhere synchronisation possible.

## Safety properties already implemented

- Google OAuth requests OpenID identity plus the narrow drive.appdata scope.
- The Drive vault is in the app-specific hidden folder, not a shared public file.
- OAuth state is checked before a callback is accepted.
- The local refresh credential is encrypted using the Dragon application secret.
- A Drive update uses its ETag through If-Match; a concurrent update is rejected
  instead of silently overwriting another device.
- Every ORM content table routes to the authenticated workspace's SQLite cache.
  The central database retains only authentication and the encrypted Drive pointer.
- The cache is downloaded when its Drive version changes and saved through a
  resumable upload after it changes; SQLite is checkpointed first so progress is
  included in the uploaded file.
- An existing single-owner SQLite installation can link Google and make one
  initial backup of its legacy workspace into the new Drive cache.
- Google sign-in and Drive workspace creation are disabled by default. They require
  both client credentials and two explicit feature flags.

## Personal features in the workspace

- Every content record is isolated per workspace, including Movie/TV progress,
  custom watch lists, reading progress, books, RSS sources, and YouTube history.
- A user can save their own YouTube API key and playlist ID. The public playlist
  API does not expose Watch Later, so users should select a playlist they manage.
- A user can upload a PocketTube JSON export directly from the PocketTube view;
  its channels and cached videos belong only to that workspace.
- Notion token and separate Movies, Books, and Book Quotes destination IDs are
  stored in the workspace. The token is never rendered in the form after saving.
- Book Quotes review state and Kindle clipping queues are persisted in the
  workspace cache rather than a shared server file.
- The News sources screen accepts a user-owned RSS or Atom feed URL directly.

## Remaining limits

- A concurrent conflicting save is detected and protected with an ETag; Dragon
  does not yet offer an interactive merge screen.
- Local ebook/audio files, downloaded playback files, and other large assets are
  not uploaded to Drive yet. Their catalog metadata synchronises, but their local
  file path cannot become a remote file automatically.
- GitHub and iCloud/CloudKit are not storage providers yet. Google Drive is the
  only supported personal sync provider in this branch.
- PocketTube is an explicit JSON import, not an automated connection to the
  browser extension.

Do not enable the Google flags in a public deployment until the Google Cloud OAuth
client is configured and this branch has been deployed. Legacy import is
deliberately restricted to SQLite so it cannot accidentally copy a shared hosted
database.

## Configuration after workspace isolation is deployed

After the isolation phase, create a Google OAuth web client and register the exact
callback URL used by the deployment. Then add only these values to that deployment's
private environment:

```dotenv
DRAGON_GOOGLE_OAUTH_ENABLED=true
DRAGON_GOOGLE_PERSONAL_VAULT_LOGIN_ENABLED=true
DRAGON_GOOGLE_PERSONAL_VAULT_SYNC_ENABLED=true
DRAGON_GOOGLE_OAUTH_CLIENT_ID=...
DRAGON_GOOGLE_OAUTH_CLIENT_SECRET=...
DRAGON_GOOGLE_OAUTH_REDIRECT_URI=https://your-host.example/auth/google/callback
```

Do not put user OAuth refresh tokens, a personal playlist identifier, or a Notion
token in this shared environment. Those belong to the user's own vault.

For a pre-existing local Dragon account, sign in with its normal password first,
then open /auth/google/connect. Dragon creates a new private Drive workspace and
copies the original SQLite workspace exactly once before future changes sync through
Google Drive.

After connection, open /auth/workspace to save that user's YouTube playlist and
Notion connection details inside their private workspace. Tokens are never rendered
back into the form after saving.

## Local and PythonAnywhere setup

Register a Google OAuth web client for each URL you use. It is normal to have one
client/redirect URI for PythonAnywhere and another for localhost or a local HTTPS
host. Sign into both Dragon installations with the same Google account: Drive
discovers the same workspace ID and restores the same cache, including progress and
watch lists. Each installation may keep its own application secret; it encrypts
only that installation's bootstrap refresh credential.
