"""Unit coverage for optional Hyprland window pinning."""
import os
import subprocess
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from peekcam import hyprland, main
from peekcam.config import Config


class HyprlandPinTests(unittest.TestCase):
    def test_returns_false_outside_hyprland_without_running_hyprctl(self) -> None:
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": ""}, clear=False), \
             patch("peekcam.hyprland.shutil.which") as which, \
             patch("peekcam.hyprland.subprocess.run") as run:
            self.assertFalse(hyprland.pin_current_window())

        which.assert_not_called()
        run.assert_not_called()

    def test_returns_false_when_hyprctl_is_missing(self) -> None:
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "instance"}, clear=False), \
             patch("peekcam.hyprland.shutil.which", return_value=None) as which, \
             patch("peekcam.hyprland.subprocess.run") as run:
            self.assertFalse(hyprland.pin_current_window())

        which.assert_called_once_with("hyprctl")
        run.assert_not_called()

    def test_dispatches_pin_for_the_current_pid(self) -> None:
        completed = SimpleNamespace(returncode=0)
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "instance"}, clear=False), \
             patch("peekcam.hyprland.shutil.which", return_value="/usr/bin/hyprctl"), \
             patch("peekcam.hyprland.os.getpid", return_value=12345), \
             patch("peekcam.hyprland.subprocess.run", return_value=completed) as run:
            self.assertTrue(hyprland.pin_current_window())

        run.assert_called_once_with(
            [
                "hyprctl",
                "dispatch",
                'hl.dsp.window.pin({ window = "pid:12345", action = "enable" })',
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1,
        )

    def test_pin_callback_starts_daemon_thread_without_running_pin_inline(self) -> None:
        controller = main.Controller.__new__(main.Controller)
        controller.config = Config()
        controller._workspace_pin_lock = threading.Lock()
        with patch("peekcam.main.threading.Thread") as thread, \
             patch("peekcam.main.hyprland.pin_current_window") as pin:
            controller._pin_hyprland_window()

        pin.assert_not_called()
        thread.assert_called_once_with(
            target=controller._pin_hyprland_window_in_background,
            args=(main._PIN_RETRY_ATTEMPTS,),
            daemon=True,
        )
        thread.return_value.start.assert_called_once_with()

    def test_background_pin_retries_are_bounded(self) -> None:
        controller = main.Controller.__new__(main.Controller)
        controller.config = Config()
        controller._workspace_pin_lock = threading.Lock()
        with patch("peekcam.main.hyprland.pin_current_window", return_value=False) as pin, \
             patch("peekcam.main.time.sleep") as sleep:
            controller._pin_hyprland_window_in_background(3)

        self.assertEqual(pin.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        sleep.assert_called_with(main._PIN_DELAY_MS / 1000)

    def test_unpin_uses_explicit_disable_action_for_current_pid(self) -> None:
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "instance"}, clear=False), \
             patch("peekcam.hyprland.shutil.which", return_value="/usr/bin/hyprctl"), \
             patch("peekcam.hyprland.os.getpid", return_value=12345), \
             patch("peekcam.hyprland.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertTrue(hyprland.unpin_current_window())
        self.assertEqual(run.call_args.args[0][2],
                         'hl.dsp.window.pin({ window = "pid:12345", action = "disable" })')

    def test_unpin_failure_does_not_raise(self) -> None:
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "instance"}, clear=False), \
             patch("peekcam.hyprland.shutil.which", return_value="/usr/bin/hyprctl"), \
             patch("peekcam.hyprland.subprocess.run", side_effect=OSError("failed")):
            self.assertFalse(hyprland.unpin_current_window())

    def test_returns_false_when_hyprctl_returns_nonzero(self) -> None:
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "instance"}, clear=False), \
             patch("peekcam.hyprland.shutil.which", return_value="/usr/bin/hyprctl"), \
             patch("peekcam.hyprland.subprocess.run", return_value=SimpleNamespace(returncode=1)):
            self.assertFalse(hyprland.pin_current_window())

    def test_returns_false_when_hyprctl_times_out_or_cannot_start(self) -> None:
        for failure in (subprocess.TimeoutExpired(["hyprctl"], 1), OSError("unavailable")):
            with self.subTest(failure=type(failure).__name__), \
                 patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "instance"}, clear=False), \
                 patch("peekcam.hyprland.shutil.which", return_value="/usr/bin/hyprctl"), \
                 patch("peekcam.hyprland.subprocess.run", side_effect=failure):
                self.assertFalse(hyprland.pin_current_window())


if __name__ == "__main__":
    unittest.main()
