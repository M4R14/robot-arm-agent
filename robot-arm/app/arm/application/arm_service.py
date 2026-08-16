"""Application/use-case layer (Hexagonal / Ports & Adapters): coordinates
domain collaborators — rate limiting, idempotency, validation, joint/pose
command logic, state queries, and synchronized motion — around the arm
physics port. Owns the sim lock, the physics stepping thread, and the
shared mutable state (commanded joint targets, grip force, last error).
Each collaborator has one job; this class's job is wiring them together
(binding domain ports to concrete driven adapters — the only place that
happens), applying the rate-limit/lock/error-recording wrapper every
mutating command needs, and exposing the operations the HTTP driving
adapter calls. Never trusts caller-supplied ranges.
"""

import threading
from typing import Dict, List, Optional, Tuple

from ..adapters.driven.idempotency_cache import IdempotencyCache
from ..adapters.driven.metrics import Metrics
from ..adapters.driven.pose_memory import PoseMemory
from ..adapters.driven.pybullet_physics_adapter import PyBulletAdapter
from ..constants import DEFAULT_WAIT_TIMEOUT_S, HOME_POSE_DEG, MAX_FORCE, RESET_SETTLE_STEPS
from ..domain.capabilities_queries import CapabilitiesQueries
from ..domain.joint_commands import JointCommands
from ..domain.motion_driver import SynchronizedMotionDriver
from ..domain.motion_validator import MotionValidator
from ..domain.ports import ArmPhysicsPort, JointAngle, PoseMemoryPort
from ..domain.pose_commands import PoseCommands
from ..domain.rate_limiter import RateLimiter
from ..domain.state_queries import StateQueries
from ..domain.stepping_clock import SteppingClock
from ..domain.util import clamp
from .command_outcome_tracker import CommandOutcomeTracker


