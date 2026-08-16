"""Whole-arm safety routes: emergency stop, reset."""

from typing import Optional

from fastapi import APIRouter

from ..arm_service import ArmService
from ..schemas import ActionResponse, StopRequest


def build_router(service: ArmService) -> APIRouter:
    router = APIRouter()

    @router.post("/stop", response_model=ActionResponse)
    def stop(req: Optional[StopRequest] = None) -> ActionResponse:
        joint_ids = req.joint_ids if req is not None else None
        service.stop(joint_ids)
        if joint_ids:
            return ActionResponse(ok=True, message=f"motion stopped for joints {joint_ids}; holding current position")
        return ActionResponse(ok=True, message="motion stopped; all joints holding current position")

    @router.post("/reset", response_model=ActionResponse)
    def reset() -> ActionResponse:
        service.reset()
        return ActionResponse(ok=True, message="simulation reset")

    return router
