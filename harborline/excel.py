"""Write the schedule workbook: one tab per service day, plus Vessels, Checks and Changes."""

from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import config as C
from .checks import CheckResult
from .engine import DaySchedule
from .ops import OpResult
from .timeutil import to_12h

NAVY = "1F3A5F"
PASS_FILL = PatternFill("solid", fgColor="D9F2E3")
FAIL_FILL = PatternFill("solid", fgColor="F8D7DA")
HEAD_FILL = PatternFill("solid", fgColor=NAVY)
BAND_FILL = PatternFill("solid", fgColor="F3F6FA")
ADDED_FILL = PatternFill("solid", fgColor="FFF4CC")
HEAD_FONT = Font(bold=True, color="FFFFFF")
THIN = Border(bottom=Side(style="thin", color="D0D7E2"))


def _header(ws, row: int, values: list[str]) -> None:
    for i, v in enumerate(values, 1):
        c = ws.cell(row=row, column=i, value=v)
        c.fill, c.font = HEAD_FILL, HEAD_FONT
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 48


def _widths(ws, widths: list[int]) -> None:
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _print_setup(ws) -> None:
    ws.page_setup.orientation = "landscape"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0


def _title(ws, text: str, sub: str) -> None:
    _print_setup(ws)
    ws["A1"] = text
    ws["A1"].font = Font(bold=True, size=14, color=NAVY)
    ws["A2"] = sub
    ws["A2"].font = Font(italic=True, color="666666")


def write(path: str, cfg: dict, schedules: dict[str, DaySchedule],
          results: list[CheckResult], changes: list[OpResult] | None = None,
          request: str | None = None) -> None:
    wb = Workbook()
    wb.remove(wb.active)
    name = cfg["network"]["name"]
    route = cfg["route"]
    sequence = route + route[-2::-1]
    dock_names = {d["id"]: d["name"] for d in cfg["docks"]}
    ok = all(r.passed for r in results)
    status = "ALL CHECKS PASS" if ok else "CHECKS FAILED - see the Checks tab"

    # One tab per service day ------------------------------------------------
    for day, sched in schedules.items():
        sd = cfg["service_days"][day]
        ws = wb.create_sheet(day.capitalize())
        _title(ws, f"{name} - {day.capitalize()} schedule",
               f"Service {to_12h(C.to_min(sd['start']))} to {to_12h(C.to_min(sd['end']))} - "
               f"{len(sched.trips)} round trips - {status}")
        heads = ["Trip", "Vessel"]
        for i, d in enumerate(sequence):
            label = dock_names[d]
            if i == 0:
                label += "\ndepart"
            elif i == len(sequence) - 1:
                label += "\narrive"
            elif i == len(route) - 1:
                label += "\narrive / depart"
            heads.append(label)
        _header(ws, 4, heads)
        for r, t in enumerate(sorted(sched.trips, key=lambda t: t.depart), start=5):
            row = [t.trip_no, t.vessel or "UNASSIGNED"]
            for i, s in enumerate(t.stops):
                if s.closed:
                    row.append("closed")
                elif i == 0:
                    row.append(to_12h(s.depart))
                elif i == len(t.stops) - 1:
                    row.append(to_12h(s.arrive))
                elif i == len(route) - 1:
                    row.append(f"{to_12h(s.arrive)} / {to_12h(s.depart)}")
                else:
                    row.append(to_12h(s.depart))
            for c, v in enumerate(row, 1):
                cell = ws.cell(row=r, column=c, value=v)
                cell.alignment = Alignment(horizontal="center")
                cell.border = THIN
                if r % 2 == 0:
                    cell.fill = BAND_FILL
                if t.source == "added":
                    cell.fill = ADDED_FILL
                if v == "UNASSIGNED":
                    cell.fill = FAIL_FILL
                    cell.font = Font(bold=True, color="9C0006")
                if v == "closed":
                    cell.font = Font(italic=True, color="9C0006")
        _widths(ws, [7, 13] + [17] * len(sequence))
        ws.freeze_panes = "C5"

    # Vessels ----------------------------------------------------------------
    ws = wb.create_sheet("Vessels")
    _title(ws, "Vessel plan", "Trips, first departure, last return and sailing hours per vessel per day")
    _header(ws, 4, ["Day", "Vessel", "Trips", "First departure", "Last return", "Sailing hours"])
    r = 5
    for day, sched in schedules.items():
        for v in cfg["service_days"][day]["vessels"]:
            vt = sorted([t for t in sched.trips if t.vessel == v], key=lambda t: t.depart)
            hours = sum(t.end - t.depart for t in vt) / 60
            vals = [day.capitalize(), v, len(vt),
                    to_12h(vt[0].depart) if vt else "-", to_12h(vt[-1].end) if vt else "-",
                    round(hours, 1)]
            for c, val in enumerate(vals, 1):
                cell = ws.cell(row=r, column=c, value=val)
                cell.border = THIN
                cell.alignment = Alignment(horizontal="center")
            r += 1
    _widths(ws, [12, 12, 8, 16, 14, 14])

    # Checks -----------------------------------------------------------------
    ws = wb.create_sheet("Checks")
    _title(ws, "Rule checks", status)
    _header(ws, 4, ["Rule", "Description", "Result", "Problems", "Details"])
    r = 5
    for res in results:
        vals = [res.rule_id, res.rule, "PASS" if res.passed else "FAIL", len(res.problems),
                "\n".join(res.problems[:12]) + (f"\n... and {len(res.problems) - 12} more"
                                                 if len(res.problems) > 12 else "")]
        for c, val in enumerate(vals, 1):
            cell = ws.cell(row=r, column=c, value=val)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = THIN
        ws.cell(row=r, column=4).alignment = Alignment(horizontal="center", vertical="top")
        ws.cell(row=r, column=3).fill = PASS_FILL if res.passed else FAIL_FILL
        ws.cell(row=r, column=3).font = Font(bold=True, color="1E7B45" if res.passed else "9C0006")
        r += 1
    _widths(ws, [7, 58, 9, 10, 75])

    # Changes ----------------------------------------------------------------
    ws = wb.create_sheet("Changes")
    _title(ws, "Requested changes", "Every edit, the words it came from, and whether it passed the grounding check")
    ws["A3"] = f"Request: {request}" if request else "Request: (none - baseline schedule)"
    ws["A3"].alignment = Alignment(wrap_text=True)
    ws.merge_cells("A3:E3")
    ws.row_dimensions[3].height = 45
    _header(ws, 5, ["#", "Operation", "Quoted from the request", "Status", "Reason"])
    r = 6
    for i, res in enumerate(changes or [], 1):
        op = {k: v for k, v in res.op.items() if k not in ("op", "quote")}
        desc = res.op.get("op", "?") + " " + ", ".join(f"{k}={v}" for k, v in op.items())
        vals = [i, desc, res.op.get("quote", ""), "APPLIED" if res.applied else "REJECTED", res.reason]
        for c, val in enumerate(vals, 1):
            cell = ws.cell(row=r, column=c, value=val)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = THIN
        ws.cell(row=r, column=4).fill = PASS_FILL if res.applied else FAIL_FILL
        r += 1
    _widths(ws, [5, 48, 48, 12, 60])

    wb.save(path)
