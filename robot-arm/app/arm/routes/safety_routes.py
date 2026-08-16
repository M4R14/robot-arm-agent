"""Whole-arm safety routes: emergency stop, reset."""

from fastapi import APIRouter

from ..arm_service import ArmService
from ..schemas import ActionResponse


def build_router(service: ArmService) -> APIRouter:
    router = APIRouter()

    @router.post("/stop", response_model=ActionResponse)
    def stop() -> ActionResponse:
        service.stop()
        return ActionResponse(ok=True, message="motion stopped; all joints holding current position")

    @router.post("/reset", response_model=ActionResponse)
    def reset() -> ActionResponse:
        service.reset()
        return ActionResponse(ok=True, message="simulation reset")

    return router
