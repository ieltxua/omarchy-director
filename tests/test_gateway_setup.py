from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from director.config import normalized_config, set_alias
from director.gateway import GatewayConfig, GatewayHandler, UnixHTTPServer, _RateGate
from director.jev import Jev, JevError
from director.models import Plan, Step
from director.providers import get_provider, provider_names
from director.setup import setup_gateway, teardown_gateway
from director.security import redact_sensitive_text
from director.service import Director
from director.store import Store


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int = -1) -> bytes:
        return json.dumps(self.payload).encode()


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        key = root / "key"
        key.write_text("test-key\n", encoding="utf-8")
        key.chmod(0o600)
        self.config = GatewayConfig(socket_path=root / "jev.sock", key_file=key, provider=get_provider("openrouter"))
        self.server = UnixHTTPServer(str(self.config.socket_path), GatewayHandler)
        self.server.gateway_config = self.config
        self.server.rate_gate = _RateGate(120)
        self.server.capacity = threading.BoundedSemaphore(4)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def test_health_reports_pinned_local_gateway(self):
        self.assertEqual(Jev(str(self.config.socket_path)).health()["model"], "typesafe/jev-1.13")

    def test_upstream_health_uses_provider_probe_without_inference(self):
        with patch("director.gateway.urlopen", return_value=_Response({"data": {}})) as upstream:
            health = Jev(str(self.config.socket_path)).health(upstream=True)
        self.assertEqual(health["status"], "upstream_ready")
        request = upstream.call_args.args[0]
        self.assertEqual(request.full_url, "https://openrouter.ai/api/v1/key")

    def test_typed_decision_round_trip(self):
        upstream = {
            "model": "typesafe/jev-1.13",
            "answers": {"intent": {"type": "choice", "choice": "focus", "confidence": 0.97, "probabilities": {"focus": 0.97, "none": 0.03}}},
            "usage": {"input_tokens": 4, "output_tokens": 2},
        }
        with patch("director.gateway.urlopen", return_value=_Response(upstream)):
            answers = Jev(str(self.config.socket_path)).decide(
                {"request": "focus terminal"},
                {"intent": {"type": "choice", "instructions": "Select intent", "criteria": {"focus": "focus", "none": "no match"}}},
            )
        self.assertEqual(answers["intent"]["choice"], "focus")

    def test_response_from_an_unexpected_model_is_rejected(self):
        upstream = {
            "model": "some/other-model",
            "answers": {"intent": {"type": "choice", "choice": "focus", "confidence": 0.97, "probabilities": {"focus": 0.97, "none": 0.03}}},
            "usage": {"input_tokens": 4, "output_tokens": 2},
        }
        with patch("director.gateway.urlopen", return_value=_Response(upstream)):
            with self.assertRaises(JevError):
                Jev(str(self.config.socket_path)).decide(
                    {"request": "focus terminal"},
                    {"intent": {"type": "choice", "instructions": "Select intent", "criteria": {"focus": "focus", "none": "no match"}}},
                )

    def test_sensitive_state_is_rejected_before_upstream(self):
        with patch("director.gateway.urlopen") as upstream:
            with self.assertRaises(JevError):
                Jev(str(self.config.socket_path)).decide(
                    {"api_key": "not-sent"},
                    {"intent": {"type": "choice", "instructions": "Select", "criteria": {"yes": "yes", "no": "no"}}},
                )
            upstream.assert_not_called()

    def test_common_secret_shapes_are_rejected_in_state_and_questions(self):
        samples = (
            "ghp_abcdefghijklmnopqrstuvwxyz123456",
            "AKIAABCDEFGHIJKLMNOP",
            "password=hunter2",
            "OPENROUTER_API_KEY=abc123",
        )
        for sample in samples:
            with self.subTest(sample=sample), patch("director.gateway.urlopen") as upstream:
                with self.assertRaises(JevError):
                    Jev(str(self.config.socket_path)).decide(
                        {"request": sample},
                        {"intent": {"type": "choice", "instructions": "Select", "criteria": {"yes": "yes", "no": "no"}}},
                    )
                upstream.assert_not_called()
        with patch("director.gateway.urlopen") as upstream:
            with self.assertRaises(JevError):
                Jev(str(self.config.socket_path)).decide(
                    {"request": "safe"},
                    {"intent": {"type": "choice", "instructions": "token=abc123", "criteria": {"yes": "yes", "no": "no"}}},
                )
            upstream.assert_not_called()

    def test_second_gateway_refuses_to_replace_live_socket(self):
        with self.assertRaisesRegex(Exception, "already active"):
            UnixHTTPServer(str(self.config.socket_path), GatewayHandler)
        self.assertEqual(Jev(str(self.config.socket_path)).health()["status"], "local_ready")


