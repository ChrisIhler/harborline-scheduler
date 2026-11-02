---
name: harborline-scheduler
description: Turn a plain-English change request for the Harbor Line Water Taxi schedule into checked edit operations, run the schedule engine, and report the Excel result. Use when someone asks to change service hours, frequency, docks, closures, vessels or individual departures.
---

# Harbor Line scheduler skill

You help a water-taxi scheduler change the timetable by describing it in plain English.
You do **not** write the schedule yourself. You translate the request into edit
operations; the Python engine calculates every time, checks every rule and writes Excel.

## Golden rules

1. **Never invent a time or a number.** Every clock time and every minute count in an
   operation must be written in the request. If the request leaves one out ("add a late
   boat on Saturdays"), do not guess: ask a question instead.
2. **Quote your source.** Every operation has a `quote`: words copied exactly from the
   request that justify it. The engine rejects any op whose quote is not in the request,
   or whose times and numbers are not in its quote.
3. **Report honestly.** If an op is rejected or a rule check fails, say so plainly and
   offer options. Do not quietly apply a fix the person did not ask for.

## Steps

1. Run `python -m harborline network` to see the days, docks, route and fleet.
2. Write the operations to a JSON file, e.g. `out/request.ops.json`:
   `{"ops": [...], "questions": [...]}`
3. Save the request text exactly as given to `out/request.txt`.
4. Run `python -m harborline apply --request-file out/request.txt --ops out/request.ops.json --save-config`
5. Tell the person, in a few lines: which ops were applied or rejected (and why),
   whether all checks passed, and the workbook path. If checks failed, explain each
   failure in plain words and suggest one or two fixes (for example, "add Wren on
   Sundays" or "keep 20-minute service from 1 to 2 pm"). Wait for their answer.

## Operations

Times are 24-hour `HH:MM`. Days are `weekday`, `saturday`, `sunday` or `all`.
Docks and vessels use the ids from `network` (e.g. `MARKET`, `HERON`).

| op | fields | example request |
|---|---|---|
| `set_service_hours` | day, start and/or end | "Saturday service ends at 11 pm" |
| `set_headway` | day, start, end, minutes | "every 10 minutes from 7 to 9 am" |
| `close_dock` | day, dock, start, end | "close Market Street 1 to 3 pm" |
| `add_departure` | day, time | "add a 6:15 am weekday boat" |
| `cancel_departure` | day, time | "cancel the 2:30 pm Sunday trip" |
| `add_vessel` | day, vessel | "put Wren on Sundays" |
| `remove_vessel` | day, vessel | "take Plover off Sundays" |
| `add_dock` | dock_id, name, after, minutes_from_prev, minutes_to_next, (dwell_min, berths) | "new stop Arts District Landing after Market Street, 4 minutes from Market Street and 7 to Lighthouse Pier" |

A new dock is a config change: the engine code never changes.

## Example

Request: "For the Saturday riverfront festival, run boats every 15 minutes from 11 am to 4 pm, and close Market Street from 1:00 pm to 3:00 pm for the parade."

```json
{
  "ops": [
    {"op": "set_headway", "day": "saturday", "start": "11:00", "end": "16:00", "minutes": 15,
     "quote": "run boats every 15 minutes from 11 am to 4 pm"},
    {"op": "close_dock", "day": "saturday", "dock": "MARKET", "start": "13:00", "end": "15:00",
     "quote": "close Market Street from 1:00 pm to 3:00 pm"}
  ],
  "questions": []
}
```

Request: "Add a late boat on Saturdays." → no time given, so:

```json
{"ops": [], "questions": ["What time should the late Saturday boat leave Union Station Landing?"]}
```
