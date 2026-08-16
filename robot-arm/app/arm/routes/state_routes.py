"""Read/telemetry routes: health, current state, wait-for-target."""

from fastapi import APIRouter

from ..arm_service import ArmService
from ..schemas import HealthResponse, StateResponse, WaitReachedRequest, WaitReachedResponse
from ..support.presenters import build_joint_states


def build_router(service: ArmService) -> APIRouter:
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(ok=True)

    @router.get("/state", response_model=StateResponse)
    def state() -> StateResponse:
        joints, ee_position, targets = service.get_state()
        return StateResponse(joints=build_joint_states(service, joints, targets), end_effector_position=ee_position)

    @router.post("/wait_reached", response_model=WaitReachedResponse)
    def wait_reached(req: WaitReachedRequest) -> WaitReachedResponse:
        reached, timed_out, joints, targets = service.wait_reached(req.joint_ids, req.timeout_s)
        return WaitReachedResponse(reached=reached, timed_out=timed_out, joints=build_joint_states(service, joints, targets))

    return router
