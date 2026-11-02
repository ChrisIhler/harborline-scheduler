#!/usr/bin/env bash
# Runs the baseline and the four example requests. Workbooks land in out/.
set -u
cd "$(dirname "$0")"
pause() { if [ -t 0 ] && [ "${NOPAUSE:-}" = "" ]; then read -r -p "  Press Enter for the next step..." _; fi; }
python3 -m harborline build;                                                                      pause
python3 -m harborline apply --request-file examples/01_festival.txt      --ops examples/01_festival.ops.json      --name 01_festival;      pause
python3 -m harborline apply --request-file examples/02_new_dock.txt      --ops examples/02_new_dock.ops.json      --name 02_new_dock --save-config; pause
python3 -m harborline apply --request-file examples/03_invented_time.txt --ops examples/03_invented_time.ops.json --name 03_invented_time; pause
python3 -m harborline apply --request-file examples/04_short_fleet.txt   --ops examples/04_short_fleet.ops.json   --name 04_short_fleet
exit 0
