---
name: messages-writing-samples
description: Read a small, bounded sample of the current user's outgoing SMS, RCS, or iMessage text for explicitly requested writing analysis or a draft grounded in their Messages history. Use the read-only messages samples command, preserve source and authorship uncertainty, and pass only relevant safe evidence to writing:impersonating.
---

# Sample Messages Writing

Messages owns source collection. The active assistant drafts directly with
`writing:impersonating`; no separate model or Claude delegation is required.
Use this source only when the current request authorizes reading the user's
Messages history for the writing objective. A request to draft alone does not
permit sending a message or inspecting unrelated conversations.

## Collect a small source sample

1. Resolve the intended chat from an exact message or chat ID supplied in the
   task, or bounded recent metadata from `messages --json scan`. Use
   `messages --json read MESSAGE_GUID` for an exact known message when needed.
   Do not infer an identity from display-name similarity alone.
2. Prefer an exact chat GUID and a bounded source-time window:

   ```bash
   messages --json samples --chat-id CHAT_GUID --since 30d --limit 30
   ```

   Use an explicit `--until` for repeatable windows. An omitted span means the
   previous 24 hours. `--limit` defaults to 30 and accepts 1–100 candidate rows;
   blank or unsupported attributed bodies can yield fewer text samples. Results
   are ordered newest first. `truncated` means additional candidate rows exist
   inside that exact window, not permission to expand the scope automatically.
3. A global sample without `--chat-id` is available only when authorized and
   useful to the current objective. Avoid unnecessary cross-chat collection.
4. `is_from_me: true` proves that Messages marked the item as sent from the
   account. It does not prove the user personally authored the text. Exclude
   known assistant-authored messages, quoted or copied passages, templates,
   boilerplate, group messages irrelevant to the audience, and ambiguous
   authorship examples. Keep the returned authorship caveat with the evidence.
5. Exclude credentials, one-time codes, account/document identifiers, intimate
   material, health or legal details, and another person's private information.
   Keep only a few relevant, nonsensitive examples and an inferred style brief.

The output includes message ID, sent timestamp, service, exact chat identity,
text, account direction, and the authorship caveat. Keep identifiers and source
text private in the current task; do not print them just to prove collection,
persist a personal style corpus, or add samples to this plugin or Git.

## Draft and report the limit

Use `writing:impersonating` with the current request, immediate reply context,
a compact summary of repeated patterns, and selected safe examples. The target
chat has greater weight than a global baseline. Sparse evidence is a limitation,
not a reason to invent stylistic certainty. If database access or body decoding
is unavailable, state that Messages examples were not verified and continue
only with other evidence already authorized and available.

All commands use the existing read-only database connection. They do not send,
reply, mark read, delete, export attachments, or change Messages. The separate
hygiene `scan` command remains incoming-only and returns metadata without text.
