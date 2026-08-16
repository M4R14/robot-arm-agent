"""Startup/reset state management: driving the arm to its configured home
pose, and reloading the URDF on reset. Distinct from JointCommands/
PoseCommands (per-request command logic) and StateQueries/
CapabilitiesQueries (reads) — this is the third concern, "what state the
arm starts/resets into."

Doesn't touch target_angles_deg/grip_force/outcome tracking itself —
those are ArmService's own state; each method returns what changed and
lets the caller assign it.
"""

from typing import Dict

from ..constants import HOME_POSE_DEG, RESET_SETTLE_STEPS
from .ports import ArmPhysicsPort


class LifecycleCommands:
    def __init__(self, adapter: ArmPhysicsPort) -> None:
        self._adapter = adapter

    def drive_to_home_pose_locked(self) -> Dict[int, float]:
        """Caller must hold the adapter's lock (or call before the
        stepping clock/HTTP layer exist, i.e. during __init__). Returns
        the new target_angles_deg mapping — empty if there's no
        configured home pose."""
        if not HOME_POSE_DEG:
            return {}
        for joint_id, target_deg in HOME_POSE_DEG.items():
            self._adapter.set_joint_target_deg(joint_id, target_deg)
        for _ in range(RESET_SETTLE_STEPS):
            self._adapter.step()
        return dict(HOME_POSE_DEG)

    def reset_locked(self) -> None:
        """Caller must hold the adapter's lock. Reloads the URDF and lets
        it settle."""
        self._adapter.load()
        for _ in range(RESET_SETTLE_STEPS):
            self._adapter.step()
