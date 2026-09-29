---
name: reminders
description: Manage Apple Reminders on the user's Mac, including reading, creating, editing, completing, deleting, moving, scheduling, recurring reminders, tags, and custom Smart Lists. Use whenever the user mentions Reminders, reminder lists, remindctl, AppleScript for reminders, tags, Smart Lists, or asks to avoid model-driven Computer Use while changing Reminders.
---

# Manage Apple Reminders

## Choose the narrowest reliable path

1. Use `remindctl` for public EventKit fields: ordinary lists, titles, notes,
   URLs, priority, due dates, alarms, location triggers, recurrence,
   completion, deletion, search, and export.
2. Use direct AppleScript or EventKit when it is more reliable for a specific
   semantic field or when the authorized host differs from `remindctl`.
3. Use AppleScript UI scripting through `System Events` for native Reminders
   features absent from EventKit, especially tags and custom Smart Lists. Read
   [references/accessibility-ui.md](references/accessibility-ui.md) completely
   before taking this path.
4. Use model-driven Computer Use only when the Reminders Accessibility tree is
   unavailable or the named controls cannot be operated deterministically.

AppleScript Accessibility is UI automation, but it is not the Computer Use
tool. Prefer it because it targets named accessibility roles and controls
without screenshots or coordinate guesses.

## Start from live state

- Run `remindctl status --json` before direct work.
- Query the current lists and exact reminder candidates; list names and IDs can
  change. Resolve an existing item before editing to avoid duplicates.
- Preserve list membership, notes, due date, alarm, recurrence, priority, and
  completion state unless the request changes them.
- Interpret dates in the user's current local timezone, not raw UTC output.

Common direct commands:

```sh
remindctl list --json
remindctl all --json
remindctl search "title or purpose" --json
remindctl info ID_PREFIX --json
remindctl add --title "Title" --list "List" --due "YYYY-MM-DD HH:mm" --json
remindctl edit ID_PREFIX --due "YYYY-MM-DD HH:mm" --alarm "YYYY-MM-DD HH:mm" --repeat weekly --json
```

## Drive UI-only fields with AppleScript

- Resolve the bundled preflight script relative to this `SKILL.md`; never run
  an editable source checkout or a version-pinned cache path from memory.
- Run `osascript scripts/reminders-ui-probe.applescript --json`. If Reminders
  is not running and the requested change authorizes opening it, open the app
  and rerun the probe.
- Select the exact reminder by stable ID or deep link before manipulating its
  UI. For Smart Lists, inspect the live New List sheet before setting filters.
- Address menus, sheets, text fields, pop-up buttons, and buttons by
  accessibility role, value, description, or name. Never click coordinates.
- Capture the original frontmost process, restore it after success or failure,
  and close transient sheets on error.
- Do not drive Reminders while the user is actively editing it. Pause instead of
  stealing focus or typing into an uncertain field.

## Verify on the capable surface

- Read back EventKit-supported fields with `remindctl info` or an exact query.
- Verify tags and Smart List definitions through Reminders Accessibility or a
  tag-aware Shortcuts action; EventKit cannot prove those fields persisted.
- For deletion, identify one exact target, use a dry run when available, and
  confirm the intended reminder or list is gone while related items remain.
- Report the final user-visible state and any UI field that could not be
  independently read back.
