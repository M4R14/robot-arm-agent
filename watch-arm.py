"""Local 3D viewer for the isolated `sim` container — entry point.

Opens a PyBullet GUI window on the host and mirrors the arm's live state
without breaking `sim`'s isolation (see SPEC.md): it never opens a direct
network route to `sim`, only polling via `docker compose exec`. See the
`viewer/` package for the pieces this wires together:
  - `viewer.state_stream` — background polling and thread-safe state
  - `viewer.camera` — camera presets, keyboard shortcuts, custom-view save
  - `viewer.overlay` — end-effector axis triad, overlay text/color, the
    new-error flash effect, and recent-rejection history
  - `viewer.joint_limits` — per-joint hardware-limit proximity coloring
  - `viewer.trail` — end-effector recent-position breadcrumb trail
  - `viewer.screenshot` — 'p' to save the current view as a PNG

The render loop runs at 60Hz (physics/motion updates every frame), but
the on-screen debug text, axis-triad lines, joint-limit coloring, and
trail redraw at a throttled 5Hz — redrawing those every frame was pure
GPU/CPU waste since nobody reads text or needs sub-200ms trail updates
at 60Hz anyway. It also draws a translucent "ghost" of the robot at its
*commanded* target pose (so you can see how far an in-flight move still
has to go) alongside the *actual* pose, and a translucent shell showing
the arm's reach envelope (reach_min_m..reach_max_m from /capabilities),
so an UNREACHABLE_POSE rejection is visually obvious rather than a
guess.
"""

import signal
import sys
import time

import pybullet as p
import pybullet_data
import typer
from loguru import logger

from viewer.camera import CONTROLS_LEGEND, apply_default, handle_keyboard_shortcuts
from viewer.joint_limits import joint_colors, radians_to_degrees
from viewer.overlay import ErrorFlashTracker, axis_endpoints, build_overlay_text, overlay_color
from viewer.screenshot import handle_keyboard_shortcut as handle_screenshot_shortcut
from viewer.sim_exec import fetch_capabilities
from viewer.state_stream import StateStream
from viewer.trail import EndEffectorTrail

FPS_WINDOW_S = 0.5
REACH_SHELL_SEGMENTS = 24  # sphere tessellation for the reach-envelope overlay — visual only, not collidable

_stream: StateStream = None

app = typer.Typer(add_completion=False)


def _shutdown(*_args) -> None:
    if _stream is not None:
        _stream.stop()
    sys.exit(0)


def _add_reach_shell(radius_m: float, rgba: list) -> int:
    shape = p.createVisualShape(p.GEOM_SPHERE, radius=radius_m, rgbaColor=rgba)
    body_id = p.createMultiBody(baseMass=0, baseVisualShapeIndex=shape, basePosition=[0, 0, 0])
    p.setCollisionFilterGroupMask(body_id, -1, 0, 0)
    return body_id


