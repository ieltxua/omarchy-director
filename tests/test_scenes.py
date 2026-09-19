from __future__ import annotations

import tempfile
import unittest

from director.scenes import SceneManager, SceneStore, capture_scene, match_window_specs, normalize_scene_name
from director.store import Store


class FakeHypr:
    def __init__(self, state): self.current = state
    def state(self): return self.current


def client(address, title, workspace=1):
    return {"address": address, "class": "foot", "initialClass": "foot", "title": title, "workspace": {"id": workspace, "name": str(workspace)}, "floating": False, "fullscreen": False, "at": [10, 20], "size": [800, 600]}


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
    def tearDown(self): self.temp.cleanup()

    def test_capture_is_semantic_and_has_an_address_free_active_selector(self):
        scene = capture_scene({"clients": [client("0xaaa", "one")], "active": {"address": "0xaaa"}})
        self.assertEqual(scene["windows"][0]["class"], "foot")
        self.assertEqual(scene["windows"][0]["workspace"]["id"], 1)
        self.assertNotIn("address", repr(scene))
        self.assertEqual(scene["active_window"]["title_hint"], "one")

    def test_duplicate_classes_match_by_title_without_reusing_clients(self):
        saved = capture_scene({"clients": [client("0x1", "first"), client("0x2", "second")]})
        specs = [saved["windows"][1], saved["windows"][0]]
        result = match_window_specs(specs, [client("0xa", "first"), client("0xb", "second")])
        self.assertEqual([pair["client"]["address"] for pair in result["matches"]], ["0xb", "0xa"])
        self.assertEqual(result["missing"], [])
        partial = match_window_specs(specs, [client("0xa", "first")])
        self.assertEqual([pair["client"]["address"] for pair in partial["matches"]], ["0xa"])
        self.assertEqual([spec["title_hint"] for spec in partial["missing"]], ["second"])

    def test_names_are_normalized_and_invalid_names_rejected(self):
        self.assertEqual(normalize_scene_name("  Trabajo - Mañana  "), "trabajo-manana")
        with self.assertRaises(ValueError): normalize_scene_name("---")

    def test_persistence_update_and_deletion(self):
        manager = SceneManager(FakeHypr({"clients": [client("0x1", "one")], "active": {"address": "0x1"}}), self.store)
        saved = manager.capture("My scene")
        self.assertEqual(saved["name"], "my-scene")
        self.assertEqual([scene["name"] for scene in manager.list()], ["my-scene"])
        self.assertEqual(manager.get("my scene")["windows"][0]["title_hint"], "one")
        manager.hypr.current = {"clients": [client("0x2", "two")], "active": {"address": "0x2"}}
        self.assertEqual(manager.update("MY SCENE")["windows"][0]["title_hint"], "two")
        self.assertTrue(manager.delete("my scene"))
        self.assertIsNone(manager.get("my scene"))

    def test_scene_store_update_requires_an_existing_scene(self):
        with self.assertRaises(KeyError): SceneStore(self.store).update("missing", {"windows": []})
