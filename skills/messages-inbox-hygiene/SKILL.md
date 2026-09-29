---
name: messages-inbox-hygiene
description: "Review incoming macOS Messages in a bounded source-time window for unwanted SMS, RCS, and iMessage candidates; distinguish legitimate source opt-out opportunities, repeated unwanted contact, deception, and scams from wanted messages without changing Messages."
---

# Review Messages Hygiene

Own the source workflow completely. This is a read-only review, not a Messages cleanup executor. Read `../../references/attention-policy.md`; its untrusted-input and zero-source-mutation rules are mandatory.

## Open the bounded source window

1. If the user supplies exact Messages IDs, process only those IDs. Otherwise run `messages --json scan` with an explicit caller-supplied `--since` and optional `--until`; when no span is supplied, let the CLI use the previous 24 hours ending at invocation time. Never interpret an omitted span as all history.
2. If `count` is zero, finish quietly. If `truncated` is true, report the exact window as incomplete rather than silently widening it.
3. Process only the returned IDs. The scan is stateless and metadata-only; replaying the same source-time window intentionally returns the same Messages records.
4. Run `messages --json read MESSAGE_ID` only for returned candidates. Use `messages --json context MESSAGE_ID --before 3 --after 3` only when bounded conversational evidence is necessary. Never inspect an attachment or follow a link.

## Evaluate candidates

Preserve source kind, stable ID, service, resolved sender label, received time, and the minimum body or repetition evidence needed. Classify each item using the policy outcomes. In particular:

- prefer `source opt-out candidate` for legitimate recurring bulk messages where an official sender/carrier/account preference may exist;
- use `block candidate` for repeated unwanted contact with no apparent future value;
- use `report candidate` for deceptive identity, phishing, or obvious scams;
- keep receipts, delivery updates, authentication codes, carrier-service state, government notices, and wanted conversations unless concrete evidence supports another verdict; and
- use `uncertain` when identity or consent cannot be grounded safely.

Do not treat frequency, unread state, Apple’s spam flag, short-code delivery, or an in-message STOP/BAJA instruction as sufficient proof by itself.

## Return review, not side effects

Return only source opt-out, block, report, or consequential uncertain results. Finish keep and no-action items silently. Combine related candidates and give the resolved sender label, source pointer, verdict, short reason, and recommended manual action.

Never reply, send an opt-out command, block, report, delete, mark read or unread, open a link, change notifications, or change a chat, carrier, sender, or account. A later explicit source change is a separate interactive action.
