"""Screenshot capture — 'p' key grabs the current view and saves it as a
timestamped PNG. Single responsibility: know how to render and write one
frame; watch-arm.py owns the keyboard-shortcut wiring (matches how
camera.py's shortcuts are handled — one poll of getKeyboardEvents() per
frame, each module's handler checks its own key(s)).

Not video recording — capturing and encoding a sequence of frames is a
meaningfully bigger feature (buffering, frame rate, an encoder
dependency) than a single-frame screenshot; this covers the same
"look at this later" need for a single moment, which covers most of why
someone would want either.
"""

from datetime import datetime
from pathlib import Path

import pybullet as p
from loguru import logger
from PIL import Image

SCREENSHOT_KEY = ord("p")
SCREENSHOT_DIR = Path.home() / "watch-arm-screenshots"
SCREENSHOT_WIDTH = 1280
SCREENSHOT_HEIGHT = 720


def capture() -> Path:
    """Renders the current debug-visualizer camera view (not tied to the
    actual window's pixel size — a fixed, reasonable capture resolution)
    and writes it as a PNG. Returns the path written."""
    _w, _h, view_matrix, proj_matrix, *_rest = p.getDebugVisualizerCamera()
    _width, _height, rgba, _depth, _seg = p.getCameraImage(
        SCREENSHOT_WIDTH, SCREENSHOT_HEIGHT, viewMatrix=view_matrix, projectionMatrix=proj_matrix,
    )
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.png"
    Image.frombuffer("RGBA", (SCREENSHOT_WIDTH, SCREENSHOT_HEIGHT), rgba, "raw", "RGBA", 0, 1).convert("RGB").save(path)
    return path


def handle_keyboard_shortcut() -> None:
    """Call once per render frame, alongside camera.handle_keyboard_shortcuts()."""
    keys = p.getKeyboardEvents()
    if keys.get(SCREENSHOT_KEY, 0) & p.KEY_WAS_TRIGGERED:
        path = capture()
        logger.info("screenshot saved to {}", path)
