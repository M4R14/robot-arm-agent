"""Persists pose-validation outcomes across sim restarts, keyed by
URDF_PATH — see constants.py for why this is a deliberate exception to
sim's otherwise fully ephemeral state. A flat JSON file is enough: this
is a rough "have I basically tried around here before" cache, not a
precision store, and entries beyond POSE_MEMORY_MAX_FACTS are evicted
oldest-first.

Not thread-safe on its own — callers (MotionValidator, ArmService) must
hold their own lock around calls, same as everything touching shared sim
state.
"""

import json
import math
import os
import time
from dataclasses import asdict, dataclass
from typing import List, Optional

from ..constants import POSE_MEMORY_LOOKUP_RADIUS_M, POSE_MEMORY_MAX_FACTS, POSE_MEMORY_PATH, URDF_PATH


@dataclass
class PoseFact:
    x: float
    y: float
    z: float
    outcome: str  # "ok" | "rejected"
    error_code: Optional[str]
    recorded_at: float  # unix timestamp


class PoseMemory:
    def __init__(self, path: str = POSE_MEMORY_PATH) -> None:
        self._path = path
        self._facts: List[PoseFact] = []
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, "r") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._facts = []
            return
        if data.get("urdf_path") != URDF_PATH:
            self._facts = []  # different model loaded since these facts were recorded — discard
            return
        self._facts = [PoseFact(**entry) for entry in data.get("facts", [])]

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w") as f:
                json.dump({"urdf_path": URDF_PATH, "facts": [asdict(fact) for fact in self._facts]}, f)
        except OSError as exc:
            print(f"pose memory: failed to persist ({exc}); continuing in-memory only for this run")

    def record(self, position: List[float], outcome: str, error_code: Optional[str]) -> None:
        self._facts.append(
            PoseFact(x=position[0], y=position[1], z=position[2], outcome=outcome, error_code=error_code, recorded_at=time.time())
        )
        if len(self._facts) > POSE_MEMORY_MAX_FACTS:
            self._facts.pop(0)
        self._save()

    def lookup_near(self, position: List[float], radius_m: float = POSE_MEMORY_LOOKUP_RADIUS_M) -> Optional[PoseFact]:
        best: Optional[PoseFact] = None
        best_distance = radius_m
        for fact in self._facts:
            d = math.sqrt((fact.x - position[0]) ** 2 + (fact.y - position[1]) ** 2 + (fact.z - position[2]) ** 2)
            if d <= best_distance:
                best = fact
                best_distance = d
        return best
