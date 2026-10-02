"""Deterministic startup geometry tests; no real monitor or config changes."""
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtWidgets import QApplication

from peekcam.geometry import normalize_geometry
from peekcam.overlay_window import OverlayWindow


class OverlayGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_stale_saved_position_is_recovered_without_showing_window(self):
        screen = Mock()
        screen.availableGeometry.return_value = QRect(0, 0, 2560, 1440)
        screen.geometry.return_value = QRect(0, 0, 2560, 1440)
        screen.name.return_value = 'fake'
        config = {"geometry": [4716, 1183, 376, 212], "click_through": True}
        with patch("peekcam.overlay_window.QGuiApplication.screens", return_value=[screen]), \
                patch("peekcam.overlay_window.QGuiApplication.primaryScreen", return_value=screen):
            overlay = OverlayWindow(config)
        self.addCleanup(overlay.deleteLater)
        self.addCleanup(overlay.stop_monitor_recovery)
        self.assertEqual(overlay.geometry(), QRect(2184, 1183, 376, 212))
        self.assertEqual(config["geometry"], [2184, 1183, 376, 212])
        self.assertFalse(overlay.isVisible())
        self.assertTrue(config["click_through"])
        self.assertTrue(overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput)

    def test_startup_save_filesystem_failure_does_not_abort_recovery(self):
        screen = Mock()
        screen.availableGeometry.return_value = QRect(0, 0, 2560, 1440)
        screen.geometry.return_value = QRect(0, 0, 2560, 1440)
        screen.name.return_value = 'fake'
        for saved in ([4716, 1183, 376, 212], None):
            for error in (PermissionError('read-only config'), OSError('disk full')):
                with self.subTest(saved=saved, error=error), \
                        patch('peekcam.overlay_window.QGuiApplication.screens', return_value=[screen]), \
                        patch('peekcam.overlay_window.QGuiApplication.primaryScreen', return_value=screen), \
                        patch('sys.stderr') as stderr:
                    class Config(dict):
                        save = Mock(side_effect=error)
                    config = Config(geometry=saved)
                    overlay = OverlayWindow(config)
                    self.addCleanup(overlay.deleteLater)
                    self.addCleanup(overlay.stop_monitor_recovery)
                    expected = (2184, 1183, 376, 212) if saved else (2176, 1176, 360, 240)
                    self.assertEqual(overlay.geometry().getRect(), expected)
                    self.assertEqual(config['geometry'], list(expected))
                    self.assertFalse(overlay.isVisible())
                    warning = ''.join(call.args[0] for call in stderr.write.call_args_list)
                    self.assertIn('[peekcam] Could not save recovered geometry', warning)
                    self.assertIn(str(error), warning)

    def test_malformed_saved_geometry_does_not_crash_startup(self):
        screen = Mock()
        screen.availableGeometry.return_value = QRect(0, 40, 800, 560)
        screen.geometry.return_value = QRect(0, 0, 800, 600)
        screen.name.return_value = 'fake'
        for saved in (7, "bad", [0, 0, -1, 200], [0, 0, float("nan"), 200]):
            with self.subTest(saved=saved), \
                    patch("peekcam.overlay_window.QGuiApplication.screens", return_value=[screen]), \
                    patch("peekcam.overlay_window.QGuiApplication.primaryScreen", return_value=screen):
                config = {"geometry": saved}
                overlay = OverlayWindow(config)
                self.addCleanup(overlay.deleteLater)
                self.addCleanup(overlay.stop_monitor_recovery)
                self.assertEqual(overlay.geometry(), QRect(416, 336, 360, 240))
                self.assertEqual(config["geometry"], [416, 336, 360, 240])
                self.assertFalse(overlay.isVisible())

    def test_empty_snapshot_defers_correction_and_config_update(self):
        for saved in ([4716, 1183, 376, 212], None):
            with self.subTest(saved=saved), \
                    patch("peekcam.overlay_window.QGuiApplication.screens", return_value=[]), \
                    patch("peekcam.overlay_window.QGuiApplication.primaryScreen", return_value=None):
                config = {"geometry": saved}
                overlay = OverlayWindow(config)
                self.addCleanup(overlay.deleteLater)
                self.addCleanup(overlay.stop_monitor_recovery)
                self.assertEqual(config["geometry"], saved)
                expected = tuple(saved) if saved else (0, 0, 360, 240)
                self.assertEqual(overlay.geometry().getRect(), expected)
                self.assertFalse(overlay.isVisible())


