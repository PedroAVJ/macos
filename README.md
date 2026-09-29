# macOS

One plugin for the Mac's own apps and system. Each section below is the former standalone plugin's documentation; skill names are now `macos:<skill>`.

## calendar

Apple Calendar as one application integration. The plugin owns deterministic
AppleScript access for calendar discovery, exact event reads and searches, and
event creation, updates, and deletion without Computer Use.

The scripts never store calendar data or credentials in the plugin. They read
the live Calendar application and rely on macOS Automation permission.

## contacts

Contacts is the user's dual-client plugin for live Apple Contacts access
on macOS. Its `contacts` CLI uses Apple's public Contacts framework to inventory
and search raw cards with their account containers, read rich structured cards,
discover and add exact directional relationships on My Card, add verified email
addresses, and safely add or remove postal addresses without visual automation.

The plugin stores no contact data, credentials, exports, or local database.
macOS owns authorization and the live address book.

## Common commands

```bash
./bin/contacts --json doctor
./bin/contacts --json list --container iCloud --limit 100 --offset 0
./bin/contacts --json search "name or phone" --container iCloud
./bin/contacts --json read CONTACT_ID
./bin/contacts --json me
./bin/contacts --json relationships
./bin/contacts --json relationships CONTACT_ID
./bin/contacts --json relationship add OWNER_CONTACT_ID RELATED_CONTACT_ID --label manager
./bin/contacts --json email add CONTACT_ID --label home --value person@example.com
./bin/contacts --json address add CONTACT_ID \
  --label home --street "Street" --city "City" --state "State" \
  --postal-code "Postal code" --country "Country" --country-code MX
```

Search returns raw cards rather than Contacts' unified people. This makes the
account boundary visible before a write when the same person exists in both
iCloud and Google.

## Relationship model

Apple contact relationships are directional labeled names, not persistent
links between two contact IDs. For example, My Card can store `sister -> Jane
Doe`; that value does not automatically create `brother -> the user` on Jane's
card. `relationships` reads the unified My Card and reports exact raw-card name
matches as `exact`, `ambiguous`, or `unmatched` so callers do not silently guess.
If Apple does not expose My Card, callers can supply one exact raw contact ID;
the plugin never guesses which person is the user.

`relationship add` requires exact raw IDs for both the owner and related card.
It stores the related card's current full name under the requested directional
label, is idempotent, and verifies the saved value by reading the owner card
back. `boss` is accepted as an alias for Apple's standard `manager` label.

`email add` requires one exact raw card ID and a verified email value. It is
additive and idempotent: an existing normalized value returns
`already_present`; a missing value is appended and read back before success is
reported. It never replaces a different email address or silently corrects a
suspected typo.

Detailed reads expose the structured fields Contacts owns well: name parts,
nickname and phonetic names; organization, department, and job title; phones,
email, addresses, URLs, messaging accounts, and social profiles; birthdays and
other labeled dates; relationships; and photo availability. Contact notes are
not read because modern Apple platforms protect them with a restricted
entitlement.

Phone reads preserve Apple's raw `value` and also expose `e164`,
`e164_source`, and `default_country_code`. Numbers already stored with `+` are
canonicalized as explicit values; historical Mexican `+521` transport values
are emitted as current `+52` with `explicit_legacy_mexico` provenance. An unprefixed national number is normalized
with Contacts' device-default country when the plugin supports that numbering
plan; the result is marked `default_country` rather than presented as an
explicitly stored country code. Short numbers and unsupported formats remain
`unavailable`.

## Validation

```bash
npm test
```

## icloud

A tool for safely working with the user's iCloud Drive through its local
macOS filesystem.

The plugin contains procedures and a guarded command-line tool. It does not
contain the private files themselves. Choose an archive directory from the current request; no personal directory
layout is assumed. The command examples below use an illustrative archive.

## Skill

| Skill | Purpose |
| --- | --- |
| `icloud-drive` | Browse exact folders, verify files, and copy individual files without overwriting existing data. |

## Command-line tool

```bash
./scripts/icloud-drive root
./scripts/icloud-drive list Records/Identity
./scripts/icloud-drive status Records/Identity/documents.yml
./scripts/icloud-drive checksum Records/Identity/documents.yml
./scripts/icloud-drive copy-file ./source.pdf Records/Identity/documents/source.pdf
```

