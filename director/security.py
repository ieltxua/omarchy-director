from __future__ import annotations

import re
from typing import Any


SENSITIVE_KEY = re.compile(r"(^|_)(password|passwd|secret|token|api_?key|authorization|cookie|private_?key)($|_)", re.I)
SENSITIVE_VALUE = re.compile(
    r"(-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\bBearer\s+[A-Za-z0-9._~+/=-]+"
    r"|\b(?:sk|ts)-[A-Za-z0-9_-]{16,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\b(?:password|passwd|secret|token|api[_-]?key|OPENROUTER_API_KEY)\s*[:=]\s*[^\s,;]+)",
    re.I,
)


def assert_no_sensitive_data(value: Any, path: str = "state") -> None:
    if isinstance(value, str):
        if SENSITIVE_VALUE.search(value):
            raise ValueError(f"Credential-like data is not allowed at {path}")
    elif isinstance(value, list):
        for index, entry in enumerate(value):
            assert_no_sensitive_data(entry, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, entry in value.items():
            if SENSITIVE_KEY.search(str(key)):
                raise ValueError(f"Sensitive field is not allowed at {path}")
            assert_no_sensitive_data(entry, f"{path}.{key}")


def redact_sensitive_text(value: str) -> str:
    return SENSITIVE_VALUE.sub("[REDACTED]", value)
