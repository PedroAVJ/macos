on booleanText(flagValue)
  if flagValue then return "true"
  return "false"
end booleanText

on run argumentsList
  set jsonMode to argumentsList contains "--json"
  set accessibilityEnabled to false
  set remindersRunning to false
  set newListAvailable to false
  set createSmartListAvailable to false
  set tagsMenuAvailable to false

  tell application "System Events"
    set accessibilityEnabled to UI elements enabled
    set remindersRunning to exists application process "Reminders"
    if accessibilityEnabled and remindersRunning then
      tell application process "Reminders"
        try
          set newListAvailable to exists menu item "New List" of menu "File" of menu bar 1
        end try
        try
          set createSmartListAvailable to exists menu item "Create Smart List" of menu "File" of menu bar 1
        end try
        try
          set tagsMenuAvailable to exists menu item "Tags" of menu "Edit" of menu bar 1
        end try
      end tell
    end if
  end tell

  if jsonMode then
    return "{" & ¬
      "\"accessibility\":" & booleanText(accessibilityEnabled) & "," & ¬
      "\"remindersRunning\":" & booleanText(remindersRunning) & "," & ¬
      "\"newListMenu\":" & booleanText(newListAvailable) & "," & ¬
      "\"createSmartListMenu\":" & booleanText(createSmartListAvailable) & "," & ¬
      "\"tagsMenu\":" & booleanText(tagsMenuAvailable) & "}"
  end if

  return "Accessibility: " & booleanText(accessibilityEnabled) & linefeed & ¬
    "Reminders running: " & booleanText(remindersRunning) & linefeed & ¬
    "New List menu: " & booleanText(newListAvailable) & linefeed & ¬
    "Create Smart List menu: " & booleanText(createSmartListAvailable) & linefeed & ¬
    "Tags menu: " & booleanText(tagsMenuAvailable)
end run
