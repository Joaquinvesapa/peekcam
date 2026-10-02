"""The overlay itself: a frameless, always-on-top, translucent window that paints the
camera feed with an optional rounded/circle mask, and supports drag, resize, opacity,
mirror, click-through, and a right-click / tray menu.

Runs as an X11 client under XWayland (see main.py) so always-on-top + free positioning
+ input passthrough actually work on GNOME/Zorin.
"""
from __future__ import annotations

import sys

from PyQt6.QtCore import Qt, QPoint, QRect, QRectF, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import (QAction, QColor, QCursor, QImage, QPainter, QPainterPath,
                         QPen, QPixmap, QGuiApplication)
from PyQt6.QtWidgets import QApplication, QMenu, QWidget

from .geometry import monitor_for_geometry, normalize_geometry

RESIZE_MARGIN = 12
MIN_SIZE = 120
SIDEBAR_BORDER_COLOR = QColor("#c1a5e4")


class OverlayWindow(QWidget):
    request_settings = pyqtSignal()
    request_snapshot = pyqtSignal()
    request_toggle_record = pyqtSignal()
    request_toggle_blur = pyqtSignal()
    request_quit = pyqtSignal()

    def __init__(self, config):
        super().__init__(None)
        self.config = config
        self._image: QImage | None = None
        self._drag_offset: QPoint | None = None
        self._resizing = False
        self._resize_start_geo = QRect()
        self._resize_start_mouse = QPoint()
        self._recording = False

        # appearance from config
        self.shape = config.get("shape", "rounded")
        self.corner_radius = int(config.get("corner_radius", 3))
        self.border_width = int(config.get("border_width", 2))
        self.border_color = QColor(config.get("border_color", "#00000000"))
        self.mirror = bool(config.get("mirror", True))

        self._apply_window_flags(initial=True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setWindowTitle("PeekCam")
        self.setWindowOpacity(float(config.get("opacity", 1.0)))

        screens = QGuiApplication.screens()
        areas = [screen.availableGeometry().getRect() for screen in screens]
        primary = QGuiApplication.primaryScreen()
        preferred = primary.availableGeometry().getRect() if primary else None
        saved = config.get("geometry")
        geometry = normalize_geometry(saved, areas, preferred)
        self.setGeometry(*geometry)
        self._deferred_startup = not any(w > 0 and h > 0 for _, _, w, h in areas)
        self._startup_geometry = self.geometry().getRect()
        if not self._deferred_startup:
            self._save_geometry()
            if saved != config.get("geometry"):
                self._persist_geometry()

        # A parented single-shot runs on Qt's thread and collapses signal bursts.
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._recover_monitor_layout)
        self._screen_hooks = {}
        self._monitor_snapshot = self._snapshot_monitors(screens)
        self._placement_geometry = self.geometry().getRect()
        self._placement_monitor = None
        self._remember_placement()
        self._screen_app = QGuiApplication.instance()
        self._screen_app.screenAdded.connect(self._screen_added)
        self._screen_app.screenRemoved.connect(self._screen_removed)
        self._screen_app.primaryScreenChanged.connect(self._schedule_monitor_recovery)
        for screen in screens:
            self._attach_screen(screen)

    # ------------------------------------------------------------ window flags
    def _apply_window_flags(self, initial: bool = False) -> None:
        flags = (Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.Tool)  # Tool keeps it out of the taskbar
        if self.config.get("always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if self.config.get("click_through", False):
            flags |= Qt.WindowType.WindowTransparentForInput
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible and not initial:
            self.show()

    def set_click_through(self, enabled: bool) -> None:
        self.config["click_through"] = enabled
        self._apply_window_flags()
        self.show()

    def toggle_click_through(self) -> None:
        self.set_click_through(not self.config.get("click_through", False))

    # ------------------------------------------------------------- frame input
    def set_image(self, image: QImage) -> None:
        self._image = image
        self.update()

    def current_pixmap(self) -> QPixmap | None:
        """The frame as currently displayed (with mirror applied) for snapshots."""
        if self._image is None:
            return None
        img = self._image
        if self.mirror:
            img = img.mirrored(True, False)
        return QPixmap.fromImage(img)

    # -------------------------------------------------------------- appearance
    def set_shape(self, shape: str) -> None:
        self.shape = shape
        self.config["shape"] = shape
        self.update()

    def set_opacity(self, value: float) -> None:
        value = max(0.2, min(1.0, value))
        self.config["opacity"] = value
        self.setWindowOpacity(value)

    def set_mirror(self, enabled: bool) -> None:
        self.mirror = enabled
        self.config["mirror"] = enabled
        self.update()

    def set_recording_indicator(self, recording: bool) -> None:
        self._recording = recording
        self.update()

    # ------------------------------------------------------------------ paint
    def _content_path(self, rect: QRectF) -> QPainterPath:
        path = QPainterPath()
        if self.shape == "circle":
            d = min(rect.width(), rect.height())
            sq = QRectF(rect.center().x() - d / 2, rect.center().y() - d / 2, d, d)
            path.addEllipse(sq)
        elif self.shape == "rounded":
            path.addRoundedRect(rect, self.corner_radius, self.corner_radius)
        else:
            path.addRect(rect)
        return path

    def _draw_sidebar_border(self, painter: QPainter, rect: QRectF) -> None:
        """Draw a one-pixel lavender outline without glow, inside the content edge."""
        width = 1.0
        painter.save()
        outer_path = self._content_path(rect)
        # The outline already follows the camera mask. Applying its clip again
        # multiplies antialiased coverage and weakens the rounded corners.
        painter.setClipping(False)

        # Fill an inner-contained band to keep the full outline inside the mask.
        inner_rect = rect.adjusted(width, width, -width, -width)
        inner_path = QPainterPath()
        if self.shape == "rounded":
            radius = max(0, self.corner_radius - width)
            inner_path.addRoundedRect(inner_rect, radius, radius)
        else:
            inner_path = self._content_path(inner_rect)
        painter.fillPath(outer_path.subtracted(inner_path), SIDEBAR_BORDER_COLOR)
        painter.restore()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing
                               | QPainter.RenderHint.SmoothPixmapTransform)
        rectf = QRectF(self.rect())
        path = self._content_path(rectf)
        painter.setClipPath(path)

        if self._image is None:
            painter.fillPath(path, QColor(20, 20, 22, 220))
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "No camera")
        else:
            img = self._image
            if self.mirror:
                img = img.mirrored(True, False)
            # scale to cover the content rect, preserving aspect (center-crop)
            scaled = img.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation)
            x = (scaled.width() - self.width()) // 2
            y = (scaled.height() - self.height()) // 2
            painter.drawImage(self.rect(), scaled, QRect(x, y, self.width(), self.height()))

        self._draw_sidebar_border(painter, rectf)

        if self.border_width > 0 and self.border_color.alpha() > 0:
            pen = QPen(self.border_color, self.border_width)
            painter.setClipping(False)
            painter.setPen(pen)
            painter.drawPath(path)

        if self._recording:
            painter.setClipping(False)
            painter.setBrush(QColor(230, 40, 40))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(10, 10, 12, 12)
        painter.end()

    # -------------------------------------------------------------- interaction
    def _in_resize_zone(self, pos: QPoint) -> bool:
        return (pos.x() >= self.width() - RESIZE_MARGIN
                and pos.y() >= self.height() - RESIZE_MARGIN)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._in_resize_zone(event.position().toPoint()):
                self._resizing = True
                self._resize_start_geo = self.geometry()
                self._resize_start_mouse = event.globalPosition().toPoint()
            else:
                self._drag_offset = (event.globalPosition().toPoint()
                                     - self.frameGeometry().topLeft())
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        pt = event.position().toPoint()
        if self._resizing:
            delta = event.globalPosition().toPoint() - self._resize_start_mouse
            g = self._resize_start_geo
            new_w = max(MIN_SIZE, g.width() + delta.x())
            new_h = max(MIN_SIZE, g.height() + delta.y())
            self.resize(new_w, new_h)
        elif self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        else:
            if self._in_resize_zone(pt):
                self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))

    def mouseReleaseEvent(self, _event) -> None:
        self._drag_offset = None
        self._resizing = False
        self._save_geometry()

    def wheelEvent(self, event) -> None:
        # Ctrl+wheel adjusts opacity for quick tuning.
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            step = 0.05 if event.angleDelta().y() > 0 else -0.05
            self.set_opacity(self.config.get("opacity", 1.0) + step)
            event.accept()

    def contextMenuEvent(self, event) -> None:
        self.build_menu().exec(event.globalPos())

    # ------------------------------------------------------------------- menu
    def build_menu(self) -> QMenu:
        menu = QMenu(self)

        act_settings = QAction("Settings…", menu)
        act_settings.triggered.connect(self.request_settings.emit)
        menu.addAction(act_settings)

        shape_menu = menu.addMenu("Shape")
        for label, key in (("Rectangle", "rect"), ("Rounded", "rounded"), ("Circle", "circle")):
            a = QAction(label, shape_menu, checkable=True)
            a.setChecked(self.shape == key)
            a.triggered.connect(lambda _c, k=key: self.set_shape(k))
            shape_menu.addAction(a)

        a_mirror = QAction("Mirror", menu, checkable=True)
        a_mirror.setChecked(self.mirror)
        a_mirror.triggered.connect(lambda c: self.set_mirror(c))
        menu.addAction(a_mirror)

        a_click = QAction("Click-through", menu, checkable=True)
        a_click.setChecked(self.config.get("click_through", False))
        a_click.triggered.connect(lambda c: self.set_click_through(c))
        menu.addAction(a_click)

        a_blur = QAction("Background blur", menu, checkable=True)
        a_blur.setChecked(self.config.get("blur", False))
        a_blur.triggered.connect(self.request_toggle_blur.emit)
        menu.addAction(a_blur)

        menu.addSeparator()
        a_snap = QAction("Snapshot", menu)
        a_snap.triggered.connect(self.request_snapshot.emit)
        menu.addAction(a_snap)

        a_rec = QAction("Stop recording" if self._recording else "Start recording", menu)
        a_rec.triggered.connect(self.request_toggle_record.emit)
        menu.addAction(a_rec)

        menu.addSeparator()
        a_quit = QAction("Quit", menu)
        a_quit.triggered.connect(self.request_quit.emit)
        menu.addAction(a_quit)
        return menu

    # ------------------------------------------------------------------ layout
    @staticmethod
    def _snapshot_monitors(screens):
        # Store values, not QScreen wrappers: removed QScreens may be destroyed.
        return [(screen.name(), screen.geometry().getRect(),
                 screen.availableGeometry().getRect()) for screen in screens
                if screen.availableGeometry().width() > 0
                and screen.availableGeometry().height() > 0]

    def _attach_screen(self, screen) -> None:
        if screen in self._screen_hooks:
            return
        signals = (screen.geometryChanged, screen.availableGeometryChanged)
        for signal in signals:
            signal.connect(self._schedule_monitor_recovery)
        self._screen_hooks[screen] = signals

    def _detach_screen(self, screen) -> None:
        for signal in self._screen_hooks.pop(screen, ()):
            try:
                signal.disconnect(self._schedule_monitor_recovery)
            except (TypeError, RuntimeError):
                # Qt may already have destroyed the removed screen.
                pass

    def _screen_added(self, screen) -> None:
        self._attach_screen(screen)
        self._schedule_monitor_recovery()

    def _screen_removed(self, screen) -> None:
        self._detach_screen(screen)
        self._schedule_monitor_recovery()

    def _window_monitor_name(self):
        handle = self.windowHandle()
        screen = handle.screen() if handle is not None else None
        return screen.name() if screen is not None else None

    def _remember_placement(self) -> None:
        """Record ownership only against a stable layout, never obsolete rectangles."""
        previous = self._monitor_snapshot
        if not previous or self._snapshot_monitors(QGuiApplication.screens()) != previous:
            return
        actual = self.geometry().getRect()
        index = monitor_for_geometry(actual, [rect for _, rect, _ in previous])
        name = previous[index][0] if index is not None else None
        identity = self._window_monitor_name()
        # A compositor move can arrive before the screen geometry notification.
        if identity in [entry[0] for entry in previous] and identity != name:
            return
        self._placement_geometry = actual
        self._placement_monitor = name

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if hasattr(self, '_monitor_snapshot'):
            # Cross-output user drags are committed on mouse release. Unsolicited
            # moves onto another output may be an early compositor adjustment.
            index = monitor_for_geometry(self.geometry().getRect(),
                                         [rect for _, rect, _ in self._monitor_snapshot])
            name = self._monitor_snapshot[index][0] if index is not None else None
            if name == self._placement_monitor or self._drag_offset is not None:
                self._remember_placement()

    def _schedule_monitor_recovery(self, *_args) -> None:
        self._layout_timer.start(0)

    def _recover_monitor_layout(self) -> None:
        screens = QGuiApplication.screens()
        for screen in list(self._screen_hooks):
            if screen not in screens:
                self._detach_screen(screen)
        for screen in screens:
            self._attach_screen(screen)
        current = self._snapshot_monitors(screens)
        if not current:
            # Retain the last usable origins across temporary empty layouts.
            return
        actual = self.geometry().getRect()
        candidate = actual
        previous = self._monitor_snapshot
        name = self._placement_monitor
        # During topology changes QWindow identity may lag the compositor move.
        # Only stable layouts may use it to supersede durable placement ownership.
        if current == previous and actual != self._placement_geometry:
            identity = self._window_monitor_name()
            if identity in [entry[0] for entry in previous]:
                name = identity
        old_matches = [entry for entry in previous if entry[0] == name]
        survivors = [entry for entry in current if entry[0] == name]
        # Missing/duplicate ownership is not evidence for translating reachable
        # geometry using obsolete rectangles.
        old = old_matches[0] if len(old_matches) == 1 else None
        survivor = survivors[0] if len(survivors) == 1 else None
        target = None
        if old is not None and survivor is not None:
            _, old_rect, _ = old
            _, new_rect, area = survivor
            dx, dy = new_rect[0] - old_rect[0], new_rect[1] - old_rect[1]
            # Unchanged placement is durable pre-change evidence. If it changed,
            # translate only when still on that old output and not already usable
            # on its new area. Otherwise preserve a possibly compositor-moved window.
            on_old = monitor_for_geometry(actual, [old_rect]) is not None
            usable_new = normalize_geometry(actual, [area], area) == actual
            if actual == self._placement_geometry or (on_old and not usable_new):
                candidate = (actual[0] + dx, actual[1] + dy, *actual[2:])
                target = area
            elif usable_new:
                target = area
        primary = QGuiApplication.primaryScreen()
        preferred = primary.availableGeometry().getRect() if primary else None
        areas = [area for _, _, area in current]
        # A survivor's translation takes precedence over stale global overlap.
        if self._deferred_startup and actual == self._startup_geometry:
            candidate = self.config.get("geometry")
        corrected = normalize_geometry(candidate, [target] if target else areas,
                                       target or preferred)
        self._monitor_snapshot = current
        deferred = self._deferred_startup
        self._deferred_startup = False
        if corrected != actual:
            self.setGeometry(*corrected)
        self._remember_placement()
        if corrected != actual or deferred or (current != previous
                                               and self.config.get('geometry') != list(corrected)):
            saved = self.config.get("geometry")
            self._save_geometry()
            if corrected != actual or saved != self.config.get("geometry"):
                self._persist_geometry()

    def _persist_geometry(self) -> None:
        # Plain dict configurations remain useful for embedding and widget tests.
        save = getattr(self.config, "save", None)
        if save is not None:
            try:
                save()
            except OSError as error:
                sys.stderr.write(f"[peekcam] Could not save recovered geometry: {error}\n")

    def stop_monitor_recovery(self) -> None:
        """Disconnect topology hooks before application shutdown."""
        self._layout_timer.stop()
        for screen in list(self._screen_hooks):
            self._detach_screen(screen)
        if self._screen_app is not None:
            self._screen_app.screenAdded.disconnect(self._screen_added)
            self._screen_app.screenRemoved.disconnect(self._screen_removed)
            self._screen_app.primaryScreenChanged.disconnect(self._schedule_monitor_recovery)
            self._screen_app = None

    def sizeHint(self) -> QSize:
        return QSize(360, 240)

    def _move_to_corner(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        margin = 24
        self.move(area.right() - self.width() - margin,
                  area.bottom() - self.height() - margin)

    def _save_geometry(self) -> None:
        g = self.geometry()
        self.config["geometry"] = [g.x(), g.y(), g.width(), g.height()]
        if hasattr(self, '_monitor_snapshot'):
            self._remember_placement()

    def closeEvent(self, event) -> None:
        self._save_geometry()
        super().closeEvent(event)
