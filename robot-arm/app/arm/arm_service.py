"""Coordinates the robot arm's collaborators — rate limiting, idempotency,
validation, and synchronized motion — around the PyBullet adapter. Owns
the sim lock, the physics stepping thread, and the shared mutable state
(commanded joint targets, grip force, last error). Each collaborator has
one job; this class's job is wiring them together and exposing the
operations the HTTP layer calls. Never trusts caller-supplied ranges.
"""

import threading
import time
from typing import Dict, List, Optional, Tuple

from .adapters.pybullet_adapter import JointAngle, PyBulletAdapter
from .constants import (
    DEFAULT_WAIT_TIMEOUT_S,
    ERROR_RECOVERY_HINTS,
    HOME_POSE_DEG,
    IK_REACHABLE_TOLERANCE_M,
    JOINT_REACHED_TOLERANCE_DEG,
    MAX_FORCE,
    MAX_JOINT_VELOCITY_DEG_S,
    MAX_WAIT_TIMEOUT_S,
    MIN_COMMAND_INTERVAL_S,
    REJECTED_HISTORY_MAX,
    RESET_SETTLE_STEPS,
    SIM_HZ,
    SINGULARITY_CONDITION_THRESHOLD,
    URDF_PATH,
    WAIT_POLL_INTERVAL_S,
)
from .support.exceptions import JointOutOfRangeError
from .support.idempotency_cache import IdempotencyCache
from .support.motion_driver import SynchronizedMotionDriver
from .support.motion_validator import MotionValidator
from .support.rate_limiter import RateLimiter
from .support.util import clamp


