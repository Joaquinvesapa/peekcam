"""Entry point. Forces the Qt X11 backend (XWayland) so always-on-top + free
positioning + click-through work on GNOME/Zorin Wayland, then runs the overlay.

Usage:
    python -m peekcam                # launch the overlay (single instance)
    python -m peekcam --snapshot     # tell a running instance to take a snapshot
    python -m peekcam --toggle-record --toggle-clickthrough --cycle-camera --show-hide --quit
"""
from __future__ import annotations

import os
import sys
import threading
import time

# Must be set before QApplication is constructed. run.sh also exports this.
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtGui import QAction, QGuiApplication, QIcon  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon  # noqa: E402

from . import APP_NAME, data_dir, device_manager, ipc, recorder  # noqa: E402
from .config import Config  # noqa: E402
from . import hyprland  # noqa: E402
from .overlay_window import OverlayWindow  # noqa: E402
from .pipeline import CameraPipeline  # noqa: E402
from .settings_dialog import SettingsDialog  # noqa: E402

ICON_PATH = os.path.join(data_dir(), "assets", "peekcam.png")
_PIN_DELAY_MS = 100
_PIN_RETRY_ATTEMPTS = 3


def app_icon() -> QIcon:
    icon = QIcon(ICON_PATH)
    if icon.isNull():  # fall back to a theme icon if the asset is missing
        icon = QIcon.fromTheme("peekcam")
    return icon


_ARG_TO_ACTION = {
    "--toggle-clickthrough": "toggle-clickthrough",
    "--snapshot": "snapshot",
    "--toggle-record": "toggle-record",
    "--cycle-camera": "cycle-camera",
    "--show-hide": "show-hide",
    "--toggle-blur": "toggle-blur",
    "--quit": "quit",
}


