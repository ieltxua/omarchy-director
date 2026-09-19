from __future__ import annotations

import secrets
import re
import time
from typing import Any

from .capabilities import CAPABILITY_CRITERIA, CapabilityError, NativeCapabilities
from .config import normalized_config
from .desktop import desktop_entries, launch
from .hyprland import Hyprland
from .jev import Jev, JevError
from .models import Plan, Step
from .scenes import SceneManager, capture_scene, match_window_specs, normalize_scene_name
from .security import redact_sensitive_text
from .store import Store

OPERATIONS = ("focus", "launch", "move", "arrange", "launch_arrange", "float", "tile", "fullscreen_on", "fullscreen_off", "resize_smaller", "resize_larger", "swap_left", "swap_right", "swap_up", "swap_down", "keep", "no_match")
LAYOUTS = ("tile", "keep", "no_match")
WORKSPACE_VIEWS = ("stay", "switch", "no_match")
MAX_WINDOWS, MAX_APPS, MIN_CONFIDENCE = 12, 12, 0.80


def _choice(prompt: str, criteria: dict[str, str]) -> dict[str, Any]:
    return {"type": "choice", "instructions": prompt, "criteria": criteria}


def _answer_choice(answers: dict[str, Any], question_id: str) -> tuple[str | None, float]:
    answer = answers.get(question_id, {})
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        return None, 0.0
    value, confidence = answer.get("choice", answer.get("value")), answer.get("confidence", 0)
    return (value if isinstance(value, str) else None, float(confidence) if isinstance(confidence, (int, float)) else 0.0)


def _selected_noul(answers: dict[str, Any], prefix: str, candidates: list[str], threshold: float = 0.85) -> list[str]:
    selected = []
    for candidate in candidates:
        answer = answers.get(f"{prefix}:{candidate}", {})
        probability = answer.get("noul", 0) if isinstance(answer, dict) and answer.get("type") == "noul" else 0
        if isinstance(probability, (int, float)) and probability >= threshold:
            selected.append(candidate)
    return selected


