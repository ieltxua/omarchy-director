from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import sys

from . import __version__
from .config import config_path, jev_socket_candidates, load_config, save_config, validate_socket_path
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
    scenes = commands.add_parser("scenes", help="manage durable semantic scenes"); scene_commands = scenes.add_subparsers(dest="scene_command", required=True)
    scene_commands.add_parser("list", help="list saved scenes")
    for action in ("save", "update", "delete", "apply"):
        scene = scene_commands.add_parser(action, help=f"{action} a named scene"); scene.add_argument("--name", required=True)
    commands.add_parser("doctor", help="check Omarchy, Hyprland, and Jev connectivity")
    configure = commands.add_parser("configure", help="show or update user configuration")
    configure.add_argument("--jev-socket", metavar="PATH")
    configure.add_argument("--show", action="store_true")
    try:
        args = parser.parse_args(argv)
        if args.command == "doctor":
            candidates = jev_socket_candidates()
            selected = next((path for path in candidates if Path(path).exists()), candidates[0] if candidates else "")
            checks = {
                "hyprland": bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")),
                "jev_socket": bool(selected and Path(selected).exists() and stat.S_ISSOCK(os.stat(selected).st_mode)),
                "omarchy": shutil.which("omarchy") is not None,
            }
            result = {"ok": all(checks.values()), "version": __version__, "checks": checks, "jev_socket": selected, "config": str(config_path())}
        elif args.command == "configure":
            values = load_config()
            if args.jev_socket: values["jev_socket_path"] = validate_socket_path(args.jev_socket)
            path = save_config(values) if args.jev_socket else config_path()
            result = {"ok": True, "config": str(path), "values": values}
        else:
            director = Director()
            if args.command == "status": result = {"ok": True, "status": director.status()}
            elif args.command == "plan": result = {"ok": True, "plan": director.plan(args.query).to_dict()}
            elif args.command == "execute": result = {"ok": True, **director.execute(args.token)}
            elif args.command == "undo": result = {"ok": True, **director.undo()}
            elif args.command == "history": result = {"ok": True, "items": director.store.history()[-max(0, args.limit):]}
            elif args.scene_command == "list": result = {"ok": True, "items": director.scene_manager.list()}
            elif args.scene_command == "save": result = {"ok": True, "scene": director._capture_named_scene(args.name, False)}
            elif args.scene_command == "update": result = {"ok": True, "scene": director._capture_named_scene(args.name, True)}
            elif args.scene_command == "delete": result = {"ok": True, "deleted": director.scene_manager.delete(args.name)}
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
