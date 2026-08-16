from typing import Dict, List

from pydantic import BaseModel


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


class ErrorRecoveryHintsResponse(BaseModel):
    hints: Dict[str, str]
