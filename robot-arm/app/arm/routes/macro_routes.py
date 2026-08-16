"""Composite multi-step routes."""

from fastapi import APIRouter

from ..arm_service import ArmService
from ..schemas import PickAndPlaceRequest, PickAndPlaceResponse
from ..support.exceptions import NearSingularityError, RateLimitedError, SelfCollisionError, UnreachablePoseError
from ..support.error_mapping import raise_http
from ..support.idempotency import with_idempotency


def build_router(service: ArmService) -> APIRouter:
    router = APIRouter()

    @router.post("/pick_and_place", response_model=PickAndPlaceResponse)
    def pick_and_place(req: PickAndPlaceRequest) -> PickAndPlaceResponse:
        def build() -> PickAndPlaceResponse:
            try:
                result = service.pick_and_place(req.pick.model_dump(), req.place.model_dump(), req.grip_force)
            except (UnreachablePoseError, SelfCollisionError, NearSingularityError) as exc:
                raise_http(exc, 400)
            except RateLimitedError as exc:
                raise_http(exc, 429)
            return PickAndPlaceResponse(
                ok=True,
                reached_pick=result["reached_pick"],
                reached_place=result["reached_place"],
                message="pick-and-place sequence complete",
            )

        return with_idempotency(service, req.command_id, PickAndPlaceResponse, build)

    return router
