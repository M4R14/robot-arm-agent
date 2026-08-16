"""Read/telemetry routes: health, current state, wait-for-target."""

from fastapi import APIRouter

from ..arm_service import ArmService
from ..schemas import (
    HealthResponse,
    LastError,
    RejectedAttempt,
    RejectedHistoryResponse,
    StateResponse,
    WaitReachedRequest,
    WaitReachedResponse,
)
from ..support.presenters import build_joint_states, build_summary


def build_router(service: ArmService) -> APIRouter:
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(ok=True)

    @router.get("/state", response_model=StateResponse)
    def state() -> StateResponse:
        joints, ee_position, ee_orientation, targets, last_error = service.get_state()
        joint_states = build_joint_states(service, joints, targets)
        return StateResponse(
            joints=joint_states,
            end_effector_position=ee_position,
            end_effector_orientation=ee_orientation,
            grip_force=service.grip_force,
            last_error=LastError(**last_error) if last_error else None,
            summary=build_summary(joint_states, service.grip_force, last_error),
        )

    @router.post("/wait_reached", response_model=WaitReachedResponse)
    def wait_reached(req: WaitReachedRequest) -> WaitReachedResponse:
        reached, timed_out, joints, targets = service.wait_reached(req.joint_ids, req.timeout_s)
        return WaitReachedResponse(reached=reached, timed_out=timed_out, joints=build_joint_states(service, joints, targets))

    @router.get("/rejected_history", response_model=RejectedHistoryResponse)
    def rejected_history() -> RejectedHistoryResponse:
        return RejectedHistoryResponse(entries=[RejectedAttempt(**entry) for entry in service.get_rejected_history()])

    return router
