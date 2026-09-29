---
name: icloud-drive
description: Browse, verify, or safely archive files in the user's iCloud Drive on macOS. Use for exact iCloud Drive paths, including user-selected sensitive archives, and for copy-before-delete migrations that require byte-for-byte verification.
---

# iCloud Drive

Use `../../scripts/icloud-drive` instead of hand-built recursive file commands.
The tool operates on the local iCloud Drive filesystem. It does not prove that
Apple's remote sync has completed.

## Read narrowly

Use the minimum exact path needed for the task:

```bash
../../scripts/icloud-drive root
../../scripts/icloud-drive list <relative-directory>
../../scripts/icloud-drive status <relative-path>
../../scripts/icloud-drive checksum <relative-file>
```

Do not inventory `Records/Identity` broadly unless the user asks. Never print file
contents or identifiers merely to prove that a record exists.

## Archive safely

Resolve the destination from the current user's request or private configuration.
For example, `Records/Identity` is an illustrative archive path:

```bash
../../scripts/icloud-drive copy-file <source-file> Records/Identity/<destination>
```

For a migration:

1. Copy each regular file to its explicit relative destination.
2. Verify the source and destination are byte-identical.
3. Report local placement separately from iCloud remote-sync status.
4. Remove the source only when that deletion is explicitly authorized. The
   `copy-file` command never deletes the source.

## Boundaries

- The plugin is a tool; private records stay in iCloud Drive, never in plugin Git.
- Reject absolute destinations, parent traversal, symlinks, and overwrites.
- Treat `Records/Identity` as highly sensitive. Do not send, publish, attach, or
  quote anything from it without the user's explicit authorization for that action.
- Do not infer remote availability from successful local filesystem access.
