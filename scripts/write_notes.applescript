use scripting additions

on run argv
    if (count of argv) < 3 then error "The Notes UI writer received an incomplete command" number 2

    set operationName to item 1 of argv
    set noteTitle to item 2 of argv
    set previousProcessName to my frontmost_process_name()

    try
        if operationName is "create" then
            set noteBody to item 3 of argv
            my create_plain_note(noteTitle, noteBody)
        else if operationName is "checklist" then
            set itemTexts to items 3 thru -1 of argv
            my create_checklist_note(noteTitle, itemTexts)
        else
            error "Unknown Notes UI writer operation: " & operationName number 2
        end if

        my restore_focus(previousProcessName)
        return "OK"
    on error errorMessage number errorNumber
        my restore_focus(previousProcessName)
        if errorNumber is -25211 or errorNumber is -1743 then
            error "macOS denied Notes UI automation to the process that launched this command. Grant Accessibility and Automation access to that host once, then retry." number errorNumber
        end if
        error errorMessage number errorNumber
    end try
end run

on create_plain_note(noteTitle, noteBody)
    set editorElement to my create_empty_note()
    my insert_text(editorElement, noteTitle)

    if noteBody is not "" then
        my press_return()
        set editorElement to my wait_for_editor(false)
        my insert_text(editorElement, noteBody)
    end if

    set editorElement to my wait_for_editor(false)
    set currentText to my editor_text(editorElement)
    if currentText does not start with noteTitle then error "Notes did not retain the requested title" number 3
    if noteBody is not "" and currentText does not contain noteBody then error "Notes did not retain the requested body" number 3
end create_plain_note

on create_checklist_note(noteTitle, itemTexts)
    if (count of itemTexts) is 0 then error "A checklist requires at least one item" number 2

    set editorElement to my create_empty_note()
    my insert_text(editorElement, noteTitle)
    my press_return()

    set editorElement to my wait_for_editor(false)
    set actionNames to my editor_action_names(editorElement)
    if actionNames does not contain "ICMacTextViewAccessibilityActionMakeTodo" then
        error "Notes did not expose its native checklist action" number 3
    end if
    my perform_editor_action(editorElement, "ICMacTextViewAccessibilityActionMakeTodo")

    repeat with itemIndex from 1 to count of itemTexts
        set editorElement to my wait_for_editor(false)
        my insert_text(editorElement, item itemIndex of itemTexts as text)
        if itemIndex is less than (count of itemTexts) then my press_return()
    end repeat

    set editorElement to my wait_for_editor(false)
    set actionNames to my editor_action_names(editorElement)
    if actionNames contains "ICMacTextViewAccessibilityActionMakeTodo" then
        error "Notes did not retain native checklist formatting" number 3
    end if

    set currentText to my editor_text(editorElement)
    if currentText does not start with noteTitle then error "Notes did not retain the requested title" number 3
    repeat with itemText in itemTexts
        if currentText does not contain (itemText as text) then
            error "Notes did not retain every requested checklist item" number 3
        end if
    end repeat
end create_checklist_note

on create_empty_note()
    do shell script "/usr/bin/open -a /System/Applications/Notes.app"

    tell application "System Events"
        if UI elements enabled is false then
            error "Accessibility access is required for Notes UI automation" number -25211
        end if

        repeat 100 times
            if exists application process "Notes" then exit repeat
            delay 0.05
        end repeat
        if not (exists application process "Notes") then error "Notes.app did not launch" number 3

        tell application process "Notes"
            set frontmost to true
            set targetWindow to my wait_for_standard_window()
            try
                perform action "AXRaise" of targetWindow
            end try
            key code 45 using {command down}
        end tell
    end tell

    delay 0.2
    return my wait_for_editor(false)
end create_empty_note

on wait_for_standard_window()
    tell application "System Events"
        tell application process "Notes"
            repeat 100 times
                try
                    return first window whose role description is "standard window"
                end try
                delay 0.05
            end repeat
        end tell
    end tell
    error "Notes did not expose its main window" number 3
end wait_for_standard_window

on wait_for_editor(requireEmpty)
    repeat 120 times
        set editorElement to my find_editor()
        if editorElement is not missing value then
            if requireEmpty is false then return editorElement
            try
                if ((value of editorElement) as text) is "" then return editorElement
            end try
        end if
        delay 0.05
    end repeat
    if requireEmpty then error "Notes did not create a new empty note" number 3
    error "Notes did not expose its note editor" number 3
end wait_for_editor

on find_editor()
    tell application "System Events"
        tell application process "Notes"
            try
                set targetWindow to first window whose role description is "standard window"
                set splitRoot to splitter group 1 of targetWindow
                repeat with candidateScroll in scroll areas of splitRoot
                    try
                        if (value of attribute "AXIdentifier" of candidateScroll) is "Note Body Scroll View" then
                            set editorElement to text area 1 of candidateScroll
                            if (value of attribute "AXIdentifier" of editorElement) is "Note Body Text View" then
                                set value of attribute "AXFocused" of editorElement to true
                                return editorElement
                            end if
                        end if
                    end try
                end repeat
            end try
        end tell
    end tell
    return missing value
end find_editor

on insert_text(editorElement, insertedText)
    tell application "System Events"
        tell application process "Notes"
            set value of attribute "AXFocused" of editorElement to true
            set value of attribute "AXSelectedText" of editorElement to insertedText
        end tell
    end tell
end insert_text

on editor_text(editorElement)
    tell application "System Events"
        tell application process "Notes" to return (value of editorElement) as text
    end tell
end editor_text

on editor_action_names(editorElement)
    tell application "System Events"
        tell application process "Notes" to return name of actions of editorElement
    end tell
end editor_action_names

on perform_editor_action(editorElement, actionName)
    tell application "System Events"
        tell application process "Notes" to perform action actionName of editorElement
    end tell
end perform_editor_action

on press_return()
    tell application "System Events"
        tell application process "Notes" to key code 36
    end tell
end press_return

on frontmost_process_name()
    tell application "System Events"
        try
            return name of first application process whose frontmost is true
        on error
            return ""
        end try
    end tell
end frontmost_process_name

on restore_focus(processName)
    if processName is "" or processName is "Notes" then return
    tell application "System Events"
        try
            if exists application process processName then
                set frontmost of application process processName to true
            end if
        end try
    end tell
end restore_focus
