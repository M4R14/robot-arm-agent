"""Per-joint hardware-limit proximity, and the color that represents it.
Single responsibility: pure math (given a current angle and a limit
range, how close is it, and what color should that be) — watch-arm.py
decides when/how often to apply the color to the actual robot geometry.
"""

import math
from typing import Dict, List, Tuple

from viewer.schemas import JointLimit

# Below this fraction of the way to a limit, joints render at their
# normal color — no point flashing "warning" colors for routine motion
# that's nowhere near a real constraint.
WARNING_THRESHOLD = 0.7

NORMAL_COLOR = (1.0, 1.0, 1.0)
WARNING_COLOR = (1.0, 0.8, 0.0)
AT_LIMIT_COLOR = (1.0, 0.15, 0.15)


def proximity_fraction(angle_deg: float, limit: JointLimit) -> float:
    """0.0 at the center of the joint's range, 1.0 exactly at either
    limit. Used to drive the warning color, not clamped beyond [0, 1]
    since a genuinely out-of-range angle (shouldn't happen — sim clamps
    server-side) should still read as "at the limit", not overflow."""
    center = (limit.min_deg + limit.max_deg) / 2
    half_range = (limit.max_deg - limit.min_deg) / 2
    if half_range <= 0:
        return 0.0
    return min(1.0, abs(angle_deg - center) / half_range)


def limit_color(fraction: float) -> Tuple[float, float, float]:
    """Blends normal -> warning -> at-limit as `fraction` approaches 1.0.
    Flat (no blend) below WARNING_THRESHOLD so ordinary motion doesn't
    tint the arm at all."""
    if fraction < WARNING_THRESHOLD:
        return NORMAL_COLOR
    # Renormalize [WARNING_THRESHOLD, 1.0] -> [0, 1] for the blend.
    t = (fraction - WARNING_THRESHOLD) / (1.0 - WARNING_THRESHOLD)
    if t < 0.5:
        blend = t / 0.5
        a, b = NORMAL_COLOR, WARNING_COLOR
    else:
        blend = (t - 0.5) / 0.5
        a, b = WARNING_COLOR, AT_LIMIT_COLOR
    return tuple(a[i] + (b[i] - a[i]) * blend for i in range(3))


def joint_colors(angles_deg: Dict[int, float], limits: List[JointLimit]) -> Dict[int, Tuple[float, float, float]]:
    """angles_deg is keyed by joint_id, in degrees (angles_rad in
    StateSnapshot needs converting by the caller — kept out of this
    module so it stays pure geometry/color math, no unit-conversion
    concerns)."""
    limits_by_id = {limit.joint_id: limit for limit in limits}
    colors = {}
    for joint_id, angle_deg in angles_deg.items():
        limit = limits_by_id.get(joint_id)
        if limit is None:
            continue
        colors[joint_id] = limit_color(proximity_fraction(angle_deg, limit))
    return colors


def radians_to_degrees(angles_rad: Dict[int, float]) -> Dict[int, float]:
    return {joint_id: math.degrees(rad) for joint_id, rad in angles_rad.items()}
