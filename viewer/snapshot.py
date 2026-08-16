"""The render-loop-facing state shape. Single responsibility: a plain
data holder — StateStream fills it in, watch-arm.py's render loop reads
it. No knowledge of pydantic, subprocesses, or how the data got here.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class StateSnapshot:
    angles_rad: Dict[int, float] = field(default_factory=dict)
    targets_rad: Dict[int, float] = field(default_factory=dict)
    ee_position: Optional[List[float]] = None
    ee_orientation: Optional[List[float]] = None
    summary: str = ""
    grip_force: float = 0.0
    last_error: Optional[dict] = None
    rejected_history: List[dict] = field(default_factory=list)
    updated_at: Optional[float] = None  # time.monotonic() of last update, or None if never updated
