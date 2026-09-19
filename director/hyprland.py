from __future__ import annotations

import json
import re
import subprocess
from typing import Any


class HyprlandError(RuntimeError):
    pass


class Hyprland:
    def __init__(self, runner=subprocess.run):
        self.runner = runner

    def json(self, noun: str) -> Any:
        result = self.runner(["hyprctl", "-j", noun], capture_output=True, text=True, check=False)
        if result.returncode:
            raise HyprlandError(result.stderr.strip() or "hyprctl unavailable")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise HyprlandError("hyprctl returned invalid JSON") from exc

    def state(self) -> dict[str, Any]:
        clients = self.json("clients")
        workspaces = self.json("workspaces")
        monitors = self.json("monitors")
        active = self.json("activewindow")
        if not isinstance(clients, list):
            raise HyprlandError("invalid client list")
        return {"clients": clients, "workspaces": workspaces, "monitors": monitors, "active": active}

    @staticmethod
    def _address(value: str) -> str:
        if not re.fullmatch(r"0x[0-9a-fA-F]+", value):
            raise HyprlandError("invalid Hyprland window address")
        return value.lower()

    @staticmethod
    def _workspace(value: int | str) -> str:
        if isinstance(value, int) and value > 0:
            return str(value)
        if isinstance(value, str) and re.fullmatch(r"name:[A-Za-z0-9_. -]{1,80}", value):
            return value
        raise HyprlandError("invalid Hyprland workspace")

    def eval_dispatch(self, dispatcher: str) -> None:
        # Hyprland 0.56 exposes dispatchers as typed Lua objects. Values are
        # validated above and JSON quoting is valid Lua string syntax.
        result = self.runner(
            ["hyprctl", "eval", f"return hl.dispatch({dispatcher})"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise HyprlandError(result.stderr.strip() or result.stdout.strip() or "Hyprland dispatch failed")

    def focus_window(self, address: str) -> None:
        selector = f"address:{self._address(address)}"
        self.eval_dispatch(f"hl.dsp.focus({{ window = hl.get_window({json.dumps(selector)}) }})")

    def move_window(self, address: str, workspace: int | str, follow: bool = False) -> None:
        selector = f"address:{self._address(address)}"
        target = self._workspace(workspace)
        follow_lua = "true" if follow else "false"
        self.eval_dispatch(
            f"hl.dsp.window.move({{ workspace = {json.dumps(target)}, window = hl.get_window({json.dumps(selector)}), follow = {follow_lua} }})"
        )

    def focus_workspace(self, workspace: int | str) -> None:
        target = self._workspace(workspace)
        self.eval_dispatch(f"hl.dsp.focus({{ workspace = {json.dumps(target)} }})")

    def _client(self, address: str) -> dict[str, Any]:
        wanted = self._address(address)
        clients = self.json("clients")
        if not isinstance(clients, list):
            raise HyprlandError("invalid client list")
        client = next((item for item in clients if str(item.get("address", "")).lower() == wanted), None)
        if not isinstance(client, dict):
            raise HyprlandError("window is no longer available")
        return client

    def set_floating(self, address: str, floating: bool) -> None:
        selector = f"address:{self._address(address)}"
        # Omarchy's installed typed dispatcher documents `toggle` for floating;
        # unknown action strings can still toggle. Read first so this is an
        # idempotent setter instead of relying on undocumented set/unset values.
        if bool(self._client(address).get("floating")) == floating:
            return
        self.eval_dispatch(f"hl.dsp.window.float({{ action = \"toggle\", window = hl.get_window({json.dumps(selector)}) }})")

    def set_fullscreen(self, address: str, fullscreen: bool) -> None:
        selector = f"address:{self._address(address)}"
        if bool(self._client(address).get("fullscreen")) == fullscreen:
            return
        self.eval_dispatch(
            f"hl.dsp.window.fullscreen({{ mode = \"fullscreen\", action = \"toggle\", window = hl.get_window({json.dumps(selector)}) }})"
        )

    def restore_geometry(self, address: str, at: list[int], size: list[int]) -> None:
        selector = f"address:{self._address(address)}"
        if len(at) != 2 or len(size) != 2 or not all(isinstance(value, int) for value in [*at, *size]):
            raise HyprlandError("invalid window geometry")
        self.eval_dispatch(
            f"hl.dsp.window.move({{ x = {at[0]}, y = {at[1]}, relative = false, window = hl.get_window({json.dumps(selector)}) }})"
        )
        self.eval_dispatch(
            f"hl.dsp.window.resize({{ x = {size[0]}, y = {size[1]}, relative = false, window = hl.get_window({json.dumps(selector)}) }})"
        )
