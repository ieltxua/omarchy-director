from __future__ import annotations

import json
from typing import Any
from urllib.request import Request

from . import ProviderAdapter


class OpenRouterAdapter(ProviderAdapter):
    def build_request(self, payload: dict[str, Any], credential: str) -> Request:
        return Request(
            "https://openrouter.ai/api/alpha/decisions",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {credential}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-OpenRouter-Title": "Omarchy Director",
                "X-OpenRouter-Categories": "desktop-agent,local-agent",
            },
        )

    def build_probe_request(self, credential: str) -> Request:
        return Request(
            "https://openrouter.ai/api/v1/key",
            method="GET",
            headers={"Authorization": f"Bearer {credential}", "Accept": "application/json"},
        )


OPENROUTER = OpenRouterAdapter(
    name="openrouter",
    model="typesafe/jev-1.13",
    credential_environment="OPENROUTER_API_KEY",
    credential_filename="openrouter_api_key",
)