class ArmService:
    def __init__(
        self,
        adapter: Optional[PyBulletAdapter] = None,
        rate_limiter: Optional[RateLimiter] = None,
        idempotency_cache: Optional[IdempotencyCache] = None,
        validator: Optional[MotionValidator] = None,
        driver: Optional[SynchronizedMotionDriver] = None,
    ) -> None:
        self._lock = threading.Lock()
        self._adapter = adapter or PyBulletAdapter()
        self._rate_limiter = rate_limiter or RateLimiter()
        self._idempotency_cache = idempotency_cache or IdempotencyCache()
        self._validator = validator or MotionValidator(self._adapter)
        self._driver = driver or SynchronizedMotionDriver(self._adapter)
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

    def _note_success(self) -> None:
        with self._lock:
            self._last_error = None

    # --- reads -------------------------------------------------------------

    def get_state(
        self,
    ) -> Tuple[List[JointAngle], List[float], List[float], Dict[int, float], Optional[Dict[str, str]]]:
        with self._lock:
            joints = self._adapter.get_joint_angles_deg()
            ee_position = self._adapter.get_end_effector_position()
            ee_orientation = self._adapter.get_end_effector_orientation()
            targets = dict(self._target_angles_deg)
            last_error = dict(self._last_error) if self._last_error else None
        return joints, ee_position, ee_orientation, targets, last_error

    def is_reached(self, joint_id: int, angle_deg: float, targets: Dict[int, float]) -> bool:
        target = targets.get(joint_id)
        if target is None:
            return True
        return abs(angle_deg - target) <= JOINT_REACHED_TOLERANCE_DEG

    def wait_reached(
        self, joint_ids: Optional[List[int]], timeout_s: Optional[float]
    ) -> Tuple[bool, bool, List[JointAngle], Dict[int, float]]:
        clamped_timeout = clamp(timeout_s if timeout_s is not None else DEFAULT_WAIT_TIMEOUT_S, 0.0, MAX_WAIT_TIMEOUT_S)
        deadline = time.monotonic() + clamped_timeout
        while True:
            joints, _ee_position, _ee_orientation, targets, _last_error = self.get_state()
            relevant = [j for j in joints if joint_ids is None or j.joint_id in joint_ids]
            if all(self.is_reached(j.joint_id, j.angle_deg, targets) for j in relevant):
                return True, False, joints, targets
            if time.monotonic() >= deadline:
                return False, True, joints, targets
            time.sleep(WAIT_POLL_INTERVAL_S)

    def get_capabilities(self) -> Dict:
        with self._lock:
            joint_ids = list(self._adapter.movable_joints)
            joint_limits = [
                {"joint_id": j, "min_deg": lo, "max_deg": hi}
                for j, (lo, hi) in self._adapter.joint_limits_deg.items()
            ]
            reach_min_m, reach_max_m = self._adapter.estimate_reach_envelope_m()
        return {
            "urdf_path": URDF_PATH,
            "joint_ids": joint_ids,
            "joint_limits": joint_limits,
            "reach_min_m": reach_min_m,
            "reach_max_m": reach_max_m,
            "max_force": MAX_FORCE,
            "max_joint_velocity_deg_s": MAX_JOINT_VELOCITY_DEG_S,
            "singularity_condition_threshold": SINGULARITY_CONDITION_THRESHOLD,
            "ik_reachable_tolerance_m": IK_REACHABLE_TOLERANCE_M,
            "min_command_interval_s": MIN_COMMAND_INTERVAL_S,
            "default_wait_timeout_s": DEFAULT_WAIT_TIMEOUT_S,
            "max_wait_timeout_s": MAX_WAIT_TIMEOUT_S,
            "home_pose_deg": dict(HOME_POSE_DEG),
        }

    def get_rejected_history(self) -> List[Dict]:
        with self._lock:
            return [dict(entry) for entry in self._rejected_history]

    def get_error_recovery_hints(self) -> Dict[str, str]:
        return dict(ERROR_RECOVERY_HINTS)

    def preview_candidates(self, candidates: List[Dict[str, Optional[float]]]) -> List[Tuple[bool, Optional[str]]]:
        return [self.preview_move_to_pose(**candidate) for candidate in candidates]

    # --- move_joint ----------------------------------------------------------

    def _move_joint_locked(self, joint_id: int, target_angle_deg: float, relative: bool = False) -> float:
        if joint_id not in self._adapter.movable_joints:
            raise JointOutOfRangeError(joint_id, self._adapter.movable_joints)
        if relative:
            current_deg = next(j.angle_deg for j in self._adapter.get_joint_angles_deg() if j.joint_id == joint_id)
            target_angle_deg = current_deg + target_angle_deg
        clamped_deg = self._validator.clamp_to_joint_limits(joint_id, target_angle_deg)
        candidate = {j.joint_id: j.angle_deg for j in self._adapter.get_joint_angles_deg()}
        candidate[joint_id] = clamped_deg
        self._validator.validate_or_raise(candidate)
        self._adapter.set_joint_target_deg(joint_id, clamped_deg)
        self._target_angles_deg[joint_id] = clamped_deg
        return clamped_deg

    def move_joint(self, joint_id: int, target_angle_deg: float, relative: bool = False) -> float:
        try:
            with self._lock:
                self._rate_limiter.check()
                result = self._move_joint_locked(joint_id, target_angle_deg, relative)
        except Exception as exc:
            self._note_error(exc)
            raise
        self._note_success()
        return result

    def preview_move_joint(
        self, joint_id: int, target_angle_deg: float, relative: bool = False
    ) -> Tuple[bool, Optional[str]]:
        with self._lock:
            if joint_id not in self._adapter.movable_joints:
                return False, str(JointOutOfRangeError(joint_id, self._adapter.movable_joints))
            if relative:
                current_deg = next(j.angle_deg for j in self._adapter.get_joint_angles_deg() if j.joint_id == joint_id)
                target_angle_deg = current_deg + target_angle_deg
            clamped_deg = self._validator.clamp_to_joint_limits(joint_id, target_angle_deg)
            candidate = {j.joint_id: j.angle_deg for j in self._adapter.get_joint_angles_deg()}
            candidate[joint_id] = clamped_deg
            try:
                self._validator.validate_or_raise(candidate)
            except ValueError as exc:
                return False, str(exc)
        return True, None

    # --- move_joints (batch) --------------------------------------------------

    def move_joints(self, targets: List[Tuple[int, float]], relative: bool = False) -> Dict[int, float]:
        try:
            with self._lock:
                self._rate_limiter.check()
                current_angles_deg = {j.joint_id: j.angle_deg for j in self._adapter.get_joint_angles_deg()}
                candidate = dict(current_angles_deg)
                for joint_id, target_deg in targets:
                    if joint_id not in self._adapter.movable_joints:
                        raise JointOutOfRangeError(joint_id, self._adapter.movable_joints)
                    effective_deg = current_angles_deg[joint_id] + target_deg if relative else target_deg
                    candidate[joint_id] = self._validator.clamp_to_joint_limits(joint_id, effective_deg)

                self._validator.validate_or_raise(candidate)

                moved_only = {joint_id: candidate[joint_id] for joint_id, _ in targets}
                self._driver.drive(moved_only, current_angles_deg, self._target_angles_deg)
        except Exception as exc:
            self._note_error(exc)
            raise
        self._note_success()
        return moved_only

    # --- move_to_pose ----------------------------------------------------------

    def _move_to_pose_locked(
        self,
        x: float,
        y: float,
        z: float,
        roll_deg: Optional[float] = None,
        pitch_deg: Optional[float] = None,
        yaw_deg: Optional[float] = None,
        relative: bool = False,
    ) -> None:
        if relative:
            current_ee = self._adapter.get_end_effector_position()
            x, y, z = current_ee[0] + x, current_ee[1] + y, current_ee[2] + z

        orientation_quat = None
        if roll_deg is not None and pitch_deg is not None and yaw_deg is not None:
            orientation_quat = self._adapter.euler_deg_to_quaternion(roll_deg, pitch_deg, yaw_deg)

        current_angles_deg = {j.joint_id: j.angle_deg for j in self._adapter.get_joint_angles_deg()}
        target_angles_deg = self._adapter.calculate_ik_deg([x, y, z], orientation_quat)
        candidate = {
            joint_id: self._validator.clamp_to_joint_limits(joint_id, target_deg)
            for joint_id, target_deg in zip(self._adapter.movable_joints, target_angles_deg)
        }
        self._validator.validate_or_raise(candidate, requested_position=[x, y, z])
        self._driver.drive(candidate, current_angles_deg, self._target_angles_deg)

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
                self._move_to_pose_locked(x, y, z, roll_deg, pitch_deg, yaw_deg, relative)
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
    ) -> Tuple[bool, Optional[str]]:
        with self._lock:
            if relative:
                current_ee = self._adapter.get_end_effector_position()
                x, y, z = current_ee[0] + x, current_ee[1] + y, current_ee[2] + z
            orientation_quat = None
            if roll_deg is not None and pitch_deg is not None and yaw_deg is not None:
                orientation_quat = self._adapter.euler_deg_to_quaternion(roll_deg, pitch_deg, yaw_deg)
            target_angles_deg = self._adapter.calculate_ik_deg([x, y, z], orientation_quat)
            candidate = {
                joint_id: self._validator.clamp_to_joint_limits(joint_id, target_deg)
                for joint_id, target_deg in zip(self._adapter.movable_joints, target_angles_deg)
            }
            try:
                self._validator.validate_or_raise(candidate, requested_position=[x, y, z])
            except ValueError as exc:
                return False, str(exc)
        return True, None

    # --- move_trajectory (sequential waypoints) ---------------------------------

    def move_trajectory(self, waypoints: List[Dict[str, Optional[float]]]) -> List[Dict]:
        results: List[Dict] = []
        all_ok = True
        for index, waypoint in enumerate(waypoints):
            try:
                with self._lock:
                    self._rate_limiter.check()
                    self._move_to_pose_locked(**waypoint)
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

    # --- pick_and_place (macro) ------------------------------------------------

    def pick_and_place(
        self, pick: Dict[str, Optional[float]], place: Dict[str, Optional[float]], grip_force: float
    ) -> Dict[str, bool]:
        try:
            with self._lock:
                self._rate_limiter.check()
                self._move_to_pose_locked(**pick)
            reached_pick, _timed_out, _joints, _targets = self.wait_reached(None, DEFAULT_WAIT_TIMEOUT_S)

            with self._lock:
                self._grip_locked(grip_force)

            with self._lock:
                self._move_to_pose_locked(**place)
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