class GeometryNormalizationTests(unittest.TestCase):
    PRIMARY = (0, 0, 2560, 1440)

    def test_reachable_secondary_and_negative_positions_are_preserved(self):
        screens = [self.PRIMARY, (2560, 0, 2560, 1440), (-1920, -200, 1920, 1080)]
        for saved in ((4716, 1183, 376, 212), (-1800, -100, 360, 240)):
            with self.subTest(saved=saved):
                self.assertEqual(normalize_geometry(saved, screens, self.PRIMARY), saved)

    def test_meaningful_partial_visibility_does_not_force_containment(self):
        for saved in ((-328, 100, 360, 240), (2528, 100, 360, 240),
                      (100, -208, 360, 240), (100, 1408, 360, 240),
                      (2550, 1430, 10, 10)):
            with self.subTest(saved=saved):
                self.assertEqual(normalize_geometry(saved, [self.PRIMARY]), saved)

    def test_one_pixel_or_narrow_slivers_are_recovered(self):
        for saved, expected in (
            ((2559, 100, 360, 240), (2200, 100, 360, 240)),
            ((-329, 100, 360, 240), (0, 100, 360, 240)),
            ((100, 1409, 360, 240), (100, 1200, 360, 240)),
            ((-328, -209, 360, 240), (0, 0, 360, 240)),
        ):
            with self.subTest(saved=saved):
                self.assertEqual(normalize_geometry(saved, [self.PRIMARY]), expected)

    def test_monitor_gap_is_not_a_visible_work_area(self):
        screens = [(0, 0, 800, 600), (1600, 0, 800, 600)]
        self.assertEqual(normalize_geometry((1000, 100, 360, 240), screens),
                         (440, 100, 360, 240))
        # Visibility on separate screens cannot be combined into one usable patch.
        self.assertEqual(normalize_geometry((780, 100, 840, 240), screens),
                         (0, 100, 800, 240))

    def test_preferred_screen_and_work_area_origin_control_fallback(self):
        preferred = (-1920, 40, 1920, 1040)
        screens = [self.PRIMARY, preferred]
        self.assertEqual(normalize_geometry((5000, 1183, 376, 212), screens, preferred),
                         (-376, 868, 376, 212))
        self.assertEqual(normalize_geometry(None, screens, preferred),
                         (-384, 816, 360, 240))
        # A missing preferred screen falls back to the first current screen.
        self.assertEqual(normalize_geometry((5000, 100, 376, 212), screens, (9, 9, 9, 9)),
                         (2184, 100, 376, 212))

    def test_oversized_geometry_is_shrunk_only_as_needed(self):
        self.assertEqual(normalize_geometry((100, 100, 4000, 2000), [self.PRIMARY]),
                         (0, 0, 2560, 1440))
        self.assertEqual(normalize_geometry((100, 100, 4000, 212), [self.PRIMARY]),
                         (0, 100, 2560, 212))
        secondary = (2560, -100, 800, 600)
        self.assertEqual(normalize_geometry((2700, 0, 1000, 200), [self.PRIMARY, secondary]),
                         (2560, 0, 800, 200))
        self.assertEqual(normalize_geometry(None, [(10, 20, 100, 80)]),
                         (10, 20, 100, 80))

    def test_malformed_data_uses_default_corner(self):
        for saved in (None, False, 7, "1234", {}, [], [0, 0, 360],
                      [0, 0, 360, 240, 5], [0, 0, 0, 240], [0, 0, 360, -1],
                      ["0", 0, 360, 240], [0, 0, True, 240],
                      [0, 0, float("inf"), 240], [0, 0, float("nan"), 240],
                      [2**40, 0, 360, 240], [0, 0, 2**40, 240]):
            with self.subTest(saved=saved):
                self.assertEqual(normalize_geometry(saved, [self.PRIMARY]),
                                 (2176, 1176, 360, 240))

    def test_no_screens_defers_valid_geometry_and_safely_defaults_invalid_data(self):
        saved = (4716, 1183, 376, 212)
        self.assertEqual(normalize_geometry(saved, []), saved)
        self.assertEqual(normalize_geometry(None, []), (0, 0, 360, 240))
        self.assertEqual(normalize_geometry(saved, [(0, 0, 0, 0)]), saved)

    def test_normalization_is_idempotent(self):
        for saved in ((4716, 1183, 376, 212), None, (100, 100, 4000, 2000)):
            with self.subTest(saved=saved):
                recovered = normalize_geometry(saved, [self.PRIMARY])
                self.assertEqual(normalize_geometry(recovered, [self.PRIMARY]), recovered)


if __name__ == "__main__":
    unittest.main()
