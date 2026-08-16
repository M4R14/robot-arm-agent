"""Domain errors raised by arm command validation. Each carries a stable
`error_code` the HTTP layer maps onto a response body, so the caller gets
a machine-readable reason instead of having to parse a string. Errors
that have actionable structured data beyond the message (e.g. a
suggested alternative target) expose it via `details`, which the HTTP
layer merges into the response body — new error types can add fields
there without touching the HTTP layer.
"""

from typing import Any, Dict, List


class JointOutOfRangeError(ValueError):
    error_code = "JOINT_OUT_OF_RANGE"

    def __init__(self, joint_id: int, valid_joints: List[int]) -> None:
        super().__init__(f"joint_id must be one of {valid_joints}")
        self.joint_id = joint_id
        self.valid_joints = valid_joints
        self.details: Dict[str, Any] = {}


class UnreachablePoseError(ValueError):
    error_code = "UNREACHABLE_POSE"

    def __init__(self, requested: List[float], achieved: List[float]) -> None:
        super().__init__(
            f"target {requested} is outside the arm's reach (closest achievable ~{achieved})"
        )
        self.requested = requested
        self.achieved = achieved
        self.details: Dict[str, Any] = {"closest_achievable_position": achieved}


class SelfCollisionError(ValueError):
    error_code = "SELF_COLLISION"

    def __init__(self) -> None:
        super().__init__("requested move would cause a self-collision; move rejected")
        self.details: Dict[str, Any] = {}


class NearSingularityError(ValueError):
    error_code = "NEAR_SINGULARITY"

    def __init__(self, condition_number: float) -> None:
        super().__init__(
            f"requested pose is near a kinematic singularity (Jacobian condition {condition_number:.1f}); move rejected"
        )
        self.condition_number = condition_number
        self.details: Dict[str, Any] = {}


class RateLimitedError(ValueError):
    error_code = "RATE_LIMITED"

    def __init__(self, retry_after_s: float) -> None:
        super().__init__(f"commands sent too fast; wait {retry_after_s:.3f}s before retrying")
        self.retry_after_s = retry_after_s
        self.details: Dict[str, Any] = {"retry_after_s": retry_after_s}
