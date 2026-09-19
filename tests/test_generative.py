"""Seed-reproducible high-volume properties for Director's desktop core.

Set ``DIRECTOR_GENERATIVE_SEED`` to replay a failing generated case.  The
default fixed seed makes CI deterministic while still covering 4,000+ generated
states, utterance variants, and execute/undo sequences without third-party
property-testing dependencies.
"""

from __future__ import annotations

import os
import math
import random
import unittest
from unittest.mock import patch

from director.models import Plan, Step
from director.scenes import capture_scene, match_window_specs
from director.service import Director
from tests.support.generative_harness import InMemoryHyprland, MemoryStore, StaticJev, answer_set, client, window_fingerprint


SEED = int(os.environ.get("DIRECTOR_GENERATIVE_SEED", "20260919"), 0)
CASE_BUDGET = max(100, int(os.environ.get("DIRECTOR_GENERATED_CASES", "5040")))


def case_count(baseline: int) -> int:
    return max(1, math.ceil(CASE_BUDGET * baseline / 5040))


def generated_clients(randomizer: random.Random, count: int) -> list[dict[str, object]]:
    classes = ("foot", "chromium", "code", "slack", "thunderbird")
    result = []
    for index in range(count):
        window_class = randomizer.choice(classes)
        result.append(client(
            f"0x{index + 0x100:x}",
            f"{window_class.title()} document {index} {randomizer.randrange(1_000_000)}",
            window_class,
            randomizer.randrange(1, 7),
            floating=randomizer.choice((False, False, True)),
            fullscreen=randomizer.choice((False, False, False, True)),
            at=(randomizer.randrange(0, 1200), randomizer.randrange(0, 700)),
            size=(randomizer.randrange(320, 1600), randomizer.randrange(240, 1000)),
        ))
    return result


