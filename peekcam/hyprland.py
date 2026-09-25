"""Optional Hyprland integration without a runtime dependency."""
from __future__ import annotations

import os
import shutil
import subprocess


_PIN_TIMEOUT_SECONDS = 1


def is_available() -> bool:
    """Return whether this process can safely send a Hyprland command."""
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) and shutil.which("hyprctl") is not None


def pin_current_window() -> bool:
    """Pin this process's window across Hyprland workspaces when available."""
    return _dispatch_pin("enable")


def unpin_current_window() -> bool:
    """Remove the workspace pin from this process's window when available."""
    return _dispatch_pin("disable")


def _dispatch_pin(action: str) -> bool:
    """Use Hyprland's explicit enable/disable action, never its toggle action."""
    if not is_available():
        return False

    command = [
        "hyprctl",
        "dispatch",
        f'hl.dsp.window.pin({{ window = "pid:{os.getpid()}", action = "{action}" }})',
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_PIN_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
