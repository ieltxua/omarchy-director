#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from director.capabilities import CAPABILITY_CRITERIA  # noqa: E402


def run_json(argv: list[str]) -> dict:
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"failed: {' '.join(argv)}")
    return json.loads(result.stdout)


def parse_hyprctl_commands(output: str) -> set[str]:
    return {line.strip().split()[0] for line in output.splitlines() if line.startswith("    ") and line.strip()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Director against the installed Omarchy and Hyprland command surfaces.")
    parser.add_argument("--matrix", type=Path, default=REPO / "tests/contracts/capability_matrix.json")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    catalog = run_json(["omarchy", "commands", "--all", "--json"])
    commands = catalog.get("commands", [])
    routes = {str(command.get("route")) for command in commands if isinstance(command, dict)}
    public = [command for command in commands if isinstance(command, dict) and not command.get("hidden")]
    relevant_groups = set(matrix["relevant_groups"])
    relevant = [command for command in public if command.get("group") in relevant_groups and not command.get("requires_sudo")]

    help_result = subprocess.run(["hyprctl", "--help"], capture_output=True, text=True, check=False)
    # Hyprland 0.56 prints valid help and exits 1 for the bare --help path.
    hypr_help = f"{help_result.stdout}\n{help_result.stderr}"
    hypr_commands = parse_hyprctl_commands(hypr_help)

    required_routes = sorted({requirement for capability in matrix["capabilities"] for requirement in capability["requirements"] if requirement.startswith("omarchy ")})
    required_routes.extend(requirement for requirement in matrix["window_engine"]["requirements"] if requirement.startswith("omarchy "))
    required_hypr = sorted({requirement.split(":", 1)[1] for capability in matrix["capabilities"] for requirement in capability["requirements"] if requirement.startswith("hyprctl:")})
    required_hypr.extend(requirement.split(":", 1)[1] for requirement in matrix["window_engine"]["requirements"] if requirement.startswith("hyprctl:"))
    required_hypr = sorted(set(required_hypr))

    public_capabilities = set(CAPABILITY_CRITERIA) - {"window_action", "no_match"}
    mapped_capabilities = {str(capability["id"]) for capability in matrix["capabilities"]}
    known_routes = set(required_routes) | set(matrix["candidate_routes"]) | set(matrix["never_route_without_new_policy"])
    unmapped = sorted(str(command["route"]) for command in relevant if command.get("route") not in known_routes)
    report = {
        "schema_version": 1,
        "installed": {"omarchy_commands": len(commands), "public_commands": len(public), "desktop_relevant_commands": len(relevant)},
        "coverage": {
            "director_capabilities": len(public_capabilities),
            "mapped_capabilities": len(mapped_capabilities),
            "missing_capabilities": sorted(public_capabilities - mapped_capabilities),
            "stale_capabilities": sorted(mapped_capabilities - public_capabilities),
            "missing_omarchy_routes": sorted(set(required_routes) - routes),
            "missing_hyprctl_commands": sorted(set(required_hypr) - hypr_commands),
        },
        "opportunities": {
            "declared_available": sorted(set(matrix["candidate_routes"]) & routes),
            "declared_missing": sorted(set(matrix["candidate_routes"]) - routes),
            "unmapped_routes": unmapped,
        },
        "policy_exclusions_available": sorted(set(matrix["never_route_without_new_policy"]) & routes),
    }
    failures = [value for value in report["coverage"].values() if isinstance(value, list) and value]
    report["ok"] = not failures
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
        os.chmod(args.report, 0o600)
    print(payload, end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
