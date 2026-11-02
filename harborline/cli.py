"""Command line: build, apply, ask, network.

  python -m harborline build                       # baseline schedule + checks
  python -m harborline apply -r "request" --ops ops.json
  python -m harborline ask -r "request"            # Claude proposes the ops (needs an API key)
  python -m harborline network                     # summary for the Claude skill
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import checks, config, engine, excel
from .ops import apply_ops

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "data" / "network.yaml"
DEFAULT_OUT = ROOT / "out"

USE_COLOR = (sys.stdout.isatty() or bool(os.environ.get("FORCE_COLOR"))) and not os.environ.get("NO_COLOR")


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def green(t): return _c(t, "32")
def red(t): return _c(t, "31")
def bold(t): return _c(t, "1")
def dim(t): return _c(t, "2")


def _report(cfg, schedules, results, out_xlsx: Path) -> bool:
    print()
    for day, s in schedules.items():
        vessels = len({t.vessel for t in s.trips if t.vessel})
        extra = red(f", {len(s.unassigned)} with no vessel") if s.unassigned else ""
        print(f"  {day.capitalize():9} {len(s.trips):3} round trips, {vessels} vessels in use{extra}")
    print()
    print(bold("  Rule checks"))
    for r in results:
        mark = green("PASS") if r.passed else red("FAIL")
        print(f"  {mark}  {r.rule_id:4} {r.rule}")
        for p in r.problems[:4]:
            print(dim(f"          - {p}"))
        if len(r.problems) > 4:
            print(dim(f"          ... and {len(r.problems) - 4} more (see the Checks tab)"))
    ok = checks.all_passed(results)
    print()
    print(("  " + green("All checks pass.")) if ok else ("  " + red("Some checks failed. The schedule is NOT ready to publish.")))
    print(f"  Workbook: {out_xlsx}")
    print()
    return ok


def _print_ops(results) -> None:
    print(bold("\n  Grounding check"))
    for i, r in enumerate(results, 1):
        op = r.op
        fields = ", ".join(f"{k}={v}" for k, v in op.items() if k not in ("op", "quote"))
        mark = green("APPLIED ") if r.applied else red("REJECTED")
        print(f"  {mark} {i}. {op.get('op')} {fields}")
        print(dim(f"             quote: \"{op.get('quote', '')}\""))
        if not r.applied:
            print(red(f"             why:   {r.reason}"))


def _run(cfg, out_dir: Path, request=None, op_results=None, save_config=False, base_name="harborline_schedule") -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    schedules = engine.build(cfg)
    results = checks.run_checks(cfg, schedules)
    out_xlsx = out_dir / f"{base_name}.xlsx"
    excel.write(str(out_xlsx), cfg, schedules, results, op_results, request)
    if save_config:
        config.save(cfg, out_dir / "network.updated.yaml")
        print(f"  Updated config: {out_dir / 'network.updated.yaml'}")
    ok = _report(cfg, schedules, results, out_xlsx)
    rejected = any(not r.applied for r in (op_results or []))
    return 0 if ok and not rejected else 2


def _load_ops(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["ops"] if isinstance(data, dict) else data


def _read_request(args) -> str:
    if args.request:
        return args.request
    if args.request_file:
        return Path(args.request_file).read_text(encoding="utf-8").strip()
    raise SystemExit("Give the request with -r \"...\" or --request-file")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="harborline", description="Harbor Line Water Taxi scheduler (demo)")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--out", default=str(DEFAULT_OUT))
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("build", help="Build the baseline schedule and run the checks")
    sub.add_parser("network", help="Print the network summary (docks, route, fleet)")

    a = sub.add_parser("apply", help="Apply an ops file to the schedule")
    a.add_argument("-r", "--request")
    a.add_argument("--request-file")
    a.add_argument("--ops", required=True)
    a.add_argument("--save-config", action="store_true")
    a.add_argument("--name", default="harborline_schedule")

    k = sub.add_parser("ask", help="Have Claude propose ops for a request (needs ANTHROPIC_API_KEY)")
    k.add_argument("-r", "--request")
    k.add_argument("--request-file")
    k.add_argument("--save-config", action="store_true")
    k.add_argument("--name", default="harborline_schedule")

    args = p.parse_args(argv)
    cfg = config.load(args.config)
    out = Path(args.out)

    if args.cmd == "network":
        from .agent import network_summary
        print(network_summary(cfg))
        return 0

    print(bold(f"\n  {cfg['network']['name']} scheduler"))

    if args.cmd == "build":
        return _run(cfg, out)

    request = _read_request(args)
    print(f"  Request: \"{request}\"")

    if args.cmd == "apply":
        ops = _load_ops(args.ops)
    else:
        from .agent import propose_ops
        proposal = propose_ops(request, cfg)
        ops = proposal["ops"]
        (out).mkdir(parents=True, exist_ok=True)
        (out / f"{args.name}.ops.json").write_text(json.dumps(proposal, indent=2), encoding="utf-8")
        for q in proposal.get("questions", []):
            print(_c(f"  Question for you: {q}", "33"))

    new_cfg, op_results = apply_ops(cfg, ops, request)
    _print_ops(op_results)
    return _run(new_cfg, out, request, op_results, args.save_config, args.name)


if __name__ == "__main__":
    sys.exit(main())
