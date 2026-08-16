"""Multi-waypoint end-effector path route. Executes sequentially and stops
at the first waypoint that fails validation, rather than raising an HTTP
error for the whole request — per-waypoint outcome matters more than
all-or-nothing here.
"""

from fastapi import APIRouter, Depends

from ..arm_service import ArmService
from ..dependencies import get_service
from ..schemas import MoveTrajectoryRequest, MoveTrajectoryResponse, WaypointResult
from ..support.idempotency import with_idempotency

router = APIRouter()


@router.post("/move_trajectory", response_model=MoveTrajectoryResponse)
def move_trajectory(req: MoveTrajectoryRequest, service: ArmService = Depends(get_service)) -> MoveTrajectoryResponse:
    def build() -> MoveTrajectoryResponse:
        results = service.move_trajectory([wp.model_dump() for wp in req.waypoints])
        waypoint_results = [WaypointResult(**r) for r in results]
        ok = all(r.ok for r in waypoint_results)
        completed = len(waypoint_results)
        message = (
            f"trajectory complete: {completed}/{len(req.waypoints)} waypoint(s) executed"
            if ok
            else f"trajectory stopped at waypoint {completed - 1}: {waypoint_results[-1].reason}"
        )
        return MoveTrajectoryResponse(ok=ok, waypoints=waypoint_results, message=message)

    return with_idempotency(service, req.command_id, MoveTrajectoryResponse, build)
