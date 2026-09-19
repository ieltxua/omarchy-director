from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


AUTOEXECUTE_NATIVE = frozenset({
    "theme_set", "nightlight_toggle", "dnd_toggle", "stay_awake", "allow_idle",
    "volume_up", "volume_down", "volume_mute", "mic_mute", "brightness_up",
    "brightness_down",
})


@dataclass
class Step:
    operation: str
    target: str | None = None
    workspace: int | None = None
    layout: str | None = None
    label: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        subject = self.label or self.target
        if self.operation == "launch": return f"Abrir {subject}"
        if self.operation in {"move", "isolate"}: return f"Llevar {subject} al workspace {self.workspace}"
        if self.operation == "arrange": return f"Acomodar {subject or 'las ventanas nuevas'} con tiling nativo"
        if self.operation == "workspace_focus": return f"Ir al workspace {self.workspace}"
        if self.operation == "window_state": return str(self.params.get("summary") or f"Cambiar {subject}")
        if self.operation == "window_resize": return str(self.params.get("summary") or f"Redimensionar {subject}")
        if self.operation == "window_swap": return str(self.params.get("summary") or f"Mover {subject}")
        if self.operation == "place_launch": return str(self.params.get("summary") or f"Ubicar {subject}")
        if self.operation == "native": return str(self.params.get("summary") or subject or "Acción de Omarchy")
        if self.operation == "scene_save": return f"Guardar la escena {subject}"
        if self.operation == "scene_apply": return f"Restaurar la escena {subject}"
        if self.operation == "scene_delete": return f"Eliminar la escena {subject}"
        return f"Enfocar {subject}"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "summary": self.summary}


@dataclass
class Plan:
    token: str
    query: str
    confidence: float
    summary: str
    steps: list[Step]
    warnings: list[str] = field(default_factory=list)
    executable: bool = False
    created_at: float = 0.0
    snapshot: dict[str, Any] = field(default_factory=dict)

    @property
    def auto_executable(self) -> bool:
        if not self.executable or not self.steps:
            return False
        for step in self.steps:
            if step.operation in {"launch", "place_launch", "scene_apply"}:
                return False
            if step.operation == "native" and step.target not in AUTOEXECUTE_NATIVE:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "confidence": self.confidence,
            "summary": self.summary,
            "steps": [step.to_dict() for step in self.steps],
            "warnings": self.warnings,
            "executable": self.executable,
            "auto_executable": self.auto_executable,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Plan":
        return cls(
            token=str(data["token"]), query=str(data.get("query", "")),
            confidence=float(data.get("confidence", 0)), summary=str(data.get("summary", "")),
            steps=[Step(**{key: value for key, value in step.items() if key != "summary"}) for step in data.get("steps", [])],
            warnings=list(data.get("warnings", [])), executable=bool(data.get("executable", False)),
            created_at=float(data.get("created_at", 0)), snapshot=dict(data.get("snapshot", {})),
        )
