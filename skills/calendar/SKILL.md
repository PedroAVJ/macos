---
name: calendar
description: Read and manage Apple Calendar.app on macOS through bundled deterministic AppleScript commands. Use for Apple Calendar calendars, event lookup, event creation or editing, recurrence, or exact event deletion without visual automation.
---

# Apple Calendar

Use the bundled scripts from this skill's `scripts/` directory. They address
Calendar.app directly through AppleScript; they do not need Computer Use.

## Commands

| Operation | Command |
| --- | --- |
| List calendars | `scripts/cal-list.sh` |
| List events | `scripts/cal-events.sh [days_ahead] [calendar_name]` |
| Read exact event | `scripts/cal-read.sh EVENT_UID [calendar_name]` |
| Search events | `scripts/cal-search.sh QUERY [days_ahead] [calendar_name]` |
| Create event | `scripts/cal-create.sh CALENDAR SUMMARY START END [location] [description] [allday] [recurrence]` |
| Update event | `scripts/cal-update.sh EVENT_UID [--calendar NAME] [--summary TEXT] [--start DATE] [--end DATE] [--location TEXT] [--description TEXT] [--allday true/false] [--recurrence RRULE]` |
| Delete event | `scripts/cal-delete.sh EVENT_UID [calendar_name]` |

Resolve the skill directory from the installed plugin rather than assuming a
developer checkout path.

## Dates and Recurrence

- Timed values use `YYYY-MM-DD HH:MM` in the Mac's local time zone.
- All-day values use `YYYY-MM-DD` and pass `true` as the all-day argument.
- Recurrence uses the Calendar AppleScript recurrence string, such as
  `FREQ=WEEKLY;BYDAY=MO,WE,FR`.
- Calendar names are case-sensitive, and read-only calendars cannot be changed.

## Read and Write Contract

Before creating an event:

1. resolve the intended writable calendar;
2. search the relevant date range for a duplicate;
3. preserve the user's exact time zone, all-day meaning, and recurrence scope.

The user's exact request to create or update an event is authorization for that
event. If the calendar, time, duration, or recurrence would require a material
guess, disclose the assumption before writing.

After every create or update, read the returned UID back and verify the
calendar, summary, start, end, all-day state, location, and recurrence. Do not
report completion from the write command alone.

Deletion is destructive. Resolve and read the exact UID first. The bundled
delete command removes the matching event or recurring series; it does not
select one occurrence. If the requested recurrence scope is ambiguous, stop
before deletion.

## Output

Event lists and searches return:

```text
UID | Summary | Start | End or AllDay | Location | Calendar
```

Use the UID for every subsequent read, update, or deletion. A title alone is
not an exact event identity.
