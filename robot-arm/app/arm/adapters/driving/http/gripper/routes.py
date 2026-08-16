"""Gripper force routes."""

from fastapi import APIRouter, Depends

from app.arm.adapters.driving.http.common_schemas import ActionResponse
from app.arm.adapters.driving.http.dependencies import get_service
from app.arm.adapters.driving.http.error_mapping import raise_http
from app.arm.adapters.driving.http.gripper.schemas import GripRequest
from app.arm.adapters.driving.http.idempotency import with_idempotency
from app.arm.application.arm_service import ArmService
from app.arm.domain.exceptions import RateLimitedError

router = APIRouter()


@router.post("/grip", response_model=ActionResponse)
def grip(req: GripRequest, service: ArmService = Depends(get_service)) -> ActionResponse:
    def build() -> ActionResponse:
        try:
            clamped_force = service.grip(req.force)
        except RateLimitedError as exc:
            raise_http(exc, 429)
        return ActionResponse(
            ok=True,
            message=(
                f"grip force set to {clamped_force:.2f} "
                "(no gripper actuator in the current placeholder URDF; value recorded for a future gripper)"
            ),
        )

    return with_idempotency(service, req.command_id, ActionResponse, build)


@router.post("/release", response_model=ActionResponse)
def release(service: ArmService = Depends(get_service)) -> ActionResponse:
    service.grip(0.0)
    return ActionResponse(ok=True, message="gripper released (force set to 0.00)")
