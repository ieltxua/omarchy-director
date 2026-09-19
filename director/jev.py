from __future__ import annotations

import http.client
import json
import os
import socket
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
    def __init__(self, socket_path: str | None = None, connection=UnixHTTPConnection):
        self.socket_path = socket_path or resolve_jev_socket()
        self.connection = connection

    def decide(self, state: dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """One typed, bounded request; semantic output is never free-form."""
        if not questions:
            raise JevError("Jev requires at least one typed question")
        payload = {"model": "typesafe/jev-1.13", "state": state, "questions": questions}
        try:
            conn = self.connection(self.socket_path)
            conn.request("POST", "/v1/systemone", body=json.dumps(payload), headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            raw = response.read().decode("utf-8")
            if response.status != 200:
                raise JevError("Jev gateway rejected request")
            answers = json.loads(raw).get("answers")
            if not isinstance(answers, dict):
                raise JevError("Jev response did not contain typed answers")
            return answers
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
            raise JevError("Jev gateway unavailable or invalid") from exc
