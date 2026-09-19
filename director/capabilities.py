from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any

from .models import Step


class CapabilityError(RuntimeError):
    pass


CAPABILITY_CRITERIA = {
    "window_action": "Focus, move, gather, tile, float, resize, or fullscreen existing windows, or launch desktop applications",
    "workspace_focus": "Switch the visible desktop directly to a numbered workspace without moving windows",
    "theme_set": "Apply a specifically named installed Omarchy theme",
    "window_rounding": "Change the global default corner rounding for all windows; includes rounded, more rounded, slightly rounded, square, or sharp corners",
    "hyprland_style": "Change safe global Hyprland appearance settings or apply a built-in style preset: gaps, border size, opacity, blur, shadows, inactive-window dimming, and animations",
    "background_next": "Cycle to the next background in the current theme",
    "nightlight_toggle": "Toggle the warm night-light color temperature",
    "dnd_toggle": "Toggle notification silencing or do-not-disturb mode",
    "stay_awake": "Prevent idle lock and screensaver",
    "allow_idle": "Restore normal idle lock and screensaver behavior",
    "volume_up": "Raise speaker/output volume",
    "volume_down": "Lower speaker/output volume",
    "volume_mute": "Toggle speaker/output mute",
    "mic_mute": "Toggle microphone mute",
    "audio_output_switch": "Switch to the next available audio output",
    "brightness_up": "Increase display brightness",
    "brightness_down": "Decrease display brightness",
    "screenshot": "Take a screenshot of the screen, a window, or a selected region",
    "screenrecord_start": "Start a screen recording",
    "screenrecord_stop": "Stop the active screen recording",
    "reminder": "Create a reminder after a stated duration with a message",
    "lock": "Lock the computer and turn off the display",
    "no_match": "None of the supported native capabilities matches the request",
}


HYPR_STYLE_OPTIONS: dict[str, dict[str, Any]] = {
    "border_size": {"path": "general:border_size", "kind": "int", "min": 0, "max": 20},
    "gaps_in": {"path": "general:gaps_in", "kind": "gap", "min": 0, "max": 100},
    "gaps_out": {"path": "general:gaps_out", "kind": "gap", "min": 0, "max": 100},
    "active_opacity": {"path": "decoration:active_opacity", "kind": "float", "min": 0.1, "max": 1.0},
    "inactive_opacity": {"path": "decoration:inactive_opacity", "kind": "float", "min": 0.1, "max": 1.0},
    "fullscreen_opacity": {"path": "decoration:fullscreen_opacity", "kind": "float", "min": 0.1, "max": 1.0},
    "rounding": {"path": "decoration:rounding", "kind": "int", "min": 0, "max": 32},
    "blur_enabled": {"path": "decoration:blur:enabled", "kind": "bool"},
    "blur_size": {"path": "decoration:blur:size", "kind": "int", "min": 0, "max": 100},
    "blur_passes": {"path": "decoration:blur:passes", "kind": "int", "min": 0, "max": 10},
    "shadow_enabled": {"path": "decoration:shadow:enabled", "kind": "bool"},
    "shadow_range": {"path": "decoration:shadow:range", "kind": "int", "min": 0, "max": 100},
    "dim_inactive": {"path": "decoration:dim_inactive", "kind": "bool"},
    "dim_strength": {"path": "decoration:dim_strength", "kind": "float", "min": 0.0, "max": 1.0},
    "animations_enabled": {"path": "animations:enabled", "kind": "bool"},
}

HYPR_STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "compact": {"gaps_in": 3, "gaps_out": 6, "border_size": 1, "rounding": 4},
    "spacious": {"gaps_in": 8, "gaps_out": 16, "border_size": 2, "rounding": 10},
    "minimal": {"gaps_in": 4, "gaps_out": 8, "border_size": 1, "rounding": 0, "blur_enabled": False, "shadow_enabled": False},
    "focus": {"inactive_opacity": 0.78, "dim_inactive": True, "dim_strength": 0.18, "blur_enabled": True},
    "performance": {"animations_enabled": False, "blur_enabled": False, "shadow_enabled": False},
}


@dataclass(frozen=True)
class NativeResult:
    message: str
    undo_step: Step | None = None


