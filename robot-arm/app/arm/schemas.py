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


class PoseTarget(BaseModel):
    x: float
    y: float
    z: float
    roll_deg: Optional[float] = None
    pitch_deg: Optional[float] = None
    yaw_deg: Optional[float] = None


class JointTarget(BaseModel):
    joint_id: int
    target_angle_deg: float


class MoveJointRequest(BaseModel):
    joint_id: int
    target_angle_deg: float
    relative: bool = False
    command_id: Optional[str] = None


class MoveJointsRequest(BaseModel):
    targets: List[JointTarget]
    relative: bool = False
    command_id: Optional[str] = None


class MoveToPoseRequest(PoseTarget):
    relative: bool = False
    command_id: Optional[str] = None


class MoveTrajectoryRequest(BaseModel):
    waypoints: List[PoseTarget]
    command_id: Optional[str] = None


class WaypointResult(BaseModel):
    index: int
    ok: bool
    reached: bool
    reason: Optional[str] = None


class MoveTrajectoryResponse(BaseModel):
    ok: bool
    waypoints: List[WaypointResult]
    message: str


class GripRequest(BaseModel):
    force: float
    command_id: Optional[str] = None


class PickAndPlaceRequest(BaseModel):
    pick: PoseTarget
    place: PoseTarget
    grip_force: float
    command_id: Optional[str] = None


class PickAndPlaceResponse(BaseModel):
    ok: bool
    reached_pick: bool
    reached_place: bool
    message: str


class WaitReachedRequest(BaseModel):
    joint_ids: Optional[List[int]] = None
    timeout_s: Optional[float] = None


class WaitReachedResponse(BaseModel):
    reached: bool
    timed_out: bool
    joints: List[JointState]


class PreviewMoveJointRequest(BaseModel):
    joint_id: int
    target_angle_deg: float
    relative: bool = False


class PreviewMoveToPoseRequest(PoseTarget):
    relative: bool = False


class PreviouslyTried(BaseModel):
    outcome: str
    error_code: Optional[str] = None
    recorded_at: float


class PreviewResponse(BaseModel):
    ok: bool
    reason: Optional[str] = None
    previously_tried: Optional[PreviouslyTried] = None


class StopRequest(BaseModel):
    joint_ids: Optional[List[int]] = None


class JointLimit(BaseModel):
    joint_id: int
    min_deg: float
    max_deg: float


class CapabilitiesResponse(BaseModel):
    urdf_path: str
    joint_ids: List[int]
    joint_limits: List[JointLimit]
    reach_min_m: float
    reach_max_m: float
    max_force: float
    max_joint_velocity_deg_s: float
    singularity_condition_threshold: float
    ik_reachable_tolerance_m: float
    min_command_interval_s: float
    default_wait_timeout_s: float
    max_wait_timeout_s: float
    home_pose_deg: Dict[int, float]


class RejectedAttempt(BaseModel):
    error_code: str
    message: str
    details: Dict[str, Any] = {}


class RejectedHistoryResponse(BaseModel):
    entries: List[RejectedAttempt]


class ErrorRecoveryHintsResponse(BaseModel):
    hints: Dict[str, str]


class PreviewCandidatesRequest(BaseModel):
    candidates: List[PoseTarget]


class PreviewCandidateResult(BaseModel):
    index: int
    ok: bool
    reason: Optional[str] = None
    previously_tried: Optional[PreviouslyTried] = None


class PreviewCandidatesResponse(BaseModel):
    results: List[PreviewCandidateResult]


class ActionResponse(BaseModel):
    ok: bool
    message: str
