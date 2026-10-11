---
name: macos-calendar
description: "Use when operating the macOS Calendar.app via osascript."
version: 1.0.0
platforms: [macos]
metadata:
  hermes:
    tags: [calendar, macos, apple, osascript, 日历]
    category: apple
---

# macOS Calendar (Calendar.app) via osascript

Operate the native macOS Calendar app directly through AppleScript. No third-party CLI needed — works on any Mac.

## Prerequisites

- macOS with Calendar.app
- Terminal has Automation permission for Calendar (first run may prompt)

## Commands (verified working)

### 1. List all calendars

```applescript
osascript -e 'tell application "Calendar" to get name of every calendar'
```

### 2. Query events in next N days (per calendar)

```bash
# Replace 7 with number of days
osascript -e '
tell application "Calendar"
    set output to ""
    repeat with c in calendars
        set calName to name of c
        set startDate to current date
        set endDate to startDate + (7 * days)
        try
            set evs to (every event of c whose start date ≥ startDate and start date ≤ endDate)
            repeat with e in evs
                set output to output & calName & " | " & (summary of e) & " | " & (start date of e as text) & linefeed
            end repeat
        end try
    end repeat
    return output
end tell'
```

### 3. Query events in a specific calendar

```applescript
tell application "Calendar"
    set c to first calendar whose name is "工作"
    set evs to every event of c
    repeat with e in evs
        log (summary of e) & " | " & (start date of e as text) & " | " & (end date of e as text)
    end repeat
end tell
```

### 4. Create an event

```applescript
tell application "Calendar"
    set c to first calendar whose name is "工作"
    set newEvent to make new event at end of c with properties {summary:"会议", start date:(date "2026-09-04 10:00:00"), end date:(date "2026-09-04 11:00:00")}
end tell
```

Note: `date "YYYY-MM-DD HH:MM:SS"` parses in the system locale. For reliable parsing use:
`(current date) + 86400` style offsets, or `set d to (current date) ; set hours of d to 10 ; set minutes of d to 0 ; set seconds of d to 0`.

### 5. Update an event (change title/time)

```applescript
tell application "Calendar"
    set c to first calendar whose name is "工作"
    set evs to (every event of c whose summary contains "会议")
    if (count of evs) > 0 then
        set summary of item 1 of evs to "新的标题"
        set start date of item 1 of evs to (date "2026-09-05 14:00:00")
    end if
end tell
```

### 6. Delete an event

```applescript
tell application "Calendar"
    set c to first calendar whose name is "工作"
    set evs to (every event of c whose summary contains "会议")
    if (count of evs) > 0 then
        delete (item 1 of evs)
    end if
end tell
```

## Pitfalls

- **Date parsing**: `date "..."` uses system locale format. Prefer constructing dates from `current date` or use ISO-ish formats that match locale.
- **Chinese calendar names**: match by `whose name is "工作"` works fine with Chinese names.
- **Permissions**: First access triggers macOS Automation permission dialog for the terminal host app — approve once.
- **All-day events**: have no start time component; filter carefully.
- **Performance**: querying `every event of c` on a huge calendar can be slow; use date-range filters (`whose start date ≥ X and start date ≤ Y`).

## When NOT to use

- Google Calendar → use `google-workspace` skill (gws CLI)
- Outlook/Exchange calendar → use Outlook app automation or its API
- Simple reminders → `apple-reminders` skill (remindctl)
