#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from director.hyprland import Hyprland  # noqa: E402
from director.service import Director  # noqa: E402
from director.store import Store  # noqa: E402

ENVIRONMENT_KEYS = {
    "DBUS_SESSION_BUS_ADDRESS",
    "DISPLAY",
    "HYPRLAND_INSTANCE_SIGNATURE",
    "WAYLAND_DISPLAY",
    "XDG_CURRENT_DESKTOP",
    "XDG_RUNTIME_DIR",
}
FIXTURES = {
    "director-e2e-alpha": "Director E2E Alpha",
    "director-e2e-beta": "Director E2E Beta",
}


def hydrate_environment() -> None:
    result = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True, text=True, check=False)
    if result.returncode:
        return
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in ENVIRONMENT_KEYS and not os.environ.get(key):
            os.environ[key] = value


def fixture_clients(hypr: Hyprland) -> dict[str, dict]:
    state = hypr.state()
    return {str(client.get("class")): client for client in state["clients"] if str(client.get("class")) in FIXTURES}


def normalized(client: dict) -> dict:
    workspace = client.get("workspace", {})
    return {
        "class": client.get("class"),
        "workspace": workspace.get("id") if isinstance(workspace, dict) else None,
        "at": client.get("at"),
        "size": client.get("size"),
        "floating": bool(client.get("floating")),
        "fullscreen": bool(client.get("fullscreen")),
    }