`copy-file` never removes the source. It rejects paths outside iCloud Drive,
refuses to overwrite a different file, and verifies byte parity before making
the destination visible.

## Install

```bash
claude plugin install macos@near
```

```bash
codex plugin add macos@near
```

## messages

A read-only macOS Messages plugin for bounded SMS, RCS, and iMessage hygiene review and authorized outgoing writing samples. It reads the local Messages SQLite database directly, exposes stable source IDs and timestamps through a JSON CLI, and keeps all block, report, reply, and opt-out actions manual.

## Requirements

- macOS
- Python 3
- Full Disk Access for the client or terminal process reading `~/Library/Messages/chat.db`

## Use

```bash
./bin/messages --json doctor
./bin/messages --json scan
./bin/messages --json scan --since 7d
./bin/messages --json read MESSAGE_GUID
./bin/messages --json context MESSAGE_GUID --before 3 --after 3
```

An omitted scan span means the previous 24 hours ending at invocation time. Explicit `--since` and `--until` values accept ISO-8601 timestamps; `--since` also accepts durations such as `24h` or `7d`. Scans are stateless and use the Messages message timestamp with `[since, until)` bounds.

`scan` returns metadata only. Read exact message bodies only with `read` or bounded `context`, after the candidate IDs are known. The CLI opens the database in SQLite read-only mode and enables `query_only`; it never sends, replies, blocks, reports, deletes, marks read, or changes Messages settings.

## Privacy

Messages content, handles, attachments, and the local database remain private runtime data and are never committed. The CLI masks phone-number-like handles in its resolved sender label; raw handles remain available only in exact read output for local classification.

This project is unofficial and is not affiliated with or endorsed by Apple Inc.

## Outgoing writing samples

For an authorized writing task, read a small sample through the same read-only
transport:

```bash
./bin/messages --json samples --since 30d --chat-id CHAT_GUID --limit 30
./bin/messages --json samples --since 24h --until 2026-01-02T00:00:00Z --limit 20
```

The default window is the previous 24 hours; the default limit is 30 candidate
rows, with a hard maximum of 100. `--chat-id` accepts an exact GUID or an
unambiguous chat identifier. Results include outgoing text, source timestamps,
service, chat IDs, and `is_from_me`. Blank or unsupported bodies are skipped
without reading beyond the bounded candidate set. A `truncated` result indicates
more candidates inside that exact window.

Messages account direction is not proof of human authorship. The output says so
explicitly; exclude known assistant-authored or copied text before using it as
writing evidence. `macos:messages-writing-samples` describes safe source collection
for `whatsapp:impersonating`. The active assistant drafts directly. The hygiene
`scan` remains incoming-only and contains no message text.

## notes

Create, find, read, update, organize, and delete Apple Notes on macOS through
host-appropriate live UI automation; create true native interactive
checklists; and retain the existing phone/FaceTime call-recording and private
transcript-cache workflows.

Version 0.6.1 supports both Codex and Claude. Codex controls Notes.app through
OpenAI's bundled Computer Use capability. Claude uses the plugin-owned `notes`
CLI, whose Node argument parser launches a bounded System Events UI script. The
write path never uses Python or Notes' sync-blocked account scripting
dictionary. The pinned, MIT-licensed `apple-notes-mcp@2.7.5` server remains
available for bounded discovery and reads.

## Create Notes

Ask Codex to create the note. The Notes skill invokes
`computer-use:computer-use`, opens Notes.app, enters the title and body, and
reads the live accessibility tree back before reporting success. It uses the
currently selected/default Notes folder unless the request explicitly names a
different folder or account.

Claude uses the same live Notes UI through the CLI:

```bash
notes create --title "Project brief" --body "First draft" --json
notes create --title "Long note" --stdin --json < body.txt
```

The CLI deliberately uses the currently selected/default Notes folder and
rejects `--account` and `--folder`; it does not enumerate iCloud accounts.

## Create Native Checklists

Apple Notes stores checklist style in a private gzipped protobuf and exposes no
checklist creation property through AppleScript. This plugin does not write the
live Notes database. Codex enters clean item lines in Notes.app, selects only
those lines, invokes Notes' own Shift+Command+L checklist action, and verifies
that every item is exposed as a native unchecked control. Existing plain lists
can be converted in place without manufacturing a duplicate note.

