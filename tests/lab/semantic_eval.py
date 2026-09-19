#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from director.capabilities import NativeCapabilities  # noqa: E402
from director.service import Director  # noqa: E402
from director.store import Store  # noqa: E402


CLIENTS = [
    {"address": "0xa1", "title": "Alpha Terminal", "class": "foot", "workspace": {"id": 1}, "at": [0, 0], "size": [900, 700], "floating": False, "fullscreen": False, "focusHistoryID": 0},
    {"address": "0xa2", "title": "Beta Terminal", "class": "foot", "workspace": {"id": 1}, "at": [900, 0], "size": [900, 700], "floating": False, "fullscreen": False, "focusHistoryID": 1},
    {"address": "0xb1", "title": "Home / X", "class": "chrome-x.com__-Profile_2", "workspace": {"id": 2}, "at": [0, 0], "size": [900, 700], "floating": False, "fullscreen": False, "focusHistoryID": 2},
    {"address": "0xc1", "title": "ChatGPT", "class": "chatgpt", "workspace": {"id": 2}, "at": [900, 0], "size": [900, 700], "floating": False, "fullscreen": False, "focusHistoryID": 3}
]
APPS = {
    "slack": {"id": "slack", "name": "Slack", "startup_wm_class": "slack", "generic_name": "Slack Client", "comment": "", "keywords": "chat"},
    "firefox": {"id": "firefox", "name": "Firefox", "startup_wm_class": "firefox", "generic_name": "Web Browser", "comment": "", "keywords": "web"},
    "firefox-developer-edition": {"id": "firefox-developer-edition", "name": "Firefox Developer Edition", "startup_wm_class": "firefoxdeveloperedition", "generic_name": "Web Browser", "comment": "", "keywords": "web development"}
}


class PlanningDesktop:
    runner = None

    def state(self):
        clients = json.loads(json.dumps(CLIENTS))
        return {
            "clients": clients,
            "workspaces": [{"id": 1, "windows": 2}, {"id": 2, "windows": 2}, {"id": 3, "windows": 0}],
            "monitors": [{"focused": True, "activeWorkspace": {"id": 1, "name": "1"}}],
            "active": clients[0],
        }


class PlanningNative(NativeCapabilities):
    def __init__(self):
        super().__init__(runner=lambda *_args, **_kwargs: None)

    def themes(self):
        return ["Nord", "Osaka Jade"]


def validate(case: dict, plan) -> list[str]:
    failures: list[str] = []
    if plan.executable is not bool(case["executable"]):
        failures.append(f"executable={plan.executable}, expected {case['executable']}")
    if not case["executable"]:
        return failures
    operations = [step.operation for step in plan.steps]
    if operations != case.get("operations"):
        failures.append(f"operations={operations}, expected {case.get('operations')}")
    expected_targets = case.get("targets")
    if expected_targets is not None:
        targets = [step.target for step in plan.steps if step.target]
        if targets != expected_targets:
            failures.append(f"targets={targets}, expected {expected_targets}")
    workspace = case.get("workspace")
    if workspace is not None and any(step.workspace != workspace for step in plan.steps if step.operation not in {"launch", "native"}):
        failures.append(f"not every relevant step targets workspace {workspace}")
    capability = case.get("capability")
    if capability is not None and (not plan.steps or plan.steps[0].target != capability):
        failures.append(f"capability={plan.steps[0].target if plan.steps else None}, expected {capability}")
    direction = case.get("direction")
    if direction is not None and (not plan.steps or plan.steps[0].params.get("direction") != direction):
        failures.append(f"direction={plan.steps[0].params.get('direction') if plan.steps else None}, expected {direction}")
    for key, expected in case.get("params", {}).items():
        actual = plan.steps[0].params.get(key) if plan.steps else None
        if actual != expected:
            failures.append(f"params.{key}={actual!r}, expected {expected!r}")
    expected_auto = case.get("auto_executable")
    if expected_auto is not None and plan.auto_executable is not bool(expected_auto):
        failures.append(f"auto_executable={plan.auto_executable}, expected {expected_auto}")
    warning_contains = case.get("warning_contains")
    if warning_contains is not None and not any(str(warning_contains).casefold() in warning.casefold() for warning in plan.warnings):
        failures.append(f"warnings={plan.warnings!r}, expected text {warning_contains!r}")
    return failures


def expand_contract(contract: dict) -> list[dict]:
    cases = list(contract.get("cases", []))
    for family in contract.get("families", []):
        family_id = str(family["id"])
        expected = dict(family.get("expect", {}))
        for index, item in enumerate(family.get("queries", []), start=1):
            if isinstance(item, str):
                query, overrides = item, {}
            elif isinstance(item, dict) and isinstance(item.get("query"), str):
                query, overrides = item["query"], {key: value for key, value in item.items() if key != "query"}
            else:
                raise ValueError(f"invalid query in family {family_id}")
            cases.append({**expected, **overrides, "id": f"{family_id}-{index:03d}", "query": query})
    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Director's semantic contracts through the configured Jev gateway without executing actions.")
    parser.add_argument("--contracts", type=Path, default=REPO / "tests/contracts/semantic.json")
    parser.add_argument("--limit", type=int, default=0, help="evaluate only the first N cases; zero means all")
    parser.add_argument("--requests-per-minute", type=int, default=int(os.environ.get("DIRECTOR_SEMANTIC_RPM", "0")), help="pace cases to stay below a gateway/provider request budget")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    contract = json.loads(args.contracts.read_text(encoding="utf-8"))
    expanded = expand_contract(contract)
    cases = expanded[: max(0, args.limit)] if args.limit else expanded
    started = time.time()
    results = []
    last_case_started = 0.0
    minimum_interval = 60.0 / args.requests_per_minute if args.requests_per_minute > 0 else 0.0
    with tempfile.TemporaryDirectory() as temporary, patch("director.service.desktop_entries", return_value=APPS):
        director = Director(hypr=PlanningDesktop(), store=Store(temporary), native=PlanningNative(), sleeper=lambda _seconds: None)
        for case in cases:
            delay = minimum_interval - (time.monotonic() - last_case_started)
            if delay > 0:
                time.sleep(delay)
            last_case_started = time.monotonic()
            try:
                plan = director.plan(case["query"])
                failures = validate(case, plan)
                infrastructure = any("jev gateway" in warning.casefold() for warning in plan.warnings)
                results.append({"id": case["id"], "query": case["query"], "passed": not failures, "category": "infrastructure" if failures and infrastructure else ("semantic" if failures else "passed"), "failures": failures, "plan": plan.to_dict()})
            except Exception as exc:
                results.append({"id": case["id"], "query": case["query"], "passed": False, "category": "infrastructure", "failures": [str(exc)]})
    report = {
        "schema_version": 1,
        "model": "typesafe/jev-1.13",
        "contracts": str(args.contracts),
        "started_at": started,
        "duration_seconds": round(time.time() - started, 3),
        "total": len(results),
        "passed": sum(result["passed"] for result in results),
        "failed": sum(not result["passed"] for result in results),
        "semantic_failed": sum(result.get("category") == "semantic" for result in results),
        "infrastructure_failed": sum(result.get("category") == "infrastructure" for result in results),
        "requests_per_minute": args.requests_per_minute,
        "results": results,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
        os.chmod(args.report, 0o600)
    print(payload, end="")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
