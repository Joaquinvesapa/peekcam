"""The overlay itself: a frameless, always-on-top, translucent window that paints the
camera feed with an optional rounded/circle mask, and supports drag, resize, opacity,
mirror, click-through, and a right-click / tray menu.

Runs as an X11 client under XWayland (see main.py) so always-on-top + free positioning
+ input passthrough actually work on GNOME/Zorin.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QPoint, QRect, QRectF, QSize, pyqtSignal
from PyQt6.QtGui import (QAction, QColor, QCursor, QImage, QPainter, QPainterPath,
                         QPen, QPixmap, QGuiApplication)
from PyQt6.QtWidgets import QApplication, QMenu, QWidget

RESIZE_MARGIN = 12
MIN_SIZE = 120
OMARCHY_ACTIVE_BORDER = QColor("#eb6f92")


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
        self.corner_radius = int(config.get("corner_radius", 18))
        self.border_width = int(config.get("border_width", 2))
        self.border_color = QColor(config.get("border_color", "#00000000"))
        self.mirror = bool(config.get("mirror", True))

        self._apply_window_flags(initial=True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setWindowTitle("PeekCam")
        self.setWindowOpacity(float(config.get("opacity", 1.0)))

        geo = config.get("geometry")
        if geo and len(geo) == 4:
            self.setGeometry(*geo)
        else:
            self.resize(360, 240)
            self._move_to_corner()

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

    def _draw_omarchy_border(self, painter: QPainter, rect: QRectF) -> None:
        """Draw a restrained Rosé Pine border aligned with the content edge."""
        core_width = 3.0
        painter.save()
        painter.setClipPath(self._content_path(rect))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Concentric one-pixel bands approximate a soft inward gradient while
        # retaining the same contour for rectangles, rounded frames and circles.
        def inset_path(distance: float) -> QPainterPath:
            inner = rect.adjusted(distance, distance, -distance, -distance)
            if self.shape == "rounded":
                path = QPainterPath()
                radius = max(0, self.corner_radius - distance)
                path.addRoundedRect(inner, radius, radius)
                return path
            return self._content_path(inner)

        painter.setPen(Qt.PenStyle.NoPen)
        for distance, alpha in enumerate((105, 72, 42, 20, 7), start=3):
            band = inset_path(distance).subtracted(inset_path(distance + 1))
            painter.fillPath(band, QColor(235, 111, 146, alpha))

        # Fill the band between the actual content edge and its inset contour.
        # A centered stroke clipped to the outer path loses its outer AA samples.
        inner_rect = rect.adjusted(core_width, core_width, -core_width, -core_width)
        inner_path = QPainterPath()
        if self.shape == "rounded":
            radius = max(0, self.corner_radius - core_width)
            inner_path.addRoundedRect(inner_rect, radius, radius)
        else:
            inner_path = self._content_path(inner_rect)
        band = self._content_path(rect).subtracted(inner_path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillPath(band, OMARCHY_ACTIVE_BORDER)
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

        self._draw_omarchy_border(painter, rectf)

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

    def closeEvent(self, event) -> None:
        self._save_geometry()
        super().closeEvent(event)
