"""Persistent configuration stored as JSON under ~/.config/peekcam/config.json.

Holds window geometry, appearance, the last selected device/format, and — keyed by a
stable device id — the v4l2 control values so each camera restores its own tuning.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    d = Path(base) / "peekcam"
    d.mkdir(parents=True, exist_ok=True)
    return d


CONFIG_PATH = config_dir() / "config.json"

DEFAULTS: dict[str, Any] = {
    # window
    "geometry": None,            # [x, y, w, h] or None -> place bottom-right
    "shape": "rounded",         # "rect" | "rounded" | "circle"
    "corner_radius": 18,
    "opacity": 1.0,              # 0.2 .. 1.0
    "border_width": 2,
    "border_color": "#00000000", # ARGB hex, transparent by default
    "mirror": True,             # webcams usually feel natural mirrored
    "always_on_top": True,
    "show_on_all_workspaces": True,  # Hyprland overlay pin preference
    "click_through": False,
    "blur": False,              # background blur (needs mediapipe; see blur.py)
    # source / format
    "device_id": None,          # stable id (see device_manager.device_id)
    "fourcc": None,             # e.g. "MJPG" / "YUYV"
    "width": None,
    "height": None,
    "fps": None,                # float
    # per-device v4l2 control values: {device_id: {ctrl_name: value}}
    "controls": {},
    # capture output dirs
    "snapshot_dir": str(Path.home() / "Pictures"),
    "video_dir": str(Path.home() / "Videos"),
}


class Config:
    def __init__(self, data: dict[str, Any] | None = None):
        self._data = dict(DEFAULTS)
        if data:
            self._data.update(data)

    @classmethod
    def load(cls) -> "Config":
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return cls(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()

    def save(self) -> None:
        tmp = CONFIG_PATH.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp, CONFIG_PATH)

    # dict-like access ----------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    # per-device controls -------------------------------------------------
    def controls_for(self, device_id: str | None) -> dict[str, Any]:
        if not device_id:
            return {}
        return dict(self._data.get("controls", {}).get(device_id, {}))

    def set_control(self, device_id: str, name: str, value: Any) -> None:
        if not device_id:
            return
        allctrls = self._data.setdefault("controls", {})
        allctrls.setdefault(device_id, {})[name] = value
