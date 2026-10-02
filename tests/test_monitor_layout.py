"""Fake topology signals, real offscreen widget; never use the user's config."""
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QObject, QPoint, QRect, pyqtSignal
from PyQt6.QtGui import QMoveEvent
from PyQt6.QtWidgets import QApplication

from peekcam.overlay_window import OverlayWindow

# config's import-time directory creation must not touch the user's home.
with patch('pathlib.Path.mkdir'):
    from peekcam import main


class Screen(QObject):
    geometryChanged = pyqtSignal(QRect)
    availableGeometryChanged = pyqtSignal(QRect)

    def __init__(self, name, rect):
        super().__init__()
        self.label = name
        self.rect = QRect(*rect)
        self.area = QRect(self.rect)

    def name(self):
        return self.label

    def geometry(self):
        return self.rect

    def availableGeometry(self):
        return self.area

    def translate(self, x, y):
        self.rect.moveTopLeft(QRect(x, y, 1, 1).topLeft())
        self.area.moveTopLeft(self.rect.topLeft())
        self.geometryChanged.emit(self.rect)
        self.availableGeometryChanged.emit(self.area)


class Topology(QObject):
    screenAdded = pyqtSignal(object)
    screenRemoved = pyqtSignal(object)
    primaryScreenChanged = pyqtSignal(object)


class SavedConfig(dict):
    def __init__(self, geometry):
        super().__init__(geometry=geometry, click_through=True)
        self.save = Mock()


class MonitorLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dp2 = Screen('DP-2', (2560, 0, 2560, 1440))
        self.dp3 = Screen('DP-3', (0, 0, 2560, 1440))
        self.screens = [self.dp2, self.dp3]
        self.primary = self.dp3
        self.events = Topology()
        for target, kwargs in (
            ('screens', {'side_effect': lambda: self.screens}),
            ('primaryScreen', {'side_effect': lambda: self.primary}),
            ('instance', {'return_value': self.events}),
        ):
            p = patch('peekcam.overlay_window.QGuiApplication.' + target, **kwargs)
            p.start()
            self.addCleanup(p.stop)
        self.config = SavedConfig([4716, 1183, 376, 212])
        self.overlay = OverlayWindow(self.config)
        self.addCleanup(self.dispose)

    def dispose(self):
        if hasattr(self.overlay, 'stop_monitor_recovery'):
            self.overlay.stop_monitor_recovery()
        self.overlay.deleteLater()

    def flush(self):
        self.assertTrue(self.overlay._layout_timer.isActive())
        self.app.processEvents()
        self.app.processEvents()

    def test_translation_burst_tracks_survivor_and_persists_once(self):
        # User/compositor movement must supersede saved config coordinates.
        self.overlay.move(4600, 1100)
        self.dp2.translate(0, 0)
        self.dp3.translate(2560, 0)  # stale coordinates now intersect DP-3
        self.primary = self.dp2
        self.events.primaryScreenChanged.emit(self.dp2)
        self.assertEqual(self.overlay.x(), 4600)  # deferred until final snapshot
        self.flush()
        self.assertEqual(self.overlay.geometry().getRect(), (2040, 1100, 376, 212))
        self.assertEqual(self.config['geometry'], [2040, 1100, 376, 212])
        self.config.save.assert_called_once_with()
        self.assertFalse(self.overlay.isVisible())
        self.assertTrue(self.config['click_through'])
        self.dp2.geometryChanged.emit(self.dp2.rect)
        self.flush()
        self.assertEqual(self.overlay.x(), 2040)
        self.config.save.assert_called_once_with()

    def test_compositor_reposition_is_not_translated_twice(self):
        for timing in ('before_signals', 'after_signals'):
            with self.subTest(timing=timing):
                self.dp2.rect = QRect(2560, 0, 2560, 1440)
                self.dp2.area = QRect(self.dp2.rect)
                self.dp3.rect = QRect(0, 0, 2560, 1440)
                self.dp3.area = QRect(self.dp3.rect)
                self.overlay._monitor_snapshot = self.overlay._snapshot_monitors(self.screens)
                self.overlay.move(4600, 1100)
                self.overlay._save_geometry()  # last user placement before topology
                self.config.save.reset_mock()
                with patch.object(self.overlay, 'windowHandle') as handle:
                    handle.return_value.screen.return_value = self.dp2
                    if timing == 'before_signals':
                        self.overlay.move(2040, 1100)
                        # Hidden widgets defer native move events; deliver one to
                        # cover the visible-window ordering without showing it.
                        self.app.sendEvent(self.overlay, QMoveEvent(
                            QPoint(2040, 1100), QPoint(4600, 1100)))
                        self.assertEqual(self.overlay._placement_geometry,
                                         (4600, 1100, 376, 212))
                    self.dp2.translate(0, 0)
                    self.dp3.translate(2560, 0)
                    if timing == 'after_signals':
                        self.overlay.move(2040, 1100)
                    self.flush()
                    self.assertEqual(self.overlay.x(), 2040)
                    self.dp2.geometryChanged.emit(self.dp2.rect)
                    self.flush()
                    self.assertEqual(self.overlay.x(), 2040)
                self.assertFalse(self.overlay.isVisible())
                self.assertEqual(self.config['geometry'], [2040, 1100, 376, 212])
                self.config.save.assert_called_once_with()

    def _assert_transient_identity_recovery(self, timing):
        self.overlay.move(4600, 1100)
        self.overlay._save_geometry()
        self.assertEqual(self.overlay._placement_monitor, 'DP-2')
        self.config.save.reset_mock()
        with patch.object(self.overlay, 'windowHandle') as handle:
            handle.return_value.screen.return_value = self.dp3
            if timing == 'before_signals':
                self.overlay.move(2040, 1100)
                self.app.sendEvent(self.overlay, QMoveEvent(
                    QPoint(2040, 1100), QPoint(4600, 1100)))
            self.dp2.translate(0, 0)
            self.dp3.translate(2560, 0)
            if timing == 'after_signals':
                self.overlay.move(2040, 1100)
            self.assertEqual(self.overlay._placement_monitor, 'DP-2')
            self.flush()
            self.assertEqual(self.overlay.geometry().getRect(), (2040, 1100, 376, 212))
            self.dp2.geometryChanged.emit(self.dp2.rect)
            self.flush()
            self.assertEqual(self.overlay.geometry().getRect(), (2040, 1100, 376, 212))
        self.assertEqual(self.config['geometry'], [2040, 1100, 376, 212])
        self.config.save.assert_called_once_with()
        self.assertFalse(self.overlay.isVisible())

    def test_transient_wrong_identity_before_signals_preserves_compositor_move(self):
        self._assert_transient_identity_recovery('before_signals')

    def test_transient_wrong_identity_after_signals_preserves_compositor_move(self):
        self._assert_transient_identity_recovery('after_signals')

    def test_transient_wrong_identity_unchanged_placement_follows_survivor(self):
        self._assert_transient_identity_recovery('unchanged')

    def test_missing_or_ambiguous_ownership_preserves_reachable_position(self):
        for ownership in (None, 'duplicate'):
            with self.subTest(ownership=ownership):
                self.dp2.label = 'DP-2'
                self.dp3.label = 'DP-3'
                self.dp2.rect = QRect(2560, 0, 2560, 1440)
                self.dp2.area = QRect(self.dp2.rect)
                self.dp3.rect = QRect(0, 0, 2560, 1440)
                self.dp3.area = QRect(self.dp3.rect)
                if ownership == 'duplicate':
                    self.dp2.label = self.dp3.label = ownership
                self.overlay._monitor_snapshot = self.overlay._snapshot_monitors(self.screens)
                self.overlay._placement_geometry = (
                    2040 if ownership == 'duplicate' else 4600, 1100, 376, 212)
                self.overlay._placement_monitor = ownership
                with patch.object(self.overlay, 'windowHandle') as handle:
                    handle.return_value.screen.return_value = self.dp3
                    self.overlay.move(2040, 1100)
                    self.dp2.translate(0, 0)
                    self.dp3.translate(2560, 0)
                    self.flush()
                    self.assertEqual(self.overlay.x(), 2040)
                    self.dp2.geometryChanged.emit(self.dp2.rect)
                    self.flush()
                    self.assertEqual(self.overlay.x(), 2040)

    def test_user_drag_to_other_output_updates_durable_ownership(self):
        with patch.object(self.overlay, 'windowHandle') as handle:
            handle.return_value.screen.return_value = self.dp3
            self.overlay.move(100, 200)
            self.overlay.mouseReleaseEvent(None)
            self.dp2.translate(0, 0)
            self.dp3.translate(2560, 0)
            self.flush()
        self.assertEqual(self.overlay.geometry().getRect(), (2660, 200, 376, 212))
        self.assertEqual(self.config['geometry'], [2660, 200, 376, 212])

    def test_compositor_move_after_recovery_and_repeated_callback_is_noop(self):
        self.overlay.move(4600, 1100)
        self.overlay._save_geometry()
        self.dp2.translate(0, 0)
        self.dp3.translate(2560, 0)
        self.flush()
        self.overlay.move(2040, 1100)
        self.dp2.geometryChanged.emit(self.dp2.rect)
        self.flush()
        self.assertEqual(self.overlay.x(), 2040)
        self.config.save.assert_called_once_with()

    def test_ambiguous_changed_placement_without_window_handle_stays_usable(self):
        with patch.object(self.overlay, 'windowHandle', return_value=None):
            self.overlay.move(100, 100)
            self.dp2.translate(0, 0)
            self.dp3.translate(2560, 0)
            self.flush()
        self.assertEqual(self.overlay.geometry().getRect(), (100, 100, 376, 212))

    def test_save_programming_errors_are_not_suppressed(self):
        self.config.save.side_effect = ValueError('programming error')
        with self.assertRaisesRegex(ValueError, 'programming error'):
            self.overlay._persist_geometry()

    def test_live_save_filesystem_failure_keeps_recovered_geometry(self):
        for error in (PermissionError('read-only config'), OSError('disk full')):
            with self.subTest(error=error):
                self.overlay.move(9000, 100)
                self.config.save.side_effect = error
                with patch('sys.stderr') as stderr:
                    # Invoke the slot directly: an uncaught Qt slot exception can abort.
                    self.overlay._recover_monitor_layout()
                self.assertEqual(self.overlay.x(), 2184)
                self.assertEqual(self.config['geometry'], [2184, 100, 376, 212])
                warning = ''.join(call.args[0] for call in stderr.write.call_args_list)
                self.assertIn('[peekcam] Could not save recovered geometry', warning)
                self.assertIn(str(error), warning)

    def test_removal_coalesces_with_translation(self):
        self.screens = [self.dp2]
        self.primary = self.dp2
        self.events.screenRemoved.emit(self.dp3)
        self.dp2.translate(0, 0)
        self.flush()
        self.assertEqual(self.overlay.x(), 2156)
        self.config.save.assert_called_once_with()
        self.assertNotIn(self.dp3, self.overlay._screen_hooks)
        self.assertEqual(self.dp3.receivers(self.dp3.geometryChanged), 0)

    def test_removed_chosen_monitor_uses_primary_fallback(self):
        self.screens = [self.dp3]
        self.events.screenRemoved.emit(self.dp2)
        self.flush()
        self.assertEqual(self.overlay.geometry().getRect(), (2184, 1183, 376, 212))
        self.config.save.assert_called_once_with()

    def test_negative_origin_and_work_area_changes(self):
        self.dp2.translate(-2560, -200)
        self.flush()
        self.assertEqual(self.overlay.geometry().getRect(), (-404, 983, 376, 212))
        self.dp2.area.setHeight(600)
        self.dp2.availableGeometryChanged.emit(self.dp2.area)
        self.flush()
        self.assertEqual(self.overlay.geometry().getRect(), (-404, 188, 376, 212))
        self.assertEqual(self.config.save.call_count, 2)

    def test_empty_then_reconnect_retains_old_origin_and_hooks(self):
        self.screens = []
        for screen in (self.dp2, self.dp3):
            self.events.screenRemoved.emit(screen)
        self.flush()
        self.assertEqual(self.overlay.x(), 4716)
        self.config.save.assert_not_called()
        self.assertFalse(self.overlay._screen_hooks)
        self.dp2.translate(0, 0)
        self.screens = [self.dp2]
        self.primary = self.dp2
        self.events.screenAdded.emit(self.dp2)
        self.events.screenAdded.emit(self.dp2)
        self.flush()
        self.assertEqual(self.overlay.x(), 2156)
        self.assertEqual(self.dp2.receivers(self.dp2.geometryChanged), 1)
        self.assertEqual(self.dp2.receivers(self.dp2.availableGeometryChanged), 1)
        self.config.save.assert_called_once_with()
        self.overlay.stop_monitor_recovery()
        self.assertEqual(self.events.receivers(self.events.screenAdded), 0)
        self.assertEqual(self.dp2.receivers(self.dp2.geometryChanged), 0)

    def test_noop_and_primary_change_do_not_move_or_save(self):
        self.overlay.move(4500, 1000)
        with patch.object(self.overlay, 'setGeometry') as move:
            self.primary = self.dp2
            self.events.primaryScreenChanged.emit(self.dp2)
            self.dp2.geometryChanged.emit(self.dp2.rect)
            self.flush()
            move.assert_not_called()
        self.assertEqual(self.overlay.x(), 4500)
        self.config.save.assert_not_called()

    def test_gap_and_oversized_live_window_use_individual_rectangles(self):
        self.overlay.setGeometry(100, 100, 6000, 2000)
        self.dp2.geometryChanged.emit(self.dp2.rect)
        self.flush()
        self.assertEqual(self.overlay.geometry().getRect(), (2560, 0, 2560, 1440))
        self.dp2.translate(4000, 0)
        self.flush()
        self.overlay.setGeometry(3000, 100, 376, 212)
        self.dp2.geometryChanged.emit(self.dp2.rect)
        self.flush()
        self.assertEqual(self.overlay.geometry().getRect(), (2184, 100, 376, 212))

    def test_quit_saves_actual_window_geometry_before_pipeline_stop(self):
        controller = main.Controller.__new__(main.Controller)
        controller.overlay = self.overlay
        controller.config = self.config
        controller.pipeline = Mock()
        controller.app = Mock()
        self.overlay.move(4200, 900)
        self.config.save.side_effect = lambda: self.assertEqual(
            self.config['geometry'], [4200, 900, 376, 212])
        controller.quit()
        self.config.save.assert_called_once_with()
        controller.pipeline.stop.assert_called_once_with()
        controller.app.quit.assert_called_once_with()
        self.assertFalse(self.overlay._layout_timer.isActive())

    def test_startup_empty_defers_save_until_usable_screens(self):
        self.overlay.stop_monitor_recovery()
        self.overlay.deleteLater()
        self.screens = []
        self.primary = None
        self.config = SavedConfig([9000, 100, 376, 212])
        self.overlay = OverlayWindow(self.config)
        self.config.save.assert_not_called()
        self.screens = [self.dp3]
        self.primary = self.dp3
        self.events.screenAdded.emit(self.dp3)
        self.flush()
        self.assertEqual(self.config['geometry'], [2184, 100, 376, 212])
        self.config.save.assert_called_once_with()

    def test_malformed_startup_without_screens_recovers_default_corner(self):
        self.overlay.stop_monitor_recovery()
        self.overlay.deleteLater()
        self.screens = []
        self.primary = None
        self.config = SavedConfig(None)
        self.overlay = OverlayWindow(self.config)
        self.config.save.assert_not_called()
        self.screens = [self.dp3]
        self.primary = self.dp3
        self.events.screenAdded.emit(self.dp3)
        self.flush()
        self.assertEqual(self.config['geometry'], [2176, 1176, 360, 240])
        self.config.save.assert_called_once_with()

    def test_startup_correction_is_persisted(self):
        config = SavedConfig([9000, 100, 376, 212])
        overlay = OverlayWindow(config)
        self.addCleanup(overlay.deleteLater)
        if hasattr(overlay, 'stop_monitor_recovery'):
            self.addCleanup(overlay.stop_monitor_recovery)
        self.assertEqual(config['geometry'], [2184, 100, 376, 212])
        config.save.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
