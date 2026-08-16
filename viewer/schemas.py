"""Pydantic schemas for sim's polled wire format (/state + /rejected_history,
merged into one line by sim_exec.py's poll script) and its error line.
Single responsibility: define and validate what comes back over the
docker-exec stream — nothing here touches threads, subprocesses, or the
render loop.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class JointState(BaseModel):
    joint_id: int
    angle_deg: float
    target_angle_deg: Optional[float] = None


class LastError(BaseModel):
    error_code: str
    message: str


class StatePayload(BaseModel):
    """Schema for sim's /state response, mirrored from
    robot-arm/app/arm/schemas.py's StateResponse (sim already validates
    this shape server-side via pydantic; this is the same validation at
    the viewer's boundary, so a shape mismatch fails clearly here instead
    of as a KeyError deep in the render loop)."""

    joints: List[JointState]
    end_effector_position: Optional[List[float]] = None
    end_effector_orientation: Optional[List[float]] = None
    summary: str = ""
    grip_force: float = 0.0
    last_error: Optional[LastError] = None


class RejectedAttempt(BaseModel):
    """Mirrored from robot-arm/app/arm/schemas.py's RejectedAttempt."""

    error_code: str
    message: str
    details: Dict[str, Any] = {}


class PolledPayload(BaseModel):
    """What the poll script (sim_exec.py's build_poll_stream_cmd) prints
    each tick: /state and /rejected_history fetched together, so the
    overlay can show recent rejections without a second stream."""

    state: StatePayload
    rejected_history: List[RejectedAttempt] = []


class StreamError(BaseModel):
    """The `{"error": "..."}` line the injected polling script prints
    when its own request to sim fails (see sim_exec.py) — distinct from
    a PolledPayload, checked first in state_stream.py's line handler."""

    error: str


class JointLimit(BaseModel):
    joint_id: int
    min_deg: float
    max_deg: float


class Capabilities(BaseModel):
    """Schema for sim's /capabilities response — fetched once at
    startup (see sim_exec.fetch_capabilities), not part of the poll
    stream. Only the fields the viewer actually uses are declared;
    pydantic ignores the rest by default."""

    urdf_path: str
    joint_limits: List[JointLimit]
    reach_min_m: float
    reach_max_m: float
