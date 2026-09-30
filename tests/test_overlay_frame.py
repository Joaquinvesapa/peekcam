"""Offscreen rendering coverage for the sidebar-style overlay outline."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath
from PyQt6.QtWidgets import QApplication

from peekcam.overlay_window import OverlayWindow


class OverlayFrameRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _render(shape: str, width: int, height: int, **appearance) -> tuple[OverlayWindow, QImage]:
        overlay = OverlayWindow({"shape": shape, "mirror": False, **appearance})
        overlay.resize(width, height)
        camera_image = QImage(width, height, QImage.Format.Format_ARGB32)
        camera_image.fill(QColor(20, 30, 40))
        overlay.set_image(camera_image)

        rendered = QImage(width, height, QImage.Format.Format_ARGB32)
        rendered.fill(QColor(0, 0, 0, 0))
        painter = QPainter(rendered)
        overlay.render(painter)
        painter.end()
        return overlay, rendered

    @staticmethod
    def _is_lavender(pixel: QColor, tolerance: int = 20) -> bool:
        lavender = QColor("#c1a5e4")
        return (pixel.alpha() > 0
                and abs(pixel.red() - lavender.red()) < tolerance
                and abs(pixel.green() - lavender.green()) < tolerance
                and abs(pixel.blue() - lavender.blue()) < tolerance)

    def test_border_is_always_visible_for_each_shape(self) -> None:
        for shape, size in (("rect", (320, 180)), ("rounded", (320, 180)),
                            ("circle", (240, 240)), ("circle", (320, 180))):
            with self.subTest(shape=shape, size=size):
                _overlay, rendered = self._render(shape, *size)
                self.assertTrue(self._is_lavender(rendered.pixelColor(size[0] // 2, 0)))

    def test_border_follows_edge_without_covering_camera_or_snapshots(self) -> None:
        overlay, rendered = self._render("rounded", 640, 360)
        self.assertEqual(rendered.pixelColor(320, 0), QColor("#c1a5e4"))
        self.assertEqual(rendered.pixelColor(320, 1), QColor(20, 30, 40))
        self.assertEqual(rendered.pixelColor(320, 180), QColor(20, 30, 40))
        snapshot = overlay.current_pixmap()
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.toImage().pixelColor(320, 0), QColor(20, 30, 40))

    def test_one_pixel_border_and_corner_continuity(self) -> None:
        for shape, size, arc in (
            ("rect", (320, 180), [(0, 0)]),
            ("rounded", (320, 180), [(3, 0), (1, 1), (0, 3)]),
            ("circle", (240, 240), [(120, 0), (35, 35), (0, 120)]),
        ):
            with self.subTest(shape=shape):
                _overlay, rendered = self._render(shape, *size)
                w, h = size
                for x, y in arc:
                    for px, py in ((x, y), (w - 1 - x, y),
                                   (x, h - 1 - y), (w - 1 - x, h - 1 - y)):
                        # Diagonal AA samples blend the one-pixel band with the camera.
                        self.assertTrue(self._is_lavender(rendered.pixelColor(px, py), 50),
                                        (shape, px, py))
                for x, y in ((w // 2, 0), (w // 2, h - 1),
                             (0, h // 2), (w - 1, h // 2)):
                    self.assertTrue(self._is_lavender(rendered.pixelColor(x, y)),
                                    (shape, x, y))
                if shape != "rect":
                    self.assertLess(rendered.pixelColor(0, 0).alpha(), 32)

    def test_camera_clip_does_not_attenuate_corner_transitions(self) -> None:
        overlay, _rendered = self._render("rounded", 376, 212)
        outline = QImage(376, 212, QImage.Format.Format_ARGB32)
        outline.fill(QColor(0, 0, 0, 0))
        painter = QPainter(outline)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        camera_mask = overlay._content_path(QRectF(outline.rect()))
        painter.setClipPath(camera_mask)
        overlay._draw_sidebar_border(painter, QRectF(outline.rect()))
        clip_restored = painter.hasClipping() and painter.clipPath() == camera_mask
        painter.end()
        self.assertTrue(clip_restored)

        # These edge-to-arc samples were missed by the original diagonal checks.
        # A second AA clip reduced their alpha from ~99/204 to ~54/185.
        for x, y, minimum_alpha in ((1, 0, 90), (0, 1, 90),
                                     (2, 0, 195), (0, 2, 195)):
            for px, py in ((x, y), (375 - x, y),
                           (x, 211 - y), (375 - x, 211 - y)):
                with self.subTest(x=px, y=py):
                    pixel = outline.pixelColor(px, py)
                    self.assertGreaterEqual(pixel.alpha(), minimum_alpha)
                    self.assertTrue(self._is_lavender(pixel))
        self.assertEqual(outline.pixelColor(188, 106).alpha(), 0)

    def test_outline_is_above_camera_with_the_exact_mask_radius(self) -> None:
        for radius in (3, 8, 18):
            with self.subTest(radius=radius):
                _overlay, rendered = self._render("rounded", 376, 212, corner_radius=radius)
                expected = QImage(376, 212, QImage.Format.Format_ARGB32)
                expected.fill(QColor(0, 0, 0, 0))
                camera = QImage(376, 212, QImage.Format.Format_ARGB32)
                camera.fill(QColor(20, 30, 40))
                outer = QPainterPath()
                outer.addRoundedRect(QRectF(0, 0, 376, 212), radius, radius)
                inner = QPainterPath()
                inner.addRoundedRect(QRectF(1, 1, 374, 210), radius - 1, radius - 1)
                painter = QPainter(expected)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setClipPath(outer)
                painter.drawImage(0, 0, camera)
                painter.setClipping(False)
                painter.fillPath(outer.subtracted(inner), QColor("#c1a5e4"))
                painter.end()
                self.assertEqual(rendered, expected)

    def test_no_inner_glow_or_shadow(self) -> None:
        camera = QColor(20, 30, 40)
        for shape, size in (("rect", (320, 180)), ("rounded", (320, 180)),
                            ("circle", (240, 240))):
            with self.subTest(shape=shape):
                _overlay, rendered = self._render(shape, *size)
                w, h = size
                for distance in range(1, 10):
                    for x, y in ((w // 2, distance), (w // 2, h - 1 - distance),
                                 (distance, h // 2), (w - 1 - distance, h // 2)):
                        pixel = rendered.pixelColor(x, y)
                        # Circle AA may spill up to two RGB levels into the adjacent pixel.
                        tolerance = 2 if shape == "circle" and distance == 1 else 0
                        for actual, expected in zip(pixel.getRgb(), camera.getRgb()):
                            self.assertLessEqual(abs(actual - expected), tolerance,
                                                 (shape, x, y, pixel.getRgb()))
                self.assertEqual(rendered.pixelColor(w // 2, h // 2), camera)

    def test_small_default_corners_preserve_explicit_radius(self) -> None:
        overlay, _rendered = self._render("rounded", 320, 180)
        self.assertEqual(overlay.corner_radius, 3)
        custom, rendered = self._render("rounded", 320, 180, corner_radius=8)
        self.assertEqual(custom.corner_radius, 8)
        self.assertTrue(self._is_lavender(rendered.pixelColor(8, 0)))
        self.assertEqual(rendered.pixelColor(0, 0).alpha(), 0)

    def test_recording_indicator_is_painted_above_the_frame(self) -> None:
        overlay, _rendered = self._render("rounded", 320, 180)
        overlay.set_recording_indicator(True)
        rendered = QImage(320, 180, QImage.Format.Format_ARGB32)
        rendered.fill(QColor(0, 0, 0, 0))
        painter = QPainter(rendered)
        overlay.render(painter)
        painter.end()
        self.assertEqual(rendered.pixelColor(15, 15), QColor(230, 40, 40))


if __name__ == "__main__":
    unittest.main()
