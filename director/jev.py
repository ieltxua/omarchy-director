from __future__ import annotations

import http.client
import json
import os
import socket
import time
from typing import Any

from .config import resolve_jev_socket


class JevError(RuntimeError):
    pass


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str):
        super().__init__("localhost")
        self.socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)


class Jev:
    def __init__(self, socket_path: str | None = None, connection=UnixHTTPConnection, sleeper=time.sleep):
        self.socket_path = socket_path or resolve_jev_socket()
        self.connection = connection
        self.sleeper = sleeper

    def health(self, *, upstream: bool = False) -> dict[str, Any]:
        try:
            conn = self.connection(self.socket_path)
            conn.request("GET", "/health/upstream" if upstream else "/health/ready")
            response = conn.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            if response.status != 200 or not isinstance(payload, dict):
                raise JevError("Jev gateway is not ready")
            return payload
        except JevError:
            raise
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise JevError("Jev gateway unavailable or invalid") from exc

    def decide(self, state: dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """One typed, bounded request; semantic output is never free-form."""
        if not questions:
            raise JevError("Jev requires at least one typed question")
        payload = {"model": "typesafe/jev-1.13", "state": state, "questions": questions}
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                conn = self.connection(self.socket_path)
                conn.request("POST", "/v1/systemone", body=json.dumps(payload), headers={"Content-Type": "application/json"})
                response = conn.getresponse()
                raw = response.read().decode("utf-8")
                if response.status != 200:
                    if response.status >= 500:
                        raise OSError(f"transient Jev gateway status {response.status}")
                    raise JevError("Jev gateway rejected request")
                answers = json.loads(raw).get("answers")
                if not isinstance(answers, dict):
                    raise ValueError("Jev response did not contain typed answers")
                return answers
            except JevError:
                raise
            except (OSError, ValueError, http.client.HTTPException) as exc:
                last_error = exc
                if attempt == 0:
                    self.sleeper(0.1)
        raise JevError("Jev gateway unavailable or invalid") from last_error
