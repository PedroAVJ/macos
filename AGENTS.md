# macOS plugin

Keep every durable runtime identity unchanged: CLI names (`contacts`, `messages`, `notes`, `voice-memos`), the `macbook-credential-broker` MCP server and Keychain alias, the `apple-notes` MCP server, LaunchAgent labels, store and cache paths. Run `npm test` and `claude plugin validate .` before releasing.

## calendar

- This repository is the canonical source for the `calendar` plugin.
- Keep the Codex and Claude manifests synchronized when both are present. The Claude plugin is intentionally absent for Codex-only plugins.
- Marketplace catalogs reference this repository; do not duplicate runtime behavior back into a marketplace repository.
- Keep credentials and personal data out of Git. Preserve stable command names, service labels, and credential identifiers across releases.
- Bump the plugin version for released behavior changes and run `npm test` before publishing.

## contacts

- This repository is the canonical source for the `contacts` plugin.
- Keep the Codex and Claude manifests synchronized.
- Marketplace catalogs reference this repository; do not duplicate runtime
  behavior into a marketplace repository.
- Keep personal contact data out of Git. The plugin operates only on the live
  macOS Contacts store through Apple's Contacts framework.
- Search raw, non-unified cards and preserve account/container identity so a
  write cannot silently cross from iCloud into Google or another account.
- Require exact contact and address identifiers for destructive operations,
  and verify every write by reading it back.
- Bump the plugin version for released behavior changes and run `npm test`
  before publishing.

## icloud

- This repository is the canonical source for the `icloud` tool plugin.
- Keep the Codex and Claude manifests synchronized.
- The plugin owns procedures, never the user's archived files. Private records live
  in iCloud Drive and must not be copied into Git.
- Treat `Records/Identity` as highly sensitive. Read the minimum exact path and
  never publish or send its contents without the user's explicit current-task
  authorization.
- Copy before deleting a source, verify byte parity, and treat source removal as
  a separate authorized operation.
- Local placement in iCloud Drive is not proof that Apple's remote sync has
  completed.
- Bump the plugin version for released behavior changes and run `npm test`
  before publishing.

## messages

- This repository is the canonical source for the `messages` plugin.
- Keep the Codex and Claude manifests synchronized.
- Treat `~/Library/Messages/chat.db` as private, read-only source data. Never copy message content, handles, database files, WAL files, or attachments into Git.
- Preserve the stable `messages` CLI name and keep hygiene review source-read-only.
- Bump all plugin and package versions together and run `npm test` before publishing.

## notes

- This repository is the canonical source for the `notes` plugin.
- Keep the Codex and Claude manifests synchronized when both are present. The Claude plugin is intentionally absent for Codex-only plugins.
- Marketplace catalogs reference this repository; do not duplicate runtime behavior back into a marketplace repository.
- Keep credentials and personal data out of Git. Preserve stable command names, service labels, and credential identifiers across releases.
- Bump the plugin version for released behavior changes and run `npm test` before publishing.

## reminders

- This repository is the canonical source for the `reminders` plugin.
- Keep the Codex and Claude manifests synchronized when both are present. The Claude plugin is intentionally absent for Codex-only plugins.
- Marketplace catalogs reference this repository; do not duplicate runtime behavior back into a marketplace repository.
- Keep credentials and personal data out of Git. Preserve stable command names, service labels, and credential identifiers across releases.
- Bump the plugin version for released behavior changes and run `npm test` before publishing.

## voice-memos

- This repository is the canonical source for the `voice-memos` plugin.
- Keep the Codex and Claude manifests synchronized when both are present. The Claude plugin is intentionally absent for Codex-only plugins.
- Marketplace catalogs reference this repository; do not duplicate runtime behavior back into a marketplace repository.
- Keep credentials and personal data out of Git. Preserve stable command names, service labels, and credential identifiers across releases.
- Bump the plugin version for released behavior changes and run `npm test` before publishing.

## apple-passwords

- This repository owns the public `apple-passwords` plugin, installed as `macos@package-manager`.
- Keep Codex and Claude plugin manifests and package version synchronized.
- Keep account identifiers, device addresses, pairing tokens, credentials, and private host observations outside Git.
- Runtime paths must resolve within the package or through explicitly configured external services. Never reference a developer's task folder or installed cache as source.
- Preserve source and icon provenance. First-party material is MIT licensed.
- Run `npm test`, the Codex plugin validator, and `claude plugin validate .` before release. Validation must not pair with or operate a physical device or initiate authentication.
- The credential broker's Keychain service `com.pedroavj.macbook.credential-broker`, alias `macos-login`, MCP server name `macbook-credential-broker`, signing identifier, and support path `~/Library/Application Support/MacBookCredentialBroker` are durable identities. Do not rename them without a planned migration.
- Rebuild `runtime/bin/macbook-credential-broker` only with `scripts/build-credential-broker`, and never add a secret-returning tool.

## macbook

- This repository is the canonical source for the `macbook` plugin.
- Keep the Codex and Claude manifests synchronized when both are present. The Claude plugin is intentionally absent for Codex-only plugins.
- Marketplace catalogs reference this repository; do not duplicate runtime behavior back into a marketplace repository.
- Keep credentials, pairing secrets, network endpoints, and hardware serial numbers out of Git. `context/mac-control-host.md` documents comparison rules; operator baselines belong outside Git and live inspection takes precedence.
- Bump the plugin version for released behavior changes and run `npm test` before publishing.
