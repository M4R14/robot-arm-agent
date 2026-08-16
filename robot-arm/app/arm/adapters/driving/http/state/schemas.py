from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class HealthResponse(BaseModel):
    ok: bool


class JointState(BaseModel):
    joint_id: int
    angle_deg: float
    velocity_deg_s: float
    applied_torque: float
    target_angle_deg: Optional[float] = None
    reached: bool = True


class LastError(BaseModel):
    error_code: str
    message: str


class StateResponse(BaseModel):
    joints: List[JointState]
    end_effector_position: List[float]
    end_effector_orientation: List[float]
    grip_force: float
    last_error: Optional[LastError] = None
    summary: str


class WaitReachedRequest(BaseModel):
    joint_ids: Optional[List[int]] = None
    timeout_s: Optional[float] = None


class WaitReachedResponse(BaseModel):
    reached: bool
    timed_out: bool
    joints: List[JointState]


class RejectedAttempt(BaseModel):
    error_code: str
    message: str
    details: Dict[str, Any] = {}


class RejectedHistoryResponse(BaseModel):
    entries: List[RejectedAttempt]
