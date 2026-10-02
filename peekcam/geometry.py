"""Deterministic geometry recovery, independent of Qt and monitor event timing."""
from __future__ import annotations

from collections.abc import Sequence

Geometry = tuple[int, int, int, int]
DEFAULT_SIZE = (360, 240)
ACCESSIBLE_PIXELS = 32
CORNER_MARGIN = 24
# QWidget dimensions are limited even though QRect uses signed 32-bit integers.
MAX_WIDGET_SIZE = 16777215


def _geometry(value: object, max_size: int = MAX_WIDGET_SIZE) -> Geometry | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    if any(type(component) is not int for component in value):
        return None
    x, y, width, height = value
    if not (-2147483648 <= x <= 2147483647
            and -2147483648 <= y <= 2147483647
            and 0 < width <= max_size and 0 < height <= max_size):
        return None
    return x, y, width, height


def monitor_for_geometry(window: Geometry, monitors: Sequence[Geometry]) -> int | None:
    """Choose the largest intersection, with snapshot order breaking ties."""
    x, y, width, height = window
    overlaps = [max(0, min(x + width, sx + sw) - max(x, sx))
                * max(0, min(y + height, sy + sh) - max(y, sy))
                for sx, sy, sw, sh in monitors]
    if not overlaps or max(overlaps) == 0:
        return None
    return overlaps.index(max(overlaps))


def normalize_geometry(saved: object, screens: Sequence[Geometry],
                       preferred: Geometry | None = None) -> Geometry:
    """Preserve accessible placement; otherwise fit on the preferred/first screen.

    Screen rectangles are individual available work areas, never their union.
    Accessibility requires up to 32 visible pixels on *both* axes on one screen.
    Oversized windows are shrunk only to the selected work area. An empty screen
    snapshot defers placement recovery (invalid input still gets a safe default).
    The caller owns applying the result and recording it, without showing a window.
    """
    original = _geometry(saved)
    geometry = original or (0, 0, *DEFAULT_SIZE)
    areas = [area for raw in screens
             if (area := _geometry(raw, 2147483647)) is not None]
    if not areas:
        return geometry

    x, y, width, height = geometry
    target = preferred if preferred in areas else areas[0]
    for area in areas:
        sx, sy, sw, sh = area
        visible_width = min(x + width, sx + sw) - max(x, sx)
        visible_height = min(y + height, sy + sh) - max(y, sy)
        if (original is not None
                and visible_width >= min(ACCESSIBLE_PIXELS, width, sw)
                and visible_height >= min(ACCESSIBLE_PIXELS, height, sh)):
            if width <= sw and height <= sh:
                return geometry
            target = area
            break

    sx, sy, sw, sh = target
    width, height = min(width, sw), min(height, sh)
    if original is None:
        x = sx + sw - width - CORNER_MARGIN
        y = sy + sh - height - CORNER_MARGIN
    # Half-open rectangle arithmetic avoids QRect.right()/bottom() off-by-ones.
    x = max(sx, min(x, sx + sw - width))
    y = max(sy, min(y, sy + sh - height))
    return x, y, width, height
