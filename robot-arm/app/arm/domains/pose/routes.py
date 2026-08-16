"""Cartesian end-effector move routes, plus their dry-run preview."""

from fastapi import APIRouter, Depends

from ...arm_service import ArmService
from ...common_schemas import ActionResponse, PreviouslyTried, PreviewResponse
from ...dependencies import get_service
from ...support.error_mapping import raise_http
from ...support.exceptions import NearSingularityError, RateLimitedError, SelfCollisionError, UnreachablePoseError
from ...support.idempotency import with_idempotency
from .schemas import (
    MoveToPoseRequest,
    PoseTowardLimitRequest,
    PoseTowardLimitResponse,
    PreviewCandidatesRequest,
    PreviewCandidatesResponse,
    PreviewCandidateResult,
    PreviewMoveToPoseRequest,
)

router = APIRouter()


@router.post("/move_to_pose", response_model=ActionResponse)
def move_to_pose(req: MoveToPoseRequest, service: ArmService = Depends(get_service)) -> ActionResponse:
    def build() -> ActionResponse:
        try:
            service.move_to_pose(req.x, req.y, req.z, req.roll_deg, req.pitch_deg, req.yaw_deg, req.relative)
        except (UnreachablePoseError, SelfCollisionError, NearSingularityError) as exc:
            raise_http(exc, 400)
        except RateLimitedError as exc:
            raise_http(exc, 429)
        return ActionResponse(ok=True, message=f"moving end effector toward ({req.x}, {req.y}, {req.z})")

    return with_idempotency(service, req.command_id, ActionResponse, build)


@router.post("/preview_move_to_pose", response_model=PreviewResponse)
def preview_move_to_pose(req: PreviewMoveToPoseRequest, service: ArmService = Depends(get_service)) -> PreviewResponse:
    ok, reason, previously_tried = service.preview_move_to_pose(
        req.x, req.y, req.z, req.roll_deg, req.pitch_deg, req.yaw_deg, req.relative
    )
    return PreviewResponse(ok=ok, reason=reason, previously_tried=PreviouslyTried(**previously_tried) if previously_tried else None)


@router.post("/pose_toward_reach_limit", response_model=PoseTowardLimitResponse)
def pose_toward_reach_limit(req: PoseTowardLimitRequest, service: ArmService = Depends(get_service)) -> PoseTowardLimitResponse:
    ok, reason, point = service.preview_pose_toward_limit(req.x, req.y, req.z, req.roll_deg, req.pitch_deg, req.yaw_deg)
    if not ok or point is None:
        return PoseTowardLimitResponse(ok=False, reason=reason)
    distance_m = (point[0] ** 2 + point[1] ** 2 + point[2] ** 2) ** 0.5
    return PoseTowardLimitResponse(ok=True, achieved_x=point[0], achieved_y=point[1], achieved_z=point[2], distance_from_base_m=distance_m)


@router.post("/preview_candidates", response_model=PreviewCandidatesResponse)
def preview_candidates(req: PreviewCandidatesRequest, service: ArmService = Depends(get_service)) -> PreviewCandidatesResponse:
    results = service.preview_candidates([c.model_dump() for c in req.candidates])
    return PreviewCandidatesResponse(
        results=[
            PreviewCandidateResult(
                index=i, ok=ok, reason=reason,
                previously_tried=PreviouslyTried(**previously_tried) if previously_tried else None,
            )
            for i, (ok, reason, previously_tried) in enumerate(results)
        ]
    )