class DirectorGenerativeTests(unittest.TestCase):
    def assertCase(self, condition: bool, case: int, message: str) -> None:
        self.assertTrue(condition, f"seed={SEED} case={case}: {message}")

    def test_explicit_utterances_select_the_exact_unique_window(self):
        """1,600 randomized title/class queries never select a similarly named peer."""
        randomizer = random.Random(SEED ^ 0x51EC7)
        for case in range(case_count(1600)):
            clients = generated_clients(randomizer, randomizer.randrange(2, 10))
            target = randomizer.choice(clients)
            target["title"] = f"Needle-{case}-{randomizer.randrange(1_000_000)}"
            hypr = InMemoryHyprland(clients)
            director = Director(hypr, StaticJev(answer_set("focus")), MemoryStore(), sleeper=lambda _: None)
            utterance = randomizer.choice(("focus", "enfocá", "mostrame", "bring me"))
            plan = director.plan(f"{utterance} Needle-{case}-{target['title'].split('-')[-1]}")
            self.assertCase(plan.executable, case, repr(plan.warnings))
            self.assertEqual([(step.operation, step.target) for step in plan.steps], [("focus", target["address"])], f"seed={SEED} case={case}")

    def test_execute_then_undo_restores_generated_desktop_invariants(self):
        """1,800 operations preserve target geometry/state/focus after undo."""
        randomizer = random.Random(SEED ^ 0xA11CE)
        # Keep test construction deterministic and avoid external desktop discovery.
        with patch("director.service.desktop_entries", return_value={}):
            for case in range(case_count(1800)):
                clients = generated_clients(randomizer, randomizer.randrange(2, 8))
                target = randomizer.choice(clients)
                hypr = InMemoryHyprland(clients, active=str(target["address"]))
                store = MemoryStore()
                director = Director(hypr, StaticJev({}), store, sleeper=lambda _: None)
                original = window_fingerprint(hypr, str(target["address"]))
                action = case % 5
                if action == 0:
                    destination = randomizer.randrange(1, 7)
                    step = Step("move", str(target["address"]), workspace=destination)
                elif action == 1:
                    step = Step("window_state", str(target["address"]), params={"state": "float"})
                elif action == 2:
                    step = Step("window_state", str(target["address"]), params={"state": "fullscreen_on"})
                elif action == 3:
                    step = Step("window_resize", str(target["address"]), params={"width": randomizer.randrange(320, 1500), "height": randomizer.randrange(240, 950)})
                else:
                    step = Step("workspace_focus", workspace=randomizer.randrange(1, 7))
                snapshot = Director._snapshot({str(item["address"]): item for item in clients}, [str(target["address"])], hypr.state()["active"])
                plan = Plan(f"generated-{case}", "", 1, "generated", [step], executable=True, snapshot=snapshot)
                store.save_plan({**plan.to_dict(), "query": "", "created_at": plan.created_at + 1, "snapshot": snapshot})
                result = director.execute(plan.token)
                self.assertCase(result["executed"], case, repr(result))
                undo = director.undo()
                self.assertCase(undo["undone"], case, repr(undo))
                self.assertEqual(window_fingerprint(hypr, str(target["address"])), original, f"seed={SEED} case={case} action={action}")

    def test_already_satisfied_window_state_is_a_generated_noop(self):
        """500 desired-state operations issue no compositor mutation and remain undoable."""
        with patch("director.service.desktop_entries", return_value={}):
            for case in range(case_count(500)):
                desired_fullscreen = bool(case % 2)
                target = client("0x100", f"Noop {case}", "foot", 1, floating=not desired_fullscreen, fullscreen=desired_fullscreen)
                hypr = InMemoryHyprland([target], active="0x100")
                store = MemoryStore()
                director = Director(hypr, StaticJev({}), store, sleeper=lambda _: None)
                original = window_fingerprint(hypr, "0x100")
                state = "fullscreen_on" if desired_fullscreen else "float"
                snapshot = Director._snapshot({"0x100": target}, ["0x100"], hypr.state()["active"])
                plan = Plan(f"noop-{case}", "", 1, "generated", [Step("window_state", "0x100", params={"state": state})], executable=True, snapshot=snapshot)
                store.save_plan({**plan.to_dict(), "query": "", "created_at": 1, "snapshot": snapshot})
                director.execute(plan.token)
                self.assertEqual(hypr.calls, [], f"seed={SEED} case={case}")
                self.assertEqual(window_fingerprint(hypr, "0x100"), original, f"seed={SEED} case={case}")
                director.undo()
                self.assertEqual(window_fingerprint(hypr, "0x100"), original, f"seed={SEED} case={case}")

    def test_scene_matching_is_one_to_one_across_duplicate_generated_classes(self):
        """900 shuffled scene/live states neither reuse a client nor lose title matches."""
        randomizer = random.Random(SEED ^ 0x5CE0E)
        for case in range(case_count(900)):
            saved_clients = generated_clients(randomizer, randomizer.randrange(2, 12))
            # Re-address and shuffle the live windows; semantic fields stay equal.
            live = []
            for index, saved in enumerate(saved_clients):
                rebuilt = dict(saved)
                rebuilt["address"] = f"0x{case:x}{index:x}f"
                live.append(rebuilt)
            randomizer.shuffle(live)
            scene = capture_scene({"clients": saved_clients, "active": saved_clients[0]})
            result = match_window_specs(scene["windows"], live)
            matched = [pair["client"]["address"] for pair in result["matches"]]
            self.assertCase(not result["missing"], case, repr(result["missing"]))
            self.assertEqual(len(matched), len(set(matched)), f"seed={SEED} case={case}")
            self.assertEqual(len(matched), len(saved_clients), f"seed={SEED} case={case}")

    def test_stale_plans_and_execution_failures_do_not_leave_partial_state(self):
        """240 generated drift/failure cases reject safely or restore the snapshot."""
        randomizer = random.Random(SEED ^ 0xD12F7)
        with patch("director.service.desktop_entries", return_value={}):
            for case in range(case_count(240)):
                clients = generated_clients(randomizer, randomizer.randrange(2, 7))
                target = randomizer.choice(clients)
                hypr = InMemoryHyprland(clients)
                store = MemoryStore()
                director = Director(hypr, StaticJev({}), store, sleeper=lambda _: None)
                original = window_fingerprint(hypr, str(target["address"]))
                snapshot = Director._snapshot({str(item["address"]): item for item in clients}, [str(target["address"])], hypr.state()["active"])
                plan = Plan(f"drift-{case}", "", 1, "generated", [Step("arrange", str(target["address"]), workspace=7, layout="tile")], executable=True, snapshot=snapshot)
                store.save_plan({**plan.to_dict(), "query": "", "created_at": 1, "snapshot": snapshot})
                if case % 2 == 0:
                    hypr.remove(str(target["address"]))
                    with self.assertRaisesRegex(ValueError, "state changed"):
                        director.execute(plan.token)
                    self.assertEqual(store.history(), [], f"seed={SEED} case={case}")
                else:
                    hypr.fail_next = "set_floating"
                    with self.assertRaisesRegex(RuntimeError, "previous window state was restored"):
                        director.execute(plan.token)
                    # A rollback restores the captured window and active client.  Its
                    # monitor workspace is intentionally not part of Director's
                    # snapshot contract for a failed arrange.
                    self.assertEqual(window_fingerprint(hypr, str(target["address"]))[:6], original[:6], f"seed={SEED} case={case}")

    def test_tiled_snapshot_restores_relative_slot_after_workspace_reinsertion(self):
        alpha = client("0x100", "Alpha", "foot", 91, at=(950, 0), size=(950, 1000))
        beta = client("0x200", "Beta", "foot", 91, at=(0, 0), size=(950, 1000))
        hypr = InMemoryHyprland([alpha, beta], active="0x200")
        director = Director(hypr, StaticJev({}), MemoryStore(), sleeper=lambda _: None)
        snapshot = {
            "windows": {"0x100": {**alpha, "at": [0, 0]}},
            "active": "0x200",
        }
        warnings = director._restore_snapshot(snapshot)
        self.assertEqual(warnings, [])
        self.assertEqual(hypr._client("0x100")["at"], [0, 0])
        self.assertEqual(hypr._client("0x200")["at"], [950, 0])


if __name__ == "__main__":
    unittest.main()
