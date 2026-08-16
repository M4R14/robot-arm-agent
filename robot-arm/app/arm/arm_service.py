"""Coordinates the robot arm's collaborators — rate limiting, idempotency,
validation, joint/pose command logic, state queries, and synchronized
motion — around the PyBullet adapter. Owns the sim lock, the physics
stepping thread, and the shared mutable state (commanded joint targets,
grip force, last error). Each collaborator has one job; this class's job
is wiring them together, applying the rate-limit/lock/error-recording
wrapper every mutating command needs, and exposing the operations the
HTTP layer calls. Never trusts caller-supplied ranges.
"""

import threading
import time
from typing import Dict, List, Optional, Tuple

from loguru import logger

from .adapters.pybullet_adapter import JointAngle, PyBulletAdapter
from .constants import (
    DEFAULT_WAIT_TIMEOUT_S,
    ERROR_RECOVERY_HINTS,
    HOME_POSE_DEG,
    MAX_FORCE,
    REJECTED_HISTORY_MAX,
    RESET_SETTLE_STEPS,
    SIM_HZ,
)
from .support.idempotency_cache import IdempotencyCache
from .support.joint_commands import JointCommands
from .support.metrics import Metrics
from .support.motion_driver import SynchronizedMotionDriver
from .support.motion_validator import MotionValidator
from .support.pose_commands import PoseCommands
from .support.rate_limiter import RateLimiter
from .support.state_queries import StateQueries
from .support.util import clamp


