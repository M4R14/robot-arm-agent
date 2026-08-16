"""Local 3D viewer for the isolated `sim` container.

Opens a PyBullet GUI window on the host and mirrors the arm's live joint
angles by polling the sim's own /state endpoint via `docker compose exec`
(no port exposure needed — sim stays isolated per SPEC.md). This process
only reads state; it never calls sim's mutating endpoints.

Polling runs on a background thread that spawns a single, long-lived
`docker compose exec` process (not a fresh subprocess per tick — that
used to cost ~100-300ms of exec overhead every poll). That one process
runs a tight loop *inside* the sim container hitting its own localhost,
streaming one JSON line per tick back over stdout. If it dies, it's
restarted with exponential backoff.

The render loop runs at 60Hz on the main thread:
  - drives each joint's *actual* pose with a real position-control motor
    + stepSimulation, so it eases into place instead of teleporting;
  - draws a translucent "ghost" of the robot at its *commanded* target
    pose, so you can see how far a move still has to go;
  - overlays sim's own summary/last_error/grip text, and a staleness
    warning if the stream has gone quiet.

The URDF path is fetched from sim's own /capabilities once at startup
(sim's constants.py is the single source of truth — never hardcoded
here), so the ghost and real robot always match what's actually loaded.
"""

import json
import math
import signal
import subprocess
import sys
import threading
import time

import pybullet as p
import pybullet_data

DOCKER_EXEC = ["/usr/bin/docker", "compose", "exec", "-T", "sim"]
POLL_INTERVAL_S = 0.05
RENDER_HZ = 60
STALE_AFTER_S = 1.0
RESTART_BACKOFF_INITIAL_S = 1.0
RESTART_BACKOFF_MAX_S = 15.0

DEFAULT_CAMERA = {"cameraDistance": 1.5, "cameraYaw": 50, "cameraPitch": -35, "cameraTargetPosition": [0, 0, 0.5]}
# Mouse already orbits/zooms/pans by default in PyBullet's GUI (drag / scroll /
# ctrl+drag) — these are just quick jumps to standard viewpoints on top of that.
CAMERA_PRESETS = {
    ord("1"): {"cameraDistance": 1.5, "cameraYaw": 0, "cameraPitch": -20, "cameraTargetPosition": [0, 0, 0.5]},   # front
    ord("2"): {"cameraDistance": 1.5, "cameraYaw": 90, "cameraPitch": -20, "cameraTargetPosition": [0, 0, 0.5]},  # side
    ord("3"): {"cameraDistance": 1.8, "cameraYaw": 0, "cameraPitch": -89, "cameraTargetPosition": [0, 0, 0.5]},   # top
    ord("4"): DEFAULT_CAMERA,                                                                                    # iso (startup view)
}
CONTROLS_LEGEND = (
    "mouse: drag orbit / scroll zoom / ctrl+drag pan\n"
    "keys: 1 front  2 side  3 top  4 iso  r reset view"
)

_latest_angles = {}
_latest_targets = {}
_latest_summary = ""
_latest_grip_force = 0.0
_latest_last_error = None
_last_update_time = 0.0
_parse_error_count = 0
_lock = threading.Lock()
_stream_process = None


