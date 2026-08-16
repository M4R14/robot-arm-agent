"""End-effector axis-triad geometry, overlay text/color, and the
new-error flash effect. Pure logic plus the one PyBullet math call
(`getMatrixFromQuaternion`) needed for the axis triad — nothing here
assumes a particular update rate; the caller decides how often to redraw.
"""

from typing import List, Optional, Tuple

import pybullet as p

AXIS_LENGTH_M = 0.08
ERROR_FLASH_DURATION_S = 1.5
ERROR_FLASH_BLINK_S = 0.15
STALE_AFTER_S = 1.0
REJECTED_HISTORY_SHOWN = 3  # most recent entries shown, out of sim's full REJECTED_HISTORY_MAX (10)


def axis_endpoints(position: List[float], orientation_quat: List[float], length: float = AXIS_LENGTH_M) -> List[List[float]]:
    """World-space endpoints of the local X/Y/Z axes at `position`, rotated
    by `orientation_quat`. PyBullet has no direct quaternion-rotate-vector
    call, but the rotation matrix's columns are exactly the rotated basis
    vectors."""
    m = p.getMatrixFromQuaternion(orientation_quat)
    x_axis, y_axis, z_axis = (m[0], m[3], m[6]), (m[1], m[4], m[7]), (m[2], m[5], m[8])
    return [[position[i] + length * axis[i] for i in range(3)] for axis in (x_axis, y_axis, z_axis)]


class ErrorFlashTracker:
    """Detects when the last-seen error_code changes and reports whether
    we're still within the flash window for it."""

    def __init__(self) -> None:
        self._last_seen_error_code: Optional[str] = None
        self._flash_start = 0.0

    def update(self, error_code: Optional[str], now: float) -> bool:
        """Call once per check; returns whether we're currently flashing."""
        if error_code != self._last_seen_error_code:
            self._last_seen_error_code = error_code
            self._flash_start = now
        return error_code is not None and (now - self._flash_start) < ERROR_FLASH_DURATION_S

    def blink_on(self, now: float) -> bool:
        return int((now - self._flash_start) / ERROR_FLASH_BLINK_S) % 2 == 0


def build_overlay_text(
    summary: str,
    grip_force: float,
    fps: float,
    stream_age_s: Optional[float],
    last_error: Optional[dict],
    rejected_history: Optional[List[dict]] = None,
) -> Tuple[str, bool]:
    """Returns (text, stale). `rejected_history` is sim's full recent
    list (newest last, per /rejected_history) — only the most recent
    REJECTED_HISTORY_SHOWN are rendered, so this doesn't grow the
    overlay unboundedly even though sim itself keeps up to 10."""
    stale = stream_age_s is not None and stream_age_s > STALE_AFTER_S
    stream_age_str = f"{stream_age_s * 1000:.0f}ms" if stream_age_s is not None else "n/a"
    lines = [
        f"STALE ({stream_age_s:.1f}s since last update)" if stale else summary,
        f"grip force: {grip_force:.0f}   render: {fps:.0f} fps   stream age: {stream_age_str}",
    ]
    if last_error:
        lines.append(f"last error: {last_error['error_code']}")
    if rejected_history:
        recent = rejected_history[-REJECTED_HISTORY_SHOWN:]
        lines.append(f"recent rejections ({len(rejected_history)} total):")
        lines.extend(f"  {entry['error_code']}" for entry in recent)
    return "\n".join(lines), stale


def overlay_color(stale: bool, has_error: bool, flashing: bool, blink_on: bool) -> List[float]:
    if flashing:
        return [1, 1, 0] if blink_on else [1, 0.3, 0.3]
    if stale or has_error:
        return [1, 0.3, 0.3]
    return [1, 1, 1]
