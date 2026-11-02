"""Rule checks. These re-check the finished schedule from scratch.

They do not trust the engine: each rule is recomputed from the trips and the
config, so a bug in the engine, a hand-edited time or a bad edit shows up as
a FAIL instead of slipping into the published schedule.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import config as C
from .engine import DaySchedule, Trip
from .timeutil import to_12h, to_min


@dataclass
class CheckResult:
    rule_id: str
    rule: str
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.problems


def _label(t: Trip) -> str:
    return f"{t.day} trip {t.trip_no} ({to_12h(t.depart)})"


def _by_vessel(trips: list[Trip]) -> dict[str, list[Trip]]:
    out: dict[str, list[Trip]] = {}
    for t in trips:
        if t.vessel:
            out.setdefault(t.vessel, []).append(t)
    for v in out.values():
        v.sort(key=lambda t: t.depart)
    return out


def run_checks(cfg: dict, schedules: dict[str, DaySchedule]) -> list[CheckResult]:
    rules = cfg["rules"]
    turn = int(rules["min_turnaround_min"])
    max_run = int(rules["max_continuous_min"])
    brk = int(rules["break_min"])
    max_hours = int(rules["max_vessel_hours"])
    max_gap = int(rules["max_gap_min"])
    route = cfg["route"]
    expected_sequence = route + route[-2::-1]
    fleet = set(C.fleet_ids(cfg))

    r = {
        "R1": CheckResult("R1", "Every trip departs and returns inside service hours"),
        "R2": CheckResult("R2", "Every trip has a vessel"),
        "R3": CheckResult("R3", "Only vessels rostered for that day (and in the fleet) are used"),
        "R4": CheckResult("R4", "No vessel is booked on two trips at once"),
        "R5": CheckResult("R5", f"At least {turn} min turnaround at each terminal"),
        "R6": CheckResult("R6", f"No crew runs more than {max_run} min without a {brk} min break"),
        "R7": CheckResult("R7", f"No vessel sails more than {max_hours} hours in a day"),
        "R8": CheckResult("R8", f"Never more than {max_gap} min between departures from the origin"),
        "R9": CheckResult("R9", "No stop is served at a dock while it is closed"),
        "R10": CheckResult("R10", "Stops follow the route, and sailing times match the config"),
        "R11": CheckResult("R11", "No dock holds more boats at once than it has berths"),
        "R12": CheckResult("R12", "Every boat ends the day at a dock with an overnight berth for it"),
    }

    for day, sched in schedules.items():
        sd = cfg["service_days"][day]
        start, end = to_min(sd["start"]), to_min(sd["end"])
        roster = set(sd["vessels"])
        trips = sorted(sched.trips, key=lambda t: t.depart)

        for t in trips:
            if t.depart < start or t.end > end:
                r["R1"].problems.append(
                    f"{_label(t)} runs {to_12h(t.depart)}-{to_12h(t.end)}; service is {to_12h(start)}-{to_12h(end)}")
            if not t.vessel:
                r["R2"].problems.append(f"{_label(t)} has no vessel (none free that meets the rules)")
            elif t.vessel not in roster or t.vessel not in fleet:
                r["R3"].problems.append(f"{_label(t)} uses {t.vessel}, which is not rostered for {day}")

            # R9 and R10: walk the stops.
            docks = [s.dock for s in t.stops]
            if docks != expected_sequence:
                r["R10"].problems.append(f"{_label(t)} stops {docks} do not match the route")
            else:
                for a, b in zip(t.stops, t.stops[1:]):
                    sail = b.arrive - a.depart
                    want = C.leg_minutes(cfg, a.dock, b.dock)
                    if sail != want:
                        r["R10"].problems.append(
                            f"{_label(t)} {a.dock}->{b.dock} takes {sail} min; config says {want}")
                    if a.depart < a.arrive:
                        r["R10"].problems.append(f"{_label(t)} leaves {a.dock} before it arrives")
            for s in t.stops[1:-1]:
                for c in sd.get("closures", []):
                    if (c["dock"] == s.dock and not s.closed
                            and to_min(c["start"]) <= s.arrive < to_min(c["end"])):
                        r["R9"].problems.append(
                            f"{_label(t)} stops at {s.dock} at {to_12h(s.arrive)}; closed {c['start']}-{c['end']}")

        for v, vt in _by_vessel(trips).items():
            block_start = None
            prev = None
            sailed = 0
            for t in vt:
                sailed += t.end - t.depart
                far = t.stops[len(route) - 1]
                if far.depart - far.arrive < turn:
                    r["R5"].problems.append(
                        f"{_label(t)} ({v}) turns at {far.dock} in {far.depart - far.arrive} min")
                if prev is not None:
                    if t.depart < prev.end:
                        r["R4"].problems.append(
                            f"{v} is on {_label(prev)} until {to_12h(prev.end)} and {_label(t)} at {to_12h(t.depart)}")
                    elif t.depart - prev.end < turn:
                        r["R5"].problems.append(
                            f"{v} gets {t.depart - prev.end} min at the origin between {_label(prev)} and {_label(t)}")
                if prev is None or t.depart - prev.end >= brk:
                    block_start = t.depart
                if t.end - block_start > max_run:
                    r["R6"].problems.append(
                        f"{v} runs {t.end - block_start} min without a break, ending {_label(t)}")
                prev = t
            if sailed > max_hours * 60:
                r["R7"].problems.append(f"{v} sails {sailed / 60:.1f} hours on {day}")

        # R11 dock conflicts: who is tied up where, minute by minute.
        occupancy: dict[str, list[tuple[int, int, str]]] = {}
        for v, vt in _by_vessel(trips).items():
            for i, t in enumerate(vt):
                for s in t.stops[1:-1]:
                    if not s.closed:
                        occupancy.setdefault(s.dock, []).append((s.arrive, max(s.depart, s.arrive + 1), v))
                # Layover at the origin between this trip and the vessel's next one.
                nxt = vt[i + 1].depart if i + 1 < len(vt) else t.end + 1
                occupancy.setdefault(t.stops[-1].dock, []).append((t.end, max(nxt, t.end + 1), v))
            occupancy.setdefault(vt[0].stops[0].dock, []).append((vt[0].depart, vt[0].depart + 1, v))
        for dock_id, spans in occupancy.items():
            berths = int(C.dock(cfg, dock_id).get("berths", 1))
            events = sorted([(a, 1, v) for a, b, v in spans] + [(b, -1, v) for a, b, v in spans])
            here: set[str] = set()
            reported = False
            for t_, delta, v in events:
                if delta == 1:
                    here.add(v)
                    if len(here) > berths and not reported:
                        r["R11"].problems.append(
                            f"{day}: {len(here)} boats at {dock_id} at {to_12h(t_)} ({', '.join(sorted(here))}); "
                            f"it has {berths} berth{'s' if berths != 1 else ''}")
                        reported = True
                else:
                    here.discard(v)
                    if len(here) <= berths:
                        reported = False

        # R12 overnight positions: where each boat finishes, against overnight berths.
        tonight: dict[str, list[str]] = {}
        for v, vt in _by_vessel(trips).items():
            tonight.setdefault(vt[-1].stops[-1].dock, []).append(v)
        for dock_id, boats in tonight.items():
            cap = int(C.dock(cfg, dock_id).get("overnight_berths", 0))
            if len(boats) > cap:
                r["R12"].problems.append(
                    f"{day}: {len(boats)} boats end the day at {dock_id} ({', '.join(sorted(boats))}); "
                    f"it has {cap} overnight berth{'s' if cap != 1 else ''}")

        departures = [t.depart for t in trips]
        if departures:
            points = [start] + departures
            for a, b in zip(points, points[1:]):
                if b - a > max_gap:
                    r["R8"].problems.append(f"{day}: {b - a} min gap from {to_12h(a)} to {to_12h(b)}")
        else:
            r["R8"].problems.append(f"{day}: no departures at all")

    return list(r.values())


def all_passed(results: list[CheckResult]) -> bool:
    return all(c.passed for c in results)
