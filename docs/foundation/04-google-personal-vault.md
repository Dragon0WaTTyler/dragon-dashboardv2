# Google personal vault foundation

This document records the first safe step from Dragon's original single-owner
installation toward portable personal workspaces. It is deliberately feature-gated:
the Google button remains off until data isolation is complete.

## What is stored where

| Location | Stored there | Not stored there |
| --- | --- | --- |
| User's Google Drive appDataFolder | Their Dragon vault document, snapshots, and future per-user integration settings | Another Dragon user's data |
| Dragon application database | Login identity, a pointer to the vault file, and an encrypted refresh credential used to reach that user's Drive | Personal content, watch progress, RSS sources, PocketTube groups, or Notion data |
| Local/PythonAnywhere runtime | A cache or projection needed while the app is running | The source of truth for a connected Google personal workspace |

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
- Google sign-in and Drive workspace creation are disabled by default. They require
  both client credentials and two explicit feature flags.

## Delivery order

1. **Foundation (this change):** Google identity, a canonical Drive vault,
   encrypted bootstrap credentials, and concurrency-safe Drive read/write support.
2. **Isolation:** replace shared state in Movies, YouTube/PocketTube, RSS, books,
   My TV, learning, and history with workspace-owned records.
3. **Portable projections:** export and merge each workspace-owned domain through
   versioned vault snapshots/events, beginning with movie watch state.
4. **Per-user integrations:** store each user's YouTube playlists, PocketTube
   import, RSS sources, and Notion OAuth configuration inside that user's vault.
5. **Other storage providers:** add GitHub as an explicit backup/portable export
   provider, then evaluate CloudKit/iCloud as a separate Apple-specific provider.

Until step 2 is finished, do not enable
DRAGON_GOOGLE_PERSONAL_VAULT_LOGIN_ENABLED in a public deployment: the original
content tables are still single-owner tables and would not yet provide the isolation
that Google sign-in promises.

## Configuration after workspace isolation is deployed

After the isolation phase, create a Google OAuth web client and register the exact
callback URL used by the deployment. Then add only these values to that deployment's
private environment:

```dotenv
DRAGON_GOOGLE_OAUTH_ENABLED=true
DRAGON_GOOGLE_PERSONAL_VAULT_LOGIN_ENABLED=true
DRAGON_GOOGLE_OAUTH_CLIENT_ID=...
DRAGON_GOOGLE_OAUTH_CLIENT_SECRET=...
DRAGON_GOOGLE_OAUTH_REDIRECT_URI=https://your-host.example/auth/google/callback
```

Do not put user OAuth refresh tokens, a personal playlist identifier, or a Notion
token in this shared environment. Those belong to the user's own vault in the later
per-user integration phase.
