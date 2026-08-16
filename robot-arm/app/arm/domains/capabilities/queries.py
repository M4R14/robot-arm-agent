"""Static arm capabilities: joint limits, reach envelope, safety/timing
constants. Single responsibility: answer "what can the arm do" — never
changes at runtime except across a URDF swap, unlike domains/state's
"what is it doing right now".
"""

import threading
from typing import Dict

from ...adapters.pybullet_adapter import PyBulletAdapter
from ...constants import (
    DEFAULT_WAIT_TIMEOUT_S,
    HOME_POSE_DEG,
    IK_REACHABLE_TOLERANCE_M,
    MAX_FORCE,
    MAX_JOINT_VELOCITY_DEG_S,
    MAX_WAIT_TIMEOUT_S,
    MIN_COMMAND_INTERVAL_S,
    SINGULARITY_CONDITION_THRESHOLD,
    URDF_PATH,
)


class CapabilitiesQueries:
    def __init__(self, lock: threading.Lock, adapter: PyBulletAdapter) -> None:
        self._lock = lock
        self._adapter = adapter

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
