"""Camera presets and keyboard-driven camera control. Mouse orbit/zoom/pan
is PyBullet's own built-in GUI navigation (drag / scroll / ctrl+drag) —
nothing here disables or replaces it, these are just quick jumps to
standard viewpoints on top of that.
"""

import json
from pathlib import Path
from typing import Optional

import pybullet as p
from loguru import logger

DEFAULT_CAMERA = {"cameraDistance": 1.5, "cameraYaw": 50, "cameraPitch": -35, "cameraTargetPosition": [0, 0, 0.5]}
CAMERA_PRESETS = {
    ord("1"): {"cameraDistance": 1.5, "cameraYaw": 0, "cameraPitch": -20, "cameraTargetPosition": [0, 0, 0.5]},   # front
    ord("2"): {"cameraDistance": 1.5, "cameraYaw": 90, "cameraPitch": -20, "cameraTargetPosition": [0, 0, 0.5]},  # side
    ord("3"): {"cameraDistance": 1.8, "cameraYaw": 0, "cameraPitch": -89, "cameraTargetPosition": [0, 0, 0.5]},   # top
    ord("4"): DEFAULT_CAMERA,                                                                                    # iso (startup view)
}
# Slot 5 is the one user-saved custom view (press c to save it) — kept
# separate from the fixed CAMERA_PRESETS above since it's read/written at
# runtime, not a constant.
CUSTOM_CAMERA_KEY = ord("5")
SAVE_CAMERA_KEY = ord("c")
SAVED_CAMERA_PATH = Path.home() / ".cache" / "watch-arm" / "camera.json"

CONTROLS_LEGEND = (
    "mouse: drag orbit / scroll zoom / ctrl+drag pan\n"
    "keys: 1 front  2 side  3 top  4 iso  5 custom (c to save)  r reset view\n"
    "      p screenshot\n"
    "solid arm = actual pose   translucent blue ghost = commanded target\n"
    "red dot + RGB axes = end effector position/orientation (X red, Y green, Z blue)\n"
    "fading trail = recent end-effector path   tinted joints = near hardware limit\n"
    "translucent shell = reach envelope (reach_min_m..reach_max_m)"
)


def apply_default() -> None:
    p.resetDebugVisualizerCamera(**DEFAULT_CAMERA)


def _current_camera_params() -> dict:
    _w, _h, _view, _proj, _up, _fwd, _horiz, _vert, yaw, pitch, dist, target = p.getDebugVisualizerCamera()
    return {"cameraDistance": dist, "cameraYaw": yaw, "cameraPitch": pitch, "cameraTargetPosition": list(target)}


def _load_saved_camera() -> Optional[dict]:
    try:
        return json.loads(SAVED_CAMERA_PATH.read_text())
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("could not read saved camera at {}: {}", SAVED_CAMERA_PATH, exc)
        return None


def _save_camera(params: dict) -> None:
    try:
        SAVED_CAMERA_PATH.parent.mkdir(parents=True, exist_ok=True)
        SAVED_CAMERA_PATH.write_text(json.dumps(params))
        logger.info("saved custom camera view to {} (press 5 to recall it, incl. next session)", SAVED_CAMERA_PATH)
    except OSError as exc:
        logger.warning("could not save camera to {}: {}", SAVED_CAMERA_PATH, exc)


def handle_keyboard_shortcuts() -> None:
    """Polls PyBullet's keyboard events for camera-preset / reset /
    save-custom-view keys and applies them immediately. Call once per
    render frame."""
    keys = p.getKeyboardEvents()
    if keys.get(ord("r"), 0) & p.KEY_WAS_TRIGGERED:
        apply_default()
    for keycode, preset in CAMERA_PRESETS.items():
        if keys.get(keycode, 0) & p.KEY_WAS_TRIGGERED:
            p.resetDebugVisualizerCamera(**preset)
    if keys.get(SAVE_CAMERA_KEY, 0) & p.KEY_WAS_TRIGGERED:
        _save_camera(_current_camera_params())
    if keys.get(CUSTOM_CAMERA_KEY, 0) & p.KEY_WAS_TRIGGERED:
        saved = _load_saved_camera()
        if saved is not None:
            p.resetDebugVisualizerCamera(**saved)
        else:
            logger.warning("no custom camera saved yet — press c first to save the current view")
