"""Load and validate the network config (docks, route, fleet, rules, service days)."""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

from .timeutil import to_min

DAY_ORDER = ["weekday", "saturday", "sunday"]


class ConfigError(ValueError):
    pass


def load(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    validate(cfg)
    return cfg


def save(cfg: dict, path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Harbor Line Water Taxi (fictional). Written by the scheduler after applying edits.\n")
        yaml.safe_dump(cfg, f, sort_keys=False, default_flow_style=None, width=100)


def clone(cfg: dict) -> dict:
    return copy.deepcopy(cfg)


def dock_ids(cfg: dict) -> list[str]:
    return [d["id"] for d in cfg["docks"]]


def dock(cfg: dict, dock_id: str) -> dict:
    for d in cfg["docks"]:
        if d["id"] == dock_id:
            return d
    raise ConfigError(f"Unknown dock {dock_id!r}")


def leg_minutes(cfg: dict, a: str, b: str) -> int:
    for leg in cfg["legs"]:
        if {leg["from"], leg["to"]} == {a, b}:
            return int(leg["minutes"])
    raise ConfigError(f"No sailing time between {a} and {b}")


def fleet_ids(cfg: dict) -> list[str]:
    return [v["id"] for v in cfg["fleet"]]


def validate(cfg: dict) -> None:
    """Structural checks so a bad config fails loudly before scheduling."""
    for key in ("network", "docks", "route", "legs", "fleet", "rules", "service_days"):
        if key not in cfg:
            raise ConfigError(f"Config is missing '{key}'")
    ids = dock_ids(cfg)
    if len(ids) != len(set(ids)):
        raise ConfigError("Duplicate dock id")
    route = cfg["route"]
    if len(route) < 2:
        raise ConfigError("Route needs at least two docks")
    for d in route:
        if d not in ids:
            raise ConfigError(f"Route uses unknown dock {d!r}")
    if route[0] != cfg["network"]["origin"]:
        raise ConfigError("The route must start at the origin dock")
    for a, b in zip(route, route[1:]):
        leg_minutes(cfg, a, b)  # raises if missing
    fleet = fleet_ids(cfg)
    for day, sd in cfg["service_days"].items():
        if to_min(sd["start"]) >= to_min(sd["end"]):
            raise ConfigError(f"{day}: service start must be before end")
        for v in sd["vessels"]:
            if v not in fleet:
                raise ConfigError(f"{day}: unknown vessel {v!r}")
        for h in sd["headways"]:
            if int(h["minutes"]) <= 0:
                raise ConfigError(f"{day}: headway must be positive")
            if to_min(h["start"]) >= to_min(h["end"]):
                raise ConfigError(f"{day}: headway period start must be before end")
