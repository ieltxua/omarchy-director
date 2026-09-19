from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import socket
from socketserver import ThreadingMixIn
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from .providers import ProviderAdapter, get_provider
from .security import assert_no_sensitive_data


PINNED_MODEL = "typesafe/jev-1.13"


class GatewayError(RuntimeError):
    def __init__(self, message: str, *, status: int = 400, code: str = "JEV_INVALID_REQUEST"):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class GatewayConfig:
    socket_path: Path
    key_file: Path
    provider: ProviderAdapter
    max_body_bytes: int = 1_048_576
    max_questions: int = 64
    timeout_seconds: float = 30.0
    max_concurrent: int = 4
    max_requests_per_minute: int = 120

    @classmethod
    def from_environment(cls) -> "GatewayConfig":
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        try:
            provider = get_provider(os.environ.get("DIRECTOR_JEV_PROVIDER", "openrouter"))
        except ValueError as exc:
            raise GatewayError(str(exc), status=78) from exc
        model = os.environ.get("JEV_DEFAULT_MODEL", provider.model)
        if model != provider.model:
            raise GatewayError("Director's public gateway only permits the pinned Jev model", status=78)
        return cls(
            socket_path=Path(os.environ.get("JEV_SOCKET_PATH", runtime / "omarchy-director" / "jev.sock")),
            key_file=Path(os.environ.get("DIRECTOR_JEV_CREDENTIAL_FILE", config_root / "omarchy-director" / provider.credential_filename)),
            provider=provider,
        )

    @property
    def model(self) -> str:
        return self.provider.model

    def api_key(self) -> str:
        value = os.environ.get(self.provider.credential_environment, "").strip()
        if not value:
            try:
                value = self.key_file.read_text(encoding="utf-8").strip()
            except FileNotFoundError as exc:
                raise GatewayError("OpenRouter credential is not configured", status=503, code="JEV_NOT_CONFIGURED") from exc
        if not value:
            raise GatewayError("OpenRouter credential is empty", status=503, code="JEV_NOT_CONFIGURED")
        return value


def _validate_request(payload: Any, config: GatewayConfig) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise GatewayError("Request body must be an object")
    if payload.get("model") != config.model:
        raise GatewayError("Only the pinned Jev model is allowed", code="JEV_MODEL_NOT_ALLOWED")
    state = payload.get("state")
    questions = payload.get("questions")
    if not isinstance(state, dict) or not isinstance(questions, dict) or not questions:
        raise GatewayError("state and at least one typed question are required")
    if len(questions) > config.max_questions:
        raise GatewayError("Too many questions", status=413, code="JEV_TOO_MANY_QUESTIONS")
    try:
        assert_no_sensitive_data(state)
        assert_no_sensitive_data(questions, "questions")
    except ValueError as exc:
        raise GatewayError(str(exc), code="JEV_SENSITIVE_DATA_BLOCKED") from exc
    for question_id, question in questions.items():
        if not isinstance(question_id, str) or not isinstance(question, dict):
            raise GatewayError("Question IDs and definitions must be objects")
        kind = question.get("type")
        if kind not in {"choice", "noul", "score"} or "instructions" not in question:
            raise GatewayError(f"Question '{question_id}' is invalid")
        criteria = question.get("criteria")
        if kind == "choice" and (not isinstance(criteria, dict) or len(criteria) < 2):
            raise GatewayError(f"Choice '{question_id}' needs at least two criteria")
        if kind == "score" and (not isinstance(criteria, list) or len(criteria) < 2):
            raise GatewayError(f"Score '{question_id}' needs at least two levels")
    return payload


