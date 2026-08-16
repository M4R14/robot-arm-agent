"""Camera presets and keyboard-driven camera control. Mouse orbit/zoom/pan
is PyBullet's own built-in GUI navigation (drag / scroll / ctrl+drag) —
nothing here disables or replaces it, these are just quick jumps to
standard viewpoints on top of that.
"""

import pybullet as p

DEFAULT_CAMERA = {"cameraDistance": 1.5, "cameraYaw": 50, "cameraPitch": -35, "cameraTargetPosition": [0, 0, 0.5]}
CAMERA_PRESETS = {
    ord("1"): {"cameraDistance": 1.5, "cameraYaw": 0, "cameraPitch": -20, "cameraTargetPosition": [0, 0, 0.5]},   # front
    ord("2"): {"cameraDistance": 1.5, "cameraYaw": 90, "cameraPitch": -20, "cameraTargetPosition": [0, 0, 0.5]},  # side
    ord("3"): {"cameraDistance": 1.8, "cameraYaw": 0, "cameraPitch": -89, "cameraTargetPosition": [0, 0, 0.5]},   # top
    ord("4"): DEFAULT_CAMERA,                                                                                    # iso (startup view)
}
CONTROLS_LEGEND = (
    "mouse: drag orbit / scroll zoom / ctrl+drag pan\n"
    "keys: 1 front  2 side  3 top  4 iso  r reset view\n"
    "solid arm = actual pose   translucent blue ghost = commanded target\n"
    "red dot + RGB axes = end effector position/orientation (X red, Y green, Z blue)"
)


def apply_default() -> None:
    p.resetDebugVisualizerCamera(**DEFAULT_CAMERA)


def handle_keyboard_shortcuts() -> None:
    """Polls PyBullet's keyboard events for camera-preset / reset keys and
    applies them immediately. Call once per render frame."""
    keys = p.getKeyboardEvents()
    if keys.get(ord("r"), 0) & p.KEY_WAS_TRIGGERED:
        apply_default()
    for keycode, preset in CAMERA_PRESETS.items():
        if keys.get(keycode, 0) & p.KEY_WAS_TRIGGERED:
            p.resetDebugVisualizerCamera(**preset)
