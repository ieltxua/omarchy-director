from __future__ import annotations

import json
import os
import stat
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, base: str | Path | None = None):
        state_home = Path(base or os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        self.base = state_home / "omarchy-director"
        self.base.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.base, 0o700)

    def _path(self, name: str) -> Path:
        return self.base / name

    def _read(self, name: str, default: Any) -> Any:
        try:
            with self._path(name).open(encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            return default

    def _write(self, name: str, value: Any) -> None:
        fd, temporary = tempfile.mkstemp(prefix=".tmp-", dir=self.base)
        try:
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path(name))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def save_plan(self, plan: dict[str, Any]) -> None:
        plans = self._read("plans.json", {})
        cutoff = time.time() - 600
        plans = {
            token: saved for token, saved in plans.items()
            if isinstance(saved, dict) and float(saved.get("created_at", 0)) >= cutoff
        }
        plans[plan["token"]] = plan
        plans = dict(sorted(plans.items(), key=lambda item: float(item[1].get("created_at", 0)))[-20:])
        self._write("plans.json", plans)

    def get_plan(self, token: str) -> dict[str, Any] | None:
        plan = self._read("plans.json", {}).get(token)
        if not isinstance(plan, dict) or float(plan.get("created_at", 0)) < time.time() - 600:
            return None
        return plan

    def plans(self) -> list[dict[str, Any]]:
        plans = self._read("plans.json", {})
        if not isinstance(plans, dict):
            return []
        cutoff = time.time() - 600
        return sorted(
            (deepcopy(plan) for plan in plans.values() if isinstance(plan, dict) and float(plan.get("created_at", 0)) >= cutoff),
            key=lambda plan: float(plan.get("created_at", 0)),
        )

    def remove_plan(self, token: str) -> None:
        plans = self._read("plans.json", {})
        plans.pop(token, None)
        self._write("plans.json", plans)

    def history(self) -> list[dict[str, Any]]:
        return self._read("history.json", [])

    def append_history(self, record: dict[str, Any]) -> None:
        history = self.history()
        history.append(record)
        self._write("history.json", history[-50:])

    # Scenes deliberately have their own file rather than sharing the bounded
    # plan/history stores.  They are user-created state and must survive plan
    # expiry and undo-history trimming.
    def list_scenes(self) -> dict[str, dict[str, Any]]:
        raw = self._read("scenes.json", {})
        if not isinstance(raw, dict):
            return {}
        return {
            name: deepcopy(scene)
            for name, scene in sorted(raw.items())
            if isinstance(name, str) and isinstance(scene, dict)
        }

    def get_scene(self, name: str) -> dict[str, Any] | None:
        scene = self.list_scenes().get(name)
        return deepcopy(scene) if scene is not None else None

    def save_scene(self, name: str, scene: dict[str, Any]) -> None:
        if not isinstance(name, str) or not isinstance(scene, dict):
            raise ValueError("invalid scene")
        scenes = self.list_scenes()
        scenes[name] = deepcopy(scene)
        self._write("scenes.json", scenes)

    def delete_scene(self, name: str) -> bool:
        scenes = self.list_scenes()
        if name not in scenes:
            return False
        del scenes[name]
        self._write("scenes.json", scenes)
        return True
