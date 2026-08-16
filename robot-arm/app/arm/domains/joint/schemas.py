from typing import List, Optional

from pydantic import BaseModel


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


class PreviewMoveJointRequest(BaseModel):
    joint_id: int
    target_angle_deg: float
    relative: bool = False
