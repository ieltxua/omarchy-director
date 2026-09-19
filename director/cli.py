from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import sys

from . import __version__
from .config import config_path, jev_socket_candidates, load_config, normalized_config, remove_alias, save_config, set_alias, validate_socket_path
from .gateway import serve
from .jev import Jev, JevError
from .providers import provider_names
from .setup import setup_gateway, teardown_gateway
from .service import Director


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="omarchy-director",
        description="Plan and apply reversible Omarchy desktop actions.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="show visible desktop state and scene names")
    planning = commands.add_parser("plan", help="prepare but do not execute a typed plan"); planning.add_argument("--query", required=True)
    executing = commands.add_parser("execute", help="execute a prepared plan token"); executing.add_argument("--token", required=True)
    commands.add_parser("undo", help="undo the latest reversible execution")
    history = commands.add_parser("history", help="show bounded execution history"); history.add_argument("--limit", type=int, default=20)
    diagnostics = commands.add_parser("diagnostics", help="show recent plans, failures, and execution summaries"); diagnostics.add_argument("--limit", type=int, default=20)
    scenes = commands.add_parser("scenes", help="manage durable semantic scenes"); scene_commands = scenes.add_subparsers(dest="scene_command", required=True)
    scene_commands.add_parser("list", help="list saved scenes")
    for action in ("save", "update", "delete", "apply"):
        scene = scene_commands.add_parser(action, help=f"{action} a named scene"); scene.add_argument("--name", required=True)
    commands.add_parser("doctor", help="check Omarchy, Hyprland, and Jev connectivity")
    setup = commands.add_parser("setup", help="configure and start the private local Jev gateway")
    setup.add_argument("--provider", choices=provider_names(), default="openrouter")
    setup.add_argument("--key-stdin", action="store_true", help="read the OpenRouter key from stdin")
    setup.add_argument("--no-start", action="store_true", help=argparse.SUPPRESS)
    teardown = commands.add_parser("teardown", help="remove the Director Jev service")
    teardown.add_argument("--purge-key", action="store_true", help="also remove the stored OpenRouter credential")
    gateway = commands.add_parser("gateway", help=argparse.SUPPRESS)
    gateway.add_argument("gateway_command", choices=("serve",))
    configure = commands.add_parser("configure", help="show or update user configuration")
    configure.add_argument("--jev-socket", metavar="PATH")
    configure.add_argument("--voice-mode", choices=("preview", "yolo"))
    configure.add_argument("--app-alias", action="append", default=[], metavar="NAME=DESKTOP_ID")
    configure.add_argument("--window-alias", action="append", default=[], metavar="NAME=CLASS_OR_TITLE")
    configure.add_argument("--remove-app-alias", action="append", default=[], metavar="NAME")
    configure.add_argument("--remove-window-alias", action="append", default=[], metavar="NAME")
    configure.add_argument("--yolo-allow", metavar="CSV", help="narrow the hard safety allowlist")
    configure.add_argument("--show", action="store_true")
    try:
        args = parser.parse_args(argv)
        if args.command == "gateway":
            serve()
            return 0
        if args.command == "setup":
            command = Path(__file__).resolve().parents[1] / "bin" / "omarchy-director"
            result = {"ok": True, **setup_gateway(command, provider_name=args.provider, key_stdin=args.key_stdin, start=not args.no_start)}
        elif args.command == "teardown":
            result = {"ok": True, **teardown_gateway(purge_key=args.purge_key)}
        elif args.command == "doctor":
            candidates = jev_socket_candidates()
            selected = next((path for path in candidates if Path(path).exists()), candidates[0] if candidates else "")
            checks: dict[str, bool] = {
                "hyprland": bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")),
                "jev_socket": bool(selected and Path(selected).exists() and stat.S_ISSOCK(os.stat(selected).st_mode)),
                "omarchy": shutil.which("omarchy") is not None,
            }
            gateway_health: dict[str, object] = {}
            if checks["jev_socket"]:
                try:
                    gateway_health = Jev(selected).health(upstream=True)
                except JevError:
                    checks["jev_ready"] = False
                else:
                    checks["jev_ready"] = True
            else:
                checks["jev_ready"] = False
            result = {"ok": all(checks.values()), "version": __version__, "checks": checks, "jev_socket": selected, "jev": gateway_health, "config": str(config_path())}
        elif args.command == "configure":
            values = load_config()
            if args.jev_socket: values["jev_socket_path"] = validate_socket_path(args.jev_socket)
            if args.voice_mode: values["voice_mode"] = args.voice_mode
            for assignment in args.app_alias: set_alias(values, "apps", assignment)
            for assignment in args.window_alias: set_alias(values, "windows", assignment)
            for alias in args.remove_app_alias: remove_alias(values, "apps", alias)
            for alias in args.remove_window_alias: remove_alias(values, "windows", alias)
            if args.yolo_allow is not None:
                values["yolo_allow"] = [item.strip() for item in args.yolo_allow.split(",") if item.strip()]
            changed = any((args.jev_socket, args.voice_mode, args.app_alias, args.window_alias, args.remove_app_alias, args.remove_window_alias, args.yolo_allow is not None))
            path = save_config(values) if changed else config_path()
            result = {"ok": True, "config": str(path), "values": normalized_config(values)}
        else:
            director = Director()
            if args.command == "status": result = {"ok": True, "status": director.status()}
            elif args.command == "plan": result = {"ok": True, "plan": director.plan(args.query).to_dict(set(director.config["yolo_allow"]))}
            elif args.command == "execute": result = {"ok": True, **director.execute(args.token)}
            elif args.command == "undo": result = {"ok": True, **director.undo()}
            elif args.command == "history": result = {"ok": True, "items": director.store.history()[-max(0, args.limit):]}
            elif args.command == "diagnostics":
                limit = max(0, args.limit)
                recent_plans = director.store.diagnostics()[-limit:] if limit else []
                recent_history = director.store.history()[-limit:] if limit else []
                plans = [{key: plan.get(key) for key in ("created_at", "query", "confidence", "executable", "summary", "warnings", "steps")} for plan in recent_plans]
                history = [{key: item.get(key) for key in ("at", "summary", "undo_of")} for item in recent_history]
                result = {"ok": True, "plans": plans, "history": history}
            elif args.scene_command == "list": result = {"ok": True, "items": director.scene_manager.list()}
            elif args.scene_command == "save": result = {"ok": True, "scene": director._capture_named_scene(args.name, False)}
            elif args.scene_command == "update": result = {"ok": True, "scene": director._capture_named_scene(args.name, True)}
            elif args.scene_command == "delete":
                plan = director.plan(f"delete scene {args.name}")
                if not plan.executable: raise ValueError("scene cannot be deleted")
                result = {"ok": True, "deleted": True, **director.execute(plan.token)}
            else:
                plan = director.plan(f"activate {args.name}")
                if not plan.executable: raise ValueError("scene cannot be applied")
                result = {"ok": True, **director.execute(plan.token)}
        print(json.dumps(result, separators=(",", ":")))
        return 0 if result.get("ok", True) else 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
