from __future__ import annotations

import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from director.cli import main
from director.config import jev_socket_candidates, load_config, resolve_jev_socket, save_config, validate_socket_path


class PublicConfigurationTests(unittest.TestCase):
    def test_saved_socket_is_private_and_discovered(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = Path(root, "runtime"); runtime.mkdir()
            socket_path = runtime / "custom.sock"
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(socket_path))
            try:
                with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(Path(root, "config")), "XDG_RUNTIME_DIR": str(runtime)}, clear=False):
                    path = save_config({"jev_socket_path": str(socket_path)})
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(load_config()["jev_socket_path"], str(socket_path))
                    self.assertEqual(resolve_jev_socket(), str(socket_path))
            finally:
                server.close()

    def test_environment_socket_has_priority(self):
        with patch.dict(os.environ, {"JEV_SOCKET_PATH": "/tmp/director-env.sock", "XDG_RUNTIME_DIR": "/tmp/director-runtime"}, clear=False):
            self.assertEqual(jev_socket_candidates()[0], "/tmp/director-env.sock")

    def test_socket_path_must_be_absolute(self):
        with self.assertRaisesRegex(ValueError, "absolute"):
            validate_socket_path("relative.sock")

    def test_configure_cli_writes_json_without_constructing_director(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"XDG_CONFIG_HOME": root}, clear=False):
            output = io.StringIO()
            with patch("sys.stdout", output):
                self.assertEqual(main(["configure", "--jev-socket", "/run/user/1000/jev.sock"]), 0)
            result = json.loads(output.getvalue())
            self.assertTrue(result["ok"])
            self.assertEqual(load_config()["jev_socket_path"], "/run/user/1000/jev.sock")


class PublicPackagingTests(unittest.TestCase):
    def test_release_metadata_and_public_docs_are_present(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "manifest.json").read_text())
        self.assertEqual(manifest["version"], "2.0.0")
        self.assertEqual(manifest["license"], "MIT")
        for relative in ("LICENSE", "SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md", "man/omarchy-director.1"):
            self.assertTrue((root / relative).is_file(), relative)

    def test_public_checkout_contains_no_symlinks(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual([path for path in root.rglob("*") if path.is_symlink()], [])


if __name__ == "__main__":
    unittest.main()
