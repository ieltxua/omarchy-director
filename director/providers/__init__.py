from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.request import Request


@dataclass(frozen=True)
class ProviderAdapter:
    name: str
    model: str
    credential_environment: str
    credential_filename: str

    def build_request(self, payload: dict[str, Any], credential: str) -> Request:
        raise NotImplementedError

    def build_probe_request(self, credential: str) -> Request:
        raise NotImplementedError


def provider_names() -> tuple[str, ...]:
    return tuple(sorted(_PROVIDERS))


def get_provider(name: str) -> ProviderAdapter:
    try:
        return _PROVIDERS[name]
    except KeyError as exc:
        raise ValueError(f"Unsupported Jev provider: {name}") from exc


from .openrouter import OPENROUTER  # noqa: E402

_PROVIDERS: dict[str, ProviderAdapter] = {OPENROUTER.name: OPENROUTER}
