"""Schedule engine: turns the config into timed trips and assigns vessels.

Every time in the output is calculated here, from the config. Nothing the
language model says is ever used as a time directly; it can only change the
config through checked edit operations (see ops.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import config as C
from .timeutil import to_min


@dataclass
class Stop:
    dock: str
    arrive: int
    depart: int
    closed: bool = False  # True = boat passes this dock without stopping


@dataclass
class Trip:
    day: str
    trip_no: int
    depart: int                 # departure from the origin dock
    stops: list[Stop]
    vessel: str | None = None
    source: str = "headway"     # "headway" or "added"

    @property
    def end(self) -> int:
        return self.stops[-1].arrive


@dataclass
class DaySchedule:
    day: str
    trips: list[Trip] = field(default_factory=list)
    unassigned: list[Trip] = field(default_factory=list)


def _closed(sd: dict, dock_id: str, t: int) -> bool:
    for c in sd.get("closures", []):
        if c["dock"] == dock_id and to_min(c["start"]) <= t < to_min(c["end"]):
            return True
    return False


def round_trip_stops(cfg: dict, sd: dict, depart: int) -> list[Stop]:
    """Outbound along the route, turn at the far terminal, then back."""
    route = cfg["route"]
    turn = int(cfg["rules"]["min_turnaround_min"])
    sequence = route + route[-2::-1]           # A B C D C B A
    far_index = len(route) - 1
    stops: list[Stop] = []
    t = depart
    for i, dock_id in enumerate(sequence):
        if i > 0:
            t += C.leg_minutes(cfg, sequence[i - 1], dock_id)
        arrive = t
        if i == 0:
            stops.append(Stop(dock_id, arrive, arrive))
            continue
        if i == len(sequence) - 1:
            stops.append(Stop(dock_id, arrive, arrive))
            break
        if i == far_index:
            t = arrive + turn
            stops.append(Stop(dock_id, arrive, t))
            continue
        if _closed(sd, dock_id, arrive):
            stops.append(Stop(dock_id, arrive, arrive, closed=True))
        else:
            t = arrive + int(C.dock(cfg, dock_id)["dwell_min"])
            stops.append(Stop(dock_id, arrive, t))
    return stops


def departure_times(cfg: dict, day: str) -> list[tuple[int, str]]:
    """Origin departures for a day: headway pattern, plus added, minus cancelled."""
    sd = cfg["service_days"][day]
    start, end = to_min(sd["start"]), to_min(sd["end"])
    cycle = round_trip_stops(cfg, sd, 0)[-1].arrive
    times: dict[int, str] = {}
    for h in sd["headways"]:
        t, stop, step = to_min(h["start"]), to_min(h["end"]), int(h["minutes"])
        while t < stop:
            # Pattern trips only run if they can finish inside service hours.
            if start <= t and t + cycle <= end:
                times[t] = "headway"
            t += step
    for t in sd.get("added_departures", []):
        times[to_min(t)] = "added"   # kept even if it breaks a rule, so the checks can flag it
    for t in sd.get("cancelled_departures", []):
        times.pop(to_min(t), None)
    return sorted(times.items())


def build_day(cfg: dict, day: str) -> DaySchedule:
    sd = cfg["service_days"][day]
    rules = cfg["rules"]
    turn = int(rules["min_turnaround_min"])
    max_run = int(rules["max_continuous_min"])
    brk = int(rules["break_min"])
    max_hours_min = int(rules["max_vessel_hours"]) * 60

    sched = DaySchedule(day)
    trips = [
        Trip(day, n + 1, t, round_trip_stops(cfg, sd, t), source=src)
        for n, (t, src) in enumerate(departure_times(cfg, day))
    ]

    # Vessel state: when it is free, when its current crew block started,
    # and how many minutes it has sailed today.
    state = {v: {"free": None, "block_start": None, "used": 0} for v in sd["vessels"]}
    roster = list(sd["vessels"])

    for trip in trips:
        duration = trip.end - trip.depart
        candidates = []
        for v in roster:
            s = state[v]
            if s["free"] is not None and s["free"] > trip.depart:
                continue  # still sailing or turning around
            if s["used"] + duration > max_hours_min:
                continue
            block_start = s["block_start"]
            if s["free"] is None or trip.depart - (s["free"] - turn) >= brk:
                block_start = trip.depart  # fresh crew block after a break (or first trip)
            if trip.end - block_start > max_run:
                continue
            in_service = s["free"] is not None
            # Would this be the crew's last trip before a forced break?
            last_before_break = trip.end + turn + duration - block_start > max_run
            # Prefer boats already in service (fewer boats out), longest-waiting first.
            # A boat about to hit its crew limit ranks below a spare boat, so the
            # spare comes out early and breaks are staggered instead of all at once.
            if in_service and not last_before_break:
                tier = 0
            elif not in_service:
                tier = 1
            else:
                tier = 2
            candidates.append((tier, s["free"] or 0, roster.index(v), v, block_start))
        if not candidates:
            sched.unassigned.append(trip)
            sched.trips.append(trip)
            continue
        candidates.sort()
        _, _, _, v, block_start = candidates[0]
        trip.vessel = v
        state[v] = {"free": trip.end + turn, "block_start": block_start, "used": state[v]["used"] + duration}
        sched.trips.append(trip)
    return sched


def build(cfg: dict) -> dict[str, DaySchedule]:
    order = [d for d in C.DAY_ORDER if d in cfg["service_days"]]
    order += [d for d in cfg["service_days"] if d not in order]
    return {day: build_day(cfg, day) for day in order}