Claude invokes Notes' native checklist Accessibility action through the CLI:

```bash
notes checklist create \
  --title "Packing" \
  --item "Passport" \
  --item "Charger" \
  --item "Medication" \
  --json
```

For a large checklist, `--items-stdin` accepts a JSON array of strings. The UI
script verifies the title, every item, and that Notes retained native checklist
formatting before reporting success.

## General Notes MCP

The bundled MCP definition exposes the upstream search, read, folder, account,
attachment, checklist-state, and diagnostic surface. Although the upstream
server also advertises mutation tools, this plugin keeps them out of its write
workflow because Notes account sync can block their AppleScript calls. It is
loaded only in a fresh agent task after installation.
The exact third-party source, version, integrity, and license are recorded in
[`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md).

Do not bulk-read or export a Notes library unless the user asked for that scope.
Before rewriting an existing note, check for attachments and whether it is
shared; full-body AppleScript updates can remove embedded content and shared
edits are visible to collaborators.

## Call Recordings

Apple's phone and FaceTime call recording store remains strictly read-only.
The plugin maintains only a private, source-local transcript cache for those
recordings.

Transcription is on demand. The `macos:process-recorded-call` skill processes an
explicitly selected call, and the CLI can manually reconcile a bounded batch
when requested. Nothing polls Notes, uploads recordings, files, routes,
summarizes, or acts on a conversation in the background.

## Install

```bash
codex plugin add macos@near
claude plugin install macos@near
```

Version 0.6.1 replaces the former Python/account-AppleScript writer with the
direct UI path and restores the Claude manifest. Existing private cache rows
and transcript artifacts remain intact.

## Call Source CLI

```bash
notes calls list --json
notes calls list --since 2026-06-01
notes calls path A1B2C3D4
notes calls transcript A1B2C3D4
notes calls doctor --json
```

A call can be referenced by its attachment UUID, a unique UUID prefix, or a
contact name. An ambiguous name is an error listing the candidates.

## Transcript Cache

```bash
notes calls transcriptions reconcile --limit 10 --json
notes calls transcriptions retry A1B2C3D4 --json
notes calls transcriptions show A1B2C3D4 --json
notes calls transcriptions status --state completed --limit 100 --json
notes calls transcriptions status --state completed --limit 100 \
  --after-cursor "$CURSOR" --json
```

`status` is a bounded, read-only cache query; it never reads Notes or invokes a
transcriber. Its opaque cursor allows independent consumers to keep their own
checkpoints. Completed items expose the stable UUID, call time and title,
source path, provider/model/format, transcript artifact path and SHA-256, and
completion timestamps.

The cache lives under:

```text
~/Library/Application Support/notes/transcriptions/
```

Each UUID is protected by a process lock. Transcript and plist writes use an
fsynced temporary file plus atomic replacement. Failures retain exponential
retry state; successful items are idempotent across renames and iCloud
rematerialization.

## Provider Order

Apple's transcript is embedded in the call note body as a gzipped protobuf in
`ZICNOTEDATA.ZDATA`. The worker uses non-empty Apple text first. Only when it is
absent does it resolve `elevenlabs` from `PATH` and run Scribe v2 with automatic
call diarization:

```bash
elevenlabs transcribe AUDIO \
  --model scribe_v2 \
  --response-format diarized_text \
  --diarize \
  --out TEMP_PATH
```

It never passes a guessed speaker count and never reaches into an ElevenLabs
plugin cache or version directory.

## Why the Notes Store Is Authoritative

Apple represents one call with a titled parent attachment and a child carrying
the real duration. The attachment pair brackets the wall-clock call window.
Media folders outlive deleted notes, file mtimes are CloudKit sync artifacts,
and the live database is WAL-mode. The CLI therefore snapshots
`NoteStore.sqlite` with its WAL sidecars, opens that snapshot read-only, and
uses the attachment UUID as identity. Globbing `Call with *.m4a` is not safe.

## Requirements and Scope

- Codex desktop with the bundled Computer Use plugin, or Claude on macOS with
  persistent Accessibility and Automation access for the signed Claude host
- Notes.app with at least one configured Notes account
- Full Disk Access for database-backed reads, call recordings, checklist state,
  and note metadata
- Python 3 for the read-only call-recording and transcript-cache CLI
- Node.js 20 or newer for Claude's write argument parser and the pinned Notes
  MCP server
- `elevenlabs` on `PATH`; `ELEVENLABS_API_KEY` is needed only on cache misses

Ordinary note and checklist writes occur only when explicitly requested. The
plugin uses the live Notes UI and never writes `NoteStore.sqlite`, call-recording
notes, attachments, recordings, or Apple transcripts. Call infrastructure
writes only its private transcript cache, receipts, and locks.
Manual semantic processing never sends messages or creates domain records
without the authority of the invoked skill and current task.

## reminders

The Reminders plugin owns Apple Reminders operations for the user's agents.
It uses the external `remindctl` CLI for public EventKit functionality and
AppleScript Accessibility UI scripting for native fields that EventKit omits,
including tags and custom Smart Lists.

The UI path is deterministic macOS automation, not model-driven Computer Use.
It still controls the visible Reminders app, so callers preserve focus, avoid
coordinate clicks, and verify the saved result from the UI-capable surface.

## Retired native app

The deprecated Reminders Clipboard macOS app and its login item were retired on
2026-08-25. This repository now ships only the useful agent plugin. Removing the
app does not delete or modify any Apple Reminders data.

## voice-memos

Read locally materialized Apple Voice Memos by stable UUID, maintain a private
on-demand transcript cache, and run independent source-owned semantic skills.
Before each store read, the plugin launches Voice Memos hidden in the background
with `open -gj` to prompt iCloud and Apple Watch synchronization. It never brings
the app to the foreground or mutates recordings.

## On-demand transcription

The worker prefers a usable transcript embedded by Apple and otherwise invokes
the installed ElevenLabs CLI with `scribe_v2` text output. It keys state by
`ZUNIQUEID`, writes transcript artifacts atomically with SHA-256 provenance,
uses per-item locks and bounded retry state, and never stores secrets in its
cache.

```bash
voice-memos transcriptions baseline --json
voice-memos transcriptions reconcile --limit 10 --json
voice-memos transcriptions status --state completed --limit 100 --json
voice-memos transcriptions show UUID --json
voice-memos transcriptions retry UUID --json
```

Version 0.7.13 restores the bounded hidden-app sync nudge on each store read
while keeping the former transcription LaunchAgent retired. Existing private
cache rows and transcript artifacts remain intact; no process watches or polls
Voice Memos continuously. `retry UUID` is the preferred exact-item path; run
bounded `reconcile` only when a wider manual scan is explicitly requested.

## Scheduled skills

Two skills independently select recordings by their capture time:

- `macos:answer-captured-questions`
- `macos:discuss-health-observations`

Their native schedules contain only the exact skill invocation. An omitted
window defaults to recordings captured during the previous 24 hours. Explicit
windows support replay or wider review, and offset paging remains stateless:

```bash
voice-memos questions scan --json
voice-memos questions scan --since 48h --json

voice-memos health-observations scan --json
voice-memos health-observations scan --since 2026-08-10T12:00:00Z --until 2026-08-12T12:00:00Z --json
```

Selection uses `recorded_at`, never transcript completion time. For a recording
inside the window, a semantic scan reuses a verified cached transcript or
invokes the source-local worker if the transcript is not ready. The same window
may be revisited without a processed cursor.

## Direct reads

```bash
voice-memos list --json
voice-memos path UUID
voice-memos transcript UUID --json
```

Requirements: macOS, Python 3, Full Disk Access for the invoking host, and the
installed ElevenLabs CLI with its API credential in macOS Keychain when Apple
has no usable embedded transcript. Private health-record publication also
follows the resolved repository's own instructions and privacy policy.

## apple-passwords

Use saved credentials without exposing them to the assistant.

## Skills

| Skill | Purpose |
| --- | --- |
| `autofill` | Fill saved logins in Chrome through the official iCloud Passwords extension. Website verification follows the normal authorized login workflow. |
| `credential-authorization` | Fill the Mac login password once, after human approval, into a signed native secure dialog through the bundled `macbook-credential-broker` MCP server. |

Install `macos@near` in Codex or Claude. Run `npm test` to validate the package.

## Credential broker

The broker is deliberately narrower than a password manager. It owns one fixed
alias, `macos-login`, and exposes presence, target inspection, one-time approval
plus fill, and synthetic verification. There is no read, reveal, export, copy,
or unattended-fill operation.

It fills only a native secure field inside a signed allowlisted dialog, rejects
web-page password fields, re-verifies the target after approval, and never
presses Return. The stable helper lives under
`~/Library/Application Support/MacBookCredentialBroker`; its Keychain item uses
service `com.pedroavj.macbook.credential-broker` and is created through a native
secure provisioning dialog, never through chat or a shell argument. These
identities are unchanged from the retired `macbook` plugin, so an existing
provisioned alias keeps working.

`npm test` covers the contract, signature, and MCP approval path. Set
`CREDENTIAL_BROKER_LIVE_TESTS=1` to also run the synthetic Keychain self-test and
the Codex app-server path, which create and delete a temporary Keychain item and
show the broker's own test window.

Newly installed MCP tools become available in fresh Codex or Claude tasks.

## macbook

Diagnostics, local host context, and human-approved native credential fills for
the user's Mac.

"My MacBook is slow" is never one question. Memory and disk fail
independently — the machine can be swapping hard with plenty of free disk, or
dying of memory starvation because the disk filled up. Collapsing them into a
single health check produces a verdict that is right about one thing and
silently wrong about the other.

So this plugin splits them, and each skill says which one it answered.

## Skills

| Skill | Question |
| --- | --- |
| `memory` | What are current RAM pressure, swap, and process-owner measurements? |
| `storage` | What is current APFS headroom and the exact shortfall to the free-space target? |
| `control-host` | What macOS, architecture, ADB, and scrcpy setup is available right now, and what restrictions apply before using iPhone Mirroring? |
| `credential-authorization` | Can a native signed macOS prompt receive one approved Mac login password fill without exposing the secret to the agent? |

The macOS plugin owns live host measurement, not cleanup eligibility. Both diagnostic
skills apply `references/cleanup-eligibility.md`, which decides whether any
measured file, application, or process may appear in a cleanup recommendation.

Unless the user chooses another threshold, storage cleanup plans target 20%
free capacity. That percentage is the literal measurement target, with no
safety buffer, and any separately authorized cleanup verifies the actual result
with `df`.

Storage answers return the target line plus only gate-qualified candidates.
If none qualify, they say so even when the target remains unmet. Logical sizes
remain projections until physical APFS reclaim is verified with `df`.

## Snapshot Script

One read-only script backs both, sectioned by concern:

```bash
./scripts/snapshot.sh memory
./scripts/snapshot.sh storage
./scripts/snapshot.sh all
```

Nothing in it mutates state, kills processes, or triggers macOS Automation
prompts.

## Credential Broker

`credential-authorization` is deliberately narrower than a password manager.
It owns one fixed alias, `macos-login`, and exposes presence, target inspection,
one-time approval plus fill, and synthetic verification. There is no read,
reveal, export, copy, or unattended-fill operation.

The broker fills only a native secure field inside a signed allowlisted dialog.
It rejects web-page password fields, re-verifies the target after approval, and
never presses Return. The stable helper lives under
`~/Library/Application Support/MacBookCredentialBroker`; its Keychain item is
created later through a native secure provisioning dialog, never through chat
or a shell argument.

Newly installed MCP tools become available in fresh Codex or Claude tasks.

## Where They Connect

Swap files share the APFS container with everything else, so free disk is the
hard ceiling on how far swap can grow. On a small-RAM machine, a full disk
lowers the OOM threshold directly — which is why `memory` checks headroom
before blaming an app, and hands off to `storage` when that is the real
constraint.

## Calibration

The snapshot derives RAM, processor count, and APFS capacity from the current
Mac. The skills use proportional pressure and headroom bands, then report the
measured hardware beside the verdict. Operator host baselines belong in private local configuration. The skill
measures the live Mac first and compares prior measurements only when supplied.

Memory diagnosis uses the kernel's categorical pressure level to establish
urgency and aggregates current process-owner trees. The cleanup eligibility
gates decide candidates. Level 0 is not an optimization target for this
Mac's normal workload.

## Install

```bash
claude plugin install macos@near
```

```bash
codex plugin add macos@near
```

Claude installs `elevenlabs@near` (the `elevenlabs` transcription CLI)
and `near@near` as dependencies.
