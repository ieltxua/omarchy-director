"""Deterministic in-memory collaborators for Director generative tests.

The harness deliberately implements the small Hyprland/Store protocols used by
``director.service.Director``.  It is not a second implementation of Director:
each mutator changes a Hyprland-shaped client record, so production planning,
execution and undo code remain under test.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


def client(
    address: str,
    title: str,
    window_class: str,
    workspace: int,
    *,
    floating: bool = False,
    fullscreen: bool = False,
    at: tuple[int, int] = (20, 30),
    size: tuple[int, int] = (800, 600),
) -> dict[str, Any]:
    """Build a realistic, independently mutable Hyprland client response."""
    return {
        "address": address,
        "title": title,
        "class": window_class,
        "initialClass": window_class,
        "workspace": {"id": workspace, "name": str(workspace)},
        "floating": floating,
        "fullscreen": fullscreen,
        "at": list(at),
        "size": list(size),
        "focusHistoryID": 0,
    }


class MemoryStore:
    """Store-compatible, process-local persistence without filesystem overhead."""

    def __init__(self) -> None:
        self._plans: dict[str, dict[str, Any]] = {}
        self._history: list[dict[str, Any]] = []
        self._scenes: dict[str, dict[str, Any]] = {}

    def save_plan(self, plan: dict[str, Any]) -> None:
        self._plans[str(plan["token"])] = deepcopy(plan)

    def get_plan(self, token: str) -> dict[str, Any] | None:
        plan = self._plans.get(token)
        return deepcopy(plan) if plan is not None else None

    def remove_plan(self, token: str) -> None:
        self._plans.pop(token, None)

    def history(self) -> list[dict[str, Any]]:
        return deepcopy(self._history)

    def append_history(self, record: dict[str, Any]) -> None:
        self._history.append(deepcopy(record))

    def list_scenes(self) -> dict[str, dict[str, Any]]:
        return deepcopy(self._scenes)

    def get_scene(self, name: str) -> dict[str, Any] | None:
        scene = self._scenes.get(name)
        return deepcopy(scene) if scene is not None else None

    def save_scene(self, name: str, scene: dict[str, Any]) -> None:
        self._scenes[name] = deepcopy(scene)

    def delete_scene(self, name: str) -> bool:
        if name not in self._scenes:
            return False
        del self._scenes[name]
        return True


class InMemoryHyprland:
    """A stateful Hyprland protocol double with optional one-shot failures."""

    def __init__(self, clients: list[dict[str, Any]], active: str | None = None) -> None:
        self.clients = deepcopy(clients)
        self.active = active or (str(clients[0]["address"]) if clients else "")
        self.focused_workspace = self._client(self.active).get("workspace", {}).get("id", 1) if self.active else 1
        self.calls: list[tuple[Any, ...]] = []
        self.fail_next: str | None = None
        # Director's default NativeCapabilities only accesses this attribute at construction.
        self.runner = lambda *args, **kwargs: None

    def _client(self, address: str) -> dict[str, Any]:
        found = next((item for item in self.clients if item.get("address") == address), None)
        if found is None:
            raise RuntimeError(f"unknown in-memory window {address}")
        return found

    def _maybe_fail(self, method: str) -> None:
        if self.fail_next == method:
            self.fail_next = None
            raise RuntimeError(f"injected {method} failure")

    def state(self) -> dict[str, Any]:
        workspace_ids = sorted({int(item["workspace"]["id"]) for item in self.clients})
        rows = [
            {"id": workspace, "name": str(workspace), "windows": sum(item["workspace"]["id"] == workspace for item in self.clients)}
            for workspace in workspace_ids
        ]
        if self.focused_workspace not in workspace_ids:
            rows.append({"id": self.focused_workspace, "name": str(self.focused_workspace), "windows": 0})
        active = next((item for item in self.clients if item.get("address") == self.active), {})
        return deepcopy({
            "clients": self.clients,
            "workspaces": sorted(rows, key=lambda row: row["id"]),
            "monitors": [{"focused": True, "activeWorkspace": {"id": self.focused_workspace, "name": str(self.focused_workspace)}}],
            "active": active,
        })

    def remove(self, address: str) -> None:
        self.clients = [item for item in self.clients if item.get("address") != address]
        if self.active == address:
            self.active = str(self.clients[0].get("address")) if self.clients else ""

    def focus_window(self, address: str) -> None:
        self._maybe_fail("focus_window")
        self._client(address)
        self.calls.append(("focus_window", address))
        self.active = address

    def move_window(self, address: str, workspace: int | str, follow: bool = False) -> None:
        self._maybe_fail("move_window")
        if not isinstance(workspace, int) or workspace < 1:
            raise RuntimeError("the generative harness only models numbered workspaces")
        self.calls.append(("move_window", address, workspace, follow))
        current = self._client(address)
        current["workspace"] = {"id": workspace, "name": str(workspace)}
        if follow:
            self.focused_workspace = workspace

    def focus_workspace(self, workspace: int) -> None:
        self._maybe_fail("focus_workspace")
        self.calls.append(("focus_workspace", workspace))
        self.focused_workspace = workspace

    def set_floating(self, address: str, floating: bool) -> None:
        self._maybe_fail("set_floating")
        current = self._client(address)
        if current["floating"] == floating:
            return
        self.calls.append(("set_floating", address, floating))
        current["floating"] = floating

    def set_fullscreen(self, address: str, fullscreen: bool) -> None:
        self._maybe_fail("set_fullscreen")
        current = self._client(address)
        if current["fullscreen"] == fullscreen:
            return
        self.calls.append(("set_fullscreen", address, fullscreen))
        current["fullscreen"] = fullscreen

    def restore_geometry(self, address: str, at: list[int], size: list[int]) -> None:
        self._maybe_fail("restore_geometry")
        current = self._client(address)
        self.calls.append(("restore_geometry", address, tuple(at), tuple(size)))
        current["at"], current["size"] = list(at), list(size)

    def resize_window(self, address: str, width: int, height: int) -> None:
        self._maybe_fail("resize_window")
        current = self._client(address)
        self.calls.append(("resize_window", address, width, height))
        current["size"] = [width, height]

    def swap_window(self, address: str, direction: str) -> None:
        self._maybe_fail("swap_window")
        current = self._client(address)
        peers = [item for item in self.clients if item["workspace"] == current["workspace"] and item.get("address") != address]
        self.calls.append(("swap_window", address, direction))
        if peers:
            peer = sorted(peers, key=lambda item: str(item.get("address")))[0]
            current["at"], peer["at"] = peer["at"], current["at"]
            current["size"], peer["size"] = peer["size"], current["size"]


@dataclass
class StaticJev:
    """Jev-shaped deterministic responder used for planning assertions."""

    answers: dict[str, Any]

    def decide(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        self.last_state = deepcopy(state)
        self.last_questions = deepcopy(questions)
        return deepcopy(self.answers)


def answer_set(intent: str, *, windows: list[str] | tuple[str, ...] = (), workspace: str = "keep") -> dict[str, Any]:
    """Return a high-confidence normal window-action answer schema."""
    result: dict[str, Any] = {
        "intent": {"type": "choice", "choice": intent, "confidence": 0.96},
        "layout": {"type": "choice", "choice": "tile", "confidence": 0.96},
        "workspace": {"type": "choice", "choice": workspace, "confidence": 0.96},
        "workspace_view": {"type": "choice", "choice": "stay", "confidence": 0.96},
    }
    result.update({f"window:{address}": {"type": "noul", "noul": 0.96} for address in windows})
    return result


def window_fingerprint(hypr: InMemoryHyprland, address: str) -> tuple[Any, ...]:
    """Stable subset of a client used by execute/undo invariant assertions."""
    current = hypr._client(address)
    return (
        current["workspace"]["id"], current["floating"], current["fullscreen"],
        tuple(current["at"]), tuple(current["size"]), hypr.active, hypr.focused_workspace,
    )
