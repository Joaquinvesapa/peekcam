"""Offscreen rendering coverage for the procedural overlay frame."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication

from peekcam.overlay_window import OverlayWindow


class OverlayFrameRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _render(shape: str, width: int, height: int) -> tuple[OverlayWindow, QImage]:
        overlay = OverlayWindow({"shape": shape, "mirror": False})
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
    def _is_rose_pine_love(pixel: QColor) -> bool:
        love = QColor("#eb6f92")
        return (abs(pixel.red() - love.red()) < 20
                and abs(pixel.green() - love.green()) < 20
                and abs(pixel.blue() - love.blue()) < 20)

    def test_border_is_always_visible_for_each_shape(self) -> None:
        for shape, size in (("rect", (320, 180)), ("rounded", (320, 180)), ("circle", (240, 240))):
            with self.subTest(shape=shape):
                _overlay, rendered = self._render(shape, *size)
                pixels = [rendered.pixelColor(x, y) for x in range(rendered.width())
                          for y in range(rendered.height())]
                self.assertTrue(any(self._is_rose_pine_love(pixel) for pixel in pixels))

    def test_border_follows_edge_without_covering_camera_or_snapshots(self) -> None:
        overlay, rendered = self._render("rounded", 640, 360)
        edge_pixels = [rendered.pixelColor(x, 1) for x in range(rendered.width())]
        self.assertTrue(any(self._is_rose_pine_love(pixel) for pixel in edge_pixels))
        self.assertNotEqual(rendered.pixelColor(320, 2), QColor(20, 30, 40))
        self.assertEqual(rendered.pixelColor(320, 9), QColor(20, 30, 40))
        self.assertEqual(rendered.pixelColor(320, 180), QColor(20, 30, 40))
        snapshot = overlay.current_pixmap()
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.toImage().pixelColor(320, 4), QColor(20, 30, 40))

    def test_three_pixel_core_and_corner_continuity(self) -> None:
        for shape, size, arc in (
            ("rect", (320, 180), [(0, 0), (1, 1), (2, 2)]),
            ("rounded", (320, 180), [(18, 1), (6, 6), (6, 7), (1, 18)]),
            ("circle", (240, 240), [(120, 1), (36, 36), (35, 36), (1, 120)]),
        ):
            with self.subTest(shape=shape):
                _overlay, rendered = self._render(shape, *size)
                w, h = size
                for x, y in arc:
                    for px, py in ((x, y), (w - 1 - x, y),
                                   (x, h - 1 - y), (w - 1 - x, h - 1 - y)):
                        self.assertTrue(self._is_rose_pine_love(rendered.pixelColor(px, py)),
                                        (shape, px, py))
                for y in (0, 1, 2):
                    self.assertTrue(self._is_rose_pine_love(
                        rendered.pixelColor(w // 2, y)), (shape, y))
                self.assertFalse(self._is_rose_pine_love(rendered.pixelColor(w // 2, 4)))
                if shape != "rect":
                    self.assertEqual(rendered.pixelColor(0, 0).alpha(), 0)

    def test_inner_shadow_fades_without_tinting_center(self) -> None:
        camera = QColor(20, 30, 40)
        for shape, size, edge in (("rect", (320, 180), (160, 5)),
                                  ("rounded", (320, 180), (160, 5)),
                                  ("circle", (240, 240), (120, 5))):
            with self.subTest(shape=shape):
                _overlay, rendered = self._render(shape, *size)
                self.assertGreater(rendered.pixelColor(*edge).red(), camera.red())
                self.assertEqual(rendered.pixelColor(size[0] // 2, size[1] // 2), camera)

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
