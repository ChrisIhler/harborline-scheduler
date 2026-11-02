"""Tests for the Harbor Line scheduler. Several plant errors on purpose to prove the checks catch them."""

import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from harborline import checks, config, engine, excel
from harborline.agent import propose_ops
from harborline.ops import apply_ops, grounding_errors
from harborline.timeutil import times_in_text, to_min

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"


@pytest.fixture
def cfg():
    return config.load(ROOT / "data" / "network.yaml")


def failed(cfg_):
    s = engine.build(cfg_)
    return {r.rule_id for r in checks.run_checks(cfg_, s) if not r.passed}, s


def example(name, cfg_):
    req = (EX / f"{name}.txt").read_text().strip()
    ops = json.loads((EX / f"{name}.ops.json").read_text())["ops"]
    return apply_ops(cfg_, ops, req)


# ---- time parsing --------------------------------------------------------------

def test_times_in_text_reads_common_formats():
    t = times_in_text("Leave at 6:30 am, again at 6 PM, then 18:45, and noon.")
    assert {to_min("06:30"), to_min("18:00"), to_min("18:45"), to_min("12:00")} <= t


def test_bare_numbers_are_not_times():
    assert times_in_text("every 15 minutes with 3 boats") == set()


def test_ranges_share_the_am_pm_marker():
    assert {to_min("07:00"), to_min("09:00")} <= times_in_text("every 10 minutes from 7 to 9 am")


# ---- baseline ------------------------------------------------------------------

def test_baseline_passes_every_rule(cfg):
    bad, _ = failed(cfg)
    assert bad == set()


def test_engine_calculates_stop_times_from_config(cfg):
    s = engine.build(cfg)["weekday"]
    first = s.trips[0]
    # 06:30 depart, +8 sail to Riverwalk; 2 min dwell; +6 to Market; 2 min; +10 to Lighthouse
    assert [x.arrive for x in first.stops[:4]] == [to_min(t) for t in ("06:30", "06:38", "06:46", "06:58")]
    assert first.end == to_min("07:32")


def test_twelve_rules_are_checked(cfg):
    results = checks.run_checks(cfg, engine.build(cfg))
    assert len(results) == 12


# ---- grounding check -------------------------------------------------------------

def test_grounding_rejects_a_time_not_in_the_request(cfg):
    new, res = example("03_invented_time", cfg)
    assert not res[0].applied and "05:45" in res[0].reason
    assert "added_departures" not in new["service_days"]["weekday"]


def test_grounding_rejects_a_quote_not_in_the_request(cfg):
    op = {"op": "cancel_departure", "day": "sunday", "time": "14:30",
          "quote": "cancel the 2:30 pm Sunday trip"}
    assert grounding_errors(op, "Please cancel Sunday service.", cfg)


def test_grounding_rejects_an_invented_minute_count(cfg):
    op = {"op": "set_headway", "day": "weekday", "start": "07:00", "end": "09:00", "minutes": 10,
          "quote": "more boats from 7 to 9 am"}
    errs = grounding_errors(op, "more boats from 7 to 9 am", cfg)
    assert any("minutes=10" in e for e in errs)


def test_grounding_rejects_unknown_dock_and_vessel(cfg):
    req = "close Pier 99 from 1 to 3 pm and add Albatross on sunday"
    a = {"op": "close_dock", "day": "saturday", "dock": "PIER99", "start": "13:00", "end": "15:00",
         "quote": "close Pier 99 from 1 to 3 pm"}
    b = {"op": "add_vessel", "day": "sunday", "vessel": "ALBATROSS", "quote": "add Albatross on sunday"}
    assert grounding_errors(a, req, cfg) and grounding_errors(b, req, cfg)


def test_grounded_op_is_accepted(cfg):
    req = "Add a 6:15 am weekday boat."
    op = {"op": "add_departure", "day": "weekday", "time": "06:15", "quote": "Add a 6:15 am weekday boat"}
    assert grounding_errors(op, req, cfg) == []


# ---- example scenarios -------------------------------------------------------------

def test_festival_changes_frequency_and_closes_dock(cfg):
    new, res = example("01_festival", cfg)
    assert all(r.applied for r in res)
    bad, s = failed(new)
    assert bad == set()
    sat = s["saturday"].trips
    noon_trips = [t for t in sat if to_min("11:00") <= t.depart < to_min("16:00")]
    gaps = {b.depart - a.depart for a, b in zip(noon_trips, noon_trips[1:])}
    assert gaps == {15}
    market = [st for t in sat for st in t.stops if st.dock == "MARKET"
              and to_min("13:00") <= st.arrive < to_min("15:00")]
    assert market and all(st.closed for st in market)


def test_new_dock_is_only_a_config_change(cfg):
    new, res = example("02_new_dock", cfg)
    assert res[0].applied
    assert new["route"] == ["UNION", "RIVERWALK", "MARKET", "ARTS", "LIGHTHOUSE"]
    bad, s = failed(new)
    assert bad == set()
    assert "ARTS" in [st.dock for st in s["weekday"].trips[0].stops]


