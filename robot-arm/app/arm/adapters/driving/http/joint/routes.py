"""Single- and multi-joint move routes, plus their dry-run preview."""

from fastapi import APIRouter, Depends

from app.arm.adapters.driving.http.common_schemas import ActionResponse, PreviewResponse
from app.arm.adapters.driving.http.dependencies import get_service
from app.arm.adapters.driving.http.error_mapping import raise_http
from app.arm.adapters.driving.http.idempotency import with_idempotency
from app.arm.adapters.driving.http.joint.schemas import MoveJointRequest, MoveJointsRequest, PreviewMoveJointRequest
from app.arm.application.arm_service import ArmService
from app.arm.domain.exceptions import JointOutOfRangeError, NearSingularityError, RateLimitedError, SelfCollisionError

router = APIRouter()


@router.post("/move_joint", response_model=ActionResponse)
def move_joint(req: MoveJointRequest, service: ArmService = Depends(get_service)) -> ActionResponse:
    def build() -> ActionResponse:
        try:
            clamped_deg = service.move_joint(req.joint_id, req.target_angle_deg, req.relative)
        except JointOutOfRangeError as exc:
            raise_http(exc, 400)
        except (SelfCollisionError, NearSingularityError) as exc:
            raise_http(exc, 400)
        except RateLimitedError as exc:
            raise_http(exc, 429)
        return ActionResponse(ok=True, message=f"joint {req.joint_id} target set to {clamped_deg:.2f} deg")

    return with_idempotency(service, req.command_id, ActionResponse, build)


@router.post("/move_joints", response_model=ActionResponse)
def move_joints(req: MoveJointsRequest, service: ArmService = Depends(get_service)) -> ActionResponse:
    def build() -> ActionResponse:
        try:
            clamped = service.move_joints([(t.joint_id, t.target_angle_deg) for t in req.targets], req.relative)
        except JointOutOfRangeError as exc:
            raise_http(exc, 400)
        except (SelfCollisionError, NearSingularityError) as exc:
            raise_http(exc, 400)
        except RateLimitedError as exc:
            raise_http(exc, 429)
        summary = ", ".join(f"{jid}:{deg:.2f}" for jid, deg in clamped.items())
        return ActionResponse(ok=True, message=f"joints set to [{summary}] deg")

    return with_idempotency(service, req.command_id, ActionResponse, build)


@router.post("/preview_move_joint", response_model=PreviewResponse)
def preview_move_joint(req: PreviewMoveJointRequest, service: ArmService = Depends(get_service)) -> PreviewResponse:
    ok, reason = service.preview_move_joint(req.joint_id, req.target_angle_deg, req.relative)
    return PreviewResponse(ok=ok, reason=reason)
