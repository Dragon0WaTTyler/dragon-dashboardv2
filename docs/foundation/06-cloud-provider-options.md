# Personal cloud-provider options

Google Drive is the shipped personal-workspace provider. It is the recommended
production path for Dragon today: a user signs in with Google and their private
workspace cache follows them between local Dragon and PythonAnywhere.

## GitHub: possible, but not through broad OAuth

GitHub is a viable future provider for a user who deliberately wants a private
repository as their Dragon vault. It must use a **GitHub App**, installed by the
user on one chosen repository, with only repository Contents read/write
permission. The vault itself should remain one encrypted snapshot plus a small
manifest, not a stream of personal activity commits.

Do not add a generic GitHub OAuth `repo` login as a shortcut. GitHub documents
that OAuth's `repo` scope grants broad access to private repositories and other
repository-owned resources, while GitHub Apps support fine-grained permissions
and installation on selected repositories only. See [GitHub OAuth
scopes](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps)
and [GitHub Apps versus OAuth
apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/differences-between-github-apps-and-oauth-apps).

This provider is not implemented yet because it needs a registered GitHub App,
key rotation, installation-token handling, and a clear user choice of repository.

## iCloud: CloudKit, not iCloud Drive

There is no suitable public web API for using a person's arbitrary iCloud Drive
folder as Dragon storage. The correct Apple option is **CloudKit JS**: it can
work with an app container's private database after an Apple developer configures
the container and enables web services. Apple's private CloudKit database is
owned by the user and is separate from other users' private records.

That requires an Apple developer account, a CloudKit container/schema, and a
small browser-side CloudKit integration; it is not a server-only PythonAnywhere
configuration. See [CloudKit JS](https://developer.apple.com/documentation/CloudKitJS)
and [Apple's private CloudKit database
documentation](https://developer.apple.com/documentation/cloudkit/ckcontainer/privateclouddatabase).

## Provider contract

Any future provider must preserve the existing invariants:

- one immutable workspace ID per person;
- no shared cache, token, source, queue, progress, or preference data;
- encrypted connection credentials at the Dragon host;
- conflict detection that preserves both copies rather than silently overwriting;
- explicit manual setup and a disconnect path;
- no secret, playlist identifier, or Notion token in shared deployment settings.
