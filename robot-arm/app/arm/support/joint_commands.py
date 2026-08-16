"""Per-joint move logic: build a candidate joint configuration, clamp it,
validate it, and (for the real — not preview — path) drive it. Single
responsibility: joint-space moves — no rate limiting, error/metrics
recording, or locking of its own (ArmService holds the lock and wraps
these calls with rate-limit checks and _note_error/_note_success; these
methods assume the lock is already held where that matters).
"""

from typing import Dict, List, Optional, Tuple

from ..adapters.pybullet_adapter import PyBulletAdapter
from ..support.exceptions import JointOutOfRangeError
from .motion_driver import SynchronizedMotionDriver
from .motion_validator import MotionValidator


class JointCommands:
    def __init__(self, adapter: PyBulletAdapter, validator: MotionValidator, driver: SynchronizedMotionDriver) -> None:
        self._adapter = adapter
        self._validator = validator
        self._driver = driver

    def move_joint_locked(
        self, joint_id: int, target_angle_deg: float, relative: bool, target_angles_deg: Dict[int, float]
    ) -> float:
        """Caller must hold the adapter's lock."""
        if joint_id not in self._adapter.movable_joints:
            raise JointOutOfRangeError(joint_id, self._adapter.movable_joints)
        if relative:
            current_deg = next(j.angle_deg for j in self._adapter.get_joint_angles_deg() if j.joint_id == joint_id)
            target_angle_deg = current_deg + target_angle_deg
        clamped_deg = self._validator.clamp_to_joint_limits(joint_id, target_angle_deg)
        candidate = {j.joint_id: j.angle_deg for j in self._adapter.get_joint_angles_deg()}
        candidate[joint_id] = clamped_deg
        self._validator.validate_or_raise(candidate)
        self._adapter.set_joint_target_deg(joint_id, clamped_deg)
        target_angles_deg[joint_id] = clamped_deg
        return clamped_deg

    def preview_move_joint(
        self, joint_id: int, target_angle_deg: float, relative: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """Caller must hold the adapter's lock (dry-run, no motor command)."""
        if joint_id not in self._adapter.movable_joints:
            return False, str(JointOutOfRangeError(joint_id, self._adapter.movable_joints))
        if relative:
            current_deg = next(j.angle_deg for j in self._adapter.get_joint_angles_deg() if j.joint_id == joint_id)
            target_angle_deg = current_deg + target_angle_deg
        clamped_deg = self._validator.clamp_to_joint_limits(joint_id, target_angle_deg)
        candidate = {j.joint_id: j.angle_deg for j in self._adapter.get_joint_angles_deg()}
        candidate[joint_id] = clamped_deg
        try:
            self._validator.validate_or_raise(candidate)
        except ValueError as exc:
            return False, str(exc)
        return True, None

    def move_joints_locked(
        self, targets: List[Tuple[int, float]], relative: bool, target_angles_deg: Dict[int, float]
    ) -> Dict[int, float]:
        """Caller must hold the adapter's lock."""
        current_angles_deg = {j.joint_id: j.angle_deg for j in self._adapter.get_joint_angles_deg()}
        candidate = dict(current_angles_deg)
        for joint_id, target_deg in targets:
            if joint_id not in self._adapter.movable_joints:
                raise JointOutOfRangeError(joint_id, self._adapter.movable_joints)
            effective_deg = current_angles_deg[joint_id] + target_deg if relative else target_deg
            candidate[joint_id] = self._validator.clamp_to_joint_limits(joint_id, effective_deg)

        self._validator.validate_or_raise(candidate)

        moved_only = {joint_id: candidate[joint_id] for joint_id, _ in targets}
        self._driver.drive(moved_only, current_angles_deg, target_angles_deg)
        return moved_only
