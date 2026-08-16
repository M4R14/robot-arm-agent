"""Whole-arm safety routes: emergency stop, reset."""

from typing import Optional

from fastapi import APIRouter, Depends

from app.arm.adapters.driving.http.common_schemas import ActionResponse
from app.arm.adapters.driving.http.dependencies import get_service
from app.arm.adapters.driving.http.safety.schemas import StopRequest
from app.arm.application.arm_service import ArmService

router = APIRouter()


@router.post("/stop", response_model=ActionResponse)
def stop(req: Optional[StopRequest] = None, service: ArmService = Depends(get_service)) -> ActionResponse:
    joint_ids = req.joint_ids if req is not None else None
    service.stop(joint_ids)
    if joint_ids:
        return ActionResponse(ok=True, message=f"motion stopped for joints {joint_ids}; holding current position")
    return ActionResponse(ok=True, message="motion stopped; all joints holding current position")


@router.post("/reset", response_model=ActionResponse)
def reset(service: ArmService = Depends(get_service)) -> ActionResponse:
    service.reset()
    return ActionResponse(ok=True, message="simulation reset")
