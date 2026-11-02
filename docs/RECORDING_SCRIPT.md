# 2–3 minute screen recording script

Setup: terminal open in the repo folder, font large, `out/` cleared. Excel (or Numbers) ready.
Run `python -m harborline build` once beforehand so nothing is slow on camera.

**0:00 – 0:15 · What it is**
"This is a working prototype of an AI scheduling assistant for a small water-taxi fleet.
The network, Harbor Line, is fictional. A scheduler types a change in plain English,
and the system rebuilds the schedule and checks it before anyone publishes it."

**0:15 – 0:55 · A normal request**
Run: `python -m harborline apply --request-file examples/01_festival.txt --ops examples/01_festival.ops.json --name 01_festival`
(Or, in Claude Code, paste the festival request and let the skill run it.)
"Claude turns the request into two edits. Each one quotes the exact words it came from.
Then Python, not the AI, calculates every time and checks twelve rules: crew breaks,
dock conflicts, double-booked boats, closed docks, overnight berths. All twelve pass."

**0:55 – 1:25 · Open the workbook**
Open `out/01_festival.xlsx`, show the Saturday tab, scroll to 1 PM.
"Fifteen-minute service starting at 11, and Market Street is marked closed during the parade.
There's a tab per service day, a vessel plan, the rule checks, and a Changes tab that
records what was asked and what was applied."

**1:25 – 1:50 · The AI can't invent a time**
Run the `03_invented_time` example.
"Here I planted a mistake. The request says 6 am; the edit says 5:45. It's rejected before
it touches the schedule. That's the safeguard against an AI making up a time."

**1:50 – 2:20 · Real problems get flagged**
Run the `04_short_fleet` example.
"Taking one boat off Sunday looks harmless, but two trips can't be covered without breaking
the crew-break rule. The system says so in plain words instead of quietly publishing a
broken schedule."

**2:20 – 2:40 · Close**
"A new dock is just a config change; the code doesn't change. There are 25 automated tests,
including planted errors. This is a prototype; a real build would start from your
actual routes, crew rules and current spreadsheets. That's what the scoping document is for."
