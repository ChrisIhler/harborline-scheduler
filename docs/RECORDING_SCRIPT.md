# 2–3 minute walkthrough: recorded on the live web page

Live page: https://harborline-scheduler.ihlerconsulting.workers.dev

## Before you hit record
- Open the page in Chrome and wait until the green "All 12 checks pass" banner shows (about 10–20 seconds the first time).
- Zoom the browser to about 110% so text is readable in the video.
- Have Excel or Numbers ready to open a downloaded file.
- Keep this script on a second screen or printed. Speak naturally; the lines are a guide, not a teleprompter.
- The live "Ask Claude" box allows 10 requests per visitor per day, so do a practice run but don't burn through them.

## The recording

**0:00 – 0:15 · What this is** *(page at the top)*
"This is a working prototype of an AI scheduling assistant for a small water-taxi fleet. The network, Harbor Line, is fictional. A scheduler asks for a change in plain English, and the system rebuilds the timetable and checks it before anyone publishes it."
*Point at the row of steps under the title: Request → Claude proposes edits → Grounding check → Engine → 12 rule checks → Excel.*

**0:15 – 0:55 · A normal request, live** *(step 1 box)*
Click into the request box, clear it, and type:
> Close Riverwalk Plaza on Sunday from 2 pm to 4 pm

Click **Ask Claude to propose edits**.
"Claude doesn't write the timetable. It proposes an edit, and every edit has to quote the words it came from."
*Point at step 2, the proposed edit, then at step 3, the grounding check, showing APPLIED and the quote.*
"Then Python, not the AI, recalculates every time and checks twelve operating rules: crew breaks, dock conflicts, double-booked boats, closed docks, overnight berths. All twelve pass."
*Click the **Sunday** tab in the timetable and scroll to about 2 PM.* "Riverwalk is marked closed for exactly those two hours."

**0:55 – 1:20 · The AI can't guess a time** *(step 1 box)*
Type:
> Add a late boat on Saturdays.

Click **Ask Claude**.
"No time was given, so Claude doesn't make one up. It asks a question instead." *Point at the yellow question.*

**1:20 – 1:45 · Even if it tried, code stops it** *(examples row)*
Click **Planted invented time**.
"Here I planted a mistake on purpose. The request says 6 am, but the edit says 5:45. The grounding check rejects it before it touches the schedule." *Point at the red REJECTED line and its reason.*

**1:45 – 2:10 · Real problems get flagged, not hidden**
Click **Boat out of service**.
"Taking one boat off Sunday looks harmless. But two trips can't be covered without breaking the crew-break rule, so the system says 'not ready to publish' and shows exactly which trips."
*Point at the red R2 line, then the Sunday tab rows marked NONE.*

**2:10 – 2:25 · The Excel output**
Click **Festival Saturday**, then **Download Excel**, and open the file.
"The output is a workbook in house format: one tab per service day, plus the rule checks and a log of every change and the words it came from."
*Flip through Saturday, Checks and Changes tabs.*

**2:25 – 2:45 · Close** *(back on the page)*
"Adding a dock is a configuration change; the code doesn't change. There are 25 automated tests, including planted errors, and the code is public on GitHub. This is a prototype. A real build would start from your actual routes, crew rules and current spreadsheets, and that's what the scoping document is for."

## After recording
- Trim the start and end, and cut any long loading pauses.
- Upload to the Ihler Consulting YouTube channel as **Unlisted**.
- Paste the link into the proposal draft where it says [VIDEO LINK].
