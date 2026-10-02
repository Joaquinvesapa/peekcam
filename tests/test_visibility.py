"""Single-instance launch and explicit visibility actions; no live IPC or capture."""
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

# main imports Config, whose module normally creates its directory at import time.
with patch('pathlib.Path.mkdir'):
    from peekcam import ipc, main


class VisibilityTests(unittest.TestCase):
    def test_plain_second_launch_sends_show_without_constructing_controller(self):
        with patch.object(main.sys, 'argv', ['peekcam']), \
                patch.object(main, 'QApplication'), \
                patch.object(main, 'QGuiApplication'), \
                patch.object(main, 'app_icon'), \
                patch.object(main.ipc, 'send_action', return_value=True) as send, \
                patch.object(main, 'Controller') as controller:
            self.assertEqual(main.main(), 0)
            send.assert_called_once_with('show')
            controller.assert_not_called()

    def test_explicit_show_and_toggle_flags_are_forwarded(self):
        for flag, action in (('--show', 'show'), ('--show-hide', 'show-hide')):
            with self.subTest(flag=flag), \
                    patch.object(main.sys, 'argv', ['peekcam', flag]), \
                    patch('PyQt6.QtCore.QCoreApplication'), \
                    patch.object(main.ipc, 'send_action', return_value=True) as send:
                self.assertEqual(main.main(), 0)
                send.assert_called_once_with(action)

    def test_show_flag_without_running_instance_reports_failure(self):
        with patch.object(main.sys, 'argv', ['peekcam', '--show']), \
                patch('PyQt6.QtCore.QCoreApplication'), \
                patch.object(main.ipc, 'send_action', return_value=False), \
                patch.object(main.sys, 'stderr') as stderr:
            self.assertEqual(main.main(), 1)
            self.assertTrue(stderr.write.called)

    def test_show_is_idempotent_and_does_not_change_workspace_preference(self):
        controller = main.Controller.__new__(main.Controller)
        controller.config = {'show_on_all_workspaces': False}
        controller.overlay = Mock()
        for visible in (False, True):
            controller.overlay.isVisible.return_value = visible
            controller.handle_action('show')
        self.assertEqual(controller.overlay.show.call_count, 2)
        controller.overlay.setVisible.assert_not_called()
        self.assertFalse(controller.config['show_on_all_workspaces'])

    def test_explicit_show_hide_still_toggles(self):
        controller = main.Controller.__new__(main.Controller)
        controller.overlay = Mock()
        for visible in (False, True):
            controller.overlay.isVisible.return_value = visible
            controller.handle_action('show-hide')
            controller.overlay.setVisible.assert_called_with(not visible)

    def test_ipc_server_accepts_show(self):
        receiver = Mock()
        conn = Mock()
        conn.readAll.return_value = b'show'
        ipc.IpcServer._on_ready(receiver, conn)
        receiver.action_received.emit.assert_called_once_with('show')


if __name__ == '__main__':
    unittest.main()
