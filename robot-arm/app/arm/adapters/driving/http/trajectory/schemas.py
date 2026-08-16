from typing import List, Optional

from pydantic import BaseModel

from app.arm.adapters.driving.http.common_schemas import PoseTarget


class MoveTrajectoryRequest(BaseModel):
    waypoints: List[PoseTarget]
    command_id: Optional[str] = None


class WaypointResult(BaseModel):
    index: int
    ok: bool
    reached: bool
    reason: Optional[str] = None


class MoveTrajectoryResponse(BaseModel):
    ok: bool
    waypoints: List[WaypointResult]
    message: str
