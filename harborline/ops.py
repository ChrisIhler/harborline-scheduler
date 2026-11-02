"""Edit operations: the ONLY way a request changes the schedule.

The language model (or a person) proposes operations as JSON. Each one must
carry a `quote`: the exact words from the request that justify it. Before an
operation touches the config, the grounding check confirms that:

  1. the quote really appears in the request, word for word;
  2. every clock time in the operation is written in that quote;
  3. every minute count in the operation is written in that quote;
  4. every day, dock and vessel it names exists in the config.

An operation that fails any test is rejected and never applied. That is how
the system refuses times the model made up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import config as C
from .timeutil import numbers_in_text, times_in_text, to_hhmm, to_min

DAYS = {"weekday", "saturday", "sunday", "all"}

# op name -> (required fields, clock-time fields, minute-count fields)
SCHEMA: dict[str, tuple[set[str], set[str], set[str]]] = {
    "set_service_hours": ({"day"}, {"start", "end"}, set()),
    "set_headway":       ({"day", "start", "end", "minutes"}, {"start", "end"}, {"minutes"}),
    "close_dock":        ({"day", "dock", "start", "end"}, {"start", "end"}, set()),
    "add_departure":     ({"day", "time"}, {"time"}, set()),
    "cancel_departure":  ({"day", "time"}, {"time"}, set()),
    "add_vessel":        ({"day", "vessel"}, set(), set()),
    "remove_vessel":     ({"day", "vessel"}, set(), set()),
    "add_dock":          ({"dock_id", "name", "after", "minutes_from_prev", "minutes_to_next"},
                          set(), {"minutes_from_prev", "minutes_to_next", "dwell_min", "berths"}),
}


@dataclass
class OpResult:
    op: dict
    applied: bool
    reason: str = ""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _days(cfg: dict, day: str) -> list[str]:
    return list(cfg["service_days"]) if day == "all" else [day]


def grounding_errors(op: dict, request: str, cfg: dict) -> list[str]:
    """Return every reason this op is not supported by the request (empty = OK)."""
    errs: list[str] = []
    name = op.get("op")
    if name not in SCHEMA:
        return [f"unknown operation {name!r}"]
    required, time_fields, minute_fields = SCHEMA[name]

    quote = str(op.get("quote", ""))
    if not quote.strip():
        return ["no quote from the request"]
    if _norm(quote) not in _norm(request):
        errs.append(f"quote {quote!r} is not in the request")

    for f in required:
        if op.get(f) in (None, ""):
            errs.append(f"missing '{f}'")

    written_times = times_in_text(quote)
    for f in time_fields:
        if op.get(f) in (None, ""):
            continue
        try:
            t = to_min(op[f])
        except ValueError as e:
            errs.append(str(e))
            continue
        if t not in written_times:
            errs.append(f"{f}={op[f]} is not a time written in the quote")

    written_numbers = numbers_in_text(quote)
    for f in minute_fields:
        if op.get(f) in (None, ""):
            continue
        try:
            n = int(op[f])
        except (TypeError, ValueError):
            errs.append(f"{f} must be a whole number of minutes")
            continue
        if n not in written_numbers:
            errs.append(f"{f}={n} is not a number written in the quote")

    if "day" in required and op.get("day") not in DAYS:
        errs.append(f"day must be one of {sorted(DAYS)}")
    elif "day" in required and op["day"] != "all" and op["day"] not in cfg["service_days"]:
        errs.append(f"no service day {op['day']!r}")

    if name == "close_dock":
        route = cfg["route"]
        if op.get("dock") not in C.dock_ids(cfg):
            errs.append(f"unknown dock {op.get('dock')!r}")
        elif op["dock"] in (route[0], route[-1]):
            errs.append("terminals cannot be closed with close_dock; change the route instead")
    if name in ("add_vessel", "remove_vessel") and op.get("vessel") not in C.fleet_ids(cfg):
        errs.append(f"unknown vessel {op.get('vessel')!r}")
    if name == "add_dock":
        if op.get("dock_id") in C.dock_ids(cfg):
            errs.append(f"dock {op.get('dock_id')!r} already exists")
        if op.get("after") not in cfg["route"][:-1]:
            errs.append(f"'after' must be a route dock that is not the last one")
        if op.get("name") and _norm(op["name"]) not in _norm(quote):
            errs.append(f"dock name {op['name']!r} is not in the quote")
    if name in ("set_service_hours",) and not (op.get("start") or op.get("end")):
        errs.append("set_service_hours needs a start or an end")
    for a, b in (("start", "end"),):
        if a in time_fields and op.get(a) and op.get(b):
            try:
                if to_min(op[a]) >= to_min(op[b]):
                    errs.append("start must be before end")
            except ValueError:
                pass
    return errs


# ---------------------------------------------------------------- applying

def _set_headway(sd: dict, start: int, end: int, minutes: int) -> None:
    kept = []
    for p in sd["headways"]:
        ps, pe = to_min(p["start"]), to_min(p["end"])
        if pe <= start or ps >= end:
            kept.append(p)
            continue
        if ps < start:
            kept.append({"start": p["start"], "end": to_hhmm(start), "minutes": p["minutes"]})
        if pe > end:
            kept.append({"start": to_hhmm(end), "end": p["end"], "minutes": p["minutes"]})
    kept.append({"start": to_hhmm(start), "end": to_hhmm(end), "minutes": int(minutes)})
    sd["headways"] = sorted(kept, key=lambda p: to_min(p["start"]))


def _set_service_hours(sd: dict, start: str | None, end: str | None) -> None:
    if start:
        sd["start"] = to_hhmm(to_min(start))
    if end:
        sd["end"] = to_hhmm(to_min(end))
    s, e = to_min(sd["start"]), to_min(sd["end"])
    periods = sorted(sd["headways"], key=lambda p: to_min(p["start"]))
    # Clip the headway pattern to the new hours, and stretch the first and
    # last periods so the pattern still covers the whole service day.
    clipped = []
    for p in periods:
        ps, pe = max(to_min(p["start"]), s), min(to_min(p["end"]), e)
        if ps < pe:
            clipped.append({"start": to_hhmm(ps), "end": to_hhmm(pe), "minutes": p["minutes"]})
    if clipped:
        clipped[0]["start"] = to_hhmm(s)
        clipped[-1]["end"] = to_hhmm(e)
    sd["headways"] = clipped


def _apply_one(cfg: dict, op: dict) -> None:
    name = op["op"]
    if name == "add_dock":
        route = cfg["route"]
        i = route.index(op["after"])
        prev_dock, next_dock = route[i], route[i + 1]
        cfg["docks"].append({"id": op["dock_id"], "name": op["name"],
                             "dwell_min": int(op.get("dwell_min", 2)),
                             "berths": int(op.get("berths", 1)), "overnight_berths": 0})
        route.insert(i + 1, op["dock_id"])
        cfg["legs"] = [l for l in cfg["legs"] if {l["from"], l["to"]} != {prev_dock, next_dock}]
        cfg["legs"].append({"from": prev_dock, "to": op["dock_id"], "minutes": int(op["minutes_from_prev"])})
        cfg["legs"].append({"from": op["dock_id"], "to": next_dock, "minutes": int(op["minutes_to_next"])})
        return
    for day in _days(cfg, op["day"]):
        sd = cfg["service_days"][day]
        if name == "set_service_hours":
            _set_service_hours(sd, op.get("start"), op.get("end"))
        elif name == "set_headway":
            _set_headway(sd, to_min(op["start"]), to_min(op["end"]), int(op["minutes"]))
        elif name == "close_dock":
            sd.setdefault("closures", []).append(
                {"dock": op["dock"], "start": to_hhmm(to_min(op["start"])), "end": to_hhmm(to_min(op["end"]))})
        elif name == "add_departure":
            t = to_hhmm(to_min(op["time"]))
            sd.setdefault("added_departures", [])
            if t not in sd["added_departures"]:
                sd["added_departures"].append(t)
            if t in sd.get("cancelled_departures", []):
                sd["cancelled_departures"].remove(t)
        elif name == "cancel_departure":
            t = to_hhmm(to_min(op["time"]))
            sd.setdefault("cancelled_departures", [])
            if t not in sd["cancelled_departures"]:
                sd["cancelled_departures"].append(t)
        elif name == "add_vessel":
            if op["vessel"] not in sd["vessels"]:
                sd["vessels"].append(op["vessel"])
        elif name == "remove_vessel":
            if op["vessel"] in sd["vessels"]:
                sd["vessels"].remove(op["vessel"])


def apply_ops(cfg: dict, ops: list[dict], request: str) -> tuple[dict, list[OpResult]]:
    """Ground-check and apply each op in order. Returns (new config, results)."""
    new = C.clone(cfg)
    results: list[OpResult] = []
    for op in ops:
        errs = grounding_errors(op, request, new)
        if errs:
            results.append(OpResult(op, False, "; ".join(errs)))
            continue
        trial = C.clone(new)
        try:
            _apply_one(trial, op)
            C.validate(trial)
        except (C.ConfigError, ValueError) as e:
            results.append(OpResult(op, False, f"would break the config: {e}"))
            continue
        new = trial
        results.append(OpResult(op, True, "applied"))
    return new, results
