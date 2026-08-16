"""Local 3D viewer for the isolated `sim` container — entry point.

Opens a PyBullet GUI window on the host and mirrors the arm's live state
without breaking `sim`'s isolation (see SPEC.md): it never opens a direct
network route to `sim`, only polling via `docker compose exec`. See the
`viewer/` package for the pieces this wires together:
  - `viewer.state_stream` — background polling and thread-safe state
  - `viewer.camera` — camera presets and keyboard shortcuts
  - `viewer.overlay` — end-effector axis triad, overlay text/color, and
    the new-error flash effect

The render loop runs at 60Hz (physics/motion updates every frame), but
the on-screen debug text and axis-triad lines redraw at a throttled 5Hz
— redrawing those every frame was pure GPU/CPU waste since nobody reads
text at 60Hz anyway. It also draws a translucent "ghost" of the robot at
its *commanded* target pose (so you can see how far a move still has to
go) alongside the *actual* pose.
"""

import signal
import sys
import time

import pybullet as p
import pybullet_data

from viewer.camera import CONTROLS_LEGEND, apply_default, handle_keyboard_shortcuts
from viewer.overlay import ErrorFlashTracker, axis_endpoints, build_overlay_text, overlay_color
from viewer.state_stream import StateStream, fetch_urdf_path

RENDER_HZ = 60
FPS_WINDOW_S = 0.5
OVERLAY_UPDATE_HZ = 5

_stream: StateStream = None


def _shutdown(*_args) -> None:
    if _stream is not None:
        _stream.stop()
    sys.exit(0)


def main():
    global _stream
    urdf_path = fetch_urdf_path()
    print(f"URDF: {urdf_path} (fetched from sim's /capabilities)")

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    p.connect(p.GUI)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.loadURDF("plane.urdf")
    robot_id = p.loadURDF(urdf_path, [0, 0, 0], useFixedBase=True)
    p.setGravity(0, 0, -9.8)
    apply_default()
    p.addUserDebugText(CONTROLS_LEGEND, [-0.9, 0, 1.8], textColorRGB=[0.7, 0.7, 0.7], textSize=1.1)

    ghost_id = p.loadURDF(urdf_path, [0, 0, 0], useFixedBase=True)
    num_ghost_links = p.getNumJoints(ghost_id)
    p.changeVisualShape(ghost_id, -1, rgbaColor=[0.2, 0.6, 1.0, 0.25])
    for link_index in range(num_ghost_links):
        p.changeVisualShape(ghost_id, link_index, rgbaColor=[0.2, 0.6, 1.0, 0.25])
    for link_index in range(-1, num_ghost_links):
        p.setCollisionFilterGroupMask(ghost_id, link_index, 0, 0)

    ee_marker_shape = p.createVisualShape(p.GEOM_SPHERE, radius=0.02, rgbaColor=[1, 0, 0, 0.9])
    ee_marker_id = p.createMultiBody(baseMass=0, baseVisualShapeIndex=ee_marker_shape, basePosition=[0, 0, 0])
    p.setCollisionFilterGroupMask(ee_marker_id, -1, 0, 0)
    axis_ids = [None, None, None]  # X, Y, Z debug lines — created lazily on first throttled update

    overlay_id = None
    frame_count = 0
    fps_window_start = time.monotonic()
    fps = 0.0
    overlay_last_update = 0.0
    flash_tracker = ErrorFlashTracker()

    _stream = StateStream()
    _stream.start()

    print("Viewer running — watching sim's live state. Ctrl+C to stop.")
    while True:
        snap = _stream.snapshot()
        age_s = time.monotonic() - snap.updated_at if snap.updated_at else None

        for joint_id, angle_rad in snap.angles_rad.items():
            p.setJointMotorControl2(robot_id, joint_id, p.POSITION_CONTROL, targetPosition=angle_rad)
        for joint_id, angle_rad in snap.targets_rad.items():
            p.resetJointState(ghost_id, joint_id, angle_rad)
        if snap.ee_position is not None:
            p.resetBasePositionAndOrientation(ee_marker_id, snap.ee_position, snap.ee_orientation or [0, 0, 0, 1])
        p.stepSimulation()

        handle_keyboard_shortcuts()

        frame_count += 1
        now = time.monotonic()
        if now - fps_window_start >= FPS_WINDOW_S:
            fps = frame_count / (now - fps_window_start)
            frame_count = 0
            fps_window_start = now

        if now - overlay_last_update >= 1.0 / OVERLAY_UPDATE_HZ:
            overlay_last_update = now

            if snap.ee_position is not None and snap.ee_orientation is not None:
                axis_colors = ([1, 0, 0], [0, 1, 0], [0, 0, 1])
                for i, endpoint in enumerate(axis_endpoints(snap.ee_position, snap.ee_orientation)):
                    axis_ids[i] = p.addUserDebugLine(
                        snap.ee_position, endpoint, lineColorRGB=axis_colors[i], lineWidth=2,
                        replaceItemUniqueId=axis_ids[i] if axis_ids[i] is not None else -1,
                    )

            error_code = snap.last_error["error_code"] if snap.last_error else None
            flashing = flash_tracker.update(error_code, now)
            text, stale = build_overlay_text(snap.summary, snap.grip_force, fps, age_s, snap.last_error)
            color = overlay_color(stale, snap.last_error is not None, flashing, flash_tracker.blink_on(now))

            if overlay_id is None:
                overlay_id = p.addUserDebugText(text, [0, 0, 1.6], textColorRGB=color, textSize=1.3)
            else:
                overlay_id = p.addUserDebugText(
                    text, [0, 0, 1.6], textColorRGB=color, textSize=1.3, replaceItemUniqueId=overlay_id
                )

        time.sleep(1.0 / RENDER_HZ)


if __name__ == "__main__":
    main()
