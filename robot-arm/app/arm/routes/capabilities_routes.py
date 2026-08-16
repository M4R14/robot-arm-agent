"""Static arm capabilities — joint limits, safety thresholds, timing
constants — so a caller can plan moves without guessing values that would
otherwise just get silently clamped or rejected.
"""

from fastapi import APIRouter, Depends

from ..arm_service import ArmService
from ..dependencies import get_service
from ..schemas import CapabilitiesResponse, ErrorRecoveryHintsResponse, JointLimit

router = APIRouter()


@router.get("/capabilities", response_model=CapabilitiesResponse)
def capabilities(service: ArmService = Depends(get_service)) -> CapabilitiesResponse:
    data = service.get_capabilities()
    return CapabilitiesResponse(
        urdf_path=data["urdf_path"],
        joint_ids=data["joint_ids"],
        joint_limits=[JointLimit(**jl) for jl in data["joint_limits"]],
        reach_min_m=data["reach_min_m"],
        reach_max_m=data["reach_max_m"],
        max_force=data["max_force"],
        max_joint_velocity_deg_s=data["max_joint_velocity_deg_s"],
        singularity_condition_threshold=data["singularity_condition_threshold"],
        ik_reachable_tolerance_m=data["ik_reachable_tolerance_m"],
        min_command_interval_s=data["min_command_interval_s"],
        default_wait_timeout_s=data["default_wait_timeout_s"],
        max_wait_timeout_s=data["max_wait_timeout_s"],
        home_pose_deg=data["home_pose_deg"],
    )


@router.get("/error_recovery_hints", response_model=ErrorRecoveryHintsResponse)
def error_recovery_hints(service: ArmService = Depends(get_service)) -> ErrorRecoveryHintsResponse:
    return ErrorRecoveryHintsResponse(hints=service.get_error_recovery_hints())
