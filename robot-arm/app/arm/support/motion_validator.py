"""Validates a candidate joint configuration before it's ever sent to a
motor: clamps to the real per-joint hardware limits, then checks the
resulting pose for reachability, self-collision, and kinematic
singularity. Read-only with respect to the arm's commanded state — never
issues a motor command. That's SynchronizedMotionDriver's job.

Not thread-safe on its own — touches the shared PyBullet client via
`adapter.dry_run`. Callers must hold the same lock the adapter requires.
"""

from typing import Dict, List, Optional

from ..adapters.pybullet_adapter import PyBulletAdapter
from ..constants import (
    IK_REACHABLE_TOLERANCE_M,
    JOINT_ANGLE_MAX_DEG,
    JOINT_ANGLE_MIN_DEG,
    SINGULARITY_CONDITION_THRESHOLD,
)
from .exceptions import NearSingularityError, SelfCollisionError, UnreachablePoseError
from .util import clamp, distance


class MotionValidator:
    def __init__(self, adapter: PyBulletAdapter) -> None:
        self._adapter = adapter

    def clamp_to_joint_limits(self, joint_id: int, target_deg: float) -> float:
        """Clamps to the intersection of the URDF's real per-joint hardware
        limit and the generic safety ceiling — whichever is tighter."""
        urdf_lower, urdf_upper = self._adapter.joint_limits_deg[joint_id]
        lo = max(JOINT_ANGLE_MIN_DEG, urdf_lower)
        hi = min(JOINT_ANGLE_MAX_DEG, urdf_upper)
        return clamp(target_deg, lo, hi)

    def validate_or_raise(
        self, candidate: Dict[int, float], requested_position: Optional[List[float]] = None
    ) -> List[float]:
        achieved_position, collision_free, condition_number = self._adapter.dry_run(candidate)
        if requested_position is not None and distance(achieved_position, requested_position) > IK_REACHABLE_TOLERANCE_M:
            raise UnreachablePoseError(requested_position, achieved_position)
        if not collision_free:
            raise SelfCollisionError()
        if condition_number > SINGULARITY_CONDITION_THRESHOLD:
            raise NearSingularityError(condition_number)
        return achieved_position