class SetupTests(unittest.TestCase):
    def test_setup_from_environment_writes_private_files_without_embedding_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = root / "plugin" / "bin" / "omarchy-director"
            command.parent.mkdir(parents=True)
            command.write_text("#!/bin/sh\n", encoding="utf-8")
            environment = {
                "HOME": str(root / "home"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_RUNTIME_DIR": str(root / "runtime"),
                "OPENROUTER_API_KEY": "secret-test-key",
            }
            with patch.dict(os.environ, environment, clear=False):
                from director.config import save_config
                save_config({"aliases": {"apps": {"browser": "firefox.desktop"}}})
                result = setup_gateway(command, start=False)
            credential = Path(str(result["credential"]))
            unit = Path(str(result["service"]))
            self.assertEqual(credential.stat().st_mode & 0o777, 0o600)
            self.assertEqual(credential.read_text().strip(), "secret-test-key")
            self.assertNotIn("secret-test-key", unit.read_text())
            self.assertIn("typesafe/jev-1.13", unit.read_text())
            self.assertIn("DIRECTOR_JEV_PROVIDER=openrouter", unit.read_text())
            with patch.dict(os.environ, environment, clear=False):
                from director.config import load_config
                self.assertEqual(load_config()["aliases"]["apps"]["browser"], "firefox.desktop")

    def test_provider_registry_is_explicit_and_pinned(self):
        self.assertEqual(provider_names(), ("openrouter",))
        self.assertEqual(get_provider("openrouter").model, "typesafe/jev-1.13")

    def test_setup_refuses_unmanaged_unit_before_writing_credential(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = root / "plugin" / "bin" / "omarchy-director"
            command.parent.mkdir(parents=True)
            command.write_text("#!/bin/sh\n", encoding="utf-8")
            environment = {
                "HOME": str(root / "home"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_RUNTIME_DIR": str(root / "runtime"),
                "OPENROUTER_API_KEY": "must-not-be-written",
            }
            with patch.dict(os.environ, environment, clear=False):
                from director.setup import credential_path, service_path
                unit = service_path()
                unit.parent.mkdir(parents=True)
                unit.write_text("# owned by somebody else\n", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "unmanaged service"):
                    setup_gateway(command, start=False)
                self.assertFalse(credential_path().exists())

    def test_teardown_keeps_managed_unit_when_systemctl_stop_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = {"HOME": str(root / "home"), "XDG_CONFIG_HOME": str(root / "config")}
            with patch.dict(os.environ, environment, clear=False), patch("director.setup.shutil.which", return_value="/usr/bin/systemctl"):
                from director.setup import service_path
                unit = service_path()
                unit.parent.mkdir(parents=True)
                unit.write_text("# Managed by Omarchy Director\n")

                class Failed:
                    returncode = 1
                    stderr = "stop failed"

                with self.assertRaisesRegex(RuntimeError, "stop failed"):
                    teardown_gateway(runner=lambda *_args, **_kwargs: Failed())
                self.assertTrue(unit.exists())

    def test_teardown_without_purge_ignores_retired_provider_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = {"HOME": str(root / "home"), "XDG_CONFIG_HOME": str(root / "config")}
            with patch.dict(os.environ, environment, clear=False), patch("director.setup.shutil.which", return_value=None):
                from director.config import save_config
                from director.setup import service_path
                save_config({"jev_provider": "retired-provider"})
                unit = service_path()
                unit.parent.mkdir(parents=True)
                unit.write_text("# Managed by Omarchy Director\n")
                result = teardown_gateway(purge_key=False)
                self.assertTrue(result["service_removed"])
                self.assertFalse(unit.exists())

    def test_teardown_without_unit_does_not_call_systemctl(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = {"HOME": str(root / "home"), "XDG_CONFIG_HOME": str(root / "config")}
            with patch.dict(os.environ, environment, clear=False), patch("director.setup.shutil.which", return_value="/usr/bin/systemctl"):
                calls: list[list[str]] = []
                result = teardown_gateway(runner=lambda argv, **_kwargs: calls.append(argv))
            self.assertEqual(calls, [])
            self.assertFalse(result["service_removed"])


class CustomizationPolicyTests(unittest.TestCase):
    def test_aliases_are_normalized_and_yolo_can_only_narrow_hard_policy(self):
        values: dict = {"yolo_allow": ["focus"]}
        set_alias(values, "apps", "Browser=firefox.desktop")
        config = normalized_config(values)
        self.assertEqual(config["aliases"]["apps"], {"browser": "firefox.desktop"})
        safe = Plan("t", "", 1, "", [Step("focus", "0x1")], executable=True)
        blocked = Plan("t", "", 1, "", [Step("move", "0x1", workspace=2)], executable=True)
        self.assertTrue(safe.to_dict(set(config["yolo_allow"]))["auto_executable"])
        self.assertFalse(blocked.to_dict(set(config["yolo_allow"]))["auto_executable"])
        irreversible = Plan("t", "", 1, "", [Step("launch", "firefox.desktop")], executable=True)
        self.assertFalse(irreversible.to_dict({"launch"})["auto_executable"])

    def test_volume_and_brightness_require_preview_even_if_user_allowlists_them(self):
        for capability in ("volume_up", "volume_down", "brightness_up", "brightness_down", "theme_set", "stay_awake", "allow_idle"):
            plan = Plan("t", "", 1, "", [Step("native", capability)], executable=True)
            self.assertFalse(plan.to_dict({capability})["auto_executable"])

    def test_credential_like_query_is_redacted_before_persistence(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(temporary)
            director = Director(hypr=object(), jev=object(), store=store, native=object())
            plan = Plan("token", "use sk-aaaaaaaaaaaaaaaaaaaaaaaa", 0, "rejected", [], ["blocked"], False, time.time())
            director._store_plan(plan)
            self.assertEqual(store.diagnostics()[0]["query"], "use [REDACTED]")
            self.assertEqual(store.plans()[0]["query"], "use [REDACTED]")

    def test_common_secret_shapes_are_redacted_before_persistence(self):
        samples = (
            "ghp_abcdefghijklmnopqrstuvwxyz123456",
            "AKIAABCDEFGHIJKLMNOP",
            "password=hunter2",
            "OPENROUTER_API_KEY=abc123",
        )
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(redact_sensitive_text(f"use {sample}"), "use [REDACTED]")


if __name__ == "__main__":
    unittest.main()
