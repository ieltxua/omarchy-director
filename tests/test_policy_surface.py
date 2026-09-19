from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from director.models import Plan, Step


REPO = Path(__file__).resolve().parents[1]


class AutoExecutePolicyTests(unittest.TestCase):
    def plan(self, step: Step, executable: bool = True) -> Plan:
        return Plan("token", "query", 1, "summary", [step], [], executable)

    def test_reversible_window_action_is_auto_executable(self):
        self.assertTrue(self.plan(Step("move", "0xabc", workspace=2)).auto_executable)

    def test_launch_and_place_are_never_auto_executable(self):
        self.assertFalse(self.plan(Step("launch", "slack")).auto_executable)
        self.assertFalse(self.plan(Step("place_launch", "slack", workspace=2)).auto_executable)

    def test_irreversible_native_capabilities_are_never_auto_executable(self):
        for capability in ("screenshot", "screenrecord_start", "reminder", "audio_output_switch", "lock"):
            with self.subTest(capability=capability):
                self.assertFalse(self.plan(Step("native", capability)).auto_executable)

    def test_safe_native_capability_is_auto_executable(self):
        self.assertTrue(self.plan(Step("native", "volume_up")).auto_executable)

    def test_serialized_policy_is_the_qml_authority(self):
        payload = self.plan(Step("native", "lock")).to_dict()
        self.assertIs(payload["auto_executable"], False)
        qml = (REPO / "Director.qml").read_text(encoding="utf-8")
        self.assertIn("candidate.auto_executable === true", qml)


class SemanticContractTests(unittest.TestCase):
    def test_contract_ids_and_expectations_are_well_formed(self):
        payload = json.loads((REPO / "tests/contracts/semantic.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        cases = payload["cases"]
        ids = [case["id"] for case in cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(cases), 15)
        for case in cases:
            self.assertIsInstance(case["query"], str)
            self.assertTrue(case["query"].strip())
            self.assertIsInstance(case["executable"], bool)
            if case["executable"]:
                self.assertTrue(case.get("operations"))


class VoiceAdapterTests(unittest.TestCase):
    def make_binary(self, directory: Path, name: str, body: str) -> None:
        path = directory / name
        path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body, encoding="utf-8")
        path.chmod(0o755)

    def run_flow(self, yolo: bool) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "bin"
            runtime = root / "runtime"
            binary.mkdir()
            runtime.mkdir()
            state = root / "voxtype-state"
            calls = root / "calls.jsonl"
            self.make_binary(binary, "voxtype", """
case "${1:-}" in
  status) exit 0 ;;
  record)
    case "${2:-}" in
      start)
        for arg in "$@"; do case "$arg" in --file=*) printf '%s' "${arg#--file=}" >"$VOXTYPE_STATE" ;; esac; done
        ;;
      stop)
        transcript="$(<"$VOXTYPE_STATE")"
        printf '%s\n' 'move Director E2E Alpha to workspace 92' >"$transcript"
        printf '%s\n' '{"ok":true}'
        ;;
      cancel) ;;
    esac
    ;;
esac
""")
            self.make_binary(binary, "omarchy-shell", "printf '%s\\n' \"$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' \"$@\")\" >>\"$DIRECTOR_CALLS\"\n")
            self.make_binary(binary, "omarchy-director-ui", "printf '%s\\n' \"$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' \"$@\")\" >>\"$DIRECTOR_CALLS\"\n")
            environment = {
                **os.environ,
                "PATH": f"{binary}:{os.environ.get('PATH', '')}",
                "OMARCHY_PATH": "/usr/share/omarchy",
                "XDG_RUNTIME_DIR": str(runtime),
                "VOXTYPE_STATE": str(state),
                "DIRECTOR_CALLS": str(calls),
            }
            voice = str(REPO / "bin/omarchy-director-voice")
            mode = "--yolo" if yolo else "--preview"
            subprocess.run([voice, "start", mode], env=environment, check=True, capture_output=True, text=True)
            subprocess.run([voice, "stop"], env=environment, check=True, capture_output=True, text=True)
            return [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]

    def test_preview_transcript_never_requests_execution(self):
        calls = self.run_flow(False)
        self.assertEqual(calls[-1], ["--query", "move Director E2E Alpha to workspace 92"])

    def test_yolo_transcript_requests_policy_gated_execution(self):
        calls = self.run_flow(True)
        self.assertEqual(calls[-1], ["--query", "move Director E2E Alpha to workspace 92", "--execute"])


if __name__ == "__main__":
    unittest.main()