class ArmService:
    def __init__(
        self,
        adapter: Optional[ArmPhysicsPort] = None,
        rate_limiter: Optional[RateLimiter] = None,
        idempotency_cache: Optional[IdempotencyCache] = None,
        pose_memory: Optional[PoseMemoryPort] = None,
        validator: Optional[MotionValidator] = None,
        driver: Optional[SynchronizedMotionDriver] = None,
        metrics: Optional[Metrics] = None,
    ) -> None:
        self._lock = threading.Lock()
        # Binding domain ports to concrete driven adapters happens here,
        # and only here — nothing under domain/ imports these concrete
        # classes.
        self._adapter = adapter or PyBulletAdapter()
        self._rate_limiter = rate_limiter or RateLimiter()
        self._validator = validator or MotionValidator(self._adapter, pose_memory or PoseMemory())
        self._driver = driver or SynchronizedMotionDriver(self._adapter)
        self._outcome = CommandOutcomeTracker(self._lock, idempotency_cache or IdempotencyCache(), metrics or Metrics())
        self._stepping_clock = SteppingClock(self._lock, self._adapter)
        self._joint_commands = JointCommands(self._adapter, self._validator, self._driver)
        self._pose_commands = PoseCommands(self._adapter, self._validator, self._driver)
        self._state_queries = StateQueries(self._lock, self._adapter)
        self._capabilities_queries = CapabilitiesQueries(self._lock, self._adapter)
        self._target_angles_deg: Dict[int, float] = {}
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
        self._stepping_clock.start()

    def shutdown(self) -> None:
        self._stepping_clock.stop()
        with self._lock:
            self._adapter.disconnect()

    # --- idempotency (delegated) ------------------------------------------

    def check_idempotent(self, command_id: Optional[str]) -> Optional[dict]:
        return self._outcome.check_idempotent(command_id)

    def remember_idempotent(self, command_id: Optional[str], payload: dict) -> None:
        self._outcome.remember_idempotent(command_id, payload)

    def get_metrics(self) -> Dict:
        return self._outcome.get_metrics()

    # --- guarded-command helper -----------------------------------------------
    # Every mutating command needs "acquire lock, check rate limit, run" —
    # this factors that out so each command method states only what it does.
    # Recording success/failure is CommandOutcomeTracker.guarded(); kept
    # separate because a few commands (pick_and_place, move_trajectory) need
    # custom locking — multiple locked sections with unlocked work between
    # them — so they use _outcome.guarded() alone and call
    # _locked_rate_limited() themselves where it fits.

    def _locked_rate_limited(self, fn):
        with self._lock:
            self._rate_limiter.check()
            return fn()

    # --- reads (delegated to StateQueries, plus the outcome tracker's
    # last_error which StateQueries doesn't know about) ---------------------

    def get_state(
        self,
    ) -> Tuple[List[JointAngle], List[float], List[float], Dict[int, float], Optional[Dict[str, str]]]:
        joints, ee_position, ee_orientation, targets = self._state_queries.read_full_state(self._target_angles_deg)
        return joints, ee_position, ee_orientation, targets, self._outcome.get_last_error()

    def is_reached(self, joint_id: int, angle_deg: float, targets: Dict[int, float]) -> bool:
        return self._state_queries.is_reached(joint_id, angle_deg, targets)

    def wait_reached(
        self, joint_ids: Optional[List[int]], timeout_s: Optional[float]
    ) -> Tuple[bool, bool, List[JointAngle], Dict[int, float]]:
        return self._state_queries.wait_reached(self._target_angles_deg, joint_ids, timeout_s)

    def get_capabilities(self) -> Dict:
        return self._capabilities_queries.get_capabilities()

    def get_rejected_history(self) -> List[Dict]:
        return self._outcome.get_rejected_history()

    def get_error_recovery_hints(self) -> Dict[str, str]:
        return self._outcome.get_error_recovery_hints()

    # --- move_joint (delegated to JointCommands) ------------------------------

    def move_joint(self, joint_id: int, target_angle_deg: float, relative: bool = False) -> float:
        return self._outcome.guarded(
            lambda: self._locked_rate_limited(
                lambda: self._joint_commands.move_joint_locked(joint_id, target_angle_deg, relative, self._target_angles_deg)
            )
        )

    def preview_move_joint(
        self, joint_id: int, target_angle_deg: float, relative: bool = False
    ) -> Tuple[bool, Optional[str]]:
        with self._lock:
            return self._joint_commands.preview_move_joint(joint_id, target_angle_deg, relative)

    # --- move_joints (batch, delegated to JointCommands) -----------------------

    def move_joints(self, targets: List[Tuple[int, float]], relative: bool = False) -> Dict[int, float]:
        return self._outcome.guarded(
            lambda: self._locked_rate_limited(
                lambda: self._joint_commands.move_joints_locked(targets, relative, self._target_angles_deg)
            )
        )

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
        self._outcome.guarded(
            lambda: self._locked_rate_limited(
                lambda: self._pose_commands.move_to_pose_locked(
                    x, y, z, roll_deg, pitch_deg, yaw_deg, relative, self._target_angles_deg
                )
            )
        )

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
                self._locked_rate_limited(
                    lambda waypoint=waypoint: self._pose_commands.move_to_pose_locked(
                        waypoint.get("x"), waypoint.get("y"), waypoint.get("z"),
                        waypoint.get("roll_deg"), waypoint.get("pitch_deg"), waypoint.get("yaw_deg"),
                        waypoint.get("relative", False), self._target_angles_deg,
                    )
                )
            except Exception as exc:
                self._outcome.note_error(exc)
                results.append({"index": index, "ok": False, "reached": False, "reason": str(exc)})
                all_ok = False
                break
            reached, _timed_out, _joints, _targets = self.wait_reached(None, DEFAULT_WAIT_TIMEOUT_S)
            results.append({"index": index, "ok": True, "reached": reached, "reason": None})
        if all_ok:
            self._outcome.note_success()
        return results

    # --- grip ----------------------------------------------------------------
    # Trivial enough (clamp + assign) to stay inline rather than its own
    # collaborator — no adapter interaction, single float field.

    def _grip_locked(self, force: float) -> float:
        clamped_force = clamp(force, 0.0, MAX_FORCE)
        self.grip_force = clamped_force
        return clamped_force

    def grip(self, force: float) -> float:
        return self._outcome.guarded(lambda: self._locked_rate_limited(lambda: self._grip_locked(force)))

    # --- pick_and_place (macro, orchestrates PoseCommands + grip) --------------

    def pick_and_place(
        self, pick: Dict[str, Optional[float]], place: Dict[str, Optional[float]], grip_force: float
    ) -> Dict[str, bool]:
        # Multiple locked sections with unlocked wait_reached() calls between
        # them, so this can't use _locked_rate_limited (one locked call) —
        # only _outcome.guarded (success/failure recording) applies here.
        def _do() -> Dict[str, bool]:
            self._locked_rate_limited(
                lambda: self._pose_commands.move_to_pose_locked(
                    pick.get("x"), pick.get("y"), pick.get("z"),
                    pick.get("roll_deg"), pick.get("pitch_deg"), pick.get("yaw_deg"),
                    pick.get("relative", False), self._target_angles_deg,
                )
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
            return {"reached_pick": reached_pick, "reached_place": reached_place}

        return self._outcome.guarded(_do)

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
            self._drive_to_home_pose()
        self._outcome.clear()