def _fetch_urdf_path() -> str:
    out = subprocess.run(
        DOCKER_EXEC + ["python3", "-c", "import urllib.request,json;"
                       "print(json.load(urllib.request.urlopen('http://localhost:8000/capabilities'))['urdf_path'])"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def _handle_state_line(line: str) -> None:
    global _last_update_time, _parse_error_count
    try:
        state = json.loads(line)
    except json.JSONDecodeError:
        _parse_error_count += 1
        if _parse_error_count % 20 == 1:
            print(f"warning: {_parse_error_count} malformed stream line(s) so far, last: {line[:80]!r}")
        return
    if "error" in state:
        print("sim-side poll failed:", state["error"])
        return

    with _lock:
        for joint in state["joints"]:
            _latest_angles[joint["joint_id"]] = math.radians(joint["angle_deg"])
            if joint.get("target_angle_deg") is not None:
                _latest_targets[joint["joint_id"]] = math.radians(joint["target_angle_deg"])
            else:
                _latest_targets.pop(joint["joint_id"], None)
        globals()["_latest_summary"] = state.get("summary", "")
        globals()["_latest_grip_force"] = state.get("grip_force", 0.0)
        globals()["_latest_last_error"] = state.get("last_error")
        _last_update_time = time.monotonic()


def _stream_loop() -> None:
    global _stream_process
    backoff = RESTART_BACKOFF_INITIAL_S
    stream_cmd = DOCKER_EXEC + [
        "python3", "-c",
        "import urllib.request,json,time\n"
        "while True:\n"
        "    try:\n"
        "        print(json.dumps(json.load(urllib.request.urlopen('http://localhost:8000/state'))), flush=True)\n"
        "    except Exception as exc:\n"
        "        print(json.dumps({'error': str(exc)}), flush=True)\n"
        f"    time.sleep({POLL_INTERVAL_S})\n",
    ]
    while True:
        try:
            _stream_process = subprocess.Popen(stream_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            for line in iter(_stream_process.stdout.readline, ""):
                _handle_state_line(line)
                backoff = RESTART_BACKOFF_INITIAL_S
            _stream_process.wait()
        except Exception as exc:
            print("stream failed:", exc)
        print(f"stream process exited, restarting in {backoff:.1f}s...")
        time.sleep(backoff)
        backoff = min(backoff * 2, RESTART_BACKOFF_MAX_S)


def _shutdown(*_args) -> None:
    if _stream_process is not None:
        _stream_process.terminate()
    sys.exit(0)


def main():
    urdf_path = _fetch_urdf_path()
    print(f"URDF: {urdf_path} (fetched from sim's /capabilities)")

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    p.connect(p.GUI)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.loadURDF("plane.urdf")
    robot_id = p.loadURDF(urdf_path, [0, 0, 0], useFixedBase=True)
    p.setGravity(0, 0, -9.8)
    p.resetDebugVisualizerCamera(**DEFAULT_CAMERA)
    p.addUserDebugText(CONTROLS_LEGEND, [-0.9, 0, 1.8], textColorRGB=[0.7, 0.7, 0.7], textSize=1.1)

    ghost_id = p.loadURDF(urdf_path, [0, 0, 0], useFixedBase=True)
    num_ghost_links = p.getNumJoints(ghost_id)
    p.changeVisualShape(ghost_id, -1, rgbaColor=[0.2, 0.6, 1.0, 0.25])
    for link_index in range(num_ghost_links):
        p.changeVisualShape(ghost_id, link_index, rgbaColor=[0.2, 0.6, 1.0, 0.25])
    for link_index in range(-1, num_ghost_links):
        p.setCollisionFilterGroupMask(ghost_id, link_index, 0, 0)

    overlay_id = None

    threading.Thread(target=_stream_loop, daemon=True).start()

    print("Viewer running — watching sim's live state. Ctrl+C to stop.")
    while True:
        with _lock:
            actual = dict(_latest_angles)
            targets = dict(_latest_targets)
            summary = _latest_summary
            grip_force = _latest_grip_force
            last_error = _latest_last_error
            age_s = time.monotonic() - _last_update_time if _last_update_time else None

        for joint_id, angle_rad in actual.items():
            p.setJointMotorControl2(robot_id, joint_id, p.POSITION_CONTROL, targetPosition=angle_rad)
        for joint_id, angle_rad in targets.items():
            p.resetJointState(ghost_id, joint_id, angle_rad)
        p.stepSimulation()

        keys = p.getKeyboardEvents()
        if keys.get(ord("r"), 0) & p.KEY_WAS_TRIGGERED:
            p.resetDebugVisualizerCamera(**DEFAULT_CAMERA)
        for keycode, preset in CAMERA_PRESETS.items():
            if keys.get(keycode, 0) & p.KEY_WAS_TRIGGERED:
                p.resetDebugVisualizerCamera(**preset)

        stale = age_s is not None and age_s > STALE_AFTER_S
        lines = [f"STALE ({age_s:.1f}s since last update)" if stale else summary, f"grip force: {grip_force:.0f}"]
        if last_error:
            lines.append(f"last error: {last_error['error_code']}")
        text = "\n".join(lines)
        color = [1, 0.3, 0.3] if (stale or last_error) else [1, 1, 1]
        if overlay_id is None:
            overlay_id = p.addUserDebugText(text, [0, 0, 1.6], textColorRGB=color, textSize=1.3)
        else:
            overlay_id = p.addUserDebugText(text, [0, 0, 1.6], textColorRGB=color, textSize=1.3, replaceItemUniqueId=overlay_id)

        time.sleep(1.0 / RENDER_HZ)


if __name__ == "__main__":
    main()