class NativeCapabilities:
    def __init__(self, runner=subprocess.run):
        self.runner = runner

    def _run(self, argv: list[str]) -> str:
        result = self.runner(argv, capture_output=True, text=True, check=False)
        if getattr(result, "returncode", 1):
            raise CapabilityError((getattr(result, "stderr", "") or "").strip() or f"Falló {' '.join(argv[:3])}")
        return getattr(result, "stdout", "") if isinstance(getattr(result, "stdout", ""), str) else ""

    def themes(self) -> list[str]:
        try:
            output = self._run(["omarchy", "theme", "list"])
        except CapabilityError:
            return []
        return [line.strip() for line in output.splitlines() if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}", line.strip())]

    def _volume_percent(self) -> int | None:
        try:
            output = self._run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
        except CapabilityError:
            return None
        match = re.search(r"Volume:\s*(\d+(?:\.\d+)?)", output)
        return max(0, min(150, round(float(match.group(1)) * 100))) if match else None

    def _brightness_percent(self) -> int | None:
        try:
            output = self._run(["brightnessctl", "-m"])
        except CapabilityError:
            return None
        match = re.search(r",(\d+)%", output)
        return max(1, min(100, int(match.group(1)))) if match else None

    def _window_rounding(self) -> int | None:
        try:
            payload = json.loads(self._run(["hyprctl", "-j", "getoption", "decoration:rounding"]))
        except (CapabilityError, json.JSONDecodeError):
            return None
        value = payload.get("int") if isinstance(payload, dict) else None
        return int(value) if isinstance(value, int) and 0 <= value <= 32 else None

    def _hypr_style_value(self, name: str) -> Any | None:
        option = HYPR_STYLE_OPTIONS.get(name)
        if not option:
            return None
        try:
            payload = json.loads(self._run(["hyprctl", "-j", "getoption", str(option["path"])]))
        except (CapabilityError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        kind = option["kind"]
        if kind == "bool":
            value = payload.get("int")
            return bool(value) if isinstance(value, int) and value in {0, 1} else None
        if kind == "int":
            value = payload.get("int")
            return int(value) if isinstance(value, int) else None
        if kind == "float":
            value = payload.get("float")
            return float(value) if isinstance(value, (int, float)) else None
        css = payload.get("str")
        if kind == "gap" and isinstance(css, str):
            parts = css.split()
            if parts and len(set(parts)) == 1 and re.fullmatch(r"\d+", parts[0]):
                return int(parts[0])
        return None

    @staticmethod
    def _bounded_style_value(name: str, value: Any) -> int | float | bool:
        option = HYPR_STYLE_OPTIONS.get(name)
        if not option:
            raise CapabilityError("Configuración visual de Hyprland no permitida")
        kind = option["kind"]
        if kind == "bool":
            if not isinstance(value, bool):
                raise CapabilityError("El ajuste visual necesita un valor booleano")
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CapabilityError("El ajuste visual necesita un valor numérico")
        bounded = max(option["min"], min(option["max"], value))
        return int(bounded) if kind in {"int", "gap"} else round(float(bounded), 3)

    @staticmethod
    def _lua_style_config(changes: dict[str, Any]) -> str:
        tree: dict[str, Any] = {}
        for name, raw_value in changes.items():
            option = HYPR_STYLE_OPTIONS.get(name)
            if not option:
                raise CapabilityError("Configuración visual de Hyprland no permitida")
            value = NativeCapabilities._bounded_style_value(name, raw_value)
            cursor = tree
            parts = str(option["path"]).split(":")
            for part in parts[:-1]:
                cursor = cursor.setdefault(part, {})
            cursor[parts[-1]] = value

        def serialize(value: Any) -> str:
            if isinstance(value, dict):
                return "{ " + ", ".join(f"{key} = {serialize(child)}" for key, child in value.items()) + " }"
            if isinstance(value, bool):
                return "true" if value else "false"
            return str(value)

        return f"hl.config({serialize(tree)})"

    @staticmethod
    def _style_number(query: str, default: int) -> int:
        match = re.search(r"(?<!\d)(\d{1,3})(?:\s*(?:px|pixels?))?\b", query)
        return int(match.group(1)) if match else default

    @classmethod
    def _requested_hypr_style(cls, query: str) -> tuple[dict[str, Any], str]:
        lowered = query.casefold()
        preset_aliases = {
            "compact": ("compact", "compacto", "compacta"),
            "spacious": ("spacious", "airy", "espacioso", "espaciosa", "amplio", "amplia"),
            "minimal": ("minimal", "minimalist", "minimalista", "flat", "plano", "plana"),
            "focus": ("focus mode", "focus preset", "modo foco", "preset foco"),
            "performance": ("performance", "rendimiento", "low power", "bajo consumo"),
        }
        for preset, aliases in preset_aliases.items():
            if any(alias in lowered for alias in aliases):
                return dict(HYPR_STYLE_PRESETS[preset]), f"Aplicar preset visual {preset}"

        changes: dict[str, Any] = {}
        disabled = bool(re.search(r"\b(?:disable|off|remove|without|no|desactiv(?:a|á)|apag(?:a|á)|sin)\b", lowered))
        enabled = bool(re.search(r"\b(?:enable|on|with|activ(?:a|á)|prend(?:e|é)|con)\b", lowered))
        style_effects = sum(bool(re.search(pattern, lowered)) for pattern in (
            r"\b(?:blur|desenfoque)\b", r"\b(?:shadow|shadows|sombra|sombras)\b", r"\b(?:animation|animations|animaci[oó]n|animaciones)\b",
        ))
        if disabled and enabled and style_effects > 1:
            raise CapabilityError("Separá los efectos que querés activar de los que querés desactivar")
        number = cls._style_number(lowered, 0)

        if re.search(r"\b(?:gap|gaps|spacing|espaciado|separaci[oó]n)\b", lowered):
            value = 0 if disabled or re.search(r"\b(?:remove|zero|cero|elimin(?:a|á))\b", lowered) else (number or 10)
            if re.search(r"\b(?:inner|inside|intern[oa]s?)\b", lowered):
                changes["gaps_in"] = value
            elif re.search(r"\b(?:outer|outside|extern[oa]s?)\b", lowered):
                changes["gaps_out"] = value
            else:
                changes.update({"gaps_in": value, "gaps_out": value})
        if re.search(r"\b(?:border size|border thickness|borders thicker|borders thinner|grosor (?:de los )?bordes?|tama[nñ]o (?:de los )?bordes?|bordes? de tama[nñ]o)\b", lowered):
            default = 0 if disabled else (1 if re.search(r"\b(?:thin|thinner|fino|finos)\b", lowered) else 3)
            changes["border_size"] = number if number else default

        percent = re.search(r"(?<!\d)(\d{1,3})\s*(?:%|percent\b|por ciento\b)", lowered)
        opacity = max(10, min(100, int(percent.group(1)))) / 100 if percent else (0.78 if re.search(r"\b(?:transparent|transparente)\b", lowered) else None)
        if opacity is not None and re.search(r"\b(?:opacity|opaque|transparent|opacidad|transparen)\w*\b", lowered):
            if re.search(r"\b(?:inactive|inactivas?)\b", lowered): changes["inactive_opacity"] = opacity
            elif re.search(r"\b(?:fullscreen|pantalla completa)\b", lowered): changes["fullscreen_opacity"] = opacity
            elif re.search(r"\b(?:active|activas?)\b", lowered): changes["active_opacity"] = opacity
            elif re.search(r"\b(?:all|global|every|todas?)\b", lowered):
                changes.update({"active_opacity": opacity, "inactive_opacity": opacity, "fullscreen_opacity": opacity})

        if re.search(r"\b(?:blur|desenfoque)\b", lowered):
            if disabled or enabled: changes["blur_enabled"] = not disabled
            if re.search(r"\b(?:size|radius|tama[nñ]o|radio)\b", lowered): changes["blur_size"] = number or 8
            if re.search(r"\b(?:passes|pasadas?)\b", lowered): changes["blur_passes"] = number or 1
            if not any(key.startswith("blur_") for key in changes): changes["blur_enabled"] = True
        if re.search(r"\b(?:shadow|shadows|sombra|sombras)\b", lowered):
            if disabled or enabled: changes["shadow_enabled"] = not disabled
            if re.search(r"\b(?:range|spread|alcance|rango)\b", lowered): changes["shadow_range"] = number or 4
            if not any(key.startswith("shadow_") for key in changes): changes["shadow_enabled"] = True
        if re.search(r"\b(?:dim|dimming|atenu(?:a|á|ar|aci[oó]n))\b", lowered) and re.search(r"\b(?:inactive|inactivas?)\b", lowered):
            changes["dim_inactive"] = not disabled
            if percent: changes["dim_strength"] = max(0, min(100, int(percent.group(1)))) / 100
        if re.search(r"\b(?:animation|animations|animaci[oó]n|animaciones)\b", lowered):
            changes["animations_enabled"] = not disabled
        if not changes:
            raise CapabilityError("Decime qué aspecto global querés cambiar y, si corresponde, su valor")
        validated = {name: cls._bounded_style_value(name, value) for name, value in changes.items()}
        return validated, "Ajustar estilo global de Hyprland"

    @staticmethod
    def _requested_rounding(query: str) -> int:
        lowered = query.casefold()
        exact = re.search(r"(?<!\d)(\d{1,2})\s*(?:px|pixels?)\b", lowered)
        if exact:
            return min(32, int(exact.group(1)))
        if any(phrase in lowered for phrase in ("square", "sharp", "no rounding", "without rounding", "remove all window rounding", "sin redondeo", "esquinas rectas", "ventanas cuadradas")):
            return 0
        if any(phrase in lowered for phrase in ("slightly", "a little", "poco redonde", "suavemente")):
            return 4
        if any(phrase in lowered for phrase in ("very rounded", "more rounded", "increase window corner rounding", "más redonde", "mas redonde", "bien redonde")):
            return 12
        return 8

    @staticmethod
    def _amount(query: str, default: int, maximum: int) -> int:
        match = re.search(r"(?<![A-Za-z0-9])(\d{1,3})\s*%?", query)
        return min(maximum, max(1, int(match.group(1)))) if match else default

    @staticmethod
    def _reminder(query: str) -> tuple[int, str]:
        text = query.strip()
        match = re.search(r"(?:in|en|dentro de)\s+(\d{1,3})\s*(minutos?|minutes?|mins?|horas?|hours?|hrs?)\s*(?:to|para|de que)?\s*(.+)$", text, re.IGNORECASE)
        if not match:
            match = re.search(r"(?:set|create|crea|creá)\s+(?:a|un)?\s*(\d{1,3})\s*(minutos?|minutes?|mins?|horas?|hours?|hrs?)\s+(?:reminder|recordatorio)\s*(?:to|para)?\s*(.+)$", text, re.IGNORECASE)
        if not match:
            raise CapabilityError("Decime cuándo y qué querés recordar")
        amount, unit, message = int(match.group(1)), match.group(2).casefold(), match.group(3).strip(" .")
        message = re.sub(r"^(?:remind\s+me\s+to|recordame(?:\s+que)?|reminder\s+to)\s+", "", message, flags=re.IGNORECASE).strip(" .")
        minutes = amount * 60 if unit.startswith(("h", "hora")) else amount
        if not message or minutes < 1 or minutes > 10080:
            raise CapabilityError("El recordatorio necesita un mensaje y un plazo de hasta 7 días")
        return minutes, message[:240]

    def build_step(self, capability: str, query: str, theme: str | None = None) -> Step:
        params: dict[str, Any] = {"capability": capability}
        labels = {
            "theme_set": f"Aplicar el tema {theme}" if theme else "Aplicar tema",
            "window_rounding": "Cambiar redondeo global de ventanas",
            "hyprland_style": "Ajustar estilo global de Hyprland",
            "background_next": "Cambiar al siguiente fondo",
            "nightlight_toggle": "Alternar luz nocturna",
            "dnd_toggle": "Alternar modo sin notificaciones",
            "stay_awake": "Mantener la computadora despierta",
            "allow_idle": "Restaurar bloqueo por inactividad",
            "volume_up": "Subir volumen",
            "volume_down": "Bajar volumen",
            "volume_mute": "Alternar silencio de audio",
            "mic_mute": "Alternar silencio del micrófono",
            "audio_output_switch": "Cambiar salida de audio",
            "brightness_up": "Subir brillo",
            "brightness_down": "Bajar brillo",
            "screenshot": "Capturar pantalla",
            "screenrecord_start": "Iniciar grabación de pantalla",
            "screenrecord_stop": "Detener grabación de pantalla",
            "reminder": "Crear recordatorio",
            "lock": "Bloquear la computadora",
        }
        if capability == "theme_set":
            if not theme or theme not in self.themes():
                raise CapabilityError("No pude resolver un tema instalado")
            params["theme"] = theme
        elif capability == "window_rounding":
            params["rounding"] = self._requested_rounding(query)
            labels[capability] = "Usar esquinas rectas" if params["rounding"] == 0 else f"Redondear ventanas a {params['rounding']} px"
        elif capability == "hyprland_style":
            params["changes"], labels[capability] = self._requested_hypr_style(query)
        elif capability in {"volume_up", "volume_down"}:
            params["amount"] = self._amount(query, 5, 20)
            labels[capability] += f" {params['amount']}%"
        elif capability in {"brightness_up", "brightness_down"}:
            params["amount"] = self._amount(query, 10, 50)
            labels[capability] += f" {params['amount']}%"
        elif capability == "screenshot":
            lowered = query.casefold()
            params["mode"] = "fullscreen" if any(word in lowered for word in ("full", "fullscreen", "whole", "entire", "entera", "completa")) else ("windows" if "window" in lowered or "ventana" in lowered else "region")
            params["destination"] = "copy" if any(word in lowered for word in ("copy", "clipboard", "portapapeles")) else "save"
            labels[capability] = f"Capturar {params['mode']} y {params['destination']}"
        elif capability == "screenrecord_start":
            lowered = query.casefold()
            params["desktop_audio"] = any(word in lowered for word in ("desktop audio", "system audio", "audio del sistema"))
            params["microphone"] = any(word in lowered for word in ("microphone", "mic", "micrófono", "microfono"))
        elif capability == "reminder":
            params["minutes"], params["message"] = self._reminder(query)
            labels[capability] = f"Recordar en {params['minutes']} min: {params['message']}"
        params["summary"] = labels.get(capability, capability)
        return Step("native", capability, label=labels.get(capability, capability), params=params)

    def execute(self, step: Step) -> NativeResult:
        capability, params = step.target or "", step.params
        undo: Step | None = None
        observed_before: int | None = None
        argv: list[str]
        if capability == "theme_set":
            previous = self._run(["omarchy", "theme", "current"]).strip()
            argv = ["omarchy", "theme", "set", str(params["theme"])]
            if previous and previous != params["theme"]:
                undo = Step("native", "theme_set", label=f"Restaurar tema {previous}", params={"capability": "theme_set", "theme": previous, "summary": f"Restaurar tema {previous}"})
        elif capability == "window_rounding":
            previous = self._window_rounding()
            desired = max(0, min(32, int(params["rounding"])))
            argv = ["hyprctl", "-r", "eval", f"hl.config({{ decoration = {{ rounding = {desired} }} }})"]
            if previous is not None and previous != desired:
                undo = Step("native", "window_rounding", label=f"Restaurar redondeo a {previous} px", params={"capability": "window_rounding", "rounding": previous, "summary": f"Restaurar redondeo a {previous} px"})
        elif capability == "hyprland_style":
            requested = params.get("changes")
            if not isinstance(requested, dict) or not requested:
                raise CapabilityError("El ajuste visual no contiene cambios")
            changes = {str(name): self._bounded_style_value(str(name), value) for name, value in requested.items()}
            previous: dict[str, Any] = {}
            for name in changes:
                observed = self._hypr_style_value(name)
                if observed is None:
                    raise CapabilityError(f"No pude observar el valor actual de {name}; no voy a cambiarlo sin poder deshacer")
                previous[name] = observed
            argv = ["hyprctl", "-r", "eval", self._lua_style_config(changes)]
            if previous != changes:
                undo = Step("native", "hyprland_style", label="Restaurar estilo anterior", params={"capability": "hyprland_style", "changes": previous, "summary": "Restaurar estilo anterior"})
        elif capability == "background_next": argv = ["omarchy", "theme", "bg", "next"]
        elif capability == "nightlight_toggle": argv, undo = ["omarchy", "toggle", "nightlight"], step
        elif capability == "dnd_toggle": argv, undo = ["omarchy", "toggle", "notification", "silencing"], step
        elif capability == "stay_awake":
            argv = ["omarchy", "toggle", "idle", "stay-awake"]
            undo = Step("native", "allow_idle", params={"capability": "allow_idle", "summary": "Restaurar inactividad"})
        elif capability == "allow_idle":
            argv = ["omarchy", "toggle", "idle", "allow-idle"]
            undo = Step("native", "stay_awake", params={"capability": "stay_awake", "summary": "Mantener despierta"})
        elif capability in {"volume_up", "volume_down"}:
            observed_before = self._volume_percent()
            amount = int(params.get("amount", 5)); sign = "+" if capability == "volume_up" else "-"
            argv = ["omarchy", "audio", "output", "volume", f"{sign}{amount}"]
        elif capability == "volume_set":
            argv = ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{max(0, min(150, int(params['percent'])))}%"]
        elif capability == "volume_mute": argv, undo = ["omarchy", "audio", "output", "volume", "mute-toggle"], step
        elif capability == "mic_mute": argv, undo = ["omarchy", "audio", "input", "mute"], step
        elif capability == "audio_output_switch": argv = ["omarchy", "audio", "output", "switch"]
        elif capability in {"brightness_up", "brightness_down"}:
            observed_before = self._brightness_percent()
            amount = int(params.get("amount", 10)); value = f"+{amount}%" if capability == "brightness_up" else f"{amount}%-"
            argv = ["omarchy", "brightness", "display", value]
        elif capability == "brightness_set":
            argv = ["omarchy", "brightness", "display", f"{max(1, min(100, int(params['percent'])))}%"]
        elif capability == "screenshot": argv = ["omarchy", "capture", "screenshot", str(params["mode"]), str(params["destination"])]
        elif capability == "screenrecord_start":
            argv = ["omarchy", "capture", "screenrecording", "--fullscreen"]
            if params.get("desktop_audio"): argv.append("--with-desktop-audio")
            if params.get("microphone"): argv.append("--with-microphone-audio")
            undo = Step("native", "screenrecord_stop", params={"capability": "screenrecord_stop", "summary": "Detener grabación"})
        elif capability == "screenrecord_stop": argv = ["omarchy", "capture", "screenrecording", "--stop-recording"]
        elif capability == "reminder": argv = ["omarchy", "reminder", str(int(params["minutes"])), str(params["message"])]
        elif capability == "lock": argv = ["omarchy", "system", "lock"]
        else: raise CapabilityError("Capacidad nativa desconocida")
        self._run(argv)
        if capability == "window_rounding":
            desired = max(0, min(32, int(params["rounding"])))
            if self._window_rounding() != desired:
                raise CapabilityError("Hyprland no aplicó el redondeo solicitado")
        elif capability == "hyprland_style":
            desired = {str(name): self._bounded_style_value(str(name), value) for name, value in params["changes"].items()}
            mismatched = [name for name, value in desired.items() if self._hypr_style_value(name) != value]
            if mismatched:
                rollback_error = ""
                try:
                    self._run(["hyprctl", "-r", "eval", self._lua_style_config(previous)])
                    not_restored = [name for name, value in previous.items() if self._hypr_style_value(name) != value]
                    if not_restored:
                        rollback_error = f"; tampoco confirmó rollback de {', '.join(not_restored)}"
                except CapabilityError as exc:
                    rollback_error = f"; rollback falló: {exc}"
                raise CapabilityError(f"Hyprland no aplicó correctamente: {', '.join(mismatched)}{rollback_error}")
        elif observed_before is not None and capability in {"volume_up", "volume_down"}:
            observed_after = self._volume_percent()
            if observed_after is not None and observed_after != observed_before:
                undo = Step("native", "volume_set", params={"capability": "volume_set", "percent": observed_before, "summary": f"Restaurar volumen a {observed_before}%"})
        elif observed_before is not None and capability in {"brightness_up", "brightness_down"}:
            observed_after = self._brightness_percent()
            if observed_after is not None and observed_after != observed_before:
                undo = Step("native", "brightness_set", params={"capability": "brightness_set", "percent": observed_before, "summary": f"Restaurar brillo a {observed_before}%"})
        return NativeResult(str(params.get("summary") or capability), undo)
