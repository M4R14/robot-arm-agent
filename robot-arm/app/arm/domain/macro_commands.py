"""Multi-step orchestration across pose moves and the gripper — currently
just pick-and-place. Unlike JointCommands/PoseCommands (single locked
call, caller holds the lock), a macro's steps need the lock released
between them (waiting for motion to finish takes real time), so this
collaborator takes the lock itself and re-acquires it per step.

Depends only on domain.ports.ArmPhysicsPort (via PoseCommands), plus two
small callables for the pieces it doesn't own: waiting for motion to
finish (ArmService.wait_reached, which reads sim state) and applying grip
force (ArmService._grip_locked, which mutates ArmService.grip_force).
"""

import threading
from typing import Callable, Dict, Optional

from ..constants import DEFAULT_WAIT_TIMEOUT_S
from .pose_commands import PoseCommands
from .rate_limiter import RateLimiter


class MacroCommands:
    def __init__(
        self,
        lock: threading.Lock,
        rate_limiter: RateLimiter,
        pose_commands: PoseCommands,
        wait_reached: Callable,
        grip_locked: Callable[[float], float],
    ) -> None:
        self._lock = lock
        self._rate_limiter = rate_limiter
        self._pose_commands = pose_commands
        self._wait_reached = wait_reached
        self._grip_locked = grip_locked

    def pick_and_place_locked(
        self,
        pick: Dict[str, Optional[float]],
        place: Dict[str, Optional[float]],
        grip_force: float,
        target_angles_deg: Dict[int, float],
    ) -> Dict[str, bool]:
        with self._lock:
            self._rate_limiter.check()
            self._pose_commands.move_to_pose_locked(
                pick.get("x"), pick.get("y"), pick.get("z"),
                pick.get("roll_deg"), pick.get("pitch_deg"), pick.get("yaw_deg"),
                pick.get("relative", False), target_angles_deg,
            )
        reached_pick, _timed_out, _joints, _targets = self._wait_reached(None, DEFAULT_WAIT_TIMEOUT_S)

        with self._lock:
            self._grip_locked(grip_force)

        with self._lock:
            self._pose_commands.move_to_pose_locked(
                place.get("x"), place.get("y"), place.get("z"),
                place.get("roll_deg"), place.get("pitch_deg"), place.get("yaw_deg"),
                place.get("relative", False), target_angles_deg,
            )
        reached_place, _timed_out, _joints, _targets = self._wait_reached(None, DEFAULT_WAIT_TIMEOUT_S)

        with self._lock:
            self._grip_locked(0.0)

        return {"reached_pick": reached_pick, "reached_place": reached_place}
