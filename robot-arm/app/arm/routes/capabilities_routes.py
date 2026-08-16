"""Static arm capabilities — joint limits, safety thresholds, timing
constants — so a caller can plan moves without guessing values that would
otherwise just get silently clamped or rejected.
"""

from fastapi import APIRouter

from ..arm_service import ArmService
from ..schemas import CapabilitiesResponse, JointLimit


def build_router(service: ArmService) -> APIRouter:
    router = APIRouter()

    @router.get("/capabilities", response_model=CapabilitiesResponse)
    def capabilities() -> CapabilitiesResponse:
        data = service.get_capabilities()
        return CapabilitiesResponse(
            urdf_path=data["urdf_path"],
            joint_ids=data["joint_ids"],
            joint_limits=[JointLimit(**jl) for jl in data["joint_limits"]],
            max_force=data["max_force"],
            max_joint_velocity_deg_s=data["max_joint_velocity_deg_s"],
            singularity_condition_threshold=data["singularity_condition_threshold"],
            ik_reachable_tolerance_m=data["ik_reachable_tolerance_m"],
            min_command_interval_s=data["min_command_interval_s"],
            default_wait_timeout_s=data["default_wait_timeout_s"],
            max_wait_timeout_s=data["max_wait_timeout_s"],
            home_pose_deg=data["home_pose_deg"],
        )

    return router
