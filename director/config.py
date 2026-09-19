from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any


DEFAULT_YOLO_ALLOW = [
    "focus", "move", "arrange", "float", "tile", "fullscreen_on", "fullscreen_off", "resize", "swap",
    "scene_save", "scene_delete", "scene_list", "workspace_focus", "nightlight_toggle", "dnd_toggle",
    "volume_mute", "mic_mute",
]


def config_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "omarchy-director" / "config.json"


def load_config() -> dict[str, Any]:
    path = config_path()
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def normalized_config(values: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = values if isinstance(values, dict) else load_config()
    aliases = raw.get("aliases") if isinstance(raw.get("aliases"), dict) else {}

    def alias_map(kind: str) -> dict[str, str]:
        source = aliases.get(kind) if isinstance(aliases.get(kind), dict) else {}
        return {
            str(alias).strip().casefold(): str(target).strip()
            for alias, target in source.items()
            if isinstance(alias, str) and isinstance(target, str)
            and 1 <= len(alias.strip()) <= 40 and 1 <= len(target.strip()) <= 200
        }

    requested = raw.get("yolo_allow")
    yolo_allow = [value for value in requested if isinstance(value, str)] if isinstance(requested, list) else list(DEFAULT_YOLO_ALLOW)
    return {
        **raw,
        "voice_mode": raw.get("voice_mode") if raw.get("voice_mode") in {"preview", "yolo"} else "preview",
        "aliases": {"apps": alias_map("apps"), "windows": alias_map("windows")},
        "yolo_allow": list(dict.fromkeys(yolo_allow)),
    }


def set_alias(values: dict[str, Any], kind: str, assignment: str) -> None:
    if "=" not in assignment:
        raise ValueError("Alias must use NAME=TARGET")
    alias, target = (part.strip() for part in assignment.split("=", 1))
    if not (1 <= len(alias) <= 40 and 1 <= len(target) <= 200):
        raise ValueError("Alias name or target is invalid")
    aliases = values.setdefault("aliases", {})
    if not isinstance(aliases, dict):
        aliases = values["aliases"] = {}
    mapping = aliases.setdefault(kind, {})
    if not isinstance(mapping, dict):
        mapping = aliases[kind] = {}
    mapping[alias.casefold()] = target


def remove_alias(values: dict[str, Any], kind: str, alias: str) -> None:
    aliases = values.get("aliases")
    mapping = aliases.get(kind) if isinstance(aliases, dict) else None
    if isinstance(mapping, dict):
        mapping.pop(alias.strip().casefold(), None)


def save_config(values: dict[str, Any]) -> Path:
    path = config_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".config.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(values, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return path


def validate_socket_path(value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute() or "\x00" in value:
        raise ValueError("Jev socket path must be absolute")
    return str(path)


def jev_socket_candidates() -> list[str]:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    configured = load_config().get("jev_socket_path")
    ordered = [
        os.environ.get("JEV_SOCKET_PATH"),
        configured if isinstance(configured, str) else None,
        str(runtime / "jev-gateway" / "jev.sock"),
        str(runtime / "agent-lab" / "jev.sock"),
        str(runtime / "jev.sock"),
    ]
    return list(dict.fromkeys(value for value in ordered if value))


def resolve_jev_socket() -> str:
    candidates = jev_socket_candidates()
    for candidate in candidates:
        try:
            if stat.S_ISSOCK(os.stat(candidate).st_mode):
                return candidate
        except OSError:
            continue
    return candidates[0]
