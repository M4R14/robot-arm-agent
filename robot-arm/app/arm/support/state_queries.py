"""Read-only queries against the arm's current state: joint angles/targets,
"has this joint arrived?", a blocking wait-until-reached poll, and static
capabilities. Single responsibility: answer "what is/can the arm do right
now" — never issues a motor command, never touches error/rejection
tracking (that's ArmService's own concern, since it also needs its own
`last_error` attribute alongside this).

Not thread-safe on its own — touches the shared PyBullet client via
adapter reads. Uses the *same* lock instance ArmService and the other
command collaborators share — `wait_reached` takes it once per poll
rather than holding it for the whole wait, since it must not block every
other caller for the full timeout.
"""

import threading
import time
from typing import Dict, List, Optional, Tuple

from ..adapters.pybullet_adapter import JointAngle, PyBulletAdapter
from ..constants import (
    DEFAULT_WAIT_TIMEOUT_S,
    HOME_POSE_DEG,
    IK_REACHABLE_TOLERANCE_M,
    JOINT_REACHED_TOLERANCE_DEG,
    MAX_FORCE,
    MAX_JOINT_VELOCITY_DEG_S,
    MAX_WAIT_TIMEOUT_S,
    MIN_COMMAND_INTERVAL_S,
    SINGULARITY_CONDITION_THRESHOLD,
    URDF_PATH,
    WAIT_POLL_INTERVAL_S,
)
from .util import clamp


class StateQueries:
    def __init__(self, lock: threading.Lock, adapter: PyBulletAdapter) -> None:
        self._lock = lock
        self._adapter = adapter

    def _read_joints_and_targets(self, target_angles_deg: Dict[int, float]) -> Tuple[List[JointAngle], Dict[int, float]]:
        with self._lock:
            joints = self._adapter.get_joint_angles_deg()
            targets = dict(target_angles_deg)
        return joints, targets

    def read_full_state(
        self, target_angles_deg: Dict[int, float]
    ) -> Tuple[List[JointAngle], List[float], List[float], Dict[int, float]]:
        with self._lock:
            joints = self._adapter.get_joint_angles_deg()
            ee_position = self._adapter.get_end_effector_position()
            ee_orientation = self._adapter.get_end_effector_orientation()
            targets = dict(target_angles_deg)
        return joints, ee_position, ee_orientation, targets

    def is_reached(self, joint_id: int, angle_deg: float, targets: Dict[int, float]) -> bool:
        target = targets.get(joint_id)
        if target is None:
            return True
        return abs(angle_deg - target) <= JOINT_REACHED_TOLERANCE_DEG

    def wait_reached(
        self, target_angles_deg: Dict[int, float], joint_ids: Optional[List[int]], timeout_s: Optional[float]
    ) -> Tuple[bool, bool, List[JointAngle], Dict[int, float]]:
        clamped_timeout = clamp(timeout_s if timeout_s is not None else DEFAULT_WAIT_TIMEOUT_S, 0.0, MAX_WAIT_TIMEOUT_S)
        deadline = time.monotonic() + clamped_timeout
        while True:
            joints, targets = self._read_joints_and_targets(target_angles_deg)
            relevant = [j for j in joints if joint_ids is None or j.joint_id in joint_ids]
            if all(self.is_reached(j.joint_id, j.angle_deg, targets) for j in relevant):
                return True, False, joints, targets
            if time.monotonic() >= deadline:
                return False, True, joints, targets
            time.sleep(WAIT_POLL_INTERVAL_S)

    def get_capabilities(self) -> Dict:
        with self._lock:
            joint_ids = list(self._adapter.movable_joints)
            joint_limits = [
                {"joint_id": j, "min_deg": lo, "max_deg": hi}
                for j, (lo, hi) in self._adapter.joint_limits_deg.items()
            ]
            reach_min_m, reach_max_m = self._adapter.estimate_reach_envelope_m()
        return {
            "urdf_path": URDF_PATH,
            "joint_ids": joint_ids,
            "joint_limits": joint_limits,
            "reach_min_m": reach_min_m,
            "reach_max_m": reach_max_m,
            "max_force": MAX_FORCE,
            "max_joint_velocity_deg_s": MAX_JOINT_VELOCITY_DEG_S,
            "singularity_condition_threshold": SINGULARITY_CONDITION_THRESHOLD,
            "ik_reachable_tolerance_m": IK_REACHABLE_TOLERANCE_M,
            "min_command_interval_s": MIN_COMMAND_INTERVAL_S,
            "default_wait_timeout_s": DEFAULT_WAIT_TIMEOUT_S,
            "max_wait_timeout_s": MAX_WAIT_TIMEOUT_S,
            "home_pose_deg": dict(HOME_POSE_DEG),
        }
