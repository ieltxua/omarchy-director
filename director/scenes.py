"""Address-free scene capture, persistence and deterministic window matching."""

from __future__ import annotations

from copy import deepcopy
import re
import unicodedata
from typing import Any, Iterable

from .store import Store

_NAME_MAX = 64
_TITLE_MAX = 120


def normalize_scene_name(value: str) -> str:
    """Return the stable, filesystem-independent key for a user scene name."""
    if not isinstance(value, str):
        raise ValueError("scene name must be text")
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.casefold()).strip("-")
    if not normalized or len(normalized) > _NAME_MAX:
        raise ValueError(f"scene name must contain 1 to {_NAME_MAX} letters or numbers")
    return normalized


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:limit] if value else None


def _workspace(client: dict[str, Any]) -> dict[str, Any]:
    raw = client.get("workspace")
    raw = raw if isinstance(raw, dict) else {}
    result: dict[str, Any] = {}
    if isinstance(raw.get("id"), int) and not isinstance(raw.get("id"), bool):
        result["id"] = raw["id"]
    name = _text(raw.get("name"), 80)
    if name:
        result["name"] = name
    return result


def window_spec(client: dict[str, Any]) -> dict[str, Any] | None:
    """Make a semantic scene spec.  Hyprland addresses are intentionally omitted."""
    window_class = _text(client.get("class"), 120)
    if not window_class:
        return None
    result: dict[str, Any] = {"class": window_class, "workspace": _workspace(client)}
    initial_class = _text(client.get("initialClass", client.get("initial_class")), 120)
    title = _text(client.get("title"), _TITLE_MAX)
    if initial_class:
        result["initial_class"] = initial_class
    if title:
        result["title_hint"] = title
    for key in ("floating", "fullscreen"):
        if isinstance(client.get(key), bool):
            result[key] = client[key]
    for key in ("at", "size"):
        value = client.get(key)
        if isinstance(value, list) and len(value) == 2 and all(isinstance(item, int) and not isinstance(item, bool) for item in value):
            result[key] = list(value)
    return result


def _selector(spec: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(spec[key]) for key in ("class", "initial_class", "title_hint", "workspace") if key in spec}


def capture_scene(state: dict[str, Any]) -> dict[str, Any]:
    """Capture valid current clients in their reported order, never their addresses."""
    raw_clients = state.get("clients", []) if isinstance(state, dict) else []
    captured = [
        (client, spec)
        for client in raw_clients
        if isinstance(client, dict)
        if (spec := window_spec(client))
    ]
    windows = [spec for _, spec in captured]
    active = state.get("active", {}) if isinstance(state, dict) else {}
    active_address = active.get("address") if isinstance(active, dict) else None
    active_index = next((index for index, (client, _) in enumerate(captured) if client.get("address") == active_address), None)
    scene: dict[str, Any] = {"version": 1, "windows": windows}
    if active_index is not None:
        active_spec = windows[active_index]
        selector = _selector(active_spec)
        # occurrence disambiguates otherwise identical terminals without saving an address.
        selector["occurrence"] = sum(1 for spec in windows[:active_index] if _selector(spec) == _selector(active_spec))
        scene["active_window"] = selector
    return scene


def _matches_class(spec: dict[str, Any], client: dict[str, Any]) -> bool:
    return _text(spec.get("class"), 120) is not None and _text(spec.get("class"), 120).casefold() == (_text(client.get("class"), 120) or "").casefold()


def _score(spec: dict[str, Any], client: dict[str, Any]) -> int:
    score = 100
    saved_initial = _text(spec.get("initial_class"), 120)
    current_initial = _text(client.get("initialClass", client.get("initial_class")), 120)
    if saved_initial and current_initial:
        score += 25 if saved_initial.casefold() == current_initial.casefold() else -25
    saved_title, current_title = _text(spec.get("title_hint"), _TITLE_MAX), _text(client.get("title"), _TITLE_MAX)
    if saved_title and current_title:
        score += 45 if saved_title.casefold() == current_title.casefold() else (20 if saved_title.casefold() in current_title.casefold() else -20)
    saved_workspace, current_workspace = spec.get("workspace", {}), _workspace(client)
    if isinstance(saved_workspace, dict):
        if saved_workspace.get("id") == current_workspace.get("id") and "id" in saved_workspace:
            score += 15
        elif saved_workspace.get("name") == current_workspace.get("name") and saved_workspace.get("name"):
            score += 10
    for key in ("floating", "fullscreen"):
        if key in spec and spec.get(key) == client.get(key):
            score += 3
    return score


