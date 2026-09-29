---
name: credential-authorization
description: Authorize one-time use of the user's Mac login password from macOS Keychain without exposing it to the agent. Use when a native signed macOS or Chrome dialog requires the Mac login password, when checking or provisioning the fixed macos-login alias, or when verifying the credential broker. Never use for website password fields, CVVs, one-time codes, passkeys, or unattended authentication.
---

# Credential Authorization

Use this plugin's MacBook credential broker for one-time, human-approved fills of the
fixed `macos-login` Keychain alias. The broker may fill a verified native secure
dialog, but it can never return the secret to the model.

## Non-negotiable boundary

- Never request, repeat, transcribe, reveal, export, log, or place the password
  in chat, a tool argument, shell history, an environment variable, a file, the
  clipboard, or a screenshot.
- Never run `security ... -w`, query Keychain data directly, inspect a secure
  field's value, or create an alternate password-reading helper.
- Never treat login failure as permission to reset, replace, or update a
  password.
- Never use this credential in a web-page password field. The broker rejects
  any secure field under an accessibility `AXWebArea`.
- Never press Return, click the confirmation button, or submit the surrounding
  action as part of the fill. Filling and submitting are separate decisions.
- Never store a dynamic CVV, one-time code, passkey response, or another
  short-lived challenge in this broker.

The broker rejects sensitive calls unless its signed executable was launched
directly by the signed Codex or Claude host. Its Keychain item trusts that exact
broker executable, and the broker exposes no read/export tool. A process with
full control of the local user account or the ability to inject code into a
trusted host remains outside this V1 boundary.

## Use a configured credential

1. Make the intended native password dialog visible and focus its secure field.
2. Call `credential_status`. It returns presence only. If `configured` is
   false, stop and use the provisioning flow below; never ask for the value.
3. Call `inspect_credential_target`. Continue only when `supported` is true.
   The target must be a signed allowlisted application, a native dialog or
   sheet, a secure accessibility field, and outside every web area.
4. Explain the exact purpose and surrounding action to the user, including the
   application and window reported by inspection.
5. Call `authorize_and_fill_credential` with:
   - `credential`: `macos-login`
   - `purpose`: a short, non-secret description of the exact action
6. The broker presents its own one-time approval card. Approval is scoped to
   the inspected target and this single call. It rechecks the target after the
   response and aborts if focus, process, window, role, or signature changed.
7. Treat `filled: true` only as proof that the field received the approved
   fill. It is not proof that authentication or the surrounding operation
   succeeded. Review and submit separately only when the user's request
   authorizes that action.

If a target is rejected, preserve the prompt and report the exact app, window,
role, subrole, and rejection reason. Do not weaken the allowlist or fall back to
clipboard, shell, Computer Use text entry, or direct Keychain access.

## Provision the fixed alias

Provisioning is a separate, explicit setup action. It must use the broker's
native secure dialog; do not collect the password in the thread or terminal.

1. Ensure the durable helper exists by running the plugin's
   `scripts/install-credential-broker`. It creates only:
   `~/Library/Application Support/MacBookCredentialBroker/bin/macbook-credential-broker`.
2. Launch that exact helper with `provision macos-login`.
3. Pause while the user connects to the Mac and enters the password twice in the
   native protected fields. Do not inspect, record, or automate those fields.
4. After the dialog reports success, call `credential_status`. Confirm only
   that the alias exists; never verify by reading it.

Updating the same alias uses the same native dialog. The old value is not
returned. Do not delete or replace the item unless the user explicitly asks to
change the stored credential.

## Verify the broker

- Use `test_credential_approval_channel` to prove that the current client can
  display and resume a no-secret MCP approval. It performs no external action.
- Use `run_credential_broker_self_test` before first real provisioning or after
  changing the broker. It creates a random synthetic Keychain item, fills it
  into a broker-owned secure field through the production path, compares it
  internally, clears the field, and deletes the exact temporary item.
- A passed synthetic test does not validate a specific third-party prompt.
  Inspect the real prompt before its first use.
