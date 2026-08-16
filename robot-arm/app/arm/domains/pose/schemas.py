from typing import List, Optional

from pydantic import BaseModel

from ...common_schemas import PoseTarget, PreviouslyTried


class MoveToPoseRequest(PoseTarget):
    relative: bool = False
    command_id: Optional[str] = None


class PreviewMoveToPoseRequest(PoseTarget):
    relative: bool = False


class PoseTowardLimitRequest(PoseTarget):
    pass


class PoseTowardLimitResponse(BaseModel):
    ok: bool
    reason: Optional[str] = None
    achieved_x: Optional[float] = None
    achieved_y: Optional[float] = None
    achieved_z: Optional[float] = None
    distance_from_base_m: Optional[float] = None


class PreviewCandidatesRequest(BaseModel):
    candidates: List[PoseTarget]


class PreviewCandidateResult(BaseModel):
    index: int
    ok: bool
    reason: Optional[str] = None
    previously_tried: Optional[PreviouslyTried] = None


class PreviewCandidatesResponse(BaseModel):
    results: List[PreviewCandidateResult]