def _probability(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= float(value) <= 1:
        raise GatewayError(f"Invalid upstream probability at {label}", status=502, code="JEV_INVALID_UPSTREAM_RESPONSE")
    return float(value)


def _distribution(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise GatewayError(f"Invalid upstream distribution at {label}", status=502, code="JEV_INVALID_UPSTREAM_RESPONSE")
    total = sum(_probability(entry, f"{label}.{key}") for key, entry in value.items())
    if abs(total - 1) > 0.01:
        raise GatewayError(f"Upstream distribution does not sum to one at {label}", status=502, code="JEV_INVALID_UPSTREAM_RESPONSE")


def _validate_response(payload: Any, request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("model") != request.get("model"):
        raise GatewayError("Invalid upstream response", status=502, code="JEV_INVALID_UPSTREAM_RESPONSE")
    answers = payload.get("answers")
    questions = request["questions"]
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise GatewayError("Upstream answer IDs do not match questions", status=502, code="JEV_INVALID_UPSTREAM_RESPONSE")
    for question_id, question in questions.items():
        answer = answers.get(question_id)
        kind = question["type"]
        if not isinstance(answer, dict) or answer.get("type") != kind:
            raise GatewayError("Upstream answer type mismatch", status=502, code="JEV_INVALID_UPSTREAM_RESPONSE")
        if kind == "noul":
            _probability(answer.get("noul"), question_id)
        elif kind == "choice":
            if answer.get("choice") not in question["criteria"]:
                raise GatewayError("Upstream choice is outside the closed set", status=502, code="JEV_INVALID_UPSTREAM_RESPONSE")
            _probability(answer.get("confidence"), question_id)
            _distribution(answer.get("probabilities"), set(question["criteria"]), question_id)
        else:
            score = answer.get("score")
            if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= float(score) <= len(question["criteria"]) - 1:
                raise GatewayError("Upstream score is outside the rubric", status=502, code="JEV_INVALID_UPSTREAM_RESPONSE")
            _probability(answer.get("confidence"), question_id)
            _distribution(answer.get("probabilities"), {str(index) for index in range(len(question["criteria"]))}, question_id)
    usage = payload.get("usage")
    if not isinstance(usage, dict) or any(not isinstance(usage.get(key), (int, float)) or usage.get(key) < 0 for key in ("input_tokens", "output_tokens")):
        raise GatewayError("Upstream usage metadata is invalid", status=502, code="JEV_INVALID_UPSTREAM_RESPONSE")
    return payload


class _RateGate:
    def __init__(self, limit: int):
        self.limit = limit
        self.events: deque[float] = deque()
        self.lock = threading.Lock()

    def take(self) -> bool:
        now = time.monotonic()
        with self.lock:
            while self.events and self.events[0] <= now - 60:
                self.events.popleft()
            if len(self.events) >= self.limit:
                return False
            self.events.append(now)
            return True


class UnixHTTPServer(ThreadingMixIn, HTTPServer):
    address_family = socket.AF_UNIX
    daemon_threads = True

    def server_bind(self) -> None:
        path = Path(self.server_address)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists():
            if not path.is_socket():
                raise GatewayError(f"Refusing to replace non-socket path: {path}", status=78)
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.settimeout(0.2)
                probe.connect(str(path))
            except (ConnectionRefusedError, FileNotFoundError):
                path.unlink(missing_ok=True)
            except OSError as exc:
                raise GatewayError(f"Cannot verify existing gateway socket: {path}", status=78) from exc
            else:
                raise GatewayError(f"Jev gateway socket is already active: {path}", status=78)
            finally:
                probe.close()
        super().server_bind()
        os.chmod(path, 0o600)


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "OmarchyDirectorJev/1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _json(self, status: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        config: GatewayConfig = self.server.gateway_config  # type: ignore[attr-defined]
        if self.path == "/health/live":
            self._json(200, {"status": "ok", "provider": config.provider.name, "model": config.model})
        elif self.path == "/health/ready":
            try:
                config.api_key()
            except GatewayError as exc:
                self._json(exc.status, {"status": "not_configured", "provider": config.provider.name, "model": config.model})
            else:
                self._json(200, {"status": "local_ready", "configured": True, "provider": config.provider.name, "model": config.model})
        elif self.path == "/health/upstream":
            try:
                request = config.provider.build_probe_request(config.api_key())
                with urlopen(request, timeout=config.timeout_seconds) as response:
                    response.read(65_536)
            except HTTPError as exc:
                status = "auth_failed" if exc.code in {401, 403} else "upstream_error"
                self._json(503, {"status": status, "provider": config.provider.name, "model": config.model})
            except (GatewayError, URLError, TimeoutError):
                self._json(503, {"status": "upstream_unavailable", "provider": config.provider.name, "model": config.model})
            else:
                self._json(200, {"status": "upstream_ready", "authenticated": True, "provider": config.provider.name, "model": config.model})
        else:
            self._json(404, {"error": {"code": "NOT_FOUND", "message": "Not found"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/systemone":
            self._json(404, {"error": {"code": "NOT_FOUND", "message": "Not found"}})
            return
        config: GatewayConfig = self.server.gateway_config  # type: ignore[attr-defined]
        rate_gate: _RateGate = self.server.rate_gate  # type: ignore[attr-defined]
        capacity: threading.BoundedSemaphore = self.server.capacity  # type: ignore[attr-defined]
        acquired = False
        try:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise GatewayError("Invalid Content-Length") from exc
            if length <= 0 or length > config.max_body_bytes:
                raise GatewayError("Invalid request size", status=413, code="JEV_BODY_TOO_LARGE")
            if not rate_gate.take():
                raise GatewayError("Local request rate exceeded", status=429, code="JEV_LOCAL_RATE_LIMIT")
            acquired = capacity.acquire(blocking=False)
            if not acquired:
                raise GatewayError("Local gateway is busy", status=429, code="JEV_LOCAL_QUEUE_FULL")
            try:
                body = json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise GatewayError("Request body must be valid JSON") from exc
            payload = _validate_request(body, config)
            upstream = config.provider.build_request(payload, config.api_key())
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    with urlopen(upstream, timeout=config.timeout_seconds) as response:
                        upstream_raw = response.read(config.max_body_bytes + 1)
                        if len(upstream_raw) > config.max_body_bytes:
                            raise GatewayError("Upstream response is too large", status=502, code="JEV_INVALID_UPSTREAM_RESPONSE")
                        result = json.loads(upstream_raw)
                    self._json(200, _validate_response(result, payload))
                    return
                except HTTPError as exc:
                    last_error = exc
                    if exc.code not in {408, 429} and exc.code < 500:
                        break
                except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                    last_error = exc
                if attempt < 2:
                    time.sleep(0.25 * (2**attempt))
            status = getattr(last_error, "code", 502)
            if not isinstance(status, int) or status < 400 or status > 599:
                status = 502
            raise GatewayError(f"{config.provider.name} request failed", status=status, code="JEV_UPSTREAM_ERROR")
        except GatewayError as exc:
            self._json(exc.status, {"error": {"code": exc.code, "message": str(exc), "retryable": exc.status in {408, 429} or exc.status >= 500}})
        except Exception:
            self._json(500, {"error": {"code": "JEV_GATEWAY_ERROR", "message": "Local gateway error", "retryable": True}})
        finally:
            if acquired:
                capacity.release()


def serve(config: GatewayConfig | None = None) -> None:
    selected = config or GatewayConfig.from_environment()
    server = UnixHTTPServer(str(selected.socket_path), GatewayHandler)
    server.gateway_config = selected  # type: ignore[attr-defined]
    server.rate_gate = _RateGate(selected.max_requests_per_minute)  # type: ignore[attr-defined]
    server.capacity = threading.BoundedSemaphore(selected.max_concurrent)  # type: ignore[attr-defined]
    try:
        server.serve_forever()
    finally:
        server.server_close()
        try:
            selected.socket_path.unlink()
        except FileNotFoundError:
            pass