class Director:
    def __init__(self, hypr: Hyprland | None = None, jev: Jev | None = None, store: Store | None = None, launcher=launch, sleeper=time.sleep, native: NativeCapabilities | None = None):
        self.hypr, self.jev, self.store, self.launcher, self.sleeper = hypr or Hyprland(), jev or Jev(), store or Store(), launcher, sleeper
        self.native = native or NativeCapabilities(self.hypr.runner)
        self.config = normalized_config()
        self.scene_manager = SceneManager(self.hypr, self.store)
        self._step_warnings: list[str] = []

    def status(self) -> dict[str, Any]:
        state = self.hypr.state()
        return {"windows": [{"address": c.get("address"), "title": c.get("title", ""), "workspace": c.get("workspace", {}).get("id")} for c in state["clients"]], "workspaces": state["workspaces"], "monitors": state["monitors"], "scenes": [scene["name"] for scene in self.scene_manager.list()]}

    def _store_plan(self, plan: Plan) -> Plan:
        safe_query = redact_sensitive_text(plan.query[:500])
        self.store.save_plan({**plan.to_dict(), "query": safe_query, "created_at": plan.created_at, "snapshot": plan.snapshot})
        append_diagnostic = getattr(self.store, "append_diagnostic", None)
        if append_diagnostic:
            append_diagnostic({
                "created_at": plan.created_at,
                "query": safe_query,
                "confidence": plan.confidence,
                "executable": plan.executable,
                "summary": plan.summary,
                "warnings": list(plan.warnings),
                "steps": [step.to_dict() for step in plan.steps],
            })
        return plan

    @staticmethod
    def _post_save(query: str) -> tuple[str, str | None]:
        match = re.search(r"\s+(?:and|y)\s+(?:save|remember|guarda|guardá|recordá)\s+(?:it\s+)?(?:as|como)\s+(.+?)\s*$", query, re.IGNORECASE)
        return (query[:match.start()].strip(), match.group(1).strip(" '\"")[:80]) if match else (query, None)

    @staticmethod
    def _scene_tail(query: str, verbs: str) -> str | None:
        match = re.match(rf"^\s*(?:{verbs})\s+(?:(?:this|the|current|my|esta|este|mi)\s+)?(?:(?:scene|setup|layout|desktop|escena|escritorio|configuraci[oó]n)\s+)?(?:(?:as|como|named|llamada?)\s+)?(.+?)\s*$", query, re.IGNORECASE)
        return match.group(1).strip(" '\"") if match else None

    def _scene_query_plan(self, query: str) -> Plan | None:
        lowered = query.strip().casefold()
        if not re.match(r"^(?:save|capture|remember|guarda|guardá|captura|capturá|recordá|update|overwrite|actualiza|actualizá|sobrescribe|sobrescribí|delete|remove|forget|elimina|eliminá|borra|borrá|olvida|olvidá|activate|load|restore|invoke|use|activa|activá|carga|cargá|restaura|restaurá|invoca|invocá|usa|usá|list|show|what are|lista|mostr[aá]|cu[aá]les son)\b", lowered):
            return None
        state = self.hypr.state()
        scene_rows = self.scene_manager.list()
        names = [scene["name"] for scene in scene_rows]
        if re.fullmatch(r"(?:list|show|what are|lista|mostr[aá]|cu[aá]les son)(?:\s+(?:my|mis|the|las))?\s+(?:scenes|setups|escenas|configuraciones)", lowered):
            label = ", ".join(names) if names else "Todavía no guardaste escenas"
            return self._store_plan(Plan(secrets.token_urlsafe(24), query, 1, f"Escenas: {label}", [Step("scene_list", label=label, params={"summary": label})], [], True, time.time(), {"windows": {}}))
        name = self._scene_tail(query, r"save|capture|remember|guarda|guardá|captura|capturá|recordá")
        if name:
            try: key = normalize_scene_name(name)
            except ValueError as exc: return self._store_plan(Plan(secrets.token_urlsafe(24), query, 0, "Nombre de escena inválido", [], [str(exc)], False, time.time()))
            update = self.scene_manager.get(key) is not None
            verb = "Actualizar" if update else "Guardar"
            return self._store_plan(Plan(secrets.token_urlsafe(24), query, 1, f"{verb} la escena {key}", [Step("scene_save", key, label=key, params={"update": update})], [], True, time.time(), {"windows": {}}))
        name = self._scene_tail(query, r"update|overwrite|actualiza|actualizá|sobrescribe|sobrescribí")
        if name:
            try: key = normalize_scene_name(name)
            except ValueError: key = ""
            exists = bool(key and self.scene_manager.get(key))
            warnings = [] if exists else ["Esa escena todavía no existe"]
            return self._store_plan(Plan(secrets.token_urlsafe(24), query, 1, f"Actualizar la escena {key or name}", [Step("scene_save", key, label=key, params={"update": True})] if exists else [], warnings, exists, time.time(), {"windows": {}}))
        name = self._scene_tail(query, r"delete|remove|forget|elimina|eliminá|borra|borrá|olvida|olvidá")
        if name:
            try: key = normalize_scene_name(name)
            except ValueError: key = ""
            exists = bool(key and self.scene_manager.get(key))
            warnings = [] if exists else ["No encontré esa escena"]
            return self._store_plan(Plan(secrets.token_urlsafe(24), query, 1, f"Eliminar la escena {key or name}", [Step("scene_delete", key, label=key)] if exists else [], warnings, exists, time.time(), {"windows": {}}))
        name = self._scene_tail(query, r"activate|load|restore|invoke|use|activa|activá|carga|cargá|restaura|restaurá|invoca|invocá|usa|usá")
        if not name: return None
        try: key = normalize_scene_name(name)
        except ValueError: key = ""
        scene = self.scene_manager.get(key) if key else None
        if not scene:
            explicit_scene = bool(re.search(r"\b(?:scene|setup|layout|desktop|escena|escritorio|configuraci[oó]n)\b", lowered))
            if not explicit_scene:
                return None
            return self._store_plan(Plan(secrets.token_urlsafe(24), query, 0, "No encontré esa escena", [], [f"Escenas disponibles: {', '.join(names) or 'ninguna'}"], False, time.time()))
        resolved = self.scene_manager.resolve(key, state)
        launchable = [spec for spec in resolved["missing"] if spec.get("desktop_id")]
        unavailable = [spec for spec in resolved["missing"] if not spec.get("desktop_id")]
        targets = [str(pair["client"].get("address")) for pair in resolved["matches"] if pair["client"].get("address")]
        snapshot = self._snapshot({str(client["address"]): client for client in state["clients"] if client.get("address")}, targets, state.get("active", {}))
        detail = f"{len(resolved['matches'])} abiertas"
        if launchable: detail += f", {len(launchable)} por abrir"
        warnings = [f"No podré reabrir {len(unavailable)} ventanas sin una app identificable"] if unavailable else []
        return self._store_plan(Plan(secrets.token_urlsafe(24), query, 1, f"Restaurar {key}: {detail}", [Step("scene_apply", key, label=key, params={"summary": f"Restaurar escena {key}"})], warnings, True, time.time(), snapshot))

    def _questions(self, clients: dict[str, dict[str, Any]], apps: dict[str, dict[str, str]], workspace_options: list[str], ranked_apps: list[str], themes: list[str], active_address: str | None = None) -> dict[str, dict[str, Any]]:
        questions = {
            "capability": _choice("Route the request to exactly one supported native desktop capability. Choose window_action for application/window manipulation and launching.", CAPABILITY_CRITERIA),
            "intent": _choice("Classify the requested safe window action. Do not use whether the user wants to follow a destination workspace to distinguish actions; workspace_view decides that separately.", {"focus": "Focus one existing selected window only", "launch": "Open selected allowlisted apps only", "move": "Relocate selected existing windows to a destination workspace without imposing a layout; includes poner, mover, mandar, llevar, aislar, or dejar solo", "arrange": "Gather selected existing windows onto a workspace and explicitly tile them together; juntar, ordenar, acomodar, or lado a lado implies this", "launch_arrange": "Open selected allowlisted apps then tile their identified new windows", "float": "Make selected existing windows floating", "tile": "Make selected existing windows tiled", "fullscreen_on": "Put selected existing windows into fullscreen", "fullscreen_off": "Exit fullscreen for selected existing windows", "resize_smaller": "Make exactly one selected existing window smaller, shrink it, or reduce its size", "resize_larger": "Make exactly one selected existing window larger, grow it, or increase its size", "swap_left": "Move or swap exactly one existing tiled window one position to the left", "swap_right": "Move or swap exactly one existing tiled window one position to the right", "swap_up": "Move or swap exactly one existing tiled window one position upward", "swap_down": "Move or swap exactly one existing tiled window one position downward", "keep": "No window action requested", "no_match": "Request is unclear or unsupported"}),
            "layout": _choice("For arrange, choose tile by default when windows should be gathered, joined, ordered, or side by side; otherwise keep/no_match.", {"tile": "Use Hyprland native tiled split", "keep": "Do not change layout", "no_match": "No layout can be safely inferred"}),
            "workspace": _choice("Choose the requested destination workspace or keep.", {option: f"Use {option}" for option in workspace_options}),
            "workspace_view": _choice("If windows are relocated, decide whether the user explicitly asks to follow them or switch the visible workspace.", {"stay": "Only put, move, send, or place windows there; do not change the user's current view", "switch": "Explicitly asks to go there, take me there, show the result, isolate, or leave me alone with the selected windows", "no_match": "The requested view behavior cannot be inferred"}),
            "theme": _choice("Choose the specifically requested installed Omarchy theme, or no_match.", {**{theme: f"Apply installed theme {theme}" for theme in themes}, "no_match": "No installed theme was requested"}),
        }
        for address in sorted(clients)[:MAX_WINDOWS]:
            client = clients[address]
            questions[f"window:{address}"] = {"type": "noul", "instructions": f"Does the request refer to this specific window? address={address}; class={str(client.get('class', ''))[:80]}; title={str(client.get('title', ''))[:120]}; workspace={client.get('workspace', {}).get('id')}; active={address == active_address}", "criteria": {"true": "The request selects this window, including a clear plural/group reference or a reference to the active/current window", "false": "The request does not select this window"}}
        for desktop_id in ranked_apps:
            questions[f"app:{desktop_id}"] = {"type": "noul", "instructions": f"Does the request ask to launch allowlisted app {desktop_id}?", "criteria": {"true": "Selected", "false": "Not selected"}}
        return questions

    @staticmethod
    def _app_match_score(query: str, app_id: str, app: dict[str, str]) -> int:
        tokens = {token for token in query.casefold().replace("-", " ").split() if len(token) > 1}
        haystack = " ".join(str(app.get(key, "")) for key in ("id", "name", "generic_name", "comment", "keywords")).casefold()
        return sum(token in haystack for token in tokens)

    @staticmethod
    def _rank_apps(query: str, apps: dict[str, dict[str, str]]) -> list[str]:
        def score(item: tuple[str, dict[str, str]]) -> tuple[int, str]:
            app_id, app = item
            return (-Director._app_match_score(query, app_id, app), app_id)
        ranked = sorted(apps.items(), key=score)
        strong = [app_id for app_id, app in ranked if -score((app_id, app))[0] > 0]
        # Named apps should not be diluted by unrelated fallback candidates.
        # A fallback catalog is only useful for genuinely generic requests.
        if strong:
            return strong[:MAX_APPS]
        return [app_id for app_id, _ in ranked[:MAX_APPS]]

    @staticmethod
    def _app_windows(app_id: str, apps: dict[str, dict[str, str]], clients: dict[str, dict[str, Any]]) -> list[str]:
        app = apps.get(app_id, {})
        expected = {str(app.get("startup_wm_class", "")).casefold(), str(app_id).casefold()}
        expected.discard("")
        matches = [address for address, client in clients.items() if str(client.get("class", "")).casefold() in expected]
        return sorted(matches, key=lambda address: int(clients[address].get("focusHistoryID", 999999)))

    @staticmethod
    def _explicit_apps(query: str, apps: dict[str, dict[str, str]], aliases: dict[str, str] | None = None) -> list[str]:
        normalized = " ".join(re.findall(r"[a-z0-9]+", query.casefold()))
        padded = f" {normalized} "
        matches: dict[str, str] = {}
        for app_id, app in apps.items():
            identities = {str(app_id), str(app.get("name", ""))}
            for identity in identities:
                candidate = " ".join(re.findall(r"[a-z0-9]+", identity.casefold()))
                if candidate and f" {candidate} " in padded:
                    if len(candidate) > len(matches.get(app_id, "")):
                        matches[app_id] = candidate
        for alias, app_id in (aliases or {}).items():
            candidate = " ".join(re.findall(r"[a-z0-9]+", alias.casefold()))
            if app_id in apps and candidate and f" {candidate} " in padded:
                matches[app_id] = candidate
        maximal = [app_id for app_id, identity in matches.items() if not any(identity != other and f" {identity} " in f" {other} " for other in matches.values())]
        return sorted(maximal)

    @staticmethod
    def _explicit_window(query: str, clients: dict[str, dict[str, Any]], active_address: str | None) -> str | None:
        lowered = query.casefold()
        if active_address and re.search(r"\b(?:this|current|active|esta|este|actual)\s+(?:window|app|ventana|aplicaci[oó]n)\b", lowered):
            return active_address if active_address in clients else None
        stop = {"a", "an", "app", "can", "could", "el", "la", "larger", "make", "me", "más", "please", "podés", "smaller", "the", "un", "una", "ventana", "window", "you"}
        tokens = {token for token in re.findall(r"[a-z0-9]+", lowered) if token not in stop}
        if not tokens:
            return None
        scores: dict[str, int] = {}
        for address, client in clients.items():
            identity = f"{client.get('class', '')} {client.get('title', '')}".casefold()
            identity_tokens = set(re.findall(r"[a-z0-9]+", identity))
            scores[address] = len(tokens & identity_tokens)
        best = max(scores.values(), default=0)
        matches = [address for address, score in scores.items() if score == best and score > 0]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _aliased_window(query: str, clients: dict[str, dict[str, Any]], aliases: dict[str, str]) -> str | None:
        normalized = " ".join(re.findall(r"[a-z0-9]+", query.casefold()))
        padded = f" {normalized} "
        selected: set[str] = set()
        for alias, target in aliases.items():
            candidate = " ".join(re.findall(r"[a-z0-9]+", alias.casefold()))
            if not candidate or f" {candidate} " not in padded:
                continue
            target_folded = target.casefold()
            matches = [address for address, client in clients.items() if target_folded in f"{client.get('class', '')} {client.get('title', '')}".casefold()]
            if len(matches) == 1:
                selected.add(matches[0])
        return next(iter(selected)) if len(selected) == 1 else None

    @staticmethod
    def _explicit_focus_query(query: str) -> bool:
        lowered = query.strip().casefold()
        if re.search(r"\b(?:workspace|left|right|up|down|izquierda|derecha|arriba|abajo)\b", lowered):
            return False
        return bool(re.match(r"^(?:focus|show me|take me to|bring me to|go to|enfoc[aá]|mostr[aá]me|llev[aá]me a|ll[eé]vame a|ir a)\b", lowered))

    def plan(self, query: str) -> Plan:
        scene_plan = self._scene_query_plan(query)
        if scene_plan: return scene_plan
        base_query, save_after = self._post_save(query)
        if save_after:
            base_plan = self.plan(base_query)
            if base_plan.executable:
                try: key = normalize_scene_name(save_after)
                except ValueError as exc:
                    base_plan.warnings.append(str(exc)); base_plan.executable = False
                else:
                    base_plan.query = query
                    base_plan.steps.append(Step("scene_save", key, label=key, params={"update": self.scene_manager.get(key) is not None}))
                    base_plan.summary += f" y guardar como {key}"
                return self._store_plan(base_plan)
            return base_plan
        state, apps, themes = self.hypr.state(), desktop_entries(), self.native.themes()
        clients = {str(c["address"]): c for c in state["clients"] if isinstance(c.get("address"), str)}
        workspace_rows = [w for w in state["workspaces"] if isinstance(w.get("id"), int) and w["id"] > 0]
        existing = sorted({int(w["id"]) for w in workspace_rows})
        next_empty = next((int(w["id"]) for w in sorted(workspace_rows, key=lambda row: row["id"]) if w.get("windows") == 0), None)
        if next_empty is None:
            next_empty = next((number for number in range(1, max(existing, default=0) + 2) if number not in existing), max(existing, default=0) + 1)
        create = max(existing, default=0) + 1
        workspace_options = ["keep", "no_match", "next_empty", *(f"workspace:{number}" for number in existing[:12]), f"create:{create}"]
        ranked_apps = self._rank_apps(query, apps)
        active_address = str(state.get("active", {}).get("address", "")) or None
        safe_state = {"request": query[:500], "windows": [{"address": address, "title": str(client.get("title", ""))[:120], "class": str(client.get("class", ""))[:80], "workspace": client.get("workspace", {}).get("id"), "size": client.get("size"), "active": address == active_address} for address, client in sorted(clients.items())[:MAX_WINDOWS]], "apps": [{"id": app, "name": apps[app]["name"]} for app in ranked_apps], "workspaces": workspace_options, "themes": themes}
        try:
            answers = self.jev.decide(safe_state, self._questions(clients, apps, workspace_options, ranked_apps, themes, active_address))
        except JevError as exc:
            return self._store_plan(Plan(secrets.token_urlsafe(24), query, 0, "No action planned", [], [str(exc)], False, time.time()))
        capability, capability_confidence = _answer_choice(answers, "capability")
        if capability is None: capability, capability_confidence = "window_action", 1.0
        theme, theme_confidence = _answer_choice(answers, "theme")
        workspace_choice, workspace_confidence = _answer_choice(answers, "workspace")
        if capability != "window_action":
            return self._plan_capability(query, capability, capability_confidence, theme, theme_confidence, workspace_choice, workspace_confidence, workspace_options, next_empty, state)
        intent, confidence = _answer_choice(answers, "intent")
        layout, layout_confidence = _answer_choice(answers, "layout")
        view_choice, view_confidence = _answer_choice(answers, "workspace_view")
        named_apps = [app_id for app_id in ranked_apps if self._app_match_score(query, app_id, apps[app_id]) > 0]
        explicit_apps = self._explicit_apps(query, apps, self.config["aliases"]["apps"])
        named_launch = intent in {"launch", "launch_arrange"} and bool(named_apps or explicit_apps)
        window_threshold = 0.65 if confidence >= 0.75 and (intent not in {"move", "arrange"} or workspace_confidence >= 0.85) else 0.85
        app_threshold = 0.50 if named_launch else 0.85
        windows = _selected_noul(answers, "window", sorted(clients)[:MAX_WINDOWS], window_threshold)
        explicit_window = self._aliased_window(query, clients, self.config["aliases"]["windows"]) or self._explicit_window(query, clients, active_address)
        if explicit_window and self._explicit_focus_query(query):
            intent, confidence = "focus", max(confidence, 0.90)
        if explicit_window and intent in {"focus", "resize_smaller", "resize_larger", "swap_left", "swap_right", "swap_up", "swap_down"}:
            windows = [explicit_window]
        selected_apps = _selected_noul(answers, "app", ranked_apps, app_threshold)
        if named_launch and explicit_apps:
            selected_apps = explicit_apps
        warnings: list[str] = []
        if intent not in OPERATIONS or intent in {"keep", "no_match"}: warnings.append("No pude identificar una acción compatible")
        single_window_focus = intent == "focus" and len(windows) == 1
        intent_threshold = 0.65 if single_window_focus else (0.40 if named_launch else MIN_CONFIDENCE)
        if confidence < intent_threshold: warnings.append("La intención no alcanzó la confianza necesaria")
        if intent in {"focus", "move", "arrange", "float", "tile", "fullscreen_on", "fullscreen_off", "resize_smaller", "resize_larger", "swap_left", "swap_right", "swap_up", "swap_down"} and not windows: warnings.append("Ninguna ventana coincidió con suficiente confianza")
        if intent == "focus" and len(windows) > 1: warnings.append("Necesito una sola ventana para cambiar el foco")
        if intent in {"resize_smaller", "resize_larger", "swap_left", "swap_right", "swap_up", "swap_down"} and len(windows) > 1: warnings.append("Necesito una sola ventana para esa acción")
        if intent in {"launch", "launch_arrange"} and not selected_apps: warnings.append("Ninguna aplicación coincidió con suficiente confianza")
        workspace = None
        if intent in {"move", "arrange"}:
            if workspace_confidence < MIN_CONFIDENCE or workspace_choice not in workspace_options or workspace_choice == "keep": warnings.append("El workspace de destino es ambiguo")
            elif workspace_choice == "next_empty": workspace = next_empty
            else: workspace = int(workspace_choice.split(":", 1)[1])
        elif intent == "launch":
            explicit_workspace = re.search(r"\bworkspace\s*(\d{1,2})\b", query, re.IGNORECASE)
            if explicit_workspace:
                workspace = int(explicit_workspace.group(1))
            elif workspace_choice in workspace_options and workspace_choice not in {"keep", "no_match"} and workspace_confidence >= 0.75:
                workspace = next_empty if workspace_choice == "next_empty" else int(workspace_choice.split(":", 1)[1])
        if intent in {"arrange", "launch_arrange"} and layout in {"keep", "no_match"}: layout = "tile"
        if intent in {"arrange", "launch_arrange"} and (layout not in LAYOUTS or layout_confidence < MIN_CONFIDENCE and layout != "tile"): warnings.append("La disposición de ventanas es ambigua")
        steps: list[Step] = []
        if not warnings:
            if intent in {"launch", "launch_arrange"}: steps.extend(Step("launch", app, label=apps[app]["name"]) for app in selected_apps)
            if intent == "launch" and workspace is not None:
                steps.extend(Step("place_launch", app, workspace=workspace, label=apps[app]["name"], params={"summary": f"Ubicar {apps[app]['name']} en el workspace {workspace}"}) for app in selected_apps)
            if intent == "focus": steps.append(Step("focus", windows[0], label=self._window_label(clients[windows[0]])))
            if intent == "move":
                operation = "isolate" if view_choice == "switch" and view_confidence >= 0.60 else "move"
                steps.extend(Step(operation, window, workspace, label=self._window_label(clients[window])) for window in windows)
            if intent == "arrange": steps.extend(Step("arrange", window, workspace, layout, self._window_label(clients[window])) for window in windows)
            if intent == "launch_arrange": steps.append(Step("arrange", None, layout=layout))
            if intent in {"float", "tile", "fullscreen_on", "fullscreen_off"}:
                state_name = {"float": "float", "tile": "tile", "fullscreen_on": "fullscreen_on", "fullscreen_off": "fullscreen_off"}[intent]
                label = {"float": "Hacer flotante", "tile": "Integrar al tiling", "fullscreen_on": "Pantalla completa", "fullscreen_off": "Salir de pantalla completa"}[intent]
                steps.extend(Step("window_state", window, label=self._window_label(clients[window]), params={"state": state_name, "summary": f"{label}: {self._window_label(clients[window])}"}) for window in windows)
            if intent in {"resize_smaller", "resize_larger"}:
                window = windows[0]
                size = clients[window].get("size")
                if not isinstance(size, list) or len(size) != 2 or not all(isinstance(value, int) and value > 0 for value in size):
                    warnings.append("No pude leer el tamaño actual de la ventana")
                else:
                    amount_match = re.search(r"(?<![A-Za-z0-9])(\d{1,2})\s*(?:%|percent\b|por\s+ciento\b)", query, re.IGNORECASE)
                    amount = min(50, max(1, int(amount_match.group(1)))) if amount_match else 15
                    factor = (100 - amount) / 100 if intent == "resize_smaller" else (100 + amount) / 100
                    width = max(160, min(8192, round(size[0] * factor)))
                    height = max(120, min(8192, round(size[1] * factor)))
                    verb = "Achicar" if intent == "resize_smaller" else "Agrandar"
                    label = self._window_label(clients[window])
                    steps.append(Step("window_resize", window, label=label, params={"width": width, "height": height, "summary": f"{verb} {label} {amount}%"}))
            if intent in {"swap_left", "swap_right", "swap_up", "swap_down"}:
                direction = {"swap_left": "l", "swap_right": "r", "swap_up": "u", "swap_down": "d"}[intent]
                label = self._window_label(clients[windows[0]])
                direction_label = {"l": "a la izquierda", "r": "a la derecha", "u": "arriba", "d": "abajo"}[direction]
                steps.append(Step("window_swap", windows[0], label=label, params={"direction": direction, "summary": f"Mover {label} {direction_label}"}))
        if not steps:
            summary = "No hay una acción segura para ejecutar"
        elif intent == "arrange":
            summary = f"Acomodar {len(windows)} ventanas en el workspace {workspace}"
        elif intent == "launch_arrange":
            summary = f"Abrir {len(selected_apps)} aplicaciones y acomodarlas"
        elif intent == "launch":
            summary = f"Abrir {len(selected_apps)} aplicaciones" if workspace is None else f"Abrir {len(selected_apps)} aplicaciones en el workspace {workspace}"
        elif intent == "focus":
            summary = f"Enfocar {self._window_label(clients[windows[0]])}"
        elif intent in {"float", "tile", "fullscreen_on", "fullscreen_off"}:
            summary = f"Cambiar el estado de {len(windows)} ventanas"
        elif intent in {"resize_smaller", "resize_larger"}:
            summary = steps[0].summary
        elif intent in {"swap_left", "swap_right", "swap_up", "swap_down"}:
            summary = steps[0].summary
        elif intent == "move" and steps and steps[0].operation == "isolate":
            summary = f"Aislar {len(windows)} ventanas en el workspace {workspace}"
        else:
            summary = f"Mover {len(windows)} ventanas al workspace {workspace}"
        snapshot_targets = list(windows)
        if intent == "launch" and workspace is not None:
            for app in selected_apps:
                snapshot_targets.extend(self._app_windows(app, apps, clients))
        plan = Plan(secrets.token_urlsafe(24), query, min(confidence, layout_confidence if intent in {"arrange", "launch_arrange"} else 1), summary, steps, warnings, bool(steps) and not warnings, time.time(), self._snapshot(clients, list(dict.fromkeys(snapshot_targets)), state.get("active", {})))
        return self._store_plan(plan)

    def _plan_capability(self, query: str, capability: str, confidence: float, theme: str | None, theme_confidence: float, workspace_choice: str | None, workspace_confidence: float, workspace_options: list[str], next_empty: int, state: dict[str, Any]) -> Plan:
        warnings: list[str] = []
        steps: list[Step] = []
        if capability == "workspace_focus":
            workspace = None
            if workspace_confidence < 0.75 or workspace_choice not in workspace_options or workspace_choice in {"keep", "no_match"}:
                warnings.append("El workspace de destino es ambiguo")
            elif workspace_choice == "next_empty": workspace = next_empty
            else: workspace = int(workspace_choice.split(":", 1)[1])
            if not warnings: steps.append(Step("workspace_focus", workspace=workspace))
        elif capability in CAPABILITY_CRITERIA and capability != "no_match":
            threshold = 0.85 if capability == "lock" else 0.62
            if confidence < threshold: warnings.append("La capacidad nativa no alcanzó la confianza necesaria")
            if capability == "theme_set" and (theme_confidence < 0.65 or theme == "no_match"): warnings.append("No pude resolver un tema instalado")
            if not warnings:
                try: steps.append(self.native.build_step(capability, query, theme))
                except CapabilityError as exc: warnings.append(str(exc))
        else: warnings.append("No pude identificar una capacidad nativa compatible")
        summary = steps[0].summary if steps else "No hay una acción segura para ejecutar"
        plan = Plan(secrets.token_urlsafe(24), query, confidence, summary, steps, warnings, bool(steps) and not warnings, time.time(), {"windows": {}, "active": state.get("active", {}).get("address")})
        return self._store_plan(plan)

    @staticmethod
    def _window_label(client: dict[str, Any]) -> str:
        title = str(client.get("title", "")).strip()
        window_class = str(client.get("class", "")).strip()
        if title and title.casefold() != window_class.casefold():
            return f"{window_class or 'ventana'} · {title}"
        return title or window_class or "ventana"

    @staticmethod
    def _snapshot(clients: dict[str, dict[str, Any]], targets: list[str], active: dict[str, Any]) -> dict[str, Any]:
        windows = {target: {key: clients[target].get(key) for key in ("address", "at", "size", "workspace", "floating", "fullscreen")} for target in targets if target in clients}
        return {"windows": windows, "active": active.get("address")}

    @staticmethod
    def _desktop_id_for_class(window_class: str, apps: dict[str, dict[str, str]]) -> str | None:
        needle = window_class.casefold()
        ranked: list[tuple[int, str]] = []
        for desktop_id, app in apps.items():
            startup = str(app.get("startup_wm_class", "")).casefold()
            app_id = desktop_id.casefold()
            name = str(app.get("name", "")).casefold()
            score = 100 if startup and startup == needle else (90 if app_id == needle else (70 if app_id in needle or needle in app_id else (50 if name and name in needle else 0)))
            if score: ranked.append((score, desktop_id))
        return sorted(ranked, key=lambda item: (-item[0], item[1]))[0][1] if ranked else None

    def _capture_named_scene(self, name: str, update: bool = False) -> dict[str, Any]:
        state, apps = self.hypr.state(), desktop_entries()
        scene = capture_scene(state)
        for spec in scene.get("windows", []):
            desktop_id = self._desktop_id_for_class(str(spec.get("class", "")), apps)
            if desktop_id: spec["desktop_id"] = desktop_id
        return self.scene_manager.scenes.update(name, scene) if update else self.scene_manager.scenes.save(name, scene)

    def _apply_named_scene(self, name: str, apps: dict[str, dict[str, str]]) -> None:
        scene = self.scene_manager.get(name)
        if not scene: raise ValueError("scene no longer exists")
        resolved = self.scene_manager.resolve(name)
        missing_ids = sorted({str(spec.get("desktop_id")) for spec in resolved["missing"] if spec.get("desktop_id") in apps})
        for desktop_id in missing_ids:
            self.launcher(desktop_id, apps)
        if missing_ids:
            for attempt in range(12):
                resolved = self.scene_manager.resolve(name)
                if not resolved["missing"]: break
                if attempt < 11: self.sleeper(0.15)
        for pair in resolved["matches"]:
            spec, client = pair["spec"], pair["client"]
            address = str(client.get("address", ""))
            workspace = spec.get("workspace", {})
            workspace_id, workspace_name = workspace.get("id"), workspace.get("name")
            destination: int | str | None = workspace_id if isinstance(workspace_id, int) and workspace_id > 0 else None
            if destination is None and isinstance(workspace_name, str) and workspace_name: destination = f"name:{workspace_name}"
            if destination is not None: self.hypr.move_window(address, destination)
            self.hypr.set_floating(address, bool(spec.get("floating")))
            self.hypr.set_fullscreen(address, bool(spec.get("fullscreen")))
            if spec.get("floating") and isinstance(spec.get("at"), list) and isinstance(spec.get("size"), list):
                self.hypr.restore_geometry(address, spec["at"], spec["size"])
        if resolved["missing"]:
            self._step_warnings.append(f"La escena se aplicó parcialmente: faltan {len(resolved['missing'])} ventanas")
        active = scene.get("active_window")
        if isinstance(active, dict):
            active_match = match_window_specs([active], [pair["client"] for pair in resolved["matches"]])
            if active_match["matches"]:
                self.hypr.focus_window(str(active_match["matches"][0]["client"].get("address")))

    def execute(self, token: str) -> dict[str, Any]:
        raw = self.store.get_plan(token)
        if not raw: raise ValueError("unknown or expired plan token")
        plan = Plan.from_dict(raw)
        if not plan.executable: raise ValueError("plan is not executable")
        before = {str(c.get("address")): c for c in self.hypr.state()["clients"]}
        targets = [step.target for step in plan.steps if step.operation in {"focus", "move", "isolate", "arrange", "window_resize", "window_swap"} and step.target]
        if any(target not in before for target in targets): raise ValueError("window state changed; request a new plan")
        apps, warnings, undo_steps = desktop_entries(), [], []
        self._step_warnings = []
        try:
            for step in plan.steps:
                if step.operation != "place_launch" and (step.operation != "arrange" or step.target):
                    undo_step = self._execute_step(step, apps)
                    if undo_step: undo_steps.append(undo_step.to_dict())
            for step in [candidate for candidate in plan.steps if candidate.operation == "place_launch"]:
                if not self._place_launched_app(before, step.target or "", step.workspace or 0, apps):
                    warnings.append(f"{step.label or step.target} se abrió, pero no pude identificar su ventana para moverla")
            deferred = [step for step in plan.steps if step.operation == "arrange" and not step.target]
            if deferred:
                new_windows = self._wait_for_new_windows(before, apps, [step.target for step in plan.steps if step.operation == "launch"])
                if len(new_windows) >= 2:
                    for address in new_windows: self._execute_step(Step("arrange", address, layout=deferred[0].layout), apps)
                else: warnings.append("Apps launched safely, but their new windows could not be identified for arrangement")
            warnings.extend(self._step_warnings)
        except Exception as exc:
            rollback_warnings = self._restore_snapshot(plan.snapshot)
            suffix = "" if not rollback_warnings else f"; rollback warnings: {'; '.join(rollback_warnings)}"
            raise RuntimeError(f"Execution failed and the previous window state was restored: {exc}{suffix}") from exc
        self.store.append_history({"token": plan.token, "summary": plan.summary, "at": time.time(), "snapshot": plan.snapshot, "steps": [step.to_dict() for step in plan.steps], "undo_steps": undo_steps})
        self.store.remove_plan(token)
        return {"executed": True, "message": "Executed" if not warnings else "Executed with warnings", "summary": plan.summary, "warnings": warnings}

    def _wait_for_new_windows(self, before: dict[str, Any], apps: dict[str, dict[str, str]], launched: list[str | None]) -> list[str]:
        expected = {apps[app].get("startup_wm_class", "").casefold() for app in launched if app in apps and apps[app].get("startup_wm_class")}
        for attempt in range(3):
            current = {str(c.get("address")): c for c in self.hypr.state()["clients"]}
            new = {address: client for address, client in current.items() if address not in before}
            matches = [address for address, client in new.items() if not expected or str(client.get("class", "")).casefold() in expected]
            if len(matches) >= 2: return sorted(matches)
            if attempt < 2: self.sleeper(0.2)
        return []

    def _place_launched_app(self, before: dict[str, dict[str, Any]], app_id: str, workspace: int, apps: dict[str, dict[str, str]]) -> bool:
        existing = self._app_windows(app_id, apps, before)
        candidates: list[str] = []
        attempts = 8 if existing else 40
        for attempt in range(attempts):
            current = {str(client.get("address")): client for client in self.hypr.state()["clients"] if client.get("address")}
            candidates = [address for address in self._app_windows(app_id, apps, current) if address not in before]
            if candidates:
                break
            if attempt < attempts - 1:
                self.sleeper(0.25)
        if not candidates:
            candidates = existing
        if not candidates:
            return False
        self.hypr.move_window(candidates[0], workspace)
        return True

    def _execute_step(self, step: Step, apps: dict[str, dict[str, str]]) -> Step | None:
        if step.operation == "launch": self.launcher(step.target or "", apps)
        elif step.operation == "focus": self.hypr.focus_window(step.target or "")
        elif step.operation == "move": self.hypr.move_window(step.target or "", step.workspace or 0)
        elif step.operation == "isolate":
            self.hypr.move_window(step.target or "", step.workspace or 0)
            self.hypr.focus_workspace(step.workspace or 0)
        elif step.operation == "arrange":
            if step.workspace is not None:
                self.hypr.move_window(step.target or "", step.workspace)
                self.hypr.focus_workspace(step.workspace)
                self._wait_for_workspace(step.target or "", step.workspace)
            self._ensure_tiled(step.target or "")
        elif step.operation == "workspace_focus":
            state = self.hypr.state()
            focused = next((monitor for monitor in state.get("monitors", []) if monitor.get("focused")), None)
            active_workspace = focused.get("activeWorkspace", {}) if isinstance(focused, dict) else {}
            previous = active_workspace.get("id") if isinstance(active_workspace, dict) else None
            self.hypr.focus_workspace(step.workspace or 0)
            if isinstance(previous, int) and previous > 0 and previous != step.workspace:
                return Step("workspace_focus", workspace=previous, params={"summary": f"Volver al workspace {previous}"})
        elif step.operation == "window_state":
            state = step.params.get("state")
            if state == "float": self.hypr.set_floating(step.target or "", True)
            elif state == "tile": self.hypr.set_floating(step.target or "", False)
            elif state == "fullscreen_on": self.hypr.set_fullscreen(step.target or "", True)
            elif state == "fullscreen_off": self.hypr.set_fullscreen(step.target or "", False)
            else: raise ValueError("unknown window state")
        elif step.operation == "window_resize":
            client = next((item for item in self.hypr.state()["clients"] if item.get("address") == step.target), None)
            previous = client.get("size") if isinstance(client, dict) else None
            width, height = step.params.get("width"), step.params.get("height")
            if not isinstance(previous, list) or len(previous) != 2 or not all(isinstance(value, int) for value in previous):
                raise ValueError("window size is unavailable")
            if not isinstance(width, int) or not isinstance(height, int):
                raise ValueError("invalid resize plan")
            self.hypr.resize_window(step.target or "", width, height)
            return Step("window_resize", step.target, label=step.label, params={"width": previous[0], "height": previous[1], "summary": f"Restaurar tamaño de {step.label or 'ventana'}"})
        elif step.operation == "window_swap":
            direction = step.params.get("direction")
            if direction not in {"l", "r", "u", "d"}:
                raise ValueError("invalid swap plan")
            before = next((item for item in self.hypr.state()["clients"] if item.get("address") == step.target), None)
            self.hypr.swap_window(step.target or "", direction)
            after = next((item for item in self.hypr.state()["clients"] if item.get("address") == step.target), None)
            geometry = lambda client: (client.get("at"), client.get("size"), client.get("workspace")) if isinstance(client, dict) else None
            if geometry(before) == geometry(after):
                self._step_warnings.append(f"{step.label or 'La ventana'} no tenía una ventana vecina en esa dirección")
                return None
            opposite = {"l": "r", "r": "l", "u": "d", "d": "u"}[direction]
            return Step("window_swap", step.target, label=step.label, params={"direction": opposite, "summary": f"Restaurar posición de {step.label or 'ventana'}"})
        elif step.operation == "native": return self.native.execute(step).undo_step
        elif step.operation == "scene_save":
            previous = self.scene_manager.get(step.target or "")
            self._capture_named_scene(step.target or "", bool(step.params.get("update")))
            if previous:
                return Step("scene_restore_definition", step.target, params={"scene": previous, "summary": f"Restaurar definición {step.target}"})
            return Step("scene_delete", step.target, params={"summary": f"Eliminar escena {step.target}"})
        elif step.operation == "scene_apply": self._apply_named_scene(step.target or "", apps)
        elif step.operation == "scene_delete":
            previous = self.scene_manager.get(step.target or "")
            if not previous or not self.scene_manager.delete(step.target or ""): raise ValueError("scene no longer exists")
            return Step("scene_restore_definition", step.target, params={"scene": previous, "summary": f"Restaurar escena {step.target}"})
        elif step.operation == "scene_restore_definition":
            scene = step.params.get("scene")
            if not isinstance(scene, dict): raise ValueError("invalid scene definition")
            self.scene_manager.scenes.save(step.target or "", scene)
        elif step.operation == "scene_list": pass
        return None

    def _wait_for_workspace(self, address: str, workspace: int) -> None:
        for attempt in range(6):
            clients = self.hypr.state()["clients"]
            client = next((item for item in clients if item.get("address") == address), None)
            if client and client.get("workspace", {}).get("id") == workspace:
                return
            if attempt < 5: self.sleeper(0.03)
        raise RuntimeError(f"window {address} did not reach workspace {workspace}")

    def _ensure_tiled(self, address: str) -> None:
        for attempt in range(3):
            self.hypr.set_floating(address, False)
            if attempt < 2: self.sleeper(0.03)
            clients = self.hypr.state()["clients"]
            client = next((item for item in clients if item.get("address") == address), None)
            if client and not bool(client.get("floating")):
                return
        raise RuntimeError(f"window {address} did not enter tiled mode")

    def undo(self) -> dict[str, Any]:
        history = self.store.history()
        if not history: raise ValueError("no reversible operation in history")
        undone = {entry.get("undo_of") for entry in history if entry.get("undo_of")}
        record = next((entry for entry in reversed(history) if entry.get("token") and entry.get("token") not in undone and (entry.get("undo_steps") or entry.get("snapshot", {}).get("windows"))), None)
        if not record: raise ValueError("no reversible operation in history")
        warnings: list[str] = []
        for raw_step in reversed(record.get("undo_steps", [])):
            try: self._execute_step(Step(**{key: value for key, value in raw_step.items() if key != "summary"}), desktop_entries())
            except Exception as exc: warnings.append(f"undo nativo: {exc}")
        warnings.extend(self._restore_snapshot(record.get("snapshot", {})))
        snapshots = record.get("snapshot", {}).get("windows", record.get("snapshot", {}))
        restored = len(snapshots) - len([warning for warning in warnings if warning.startswith("missing window")])
        self.store.append_history({"undo_of": record.get("token"), "at": time.time(), "summary": "undo"})
        return {"undone": True, "message": "Undo completed" if not warnings else "Undo completed with warnings", "restored_windows": restored, "warnings": warnings}

    def _restore_snapshot(self, snapshot_root: dict[str, Any]) -> list[str]:
        current = {str(c.get("address")): c for c in self.hypr.state()["clients"]}
        snapshots = snapshot_root.get("windows", snapshot_root)
        warnings: list[str] = []
        for address, snapshot in snapshots.items():
            if address not in current:
                warnings.append(f"missing window {address}")
                continue
            try:
                workspace = snapshot.get("workspace", {})
                workspace_id = workspace.get("id") if isinstance(workspace, dict) else None
                workspace_name = workspace.get("name") if isinstance(workspace, dict) else None
                destination: int | str | None = workspace_id if isinstance(workspace_id, int) and workspace_id > 0 else None
                if destination is None and isinstance(workspace_name, str) and workspace_name:
                    destination = f"name:{workspace_name}"
                if destination is not None: self.hypr.move_window(address, destination)
                if bool(current[address].get("floating")) != bool(snapshot.get("floating")): self.hypr.set_floating(address, bool(snapshot.get("floating")))
                if bool(current[address].get("fullscreen")) != bool(snapshot.get("fullscreen")): self.hypr.set_fullscreen(address, bool(snapshot.get("fullscreen")))
                if snapshot.get("floating") and isinstance(snapshot.get("at"), list) and isinstance(snapshot.get("size"), list):
                    self.hypr.restore_geometry(address, snapshot["at"], snapshot["size"])
            except Exception as exc:
                warnings.append(f"{address}: {exc}")
        for address, snapshot in snapshots.items():
            if address not in current or bool(snapshot.get("floating")):
                continue
            target_at, target_size = snapshot.get("at"), snapshot.get("size")
            if not isinstance(target_at, list) or len(target_at) != 2 or not isinstance(target_size, list) or len(target_size) != 2:
                continue
            try:
                if not self._restore_tiled_position(address, target_at, max(2, len(snapshots) * 2)):
                    warnings.append(f"{address}: tiled position did not return to its previous slot")
            except Exception as exc:
                warnings.append(f"{address}: tiled position: {exc}")
        active = snapshot_root.get("active")
        if isinstance(active, str) and active in current:
            try: self.hypr.focus_window(active)
            except Exception as exc: warnings.append(f"focus {active}: {exc}")
        return warnings

    def _restore_tiled_position(self, address: str, target_at: list[int], attempts: int) -> bool:
        for attempt in range(attempts + 1):
            client = next((item for item in self.hypr.state()["clients"] if item.get("address") == address), None)
            if not isinstance(client, dict):
                return False
            current_at, current_size = client.get("at"), client.get("size")
            if current_at == target_at:
                return True
            if attempt == attempts or not isinstance(current_at, list) or len(current_at) != 2:
                return False
            delta_x, delta_y = target_at[0] - current_at[0], target_at[1] - current_at[1]
            if abs(delta_x) >= abs(delta_y) and delta_x:
                direction = "r" if delta_x > 0 else "l"
            elif delta_y:
                direction = "d" if delta_y > 0 else "u"
            else:
                return False
            before = (current_at, current_size)
            self.hypr.swap_window(address, direction)
            self.sleeper(0.03)
            after = next((item for item in self.hypr.state()["clients"] if item.get("address") == address), None)
            if not isinstance(after, dict) or (after.get("at"), after.get("size")) == before:
                return False
        return False