class Controller:
    def __init__(self, app: QApplication):
        self.app = app
        self.config = Config.load()
        self._workspace_pin_lock = threading.Lock()
        self.cameras: list[device_manager.Camera] = []
        self.cam_index = 0

        self.overlay = OverlayWindow(self.config)
        self.pipeline = CameraPipeline()
        self.settings: SettingsDialog | None = None

        # IPC (single instance + hotkey actions)
        self.server = ipc.IpcServer()
        self.server.start()
        self.server.action_received.connect(self.handle_action)

        # wiring
        self.pipeline.frame_ready.connect(self.overlay.set_image)
        self.pipeline.recording_changed.connect(self.overlay.set_recording_indicator)
        self.pipeline.error.connect(self._on_pipeline_error)
        self.overlay.request_settings.connect(self.open_settings)
        self.overlay.request_snapshot.connect(self.take_snapshot)
        self.overlay.request_toggle_record.connect(self.toggle_record)
        self.overlay.request_toggle_blur.connect(self.toggle_blur)
        self.overlay.request_quit.connect(self.quit)

        self._build_tray()
        self.overlay.show()
        if hyprland.is_available() and self.config.get("show_on_all_workspaces"):
            QTimer.singleShot(_PIN_DELAY_MS, self._pin_hyprland_window)
        # start capture shortly after the event loop is up
        QTimer.singleShot(0, self.start_default_capture)

    def _pin_hyprland_window(self, attempts_remaining: int = _PIN_RETRY_ATTEMPTS) -> None:
        """Start bounded Hyprland pin attempts without blocking Qt's event thread."""
        if not self.config.get("show_on_all_workspaces"):
            return
        threading.Thread(
            target=self._pin_hyprland_window_in_background,
            args=(attempts_remaining,),
            daemon=True,
        ).start()

    def _pin_hyprland_window_in_background(self, attempts_remaining: int) -> None:
        """Retry the bounded pin operation outside Qt's event thread."""
        for attempt in range(max(attempts_remaining, 1)):
            with self._workspace_pin_lock:
                if not self.config.get("show_on_all_workspaces"):
                    return
                if hyprland.pin_current_window():
                    return
            if attempt + 1 < max(attempts_remaining, 1):
                if not self.config.get("show_on_all_workspaces"):
                    return
                time.sleep(_PIN_DELAY_MS / 1000)

    def _set_workspace_pin(self, enabled: bool) -> None:
        """Persist the preference on Qt's thread; dispatch compositor work in a daemon."""
        self.config["show_on_all_workspaces"] = enabled
        self.config.save()
        if enabled:
            self._pin_hyprland_window()
        else:
            threading.Thread(target=self._unpin_hyprland_window_in_background,
                             daemon=True).start()

    def _unpin_hyprland_window_in_background(self) -> None:
        """Retry unpin outside Qt, serializing each attempt against pin attempts."""
        for attempt in range(_PIN_RETRY_ATTEMPTS):
            with self._workspace_pin_lock:
                if self.config.get("show_on_all_workspaces"):
                    return
                if hyprland.unpin_current_window():
                    return
            if attempt + 1 < _PIN_RETRY_ATTEMPTS:
                if self.config.get("show_on_all_workspaces"):
                    return
                time.sleep(_PIN_DELAY_MS / 1000)

    # ------------------------------------------------------------- capture
    def start_default_capture(self) -> None:
        self.cameras = device_manager.list_cameras()
        if not self.cameras:
            self._on_pipeline_error("No capture cameras found (is v4l-utils installed?).")
            return
        cam = device_manager.find_by_id(self.cameras, self.config.get("device_id"))
        self.cam_index = self.cameras.index(cam)
        fourcc, w, h, fps = self._resolve_format(cam)
        self._apply_saved_controls(cam)
        self.pipeline.start(cam.path, fourcc, w, h, fps)
        # restore background blur if it was on and the ML stack is available
        if self.config.get("blur", False):
            if not self.pipeline.set_blur_enabled(True):
                self.config["blur"] = False  # stack missing; don't keep claiming it's on

    def _resolve_format(self, cam: device_manager.Camera):
        # honor saved format if it still exists on this camera
        want_fourcc = self.config.get("fourcc")
        want = (self.config.get("width"), self.config.get("height"))
        for pf in cam.formats:
            if pf.fourcc == want_fourcc:
                for s in pf.sizes:
                    if (s.width, s.height) == want and s.fps:
                        fps = self.config.get("fps") or s.fps[0]
                        return pf.fourcc, s.width, s.height, float(fps)
        # otherwise prefer MJPG, largest size, highest fps
        pref = next((pf for pf in cam.formats if pf.fourcc == "MJPG"), cam.formats[0])
        size = pref.sizes[0]
        fps = size.fps[0] if size.fps else 30.0
        return pref.fourcc, size.width, size.height, float(fps)

    def _apply_saved_controls(self, cam: device_manager.Camera) -> None:
        from . import v4l2_controls
        v4l2_controls.apply_all(cam.path, self.config.controls_for(cam.device_id))

    def restart_capture(self, path: str, fourcc: str, w: int, h: int, fps: float) -> None:
        self.pipeline.start(path, fourcc, w, h, fps)

    # ------------------------------------------------------------- settings
    def open_settings(self) -> None:
        if self.settings is None:
            self.settings = SettingsDialog(self.config, None)
            self.settings.format_selected.connect(self._on_format_selected)
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def _on_format_selected(self, path: str, fourcc: str, w: int, h: int, fps: float) -> None:
        # refresh camera list/index to keep cycle-camera in sync
        self.cameras = device_manager.list_cameras()
        for i, c in enumerate(self.cameras):
            if c.path == path:
                self.cam_index = i
                break
        self.restart_capture(path, fourcc, w, h, fps)

    # ---------------------------------------------------------------- actions
    def handle_action(self, action: str) -> None:
        if action == "toggle-clickthrough":
            self.overlay.toggle_click_through()
        elif action == "snapshot":
            self.take_snapshot()
        elif action == "toggle-record":
            self.toggle_record()
        elif action == "cycle-camera":
            self.cycle_camera()
        elif action == "toggle-blur":
            self.toggle_blur()
        elif action == "show-hide":
            self.overlay.setVisible(not self.overlay.isVisible())
        elif action == "quit":
            self.quit()

    def take_snapshot(self) -> None:
        pix = self.overlay.current_pixmap()
        path = recorder.save_snapshot(pix, self.config.get("snapshot_dir"))
        if path:
            self._notify("Snapshot saved", str(path))
        else:
            self._notify("Snapshot failed", "No frame available yet.")

    def toggle_record(self) -> None:
        if self.pipeline.is_recording:
            self.pipeline.stop_recording()
            self._notify("Recording stopped", "Saved to your Videos folder.")
        else:
            path = recorder.video_path(self.config.get("video_dir"))
            self.pipeline.start_recording(str(path))
            self._notify("Recording started", str(path))

    def toggle_blur(self) -> None:
        want = not self.config.get("blur", False)
        result = self.pipeline.set_blur_enabled(want)
        self.config["blur"] = result
        if want and not result:
            from . import blur
            self._notify("Background blur unavailable",
                         "Run setup_blur.sh to install it. " + blur.import_error())
        else:
            self._notify("Background blur", "on" if result else "off")

    def cycle_camera(self) -> None:
        if len(self.cameras) < 2:
            return
        self.cam_index = (self.cam_index + 1) % len(self.cameras)
        cam = self.cameras[self.cam_index]
        fourcc, w, h, fps = self._resolve_format(cam)
        self.config["device_id"] = cam.device_id
        self._apply_saved_controls(cam)
        self.restart_capture(cam.path, fourcc, w, h, fps)
        self._notify("Camera", cam.name)

    # ------------------------------------------------------------------- tray
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon(), self.app)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        for label, slot in (
            ("Show / hide", lambda: self.handle_action("show-hide")),
            ("Settings…", self.open_settings),
            ("Snapshot", self.take_snapshot),
            ("Start / stop recording", self.toggle_record),
            ("Toggle click-through", self.overlay.toggle_click_through),
            ("Toggle background blur", self.toggle_blur),
            ("Cycle camera", self.cycle_camera),
        ):
            a = QAction(label, menu)
            a.triggered.connect(slot)
            menu.addAction(a)
        if hyprland.is_available():
            a_workspaces = QAction("Show on all workspaces", menu)
            a_workspaces.setCheckable(True)
            a_workspaces.setChecked(bool(self.config.get("show_on_all_workspaces")))
            a_workspaces.toggled.connect(self._set_workspace_pin)
            menu.addAction(a_workspaces)
        menu.addSeparator()
        a_quit = QAction("Quit", menu)
        a_quit.triggered.connect(self.quit)
        menu.addAction(a_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.handle_action("show-hide")
            if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def _notify(self, title: str, message: str) -> None:
        if getattr(self, "tray", None) is not None and self.tray.isVisible():
            self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 3000)

    def _on_pipeline_error(self, message: str) -> None:
        self._notify("PeekCam", message)
        sys.stderr.write(f"[peekcam] {message}\n")

    # ------------------------------------------------------------------- quit
    def quit(self) -> None:
        self.config.save()
        self.pipeline.stop()
        self.app.quit()


def main() -> int:
    args = sys.argv[1:]
    # CLI action forwarding to a running instance
    actions = [_ARG_TO_ACTION[a] for a in args if a in _ARG_TO_ACTION]
    if actions:
        # need a QCoreApplication for QLocalSocket
        from PyQt6.QtCore import QCoreApplication
        _ = QCoreApplication(sys.argv)
        ok = all(ipc.send_action(a) for a in actions)
        if not ok:
            sys.stderr.write("peekcam: no running instance to receive the action.\n")
            return 1
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("peekcam")
    app.setWindowIcon(app_icon())
    QGuiApplication.setQuitOnLastWindowClosed(False)

    # Single instance: if one is already running, toggle its visibility and exit.
    if ipc.send_action("show-hide"):
        return 0

    controller = Controller(app)
    _ = controller  # keep alive
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
