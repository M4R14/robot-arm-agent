"""Schemas genuinely shared across more than one domain — everything
else lives in its own domains/<name>/schemas.py. A type only belongs
here if moving it into a single domain would force the other domains
that use it to import across domain boundaries for something that isn't
really "theirs" (e.g. PoseTarget is the shape of a pose, used by pose,
trajectory, and macro alike — no single one of those owns the concept).
"""

from typing import Optional

from pydantic import BaseModel


class ActionResponse(BaseModel):
    ok: bool
    message: str


class PoseTarget(BaseModel):
    x: float
    y: float
    z: float
    roll_deg: Optional[float] = None
    pitch_deg: Optional[float] = None
    yaw_deg: Optional[float] = None


class PreviouslyTried(BaseModel):
    outcome: str
    error_code: Optional[str] = None
    recorded_at: float


class PreviewResponse(BaseModel):
    ok: bool
    reason: Optional[str] = None
    previously_tried: Optional[PreviouslyTried] = None
