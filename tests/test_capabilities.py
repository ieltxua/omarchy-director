from __future__ import annotations

import unittest
from unittest.mock import Mock

from director.capabilities import CapabilityError, NativeCapabilities


class Result:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


class NativeCapabilitiesTests(unittest.TestCase):
    def test_theme_is_closed_over_installed_values_and_undoes(self):
        runner = Mock(side_effect=[Result("Osaka Jade\nNord\n"), Result("Osaka Jade\n"), Result()])
        native = NativeCapabilities(runner)
        step = native.build_step("theme_set", "use Nord", "Nord")
        result = native.execute(step)
        self.assertEqual(result.undo_step.params["theme"], "Osaka Jade")
        self.assertEqual(runner.call_args.args[0], ["omarchy", "theme", "set", "Nord"])

    def test_theme_rejects_uninstalled_name(self):
        native = NativeCapabilities(Mock(return_value=Result("Nord\n")))
        with self.assertRaises(CapabilityError): native.build_step("theme_set", "theme Evil", "Evil")

    def test_volume_bounds_and_exact_argv(self):
        def run(argv, **kwargs):
            if argv[:2] == ["wpctl", "get-volume"]: return Result("Volume: 0.70\n" if run.reads == 0 else "Volume: 0.90\n")
            return Result()
        run.reads = 0
        def counting_run(argv, **kwargs):
            result = run(argv, **kwargs)
            if argv[:2] == ["wpctl", "get-volume"]: run.reads += 1
            return result
        runner = Mock(side_effect=counting_run); native = NativeCapabilities(runner)
        step = native.build_step("volume_up", "raise volume 99 percent")
        self.assertEqual(step.params["amount"], 20)
        undo = native.execute(step).undo_step
        self.assertIn(["omarchy", "audio", "output", "volume", "+20"], [call.args[0] for call in runner.call_args_list])
        self.assertEqual(undo.target, "volume_set"); self.assertEqual(undo.params["percent"], 70)

    def test_volume_at_ceiling_does_not_create_a_false_inverse(self):
        def run(argv, **kwargs):
            return Result("Volume: 1.00\n") if argv[:2] == ["wpctl", "get-volume"] else Result()
        native = NativeCapabilities(Mock(side_effect=run))
        result = native.execute(native.build_step("volume_up", "raise volume 5 percent"))
        self.assertIsNone(result.undo_step)

    def test_reminder_parses_bounded_time_and_message(self):
        step = NativeCapabilities(Mock()).build_step("reminder", "remind me in 2 hours to stretch")
        self.assertEqual(step.params["minutes"], 120); self.assertEqual(step.params["message"], "stretch")

    def test_spanish_reminder_keeps_message_after_full_unit(self):
        step = NativeCapabilities(Mock()).build_step("reminder", "recordame en 20 minutos estirar")
        self.assertEqual((step.params["minutes"], step.params["message"]), (20, "estirar"))

    def test_reminder_accepts_duration_first_and_set_forms(self):
        native = NativeCapabilities(Mock())
        first = native.build_step("reminder", "in 20 minutes remind me to stretch")
        second = native.build_step("reminder", "set a 20 minute reminder to stretch")
        self.assertEqual((first.params["minutes"], first.params["message"]), (20, "stretch"))
        self.assertEqual((second.params["minutes"], second.params["message"]), (20, "stretch"))

    def test_screenshot_never_accepts_command_text(self):
        runner = Mock(return_value=Result()); native = NativeCapabilities(runner)
        native.execute(native.build_step("screenshot", "fullscreen screenshot and rm -rf /"))
        self.assertEqual(runner.call_args.args[0], ["omarchy", "capture", "screenshot", "fullscreen", "save"])

    def test_screenshot_understands_entire_screen_as_fullscreen(self):
        step = NativeCapabilities(Mock()).build_step("screenshot", "save a screenshot of the entire screen")
        self.assertEqual(step.params["mode"], "fullscreen")

    def test_window_rounding_is_bounded_typed_verified_and_reversible(self):
        reads = iter((0, 8))
        def run(argv, **kwargs):
            if argv[:3] == ["hyprctl", "-j", "getoption"]:
                return Result(f'{{"int":{next(reads)}}}')
            return Result("ok\n")
        runner = Mock(side_effect=run); native = NativeCapabilities(runner)
        step = native.build_step("window_rounding", "make all window borders rounded")
        self.assertEqual(step.params["rounding"], 8)
        result = native.execute(step)
        self.assertEqual(result.undo_step.params["rounding"], 0)
        self.assertIn(
            ["hyprctl", "-r", "eval", "hl.config({ decoration = { rounding = 8 } })"],
            [call.args[0] for call in runner.call_args_list],
        )

    def test_window_rounding_understands_square_and_bounded_pixels(self):
        native = NativeCapabilities(Mock())
        self.assertEqual(native.build_step("window_rounding", "make every window square").params["rounding"], 0)
        self.assertEqual(native.build_step("window_rounding", "round corners to 99 px").params["rounding"], 32)

    def test_hyprland_style_is_typed_verified_and_reversible(self):
        reads = iter(('5 5 5 5', '14 14 14 14'))
        def run(argv, **kwargs):
            if argv[:3] == ["hyprctl", "-j", "getoption"]:
                return Result(f'{{"str":"{next(reads)}"}}')
            return Result("ok\n")
        runner = Mock(side_effect=run); native = NativeCapabilities(runner)
        step = native.build_step("hyprland_style", "set outer gaps to 14 pixels")
        self.assertEqual(step.params["changes"], {"gaps_out": 14})
        result = native.execute(step)
        self.assertEqual(result.undo_step.params["changes"], {"gaps_out": 5})
        self.assertIn(
            ["hyprctl", "-r", "eval", "hl.config({ general = { gaps_out = 14 } })"],
            [call.args[0] for call in runner.call_args_list],
        )

    def test_hyprland_style_supports_compound_changes_and_presets(self):
        native = NativeCapabilities(Mock())
        compound = native.build_step("hyprland_style", "turn off blur, shadows and animations")
        self.assertEqual(compound.params["changes"], {
            "blur_enabled": False, "shadow_enabled": False, "animations_enabled": False,
        })
        preset = native.build_step("hyprland_style", "apply the compact desktop preset")
        self.assertEqual(preset.params["changes"], {
            "gaps_in": 3, "gaps_out": 6, "border_size": 1, "rounding": 4,
        })
        opacity = native.build_step("hyprland_style", "make all inactive windows 80% opaque")
        self.assertEqual(opacity.params["changes"], {"inactive_opacity": 0.8})
        dim = native.build_step("hyprland_style", "activá la atenuación de inactivas al 20%")
        self.assertEqual(dim.params["changes"], {"dim_inactive": True, "dim_strength": 0.2})

    def test_hyprland_style_rejects_unknown_or_unobservable_settings(self):
        native = NativeCapabilities(Mock(return_value=Result('{}')))
        with self.assertRaises(CapabilityError):
            native.build_step("hyprland_style", "change the Hyprland config")
        step = native.build_step("hyprland_style", "enable blur")
        with self.assertRaisesRegex(CapabilityError, "no voy a cambiarlo sin poder deshacer"):
            native.execute(step)
        with self.assertRaisesRegex(CapabilityError, "Separá los efectos"):
            native.build_step("hyprland_style", "enable blur and disable shadows")
        with self.assertRaisesRegex(CapabilityError, "perfil de energía"):
            native.build_step("hyprland_style", "switch to performance power mode")

    def test_hyprland_style_rolls_back_if_effect_cannot_be_verified(self):
        reads = iter(('5 5 5 5', '6 6 6 6', '5 5 5 5'))
        def run(argv, **kwargs):
            if argv[:3] == ["hyprctl", "-j", "getoption"]:
                return Result(f'{{"str":"{next(reads)}"}}')
            return Result("ok\n")
        runner = Mock(side_effect=run); native = NativeCapabilities(runner)
        step = native.build_step("hyprland_style", "set outer gaps to 14 pixels")
        with self.assertRaisesRegex(CapabilityError, "no aplicó correctamente"):
            native.execute(step)
        evals = [call.args[0] for call in runner.call_args_list if call.args[0][:3] == ["hyprctl", "-r", "eval"]]
        self.assertEqual(evals[-1], ["hyprctl", "-r", "eval", "hl.config({ general = { gaps_out = 5 } })"])


if __name__ == "__main__":
    unittest.main()
