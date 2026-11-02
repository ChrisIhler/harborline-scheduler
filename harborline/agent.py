"""Optional: ask Claude (through the Anthropic API) to turn a request into edit ops.

The model only PROPOSES operations. It never writes times into the schedule:
every op still goes through the grounding check in ops.py, and every time in
the output is calculated by the engine.

Needs `pip install anthropic` and ANTHROPIC_API_KEY. Without them, use the
Claude skill in skills/harborline-scheduler (Claude Code or the Claude app),
or pass a hand-written ops file to `harborline apply`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .ops import SCHEMA

DEFAULT_MODEL = os.environ.get("HARBORLINE_MODEL", "claude-sonnet-5-5")
SKILL_PATH = Path(__file__).resolve().parent.parent / "skills" / "harborline-scheduler" / "SKILL.md"


def network_summary(cfg: dict) -> str:
    """The facts the model needs, and nothing it could copy times from by accident."""
    return json.dumps({
        "days": list(cfg["service_days"]),
        "docks": [{"id": d["id"], "name": d["name"]} for d in cfg["docks"]],
        "route": cfg["route"],
        "fleet": [v["id"] for v in cfg["fleet"]],
        "rostered": {d: sd["vessels"] for d, sd in cfg["service_days"].items()},
    }, indent=2)


def _tool() -> dict:
    op_names = sorted(SCHEMA)
    return {
        "name": "propose_edits",
        "description": "Propose schedule edit operations for the request. Each op must quote the request.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ops": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string", "enum": op_names},
                            "quote": {"type": "string", "description": "Exact words copied from the request"},
                            "day": {"type": "string", "enum": ["weekday", "saturday", "sunday", "all"]},
                            "start": {"type": "string", "description": "HH:MM, 24-hour"},
                            "end": {"type": "string", "description": "HH:MM, 24-hour"},
                            "time": {"type": "string", "description": "HH:MM, 24-hour"},
                            "minutes": {"type": "integer"},
                            "dock": {"type": "string"},
                            "vessel": {"type": "string"},
                            "dock_id": {"type": "string"},
                            "name": {"type": "string"},
                            "after": {"type": "string"},
                            "minutes_from_prev": {"type": "integer"},
                            "minutes_to_next": {"type": "integer"},
                            "dwell_min": {"type": "integer"},
                            "berths": {"type": "integer"},
                        },
                        "required": ["op", "quote"],
                    },
                },
                "questions": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Questions for the scheduler when the request leaves out a needed time or number",
                },
            },
            "required": ["ops", "questions"],
        },
    }


def propose_ops(request: str, cfg: dict, client=None, model: str = DEFAULT_MODEL) -> dict:
    """Return {'ops': [...], 'questions': [...]} proposed by Claude."""
    if client is None:
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError("pip install anthropic (or use the Claude skill / an ops file)") from e
        client = anthropic.Anthropic()
    skill = SKILL_PATH.read_text(encoding="utf-8") if SKILL_PATH.exists() else ""
    system = (
        "You turn a water-taxi scheduler's plain-English request into edit operations.\n"
        "Follow these instructions:\n\n" + skill +
        "\n\nCurrent network:\n" + network_summary(cfg)
    )
    resp = client.messages.create(
        model=model,
        max_tokens=2000,
        system=system,
        tools=[_tool()],
        tool_choice={"type": "tool", "name": "propose_edits"},
        messages=[{"role": "user", "content": request}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            data = dict(block.input)
            data.setdefault("ops", [])
            data.setdefault("questions", [])
            return data
    raise RuntimeError("Claude did not return edit operations")