def test_short_fleet_is_flagged_not_hidden(cfg):
    new, res = example("04_short_fleet", cfg)
    assert res[0].applied
    bad, s = failed(new)
    assert "R2" in bad and s["sunday"].unassigned


# ---- planted errors: the checks must catch a broken schedule -----------------------

def test_planted_double_booking_is_caught(cfg):
    s = engine.build(cfg)
    trips = s["weekday"].trips
    trips[1].vessel = trips[0].vessel  # 15 minutes apart, same boat
    bad = {r.rule_id for r in checks.run_checks(cfg, s) if not r.passed}
    assert "R4" in bad


def test_planted_wrong_sailing_time_is_caught(cfg):
    s = engine.build(cfg)
    s["weekday"].trips[3].stops[1].arrive -= 3   # someone typed a faster time by hand
    s["weekday"].trips[3].stops[1].depart -= 3
    bad = {r.rule_id for r in checks.run_checks(cfg, s) if not r.passed}
    assert "R10" in bad


def test_planted_trip_after_hours_is_caught(cfg):
    cfg["service_days"]["sunday"]["added_departures"] = ["18:45"]   # returns 19:47, service ends 19:00
    bad, _ = failed(cfg)
    assert "R1" in bad


def test_planted_unrostered_vessel_is_caught(cfg):
    s = engine.build(cfg)
    s["sunday"].trips[0].vessel = "WREN"
    bad = {r.rule_id for r in checks.run_checks(cfg, s) if not r.passed}
    assert "R3" in bad


def test_planted_stop_at_closed_dock_is_caught(cfg):
    cfg["service_days"]["weekday"]["closures"] = [{"dock": "MARKET", "start": "07:00", "end": "08:00"}]
    s = engine.build(cfg)
    for t in s["weekday"].trips:
        for st in t.stops:
            st.closed = False      # engine "forgot" the closure
    bad = {r.rule_id for r in checks.run_checks(cfg, s) if not r.passed}
    assert "R9" in bad


def test_planted_long_gap_is_caught(cfg):
    cfg["service_days"]["weekday"]["cancelled_departures"] = ["11:00", "11:30"]
    bad, _ = failed(cfg)
    assert "R8" in bad


def test_planted_crew_overrun_is_caught(cfg):
    s = engine.build(cfg)
    # Put HERON on every morning trip it can physically reach back-to-back, with no break.
    for t in s["weekday"].trips:
        if t.vessel == "HERON":
            t.vessel = None
    free = 0
    for t in s["weekday"].trips:
        if t.depart >= free and t.depart < to_min("13:00"):
            t.vessel, free = "HERON", t.end + cfg["rules"]["min_turnaround_min"]
    bad = {r.rule_id for r in checks.run_checks(cfg, s) if not r.passed}
    assert "R6" in bad


def test_planted_dock_conflict_is_caught(cfg):
    # An extra departure two minutes after a pattern boat: both sit at Riverwalk together,
    # and the dock is cut to one berth.
    cfg["docks"][1]["berths"] = 1
    cfg["service_days"]["weekday"]["added_departures"] = ["10:02"]
    bad, _ = failed(cfg)
    assert "R11" in bad


def test_planted_overnight_shortfall_is_caught(cfg):
    cfg["docks"][0]["overnight_berths"] = 4   # Saturday ends with five boats at the origin
    bad, _ = failed(cfg)
    assert "R12" in bad


# ---- Excel and the model wrapper -------------------------------------------------------

def test_workbook_has_day_tabs_and_checks(cfg, tmp_path):
    new, res = example("01_festival", cfg)
    s = engine.build(new)
    path = tmp_path / "out.xlsx"
    excel.write(str(path), new, s, checks.run_checks(new, s), res, "request")
    wb = load_workbook(path)
    assert wb.sheetnames == ["Weekday", "Saturday", "Sunday", "Vessels", "Checks", "Changes"]
    assert wb["Checks"]["C5"].value == "PASS"
    assert wb["Saturday"]["C5"].value == "9:00 AM"


def test_model_proposals_still_go_through_grounding(cfg):
    """A fake Claude that invents a time: the op is rejected before it reaches the schedule."""
    class Block:
        type = "tool_use"
        input = {"ops": [{"op": "add_departure", "day": "saturday", "time": "22:30",
                          "quote": "add a late boat on Saturdays"}], "questions": []}

    class FakeClient:
        class messages:
            @staticmethod
            def create(**kw):
                assert kw["tool_choice"]["name"] == "propose_edits"
                return type("R", (), {"content": [Block()]})

    req = "add a late boat on Saturdays"
    proposal = propose_ops(req, cfg, client=FakeClient())
    _, res = apply_ops(cfg, proposal["ops"], req)
    assert not res[0].applied