@app.command()
def main(
    render_hz: float = typer.Option(60.0, help="Render/physics-step frequency."),
    poll_interval_s: float = typer.Option(0.05, help="How often the background thread polls sim's /state."),
    overlay_hz: float = typer.Option(5.0, help="Overlay/trail/joint-color redraw frequency (throttled below render_hz)."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Only log warnings and errors, not startup/info messages."),
) -> None:
    """Open the local 3D viewer and mirror sim's live state."""
    global _stream

    logger.remove()
    logger.add(sys.stderr, level="WARNING" if quiet else "INFO")

    capabilities = fetch_capabilities()
    logger.info("URDF: {} (fetched from sim's /capabilities)", capabilities.urdf_path)
    logger.info("reach envelope: {:.3f}m - {:.3f}m", capabilities.reach_min_m, capabilities.reach_max_m)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    p.connect(p.GUI)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.loadURDF("plane.urdf")
    robot_id = p.loadURDF(capabilities.urdf_path, [0, 0, 0], useFixedBase=True)
    p.setGravity(0, 0, -9.8)
    apply_default()
    p.addUserDebugText(CONTROLS_LEGEND, [-0.9, 0, 1.8], textColorRGB=[0.7, 0.7, 0.7], textSize=1.1)

    ghost_id = p.loadURDF(capabilities.urdf_path, [0, 0, 0], useFixedBase=True)
    num_ghost_links = p.getNumJoints(ghost_id)
    p.changeVisualShape(ghost_id, -1, rgbaColor=[0.2, 0.6, 1.0, 0.25])
    for link_index in range(num_ghost_links):
        p.changeVisualShape(ghost_id, link_index, rgbaColor=[0.2, 0.6, 1.0, 0.25])
    for link_index in range(-1, num_ghost_links):
        p.setCollisionFilterGroupMask(ghost_id, link_index, 0, 0)

    _add_reach_shell(capabilities.reach_max_m, [0.5, 0.5, 1.0, 0.04])
    _add_reach_shell(capabilities.reach_min_m, [1.0, 0.5, 0.2, 0.06])

    ee_marker_shape = p.createVisualShape(p.GEOM_SPHERE, radius=0.02, rgbaColor=[1, 0, 0, 0.9])
    ee_marker_id = p.createMultiBody(baseMass=0, baseVisualShapeIndex=ee_marker_shape, basePosition=[0, 0, 0])
    p.setCollisionFilterGroupMask(ee_marker_id, -1, 0, 0)
    axis_ids = [None, None, None]  # X, Y, Z debug lines — created lazily on first throttled update
    trail_line_ids: list = []
    trail = EndEffectorTrail()
    last_joint_colors: dict = {}

    overlay_id = None
    frame_count = 0
    fps_window_start = time.monotonic()
    fps = 0.0
    overlay_last_update = 0.0
    flash_tracker = ErrorFlashTracker()

    _stream = StateStream(poll_interval_s=poll_interval_s)
    _stream.start()

    logger.info("Viewer running — watching sim's live state. Ctrl+C to stop.")
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
        handle_screenshot_shortcut()

        frame_count += 1
        now = time.monotonic()
        if now - fps_window_start >= FPS_WINDOW_S:
            fps = frame_count / (now - fps_window_start)
            frame_count = 0
            fps_window_start = now

        trail.add(snap.ee_position, now)

        if now - overlay_last_update >= 1.0 / overlay_hz:
            overlay_last_update = now

            if snap.ee_position is not None and snap.ee_orientation is not None:
                axis_colors = ([1, 0, 0], [0, 1, 0], [0, 0, 1])
                for i, endpoint in enumerate(axis_endpoints(snap.ee_position, snap.ee_orientation)):
                    axis_ids[i] = p.addUserDebugLine(
                        snap.ee_position, endpoint, lineColorRGB=axis_colors[i], lineWidth=2,
                        replaceItemUniqueId=axis_ids[i] if axis_ids[i] is not None else -1,
                    )

            # Reuse existing line IDs via replaceItemUniqueId instead of
            # removing and recreating every segment each tick — with a
            # fast move generating dozens of segments, remove+recreate
            # bursts that many PyBullet calls into a single frame, which
            # showed up as a periodic stutter every throttled tick rather
            # than a steady framerate drop. Only the count actually
            # changing (segments added or aged out) touches
            # add/removeUserDebugItem; unchanged segments just get their
            # endpoints/alpha updated in place.
            segments = trail.segments(now)
            for i, (start, end, alpha) in enumerate(segments):
                line_kwargs = dict(lineColorRGB=[1, 0, 0], lineWidth=2 + 2 * alpha)
                if i < len(trail_line_ids):
                    trail_line_ids[i] = p.addUserDebugLine(start, end, replaceItemUniqueId=trail_line_ids[i], **line_kwargs)
                else:
                    trail_line_ids.append(p.addUserDebugLine(start, end, **line_kwargs))
            while len(trail_line_ids) > len(segments):
                p.removeUserDebugItem(trail_line_ids.pop())

            # Only touch joints whose color actually changed since the
            # last tick — most joints sit at NORMAL_COLOR most of the
            # time, and changeVisualShape isn't free even when setting an
            # unchanged color.
            angles_deg = radians_to_degrees(snap.angles_rad)
            for joint_id, color in joint_colors(angles_deg, capabilities.joint_limits).items():
                if last_joint_colors.get(joint_id) != color:
                    p.changeVisualShape(robot_id, joint_id, rgbaColor=[*color, 1.0])
                    last_joint_colors[joint_id] = color

            error_code = snap.last_error["error_code"] if snap.last_error else None
            flashing = flash_tracker.update(error_code, now)
            text, stale = build_overlay_text(
                snap.summary, snap.grip_force, fps, age_s, snap.last_error, snap.rejected_history
            )
            color = overlay_color(stale, snap.last_error is not None, flashing, flash_tracker.blink_on(now))

            if overlay_id is None:
                overlay_id = p.addUserDebugText(text, [0, 0, 1.6], textColorRGB=color, textSize=1.3)
            else:
                overlay_id = p.addUserDebugText(
                    text, [0, 0, 1.6], textColorRGB=color, textSize=1.3, replaceItemUniqueId=overlay_id
                )

        time.sleep(1.0 / render_hz)


if __name__ == "__main__":
    app()
