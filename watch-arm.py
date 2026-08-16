"""Local 3D viewer for the isolated `sim` container.

Opens a PyBullet GUI window on the host and mirrors the arm's live joint
angles by polling the sim's own /state endpoint via `docker compose exec`
(no port exposure needed — sim stays isolated per SPEC.md). This process
only reads state; it never calls sim's mutating endpoints.

Polling (slow, subprocess-based) runs on a background thread. The render
loop runs at 60Hz on the main thread and drives each joint toward the
latest known angle with a real position-control motor + stepSimulation,
so the arm eases into place instead of teleporting between polls.
"""

import json
import math
import subprocess
import threading
import time

import pybullet as p
import pybullet_data

URDF_PATH = "kuka_iiwa/model.urdf"
POLL_CMD = [
    "/usr/bin/docker", "compose", "exec", "-T", "sim",
    "python3", "-c",
    "import urllib.request,json;"
    "print(json.dumps(json.load(urllib.request.urlopen('http://localhost:8000/state'))))",
]
RENDER_HZ = 60

_latest_angles = {}
_lock = threading.Lock()


def _poll_loop():
    while True:
        try:
            out = subprocess.run(POLL_CMD, capture_output=True, text=True, check=True)
            state = json.loads(out.stdout)
            with _lock:
                for joint in state["joints"]:
                    _latest_angles[joint["joint_id"]] = math.radians(joint["angle_deg"])
        except Exception as exc:
            print("poll failed:", exc)
        time.sleep(0.1)


def main():
    p.connect(p.GUI)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.loadURDF("plane.urdf")
    robot_id = p.loadURDF(URDF_PATH, [0, 0, 0], useFixedBase=True)
    p.setGravity(0, 0, -9.8)
    p.resetDebugVisualizerCamera(cameraDistance=1.5, cameraYaw=50, cameraPitch=-35,
                                  cameraTargetPosition=[0, 0, 0.5])

    threading.Thread(target=_poll_loop, daemon=True).start()

    print("Viewer running — watching sim's live state. Ctrl+C to stop.")
    while True:
        with _lock:
            targets = dict(_latest_angles)
        for joint_id, angle_rad in targets.items():
            p.setJointMotorControl2(robot_id, joint_id, p.POSITION_CONTROL, targetPosition=angle_rad)
        p.stepSimulation()
        time.sleep(1.0 / RENDER_HZ)


if __name__ == "__main__":
    main()
