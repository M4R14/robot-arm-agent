"""Validates a candidate joint configuration before it's ever sent to a
motor: clamps to the real per-joint hardware limits, then checks the
resulting pose for reachability, self-collision, and kinematic
singularity. Read-only with respect to the arm's commanded state — never
issues a motor command. That's SynchronizedMotionDriver's job.

Also the single choke point every Cartesian pose passes through (both
real moves and previews), so it's where pose-memory recording happens —
one place to keep it consistent rather than duplicating the record call
at every caller.

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
from .pose_memory import PoseMemory
from .util import clamp, distance


class MotionValidator:
    def __init__(self, adapter: PyBulletAdapter, pose_memory: Optional[PoseMemory] = None) -> None:
        self._adapter = adapter
        self._pose_memory = pose_memory or PoseMemory()

    def clamp_to_joint_limits(self, joint_id: int, target_deg: float) -> float:
        """Clamps to the intersection of the URDF's real per-joint hardware
        limit and the generic safety ceiling — whichever is tighter."""
        urdf_lower, urdf_upper = self._adapter.joint_limits_deg[joint_id]
        lo = max(JOINT_ANGLE_MIN_DEG, urdf_lower)
        hi = min(JOINT_ANGLE_MAX_DEG, urdf_upper)
        return clamp(target_deg, lo, hi)

    def recall_pose(self, position: List[float]):
        return self._pose_memory.lookup_near(position)

    def validate_or_raise(
        self, candidate: Dict[int, float], requested_position: Optional[List[float]] = None
    ) -> List[float]:
        achieved_position, collision_free, condition_number = self._adapter.dry_run(candidate)

        error: Optional[Exception] = None
        if requested_position is not None and distance(achieved_position, requested_position) > IK_REACHABLE_TOLERANCE_M:
            error = UnreachablePoseError(requested_position, achieved_position)
        elif not collision_free:
            error = SelfCollisionError()
        elif condition_number > SINGULARITY_CONDITION_THRESHOLD:
            error = NearSingularityError(condition_number)

        if requested_position is not None:
            self._pose_memory.record(
                requested_position, "rejected" if error else "ok", error.error_code if error else None
            )

        if error is not None:
            raise error
        return achieved_position
