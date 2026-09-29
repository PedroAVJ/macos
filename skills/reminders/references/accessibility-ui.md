# AppleScript Accessibility UI path

Use this path only for a requested Reminders change that public EventKit does
not expose. It controls the visible app through `System Events`, so preserve
focus and fail closed when the target is ambiguous.

## Preflight

Run the bundled read-only probe from this skill directory:

```sh
osascript scripts/reminders-ui-probe.applescript --json
```

Require `accessibility=true`. If `remindersRunning=false`, open Reminders only
when the current request authorizes the UI operation, then rerun the probe.

## Safe interaction pattern

1. Record the name of the frontmost process.
2. Resolve the exact reminder through `remindctl` before touching the UI. Use
   `remindctl open ID_PREFIX` to select it when an item is the target.
3. Activate Reminders and wait only long enough for the named window or sheet.
4. Use `System Events` and named AX elements. Query `entire contents` when the
   control is nested instead of assuming a fixed hierarchy.
5. On any error, press Escape only for a transient sheet opened by the script,
   restore the original frontmost process, and stop without guessing.
6. Save only after every intended field is resolved. Reopen or inspect the
   resulting object and verify it from a tag-aware/UI-capable surface.

Never use coordinate clicks, raw keystrokes before focus is proven, or a fuzzy
title match when a stable reminder ID is available.

## Current named surfaces

Re-inspect these before every mutation because macOS updates can change them.
The current Reminders Accessibility tree exposes:

- `File` > `New List`, with a sheet containing a Name text field and a List
  Type pop-up whose initial value is `Standard`;
- choosing `Smart List` reveals a match pop-up (`all` or `any`), a `Filters`
  scroll area, a filter-type pop-up such as `Tags`, and its operator/value
  controls;
- `File` > `Create Smart List` and `Convert to Smart List` in applicable
  contexts; and
- `Edit` > `Tags`, whose selected-reminder submenu includes `Add Tag…` and
  `Clear Tags` when available.

Treat menu availability as contextual. If an expected control is absent,
inspect the active window and selection rather than switching to Computer Use.

## Focus restoration skeleton

```applescript
tell application "System Events"
  set originalName to name of first application process whose frontmost is true
end tell

try
  tell application "Reminders" to activate
  tell application "System Events" to tell process "Reminders"
    -- Resolve and operate named accessibility elements here.
  end tell
on error errorMessage number errorNumber
  tell application "System Events" to key code 53
  tell application "System Events" to set frontmost of process originalName to true
  error errorMessage number errorNumber
end try

tell application "System Events" to set frontmost of process originalName to true
```

Only send Escape when this script opened the active transient sheet. Do not
dismiss unrelated user UI.
