from typing import Optional

from pydantic import BaseModel

from app.arm.adapters.driving.http.common_schemas import PoseTarget


class PickAndPlaceRequest(BaseModel):
    pick: PoseTarget
    place: PoseTarget
    grip_force: float
    command_id: Optional[str] = None


class PickAndPlaceResponse(BaseModel):
    ok: bool
    reached_pick: bool
    reached_place: bool
    message: str