class ArmService:
    def __init__(
        self,
        adapter: Optional[PyBulletAdapter] = None,
        rate_limiter: Optional[RateLimiter] = None,
        idempotency_cache: Optional[IdempotencyCache] = None,
        validator: Optional[MotionValidator] = None,
        driver: Optional[SynchronizedMotionDriver] = None,
        metrics: Optional[Metrics] = None,
    ) -> None:
        self._lock = threading.Lock()
        self._adapter = adapter or PyBulletAdapter()
        self._rate_limiter = rate_limiter or RateLimiter()
        self._idempotency_cache = idempotency_cache or IdempotencyCache()
        self._validator = validator or MotionValidator(self._adapter)
        self._driver = driver or SynchronizedMotionDriver(self._adapter)
        self._metrics = metrics or Metrics()
        self._joint_commands = JointCommands(self._adapter, self._validator, self._driver)
        self._pose_commands = PoseCommands(self._adapter, self._validator, self._driver)
        self._state_queries = StateQueries(self._lock, self._adapter)
        self._stop_stepping = threading.Event()
        self._target_angles_deg: Dict[int, float] = {}
        self._last_error: Optional[Dict[str, str]] = None
        self._rejected_history: List[Dict] = []
        self.grip_force = 0.0
        self._drive_to_home_pose()

    def _drive_to_home_pose(self) -> None:
        if not HOME_POSE_DEG:
            return
        for joint_id, target_deg in HOME_POSE_DEG.items():
            self._adapter.set_joint_target_deg(joint_id, target_deg)
        for _ in range(RESET_SETTLE_STEPS):
            self._adapter.step()
        self._target_angles_deg = dict(HOME_POSE_DEG)

    def start_stepping(self) -> None:
        threading.Thread(target=self._stepping_loop, daemon=True).start()

    def _stepping_loop(self) -> None:
        while not self._stop_stepping.is_set():
            with self._lock:
                self._adapter.step()
            time.sleep(1.0 / SIM_HZ)

    def shutdown(self) -> None:
        self._stop_stepping.set()
        with self._lock:
            self._adapter.disconnect()

    # --- idempotency (delegated) ------------------------------------------

    def check_idempotent(self, command_id: Optional[str]) -> Optional[dict]:
        return self._idempotency_cache.check(command_id)

    def remember_idempotent(self, command_id: Optional[str], payload: dict) -> None:
        self._idempotency_cache.remember(command_id, payload)

    # --- last-command-error tracking ----------------------------------------
    # Self-locking so they're safe to call from outside any `with self._lock`
    # block (e.g. right after a locked block raises and releases the lock).

    def _note_error(self, exc: Exception) -> None:
        entry = {
            "error_code": getattr(exc, "error_code", "ERROR"),
            "message": str(exc),
            "details": getattr(exc, "details", {}),
        }
        with self._lock:
            self._last_error = {"error_code": entry["error_code"], "message": entry["message"]}
            self._rejected_history.append(entry)
            if len(self._rejected_history) > REJECTED_HISTORY_MAX:
                self._rejected_history.pop(0)
        self._metrics.note_rejected(entry["error_code"])
        logger.warning("command rejected: {} — {}", entry["error_code"], entry["message"])

    def _note_success(self) -> None:
        with self._lock:
            self._last_error = None
        self._metrics.note_accepted()
        logger.debug("command accepted")

    def get_metrics(self) -> Dict:
        return self._metrics.snapshot()

    # --- reads (delegated to StateQueries, plus ArmService's own
    # last_error which StateQueries doesn't know about) ---------------------

    def get_state(
        self,
    ) -> Tuple[List[JointAngle], List[float], List[float], Dict[int, float], Optional[Dict[str, str]]]:
        joints, ee_position, ee_orientation, targets = self._state_queries.read_full_state(self._target_angles_deg)
        with self._lock:
            last_error = dict(self._last_error) if self._last_error else None
        return joints, ee_position, ee_orientation, targets, last_error

    def is_reached(self, joint_id: int, angle_deg: float, targets: Dict[int, float]) -> bool:
        return self._state_queries.is_reached(joint_id, angle_deg, targets)

    def wait_reached(
        self, joint_ids: Optional[List[int]], timeout_s: Optional[float]
    ) -> Tuple[bool, bool, List[JointAngle], Dict[int, float]]:
        return self._state_queries.wait_reached(self._target_angles_deg, joint_ids, timeout_s)

    def get_capabilities(self) -> Dict:
        return self._state_queries.get_capabilities()

    def get_rejected_history(self) -> List[Dict]:
        with self._lock:
            return [dict(entry) for entry in self._rejected_history]

    def get_error_recovery_hints(self) -> Dict[str, str]:
        return dict(ERROR_RECOVERY_HINTS)

    # --- move_joint (delegated to JointCommands) ------------------------------

    def move_joint(self, joint_id: int, target_angle_deg: float, relative: bool = False) -> float:
        try:
            with self._lock:
                self._rate_limiter.check()
                result = self._joint_commands.move_joint_locked(joint_id, target_angle_deg, relative, self._target_angles_deg)
        except Exception as exc:
            self._note_error(exc)
            raise
        self._note_success()
        return result

    def preview_move_joint(
        self, joint_id: int, target_angle_deg: float, relative: bool = False
    ) -> Tuple[bool, Optional[str]]:
        with self._lock:
            return self._joint_commands.preview_move_joint(joint_id, target_angle_deg, relative)

    # --- move_joints (batch, delegated to JointCommands) -----------------------

    def move_joints(self, targets: List[Tuple[int, float]], relative: bool = False) -> Dict[int, float]:
        try:
            with self._lock:
                self._rate_limiter.check()
                result = self._joint_commands.move_joints_locked(targets, relative, self._target_angles_deg)
        except Exception as exc:
            self._note_error(exc)
            raise
        self._note_success()
        return result

    # --- move_to_pose (delegated to PoseCommands) -------------------------------

    def move_to_pose(
        self,
        x: float,
        y: float,
        z: float,
        roll_deg: Optional[float] = None,
        pitch_deg: Optional[float] = None,
        yaw_deg: Optional[float] = None,
        relative: bool = False,
    ) -> None:
        try:
            with self._lock:
                self._rate_limiter.check()
                self._pose_commands.move_to_pose_locked(
                    x, y, z, roll_deg, pitch_deg, yaw_deg, relative, self._target_angles_deg
                )
        except Exception as exc:
            self._note_error(exc)
            raise
        self._note_success()

    def preview_move_to_pose(
        self,
        x: float,
        y: float,
        z: float,
        roll_deg: Optional[float] = None,
        pitch_deg: Optional[float] = None,
        yaw_deg: Optional[float] = None,
        relative: bool = False,
    ) -> Tuple[bool, Optional[str], Optional[Dict]]:
        with self._lock:
            return self._pose_commands.preview_move_to_pose(x, y, z, roll_deg, pitch_deg, yaw_deg, relative)

    def preview_candidates(
        self, candidates: List[Dict[str, Optional[float]]]
    ) -> List[Tuple[bool, Optional[str], Optional[Dict]]]:
        with self._lock:
            return self._pose_commands.preview_candidates(candidates)

    def preview_pose_toward_limit(
        self,
        x: float,
        y: float,
        z: float,
        roll_deg: Optional[float] = None,
        pitch_deg: Optional[float] = None,
        yaw_deg: Optional[float] = None,
    ) -> Tuple[bool, Optional[str], Optional[List[float]]]:
        with self._lock:
            return self._pose_commands.preview_pose_toward_limit(x, y, z, roll_deg, pitch_deg, yaw_deg)

    # --- move_trajectory (sequential waypoints, orchestrates PoseCommands) -----

    def move_trajectory(self, waypoints: List[Dict[str, Optional[float]]]) -> List[Dict]:
        results: List[Dict] = []
        all_ok = True
        for index, waypoint in enumerate(waypoints):
            try:
                with self._lock:
                    self._rate_limiter.check()
                    self._pose_commands.move_to_pose_locked(
                        waypoint.get("x"), waypoint.get("y"), waypoint.get("z"),
                        waypoint.get("roll_deg"), waypoint.get("pitch_deg"), waypoint.get("yaw_deg"),
                        waypoint.get("relative", False), self._target_angles_deg,
                    )
            except Exception as exc:
                self._note_error(exc)
                results.append({"index": index, "ok": False, "reached": False, "reason": str(exc)})
                all_ok = False
                break
            reached, _timed_out, _joints, _targets = self.wait_reached(None, DEFAULT_WAIT_TIMEOUT_S)
            results.append({"index": index, "ok": True, "reached": reached, "reason": None})
        if all_ok:
            self._note_success()
        return results

    # --- grip ----------------------------------------------------------------
    # Trivial enough (clamp + assign) to stay inline rather than its own
    # collaborator — no adapter interaction, single float field.

    def _grip_locked(self, force: float) -> float:
        clamped_force = clamp(force, 0.0, MAX_FORCE)
        self.grip_force = clamped_force
        return clamped_force

    def grip(self, force: float) -> float:
        try:
            with self._lock:
                self._rate_limiter.check()
                result = self._grip_locked(force)
        except Exception as exc:
            self._note_error(exc)
            raise
        self._note_success()
        return result

    # --- pick_and_place (macro, orchestrates PoseCommands + grip) --------------

    def pick_and_place(
        self, pick: Dict[str, Optional[float]], place: Dict[str, Optional[float]], grip_force: float
    ) -> Dict[str, bool]:
        try:
            with self._lock:
                self._rate_limiter.check()
                self._pose_commands.move_to_pose_locked(
                    pick.get("x"), pick.get("y"), pick.get("z"),
                    pick.get("roll_deg"), pick.get("pitch_deg"), pick.get("yaw_deg"),
                    pick.get("relative", False), self._target_angles_deg,
                )
            reached_pick, _timed_out, _joints, _targets = self.wait_reached(None, DEFAULT_WAIT_TIMEOUT_S)

            with self._lock:
                self._grip_locked(grip_force)

            with self._lock:
                self._pose_commands.move_to_pose_locked(
                    place.get("x"), place.get("y"), place.get("z"),
                    place.get("roll_deg"), place.get("pitch_deg"), place.get("yaw_deg"),
                    place.get("relative", False), self._target_angles_deg,
                )
            reached_place, _timed_out, _joints, _targets = self.wait_reached(None, DEFAULT_WAIT_TIMEOUT_S)

            with self._lock:
                self._grip_locked(0.0)
        except Exception as exc:
            self._note_error(exc)
            raise
        self._note_success()
        return {"reached_pick": reached_pick, "reached_place": reached_place}

    # --- stop (emergency, never rate-limited) -----------------------------------

    def stop(self, joint_ids: Optional[List[int]] = None) -> None:
        with self._lock:
            for joint in self._adapter.get_joint_angles_deg():
                if joint_ids is not None and joint.joint_id not in joint_ids:
                    continue
                self._adapter.set_joint_target_deg(joint.joint_id, joint.angle_deg)
                self._target_angles_deg[joint.joint_id] = joint.angle_deg

    # --- reset -----------------------------------------------------------------

    def reset(self) -> None:
        with self._lock:
            self._adapter.load()
            for _ in range(RESET_SETTLE_STEPS):
                self._adapter.step()
            self._target_angles_deg.clear()
            self.grip_force = 0.0
            self._last_error = None
            self._rejected_history.clear()
            self._idempotency_cache.clear()
            self._drive_to_home_pose()
