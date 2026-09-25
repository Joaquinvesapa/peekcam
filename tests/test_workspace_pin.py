"""Tray workspace pin preference and delayed dispatch regression tests."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QApplication

from peekcam import main
from peekcam.config import Config


class WorkspacePinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def controller(self, enabled=True):
        controller = main.Controller.__new__(main.Controller)
        controller.app = self.app
        controller.config = Config({"show_on_all_workspaces": enabled})
        controller.overlay = Mock()
        controller._workspace_pin_lock = threading.Lock()
        return controller

    def test_default_and_persistence(self):
        self.assertTrue(Config().get("show_on_all_workspaces"))
        with tempfile.TemporaryDirectory() as directory, \
             patch("peekcam.config.CONFIG_PATH", Path(directory) / "config.json"):
            config = Config()
            config["show_on_all_workspaces"] = False
            config.save()
            self.assertFalse(Config.load().get("show_on_all_workspaces"))
            self.assertFalse(json.loads((Path(directory) / "config.json").read_text())["show_on_all_workspaces"])

    def test_tray_checked_state_and_immediate_save(self):
        controller = self.controller(False)
        with patch("peekcam.main.hyprland.is_available", return_value=True), \
             patch("peekcam.main.Config.save") as save, \
             patch.object(controller, "_pin_hyprland_window") as dispatch:
            controller._build_tray()
            action = next(a for a in controller.tray.contextMenu().actions()
                          if a.text() == "Show on all workspaces")
            self.assertTrue(action.isCheckable())
            self.assertFalse(action.isChecked())
            action.trigger()
            self.assertTrue(controller.config["show_on_all_workspaces"])
            save.assert_called_once_with()
            dispatch.assert_called_once()
        controller.tray.hide()

    def test_unsupported_compositor_hides_action(self):
        controller = self.controller()
        with patch("peekcam.main.hyprland.is_available", return_value=False):
            controller._build_tray()
            self.assertNotIn("Show on all workspaces",
                             [a.text() for a in controller.tray.contextMenu().actions()])
        controller.tray.hide()

    def test_startup_preference_and_delayed_stale_callback(self):
        controller = self.controller(False)
        with patch("peekcam.main.threading.Thread") as thread:
            controller._pin_hyprland_window()
            thread.assert_not_called()
            controller.config["show_on_all_workspaces"] = True
            controller._pin_hyprland_window()
            thread.assert_called_once()
            controller.config["show_on_all_workspaces"] = False
            controller._pin_hyprland_window_in_background(3)
            thread.return_value.start.assert_called_once()

    def test_stale_retry_does_not_repin_after_toggle_off(self):
        controller = self.controller()
        def pin():
            controller.config["show_on_all_workspaces"] = False
            return False
        with patch("peekcam.main.hyprland.pin_current_window", side_effect=pin) as attempt, \
             patch("peekcam.main.time.sleep") as sleep:
            controller._pin_hyprland_window_in_background(3)
            attempt.assert_called_once()
            sleep.assert_not_called()

    def test_unpin_worker_dispatches_only_while_disabled(self):
        controller = self.controller(False)
        with patch("peekcam.main.hyprland.unpin_current_window", return_value=False) as unpin, \
             patch("peekcam.main.time.sleep") as sleep:
            controller._unpin_hyprland_window_in_background()
            self.assertEqual(unpin.call_count, main._PIN_RETRY_ATTEMPTS)
            self.assertEqual(sleep.call_count, main._PIN_RETRY_ATTEMPTS - 1)
            controller.config["show_on_all_workspaces"] = True
            controller._unpin_hyprland_window_in_background()
            self.assertEqual(unpin.call_count, main._PIN_RETRY_ATTEMPTS)

    def test_unpin_retries_transient_failure_then_succeeds(self):
        controller = self.controller(False)
        with patch("peekcam.main.hyprland.unpin_current_window", side_effect=[False, True]) as unpin, \
             patch("peekcam.main.time.sleep") as sleep:
            controller._unpin_hyprland_window_in_background()
            self.assertEqual(unpin.call_count, 2)
            sleep.assert_called_once_with(main._PIN_DELAY_MS / 1000)

    def test_unpin_retry_stops_when_enable_supersedes_it(self):
        controller = self.controller(False)
        def unpin():
            controller.config["show_on_all_workspaces"] = True
            return False
        with patch("peekcam.main.hyprland.unpin_current_window", side_effect=unpin) as attempt, \
             patch("peekcam.main.time.sleep") as sleep:
            controller._unpin_hyprland_window_in_background()
            attempt.assert_called_once_with()
            sleep.assert_not_called()

    def test_toggle_off_dispatches_unpin_outside_ui_thread(self):
        controller = self.controller()
        with patch("peekcam.main.Config.save") as save, \
             patch("peekcam.main.threading.Thread") as thread, \
             patch("peekcam.main.hyprland.unpin_current_window") as unpin:
            controller._set_workspace_pin(False)
            self.assertFalse(controller.config["show_on_all_workspaces"])
            save.assert_called_once_with()
            unpin.assert_not_called()
            self.assertTrue(thread.return_value.start.called)


if __name__ == "__main__":
    unittest.main()
