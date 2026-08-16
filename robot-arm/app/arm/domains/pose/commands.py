"""Cartesian end-effector move logic: IK, candidate clamping, validation,
and (for the real — not preview — path) driving. Single responsibility:
pose-space moves — no rate limiting, error/metrics recording, or locking
of its own (ArmService holds the lock and wraps these calls with
rate-limit checks and _note_error/_note_success; these methods assume
the lock is already held where that matters).
"""

from typing import Dict, List, Optional, Tuple

from ...adapters.pybullet_adapter import PyBulletAdapter
from ...constants import POSE_TOWARD_LIMIT_COARSE_STEPS, POSE_TOWARD_LIMIT_REFINE_ITERATIONS
from ...support.motion_driver import SynchronizedMotionDriver
from ...support.motion_validator import MotionValidator
from ...support.pose_memory import PoseFact


def _fact_to_dict(fact: Optional[PoseFact]) -> Optional[Dict]:
    if fact is None:
        return None
    return {"outcome": fact.outcome, "error_code": fact.error_code, "recorded_at": fact.recorded_at}


class PoseCommands:
    def __init__(self, adapter: PyBulletAdapter, validator: MotionValidator, driver: SynchronizedMotionDriver) -> None:
        self._adapter = adapter
        self._validator = validator
        self._driver = driver

    def move_to_pose_locked(
        self,
        x: float,
        y: float,
        z: float,
        roll_deg: Optional[float],
        pitch_deg: Optional[float],
        yaw_deg: Optional[float],
        relative: bool,
        target_angles_deg: Dict[int, float],
    ) -> None:
        """Caller must hold the adapter's lock."""
        if relative:
            current_ee = self._adapter.get_end_effector_position()
            x, y, z = current_ee[0] + x, current_ee[1] + y, current_ee[2] + z

        orientation_quat = None
        if roll_deg is not None and pitch_deg is not None and yaw_deg is not None:
            orientation_quat = self._adapter.euler_deg_to_quaternion(roll_deg, pitch_deg, yaw_deg)

        current_angles_deg = {j.joint_id: j.angle_deg for j in self._adapter.get_joint_angles_deg()}
        target_angles = self._adapter.calculate_ik_deg([x, y, z], orientation_quat)
        candidate = {
            joint_id: self._validator.clamp_to_joint_limits(joint_id, target_deg)
            for joint_id, target_deg in zip(self._adapter.movable_joints, target_angles)
        }
        self._validator.validate_or_raise(candidate, requested_position=[x, y, z])
        self._driver.drive(candidate, current_angles_deg, target_angles_deg)

    def preview_move_to_pose(
        self,
        x: float,
        y: float,
        z: float,
        roll_deg: Optional[float] = None,
        pitch_deg: Optional[float] = None,
        yaw_deg: Optional[float] = None,
        relative: bool = False,
    ) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """Caller must hold the adapter's lock (dry-run, no motor command)."""
        if relative:
            current_ee = self._adapter.get_end_effector_position()
            x, y, z = current_ee[0] + x, current_ee[1] + y, current_ee[2] + z
        previously_tried = _fact_to_dict(self._validator.recall_pose([x, y, z]))
        orientation_quat = None
        if roll_deg is not None and pitch_deg is not None and yaw_deg is not None:
            orientation_quat = self._adapter.euler_deg_to_quaternion(roll_deg, pitch_deg, yaw_deg)
        target_angles_deg = self._adapter.calculate_ik_deg([x, y, z], orientation_quat)
        candidate = {
            joint_id: self._validator.clamp_to_joint_limits(joint_id, target_deg)
            for joint_id, target_deg in zip(self._adapter.movable_joints, target_angles_deg)
        }
        try:
            self._validator.validate_or_raise(candidate, requested_position=[x, y, z])
        except ValueError as exc:
            return False, str(exc), previously_tried
        return True, None, previously_tried

    def preview_candidates(
        self, candidates: List[Dict[str, Optional[float]]]
    ) -> List[Tuple[bool, Optional[str], Optional[Dict]]]:
        """Caller must hold the adapter's lock."""
        return [self.preview_move_to_pose(**candidate) for candidate in candidates]

    def preview_pose_toward_limit(
        self,
        x: float,
        y: float,
        z: float,
        roll_deg: Optional[float] = None,
        pitch_deg: Optional[float] = None,
        yaw_deg: Optional[float] = None,
    ) -> Tuple[bool, Optional[str], Optional[List[float]]]:
        """Finds the farthest point reachable along the direction from the
        base toward (x, y, z), via server-side binary search — instead of
        the caller guessing points and checking each with
        preview_move_to_pose. (x, y, z) is a direction, not necessarily
        itself reachable (or even within the reach envelope at all).
        Caller must hold the adapter's lock."""
        magnitude = (x * x + y * y + z * z) ** 0.5
        if magnitude < 1e-6:
            return False, "direction is degenerate (too close to the base to define a direction)", None
        unit = [x / magnitude, y / magnitude, z / magnitude]
        _reach_min, reach_max = self._adapter.estimate_reach_envelope_m()

        orientation_quat = None
        if roll_deg is not None and pitch_deg is not None and yaw_deg is not None:
            orientation_quat = self._adapter.euler_deg_to_quaternion(roll_deg, pitch_deg, yaw_deg)

        def try_scale(scale: float) -> Optional[List[float]]:
            point = [unit[i] * scale for i in range(3)]
            target_angles_deg = self._adapter.calculate_ik_deg(point, orientation_quat)
            candidate = {
                joint_id: self._validator.clamp_to_joint_limits(joint_id, target_deg)
                for joint_id, target_deg in zip(self._adapter.movable_joints, target_angles_deg)
            }
            try:
                self._validator.validate_or_raise(candidate, requested_position=point, record=False)
                return point
            except ValueError:
                return None

        # Coarse scan from the far end inward: the first hit is the true
        # outer boundary, regardless of any unreachable dip closer to the
        # base (see constants.py for why that dip rules out a plain
        # binary search from 0).
        samples = [reach_max * i / POSE_TOWARD_LIMIT_COARSE_STEPS for i in range(POSE_TOWARD_LIMIT_COARSE_STEPS, -1, -1)]
        best_point: Optional[List[float]] = None
        best_scale = 0.0
        upper_bound = reach_max
        for idx, scale in enumerate(samples):
            point = try_scale(scale)
            if point is not None:
                best_point = point
                best_scale = scale
                upper_bound = samples[idx - 1] if idx > 0 else reach_max
                break

        if best_point is None:
            return False, "no reachable point found along that direction", None

        lo, hi = best_scale, upper_bound
        for _ in range(POSE_TOWARD_LIMIT_REFINE_ITERATIONS):
            mid = (lo + hi) / 2
            point = try_scale(mid)
            if point is not None:
                best_point = point
                lo = mid
            else:
                hi = mid

        return True, None, best_point
