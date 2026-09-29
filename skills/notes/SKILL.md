---
name: notes
description: Create, search, read, update, organize, and delete Apple Notes on macOS; create native interactive checklists; and read phone or FaceTime call recordings plus their transcript cache. Use whenever the user asks to save to, find in, manage, or make a checklist in Apple Notes, or to work with an Apple call recording.
---

# Notes

Choose the write path by host:

- In Codex, invoke `computer-use:computer-use` and control Notes.app directly
  for every mutation.
- In Claude, use the stable `notes create` and `notes checklist create` UI
  commands below. They drive Notes.app through System Events without Python and
  without querying an iCloud account.

Use the pinned Apple Notes MCP for bounded discovery and reads. Its mutation
tools are not the preferred create path because their AppleScript account calls
can block behind Notes sync. Use the stable `notes calls` CLI for call
recordings and their private transcript cache. A newly released MCP surface
appears only in a fresh task after installation.

## General Apple Notes

The `apple-notes` MCP server exposes search, read, folder, attachment,
checklist-state, and diagnostic tools. Keep its use read-only for ordinary
creation and checklist tasks; its AppleScript-backed account operations can
block behind Notes sync.

- Prefer the returned Core Data note id for follow-up reads. Titles can be
  duplicated or truncated; UI mutations still require resolving the exact
  visible note.
- Before replacing a note body, check `list-attachments` when attachments are
  present or plausible. A full-body replacement can remove embedded images,
  scans, PDFs, files, and audio.
- Treat shared notes as external collaboration. Do not edit one unless the
  user's request clearly includes that shared note.
- Do not bulk-read, export, or summarize the whole Notes library merely because
  the tools exist. Keep reads bounded to the user's request.
- Deletion moves a note to Recently Deleted. Resolve the exact visible note
  first and never choose silently among duplicate titles.

In Codex, first follow the Computer Use skill bootstrap and inspect Notes.app
with `get_app_state`. Re-fetch state after each action and use fresh element
indices. Prefer the currently selected/default Notes folder; do not ask the
user to choose an iCloud account unless they explicitly requested a different
account or folder.

For a new note, activate Notes' New Note control, enter the title as the first
line and the body below it, then verify the visible title and body through a
fresh accessibility snapshot. For an existing note, search or select the exact
visible result and inspect its content before editing. Never overwrite an
attachment-bearing or shared note merely because its title matches.

In Claude, create an ordinary note through the UI CLI:

```bash
notes create --title "Project brief" --body "First draft" --json
notes create --title "Long note" --stdin --json < BODY_FILE
```

The UI writer activates Notes, creates a note in the currently selected/default
folder, inserts Unicode through Accessibility, verifies the visible title and
body, and restores the previous app. It never invokes Notes' account scripting
dictionary. `--account` and `--folder` are intentionally rejected instead of
guessing or triggering a sync-blocked account lookup.

## Native Interactive Checklists

AppleScript cannot create Notes' private checklist paragraph style. Never write
`NoteStore.sqlite` or manufacture its gzipped protobuf. Codex uses Computer Use
against Notes.app itself. Claude uses the plugin-owned System Events script,
launched directly from the signed Claude host rather than from Python.

In Claude:

```bash
notes checklist create \
  --title "Packing" \
  --item "Passport" \
  --item "Charger" \
  --item "Medication" \
  --json
```

For many items, pass a JSON array on stdin:

```bash
notes checklist create --title "Packing" --items-stdin --json < ITEMS_JSON
```

Create or open the exact target note, insert one clean line per item, select
only the intended item lines, and press Shift+Command+L. When converting an
existing bulleted or numbered list, remove the old list markers before applying
the checklist style. Preserve the title and unrelated content.

In Codex, verify success from a fresh Notes accessibility snapshot:

- the Checklist toolbar control reports `Value: On` while the items are
  selected;
- the note body exposes every row as a checklist `[button]`;
- the item count, order, wording, and unchecked state match the request; and
- only the intended live note remains when the user requested replacement or
  deduplication.

If formatting fails after content was entered, leave the recoverable note
intact and report the exact partial state. Do not reinterpret an old
Notes-account timeout as a new permission failure; diagnose the live Notes UI.
Claude's CLI reports a permission problem only when macOS actually denies the
direct host. That grant is persistent for the signed Claude application, not a
per-note or per-account prompt.

## Read Calls

```bash
notes calls list --json
notes calls list --since 2026-06-01
notes calls path A1B2C3D4
notes calls transcript A1B2C3D4
notes calls doctor --json
```

Resolve a call by attachment UUID whenever possible. Unique UUID prefixes and
unambiguous contact labels are accepted for interactive lookup; never silently
choose among multiple calls.

The call database is authoritative and read-only. Do not glob the Notes media folders: deleted
notes leave plausible audio behind, the titled attachment reports zero
duration while its child carries the real value, file mtime is not call time,
and a live WAL-mode store can look valid while missing recent rows. The CLI
snapshots the database plus WAL sidecars and opens the snapshot read-only.

## Read Cached Transcripts

```bash
notes calls transcriptions show CALL_UUID --json
notes calls transcriptions status --state completed --limit 100 --json
notes calls transcriptions status --state completed --limit 100 \
  --after-cursor "$CURSOR" --json
```

`status` reads only the private cache. It never scans Notes and never invokes
ElevenLabs. Results include UUID, `call_started_at`, title, source path, state,
provider/model/format, transcript path and SHA-256, and timestamps. Consumers
own their checkpoints; pass the returned opaque `next_cursor` on the next page.

When an explicitly requested exact call is not cached, retry that item without
enumerating or acting on unrelated calls:

```bash
notes calls transcriptions retry CALL_UUID --json
```

The worker prefers non-empty Apple transcript text. Only when Apple text is
absent does it resolve the `elevenlabs` CLI from `PATH` and use `scribe_v2`,
`diarized_text`, and automatic `--diarize`; it never supplies
`--num-speakers`.

## On-Demand Transcription Only

This plugin does not install or run a transcription LaunchAgent. Prefer
`retry CALL_UUID` for the exact call the user selected. Run bounded `reconcile`
only when the user explicitly asks to scan for uncached calls; it may invoke
ElevenLabs and therefore incur cost. Existing cache artifacts remain durable.

## Evidence and Scope

Apple call transcript coverage is region- and language-gated. For noisy calls,
speaker labels and exact wording remain approximate; never invent identities or
repair garbled language. Keep UUID, call window, title/contact label, source
path, transcript provider/options, artifact hash, and known limitations
together.

Never edit a call-recording source note, Apple transcript, or recording. Never
move source audio. Full Disk Access is required for the exact launched process;
an empty database result is not proof of access, so use `notes calls doctor`
when diagnosing call permissions. General note writes do not authorize edits to
call-recording notes.
