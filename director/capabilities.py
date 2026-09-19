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
    "window_action": "Focus, move, gather, tile, float, tile, or fullscreen existing windows, or launch desktop applications",
    "workspace_focus": "Switch the visible desktop directly to a numbered workspace without moving windows",
    "theme_set": "Apply a specifically named installed Omarchy theme",
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

    @staticmethod
    def _amount(query: str, default: int, maximum: int) -> int:
        match = re.search(r"(?<![A-Za-z0-9])(\d{1,3})\s*%?", query)
        return min(maximum, max(1, int(match.group(1)))) if match else default

    @staticmethod
    def _reminder(query: str) -> tuple[int, str]:
        match = re.search(
            r"(?:in|en|dentro de)\s+(\d{1,3})\s*(minutes?|mins?|minutos?|hours?|hrs?|horas?)\s*(?:to|para|de que)?\s*(.+)$",
            query.strip(), re.IGNORECASE,
        )
        if not match:
            raise CapabilityError("Decime cuándo y qué querés recordar")
        amount, unit, message = int(match.group(1)), match.group(2).casefold(), match.group(3).strip(" .")
        minutes = amount * 60 if unit.startswith(("h", "hora")) else amount
        if not message or minutes < 1 or minutes > 10080:
            raise CapabilityError("El recordatorio necesita un mensaje y un plazo de hasta 7 días")
        return minutes, message[:240]

    def build_step(self, capability: str, query: str, theme: str | None = None) -> Step:
        params: dict[str, Any] = {"capability": capability}
        labels = {
            "theme_set": f"Aplicar el tema {theme}" if theme else "Aplicar tema",
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
        elif capability in {"volume_up", "volume_down"}:
            params["amount"] = self._amount(query, 5, 20)
            labels[capability] += f" {params['amount']}%"
        elif capability in {"brightness_up", "brightness_down"}:
            params["amount"] = self._amount(query, 10, 50)
            labels[capability] += f" {params['amount']}%"
        elif capability == "screenshot":
            lowered = query.casefold()
            params["mode"] = "fullscreen" if any(word in lowered for word in ("full", "entera", "completa")) else ("windows" if "window" in lowered or "ventana" in lowered else "region")
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
        if observed_before is not None and capability in {"volume_up", "volume_down"}:
            observed_after = self._volume_percent()
            if observed_after is not None and observed_after != observed_before:
                undo = Step("native", "volume_set", params={"capability": "volume_set", "percent": observed_before, "summary": f"Restaurar volumen a {observed_before}%"})
        elif observed_before is not None and capability in {"brightness_up", "brightness_down"}:
            observed_after = self._brightness_percent()
            if observed_after is not None and observed_after != observed_before:
                undo = Step("native", "brightness_set", params={"capability": "brightness_set", "percent": observed_before, "summary": f"Restaurar brillo a {observed_before}%"})
        return NativeResult(str(params.get("summary") or capability), undo)