def match_window_specs(specs: Iterable[dict[str, Any]], clients: Iterable[dict[str, Any]]) -> dict[str, list[Any]]:
    """Match each saved spec at most once; a live client is never reused."""
    saved = [deepcopy(spec) for spec in specs if isinstance(spec, dict) and _text(spec.get("class"), 120)]
    current = [client for client in clients if isinstance(client, dict)]
    # Choose the strongest pair globally so generic duplicate classes cannot steal a titled one.
    remaining_specs = dict(enumerate(saved))
    remaining_clients = dict(enumerate(current))
    pairs: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    while remaining_specs and remaining_clients:
        candidates = [
            (_score(spec, client), spec_index, client_index, spec, client)
            for spec_index, spec in remaining_specs.items()
            for client_index, client in remaining_clients.items()
            if _matches_class(spec, client)
        ]
        if not candidates:
            break
        _, index, position, spec, client = min(
            candidates,
            key=lambda item: (-item[0], item[1], str(item[4].get("address", "")), item[2]),
        )
        del remaining_specs[index]
        del remaining_clients[position]
        pairs.append((index, spec, client))
    return {
        "matches": [{"spec": spec, "client": client} for _, spec, client in sorted(pairs)],
        "missing": [spec for _, spec in sorted(remaining_specs.items())],
    }


class SceneStore:
    """Validated scene CRUD backed only by Store's atomic public scene methods."""

    def __init__(self, store: Store):
        self.store = store

    def list(self) -> list[dict[str, Any]]:
        return [self.store.get_scene(name) for name in self.store.list_scenes()]

    def get(self, name: str) -> dict[str, Any] | None:
        return self.store.get_scene(normalize_scene_name(name))

    def save(self, name: str, scene: dict[str, Any]) -> dict[str, Any]:
        key = normalize_scene_name(name)
        if not isinstance(scene, dict) or not isinstance(scene.get("windows"), list):
            raise ValueError("scene must contain a windows list")
        saved = deepcopy(scene)
        saved["name"] = key
        self.store.save_scene(key, saved)
        return deepcopy(saved)

    def update(self, name: str, scene: dict[str, Any]) -> dict[str, Any]:
        if self.get(name) is None:
            raise KeyError(normalize_scene_name(name))
        return self.save(name, scene)

    def delete(self, name: str) -> bool:
        return self.store.delete_scene(normalize_scene_name(name))


class SceneManager:
    """Captures/restores matching inputs; execution remains the Director's responsibility."""

    def __init__(self, hypr: Any, scenes: SceneStore | Store):
        self.hypr = hypr
        self.scenes = scenes if isinstance(scenes, SceneStore) else SceneStore(scenes)

    def capture(self, name: str) -> dict[str, Any]:
        return self.scenes.save(name, capture_scene(self.hypr.state()))

    def update(self, name: str) -> dict[str, Any]:
        return self.scenes.update(name, capture_scene(self.hypr.state()))

    def list(self) -> list[dict[str, Any]]:
        return self.scenes.list()

    def get(self, name: str) -> dict[str, Any] | None:
        return self.scenes.get(name)

    def delete(self, name: str) -> bool:
        return self.scenes.delete(name)

    def resolve(self, name: str, state: dict[str, Any] | None = None) -> dict[str, list[Any]]:
        scene = self.scenes.get(name)
        if scene is None:
            raise KeyError(normalize_scene_name(name))
        current = state if state is not None else self.hypr.state()
        clients = current.get("clients", []) if isinstance(current, dict) else []
        return match_window_specs(scene["windows"], clients)
