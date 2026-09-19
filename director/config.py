from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any


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


def save_config(values: dict[str, Any]) -> Path:
    path = config_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, indent=2, sort_keys=True) + "\n")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
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