def window_rounding() -> int:
    result = subprocess.run(["hyprctl", "-j", "getoption", "decoration:rounding"], capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    return int(payload["int"])


def border_size() -> int:
    result = subprocess.run(["hyprctl", "-j", "getoption", "general:border_size"], capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    return int(payload["int"])


def wait_for_fixtures(hypr: Hyprland, timeout: float = 8.0) -> dict[str, dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        clients = fixture_clients(hypr)
        if set(clients) == set(FIXTURES):
            return clients
        time.sleep(0.1)
    raise RuntimeError(f"fixture windows did not appear: {sorted(fixture_clients(hypr))}")


def start_fixtures() -> list[subprocess.Popen]:
    processes = []
    for app_id, title in FIXTURES.items():
        processes.append(subprocess.Popen(
            ["foot", f"--app-id={app_id}", f"--title={title}", "sleep", "900"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        ))
    return processes


def stop_fixtures(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 2
    for process in processes:
        try:
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def reset_fixture_layout(hypr: Hyprland, workspace: int) -> dict[str, dict]:
    clients = wait_for_fixtures(hypr)
    for client in clients.values():
        address = str(client["address"])
        if bool(client.get("fullscreen")):
            hypr.set_fullscreen(address, False)
        if bool(client.get("floating")):
            hypr.set_floating(address, False)
        hypr.move_window(address, workspace)
    hypr.focus_workspace(workspace)
    time.sleep(0.25)
    return fixture_clients(hypr)


def run_case(director: Director, hypr: Hyprland, case: dict, workspace: int) -> dict:
    baseline_clients = reset_fixture_layout(hypr, workspace)
    alpha = str(baseline_clients["director-e2e-alpha"]["address"])
    beta = str(baseline_clients["director-e2e-beta"]["address"])
    if case["id"] == "focus":
        hypr.focus_window(beta)
    elif case["id"] == "tile":
        hypr.set_floating(alpha, True)
        time.sleep(0.15)
    baseline_active = str(hypr.state()["active"].get("address"))
    baseline = {key: normalized(value) for key, value in fixture_clients(hypr).items()}
    baseline_rounding = window_rounding()
    baseline_border = border_size()
    query = case["query"]
    if case["id"] == "swap":
        direction = "right" if baseline["director-e2e-alpha"]["at"][0] < baseline["director-e2e-beta"]["at"][0] else "left"
        query = f"move Director E2E Alpha one tile to the {direction}"
    elif case["id"] == "style":
        query = f"set global border size to {1 if baseline_border != 1 else 2} pixels"
    plan = director.plan(query)
    result = {"id": case["id"], "query": query, "plan": plan.to_dict(), "passed": False}
    if not plan.executable:
        result["error"] = "plan was not executable"
        return result
    execution = director.execute(plan.token)
    current = fixture_clients(hypr)
    check = False
    if case["id"] == "focus":
        check = str(hypr.state()["active"].get("address")) == alpha
    elif case["id"] == "move":
        check = current["director-e2e-alpha"]["workspace"]["id"] == workspace + 1
    elif case["id"] == "float":
        check = bool(current["director-e2e-alpha"].get("floating"))
    elif case["id"] == "tile":
        check = not bool(current["director-e2e-alpha"].get("floating"))
    elif case["id"] == "fullscreen":
        check = bool(current["director-e2e-alpha"].get("fullscreen"))
    elif case["id"] == "arrange":
        check = all(client.get("workspace", {}).get("id") == workspace + 1 and not bool(client.get("floating")) for client in current.values())
    elif case["id"] == "workspace":
        check = next((monitor.get("activeWorkspace", {}).get("id") for monitor in hypr.state()["monitors"] if monitor.get("focused")), None) == workspace + 1
    elif case["id"] in {"resize", "swap"}:
        check = normalized(current["director-e2e-alpha"]) != baseline["director-e2e-alpha"]
    elif case["id"] == "rounding":
        check = window_rounding() == 8
    elif case["id"] == "style":
        check = border_size() == (1 if baseline_border != 1 else 2)
    undo = director.undo()
    time.sleep(0.15)
    restored = {key: normalized(value) for key, value in fixture_clients(hypr).items()}
    focus_restored = str(hypr.state()["active"].get("address")) == baseline_active
    rounding_restored = window_rounding() == baseline_rounding
    border_restored = border_size() == baseline_border
    result.update({"execution": execution, "undo": undo, "effect_verified": check, "restored": restored == baseline and rounding_restored and border_restored, "focus_restored": focus_restored})
    result["passed"] = bool(check and restored == baseline and rounding_restored and border_restored and focus_restored and not undo.get("warnings"))
    if not result["passed"]:
        result["baseline"] = baseline
        result["after_undo"] = restored
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run isolated Director acceptance cases against the live Omarchy desktop.")
    parser.add_argument("--workspace", type=int, default=91)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.workspace < 50 or args.workspace > 98:
        parser.error("the reserved base workspace must be between 50 and 98")
    hydrate_environment()
    missing = [command for command in ("foot", "hyprctl", "systemctl") if shutil.which(command) is None]
    if missing or not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        print(json.dumps({"ok": False, "error": f"live Omarchy preflight failed; missing={missing}, hyprland={bool(os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'))}"}))
        return 2
    hypr = Hyprland()
    original = hypr.state()
    original_workspace = next((monitor.get("activeWorkspace", {}).get("id") for monitor in original["monitors"] if monitor.get("focused")), None)
    stale_fixtures = [client for client in original["clients"] if client.get("class") in FIXTURES]
    if stale_fixtures:
        print(json.dumps({"ok": False, "error": "stale Director E2E fixture windows already exist"}))
        return 2
    occupied = [client for client in original["clients"] if isinstance(client.get("workspace"), dict) and client["workspace"].get("id") in {args.workspace, args.workspace + 1}]
    if occupied:
        print(json.dumps({"ok": False, "error": "reserved workspaces are not empty", "classes": sorted(str(client.get("class")) for client in occupied)}))
        return 2
    cases = [
        {"id": "focus", "query": "focus Director E2E Alpha"},
        {"id": "move", "query": f"move Director E2E Alpha to workspace {args.workspace + 1}"},
        {"id": "float", "query": "make Director E2E Alpha floating"},
        {"id": "tile", "query": "put Director E2E Alpha back into the tiling"},
        {"id": "fullscreen", "query": "make Director E2E Alpha fullscreen"},
        {"id": "resize", "query": "make Director E2E Alpha 20 percent smaller"},
        {"id": "swap", "query": "move Director E2E Alpha one tile to the right"},
        {"id": "arrange", "query": f"put Director E2E Alpha and Director E2E Beta side by side on workspace {args.workspace + 1}"},
        {"id": "workspace", "query": f"switch to workspace {args.workspace + 1}"},
        {"id": "rounding", "query": "make all window borders rounded"},
        {"id": "style", "query": "set global border size to 3 pixels"},
    ]
    processes: list[subprocess.Popen] = []
    results: list[dict] = []
    started = time.time()
    try:
        processes = start_fixtures()
        wait_for_fixtures(hypr)
        with tempfile.TemporaryDirectory() as temporary:
            for case in cases:
                try:
                    director = Director(hypr=hypr, store=Store(str(Path(temporary) / case["id"])))
                    results.append(run_case(director, hypr, case, args.workspace))
                except Exception as exc:
                    results.append({"id": case["id"], "query": case["query"], "passed": False, "error": str(exc)})
    finally:
        stop_fixtures(processes)
        if isinstance(original_workspace, int) and original_workspace > 0:
            try:
                hypr.focus_workspace(original_workspace)
            except Exception:
                pass
    report = {
        "schema_version": 1,
        "started_at": started,
        "duration_seconds": round(time.time() - started, 3),
        "base_workspace": args.workspace,
        "total": len(results),
        "passed": sum(result.get("passed") is True for result in results),
        "failed": sum(result.get("passed") is not True for result in results),
        "results": results,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
        os.chmod(args.report, 0o600)
    print(payload, end="")
    return 0 if report["failed"] == 0 and report["total"] == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
