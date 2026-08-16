from typing import List, Optional

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


class StateResponse(BaseModel):
    joints: List[JointState]
    end_effector_position: List[float]


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
    command_id: Optional[str] = None


class MoveJointsRequest(BaseModel):
    targets: List[JointTarget]
    command_id: Optional[str] = None


class MoveToPoseRequest(PoseTarget):
    command_id: Optional[str] = None


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


class PreviewMoveToPoseRequest(PoseTarget):
    pass


class PreviewResponse(BaseModel):
    ok: bool
    reason: Optional[str] = None


class ActionResponse(BaseModel):
    ok: bool
    message: str
