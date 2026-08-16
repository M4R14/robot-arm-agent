"""End-effector position trail: a fading breadcrumb of where the arm has
*actually* been recently. Single responsibility: keep the recent-position
buffer — watch-arm.py owns drawing the debug lines from it.

Not a preview of an in-flight move_trajectory's upcoming waypoints —
sim's /state never exposes those (move_trajectory runs the whole
sequence server-side within one blocking HTTP call, so there's nothing
for an external poller to see ahead of time; see SPEC.md §4.3). This is
the achievable alternative: a trail of the actual path already traveled,
which is what's actually observable from outside sim, and still gives a
clear sense of the motion as it happens.
"""

from collections import deque
from dataclasses import dataclass
from typing import List, Optional, Tuple

TRAIL_DURATION_S = 3.0
# Skip near-duplicate points while the arm is nearly still, and bound how
# many segments a fast, continuous move can generate — each segment costs
# one PyBullet debug-line update per redraw (see watch-arm.py's
# replaceItemUniqueId-based reuse), so keeping this coarse enough matters
# for a smooth throttled redraw, not just visual clutter.
TRAIL_MIN_POINT_SPACING_M = 0.015
TRAIL_MAX_SEGMENTS = 60


@dataclass
class TrailPoint:
    position: Tuple[float, float, float]
    timestamp: float


class EndEffectorTrail:
    def __init__(self, duration_s: float = TRAIL_DURATION_S) -> None:
        self._duration_s = duration_s
        self._points: deque = deque()

    def add(self, position: Optional[List[float]], now: float) -> None:
        if position is None:
            return
        if self._points:
            last = self._points[-1].position
            dist = sum((position[i] - last[i]) ** 2 for i in range(3)) ** 0.5
            if dist < TRAIL_MIN_POINT_SPACING_M:
                return
        self._points.append(TrailPoint(position=tuple(position), timestamp=now))
        while self._points and now - self._points[0].timestamp > self._duration_s:
            self._points.popleft()
        while len(self._points) > TRAIL_MAX_SEGMENTS + 1:
            self._points.popleft()

    def segments(self, now: float) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float], float]]:
        """Consecutive point pairs with an alpha (0..1, newer = more
        opaque) for each — the caller draws one line per segment so the
        trail can fade instead of being a single flat-color line."""
        result = []
        points = list(self._points)
        for i in range(1, len(points)):
            age_s = now - points[i].timestamp
            alpha = max(0.0, 1.0 - age_s / self._duration_s)
            result.append((points[i - 1].position, points[i].position, alpha))
        return result
