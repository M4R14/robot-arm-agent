"""Single- and multi-joint move routes, plus their dry-run preview."""

from fastapi import APIRouter

from ..arm_service import ArmService
from ..schemas import ActionResponse, MoveJointRequest, MoveJointsRequest, PreviewMoveJointRequest, PreviewResponse
from ..support.error_mapping import raise_http
from ..support.exceptions import JointOutOfRangeError, NearSingularityError, RateLimitedError, SelfCollisionError
from ..support.idempotency import with_idempotency


def build_router(service: ArmService) -> APIRouter:
    router = APIRouter()

    @router.post("/move_joint", response_model=ActionResponse)
    def move_joint(req: MoveJointRequest) -> ActionResponse:
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
    def move_joints(req: MoveJointsRequest) -> ActionResponse:
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
    def preview_move_joint(req: PreviewMoveJointRequest) -> PreviewResponse:
        ok, reason = service.preview_move_joint(req.joint_id, req.target_angle_deg, req.relative)
        return PreviewResponse(ok=ok, reason=reason)

    return router
