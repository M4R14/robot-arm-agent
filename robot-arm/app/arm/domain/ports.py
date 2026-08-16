"""Ports: the interfaces the domain defines for what it needs from the
outside world (Hexagonal / Ports & Adapters). Domain code (motion_validator,
motion_driver, joint_commands, pose_commands, state_queries,
capabilities_queries) depends only on these Protocols — never on a
concrete PyBullet or filesystem type — so the domain has zero import of
`pybullet` anywhere in it. `adapters/driven/` provides the concrete
implementations that plug into these ports; swapping physics engines or
pose-memory storage means writing a new driven adapter, not touching
domain logic.

Protocols (structural typing) rather than ABCs — a driven adapter
satisfies a port by having the right shape, no explicit inheritance
required. `JointAngle` lives here too since it's the port's own return
type, not any one adapter's implementation detail.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, Tuple


@dataclass
class JointAngle:
    joint_id: int
    angle_deg: float
    velocity_deg_s: float
    applied_torque: float


class ArmPhysicsPort(Protocol):
    """Everything the domain needs from a robot-arm physics backend.
    Mirrors PyBulletAdapter's public interface exactly — extracted here
    so domain code depends on the shape, not the PyBullet package."""

    movable_joints: List[int]
    joint_limits_deg: Dict[int, Tuple[float, float]]

    def load(self) -> None: ...
    def step(self) -> None: ...
    def get_joint_angles_deg(self) -> List[JointAngle]: ...
    def get_joint_positions_rad(self) -> Dict[int, float]: ...
    def get_end_effector_position(self) -> List[float]: ...
    def get_end_effector_orientation(self) -> List[float]: ...
    def set_joint_target_deg(self, joint_id: int, target_deg: float, max_velocity_deg_s: Optional[float] = None) -> None: ...
    def euler_deg_to_quaternion(self, roll_deg: float, pitch_deg: float, yaw_deg: float) -> List[float]: ...
    def calculate_ik_deg(self, position: List[float], orientation_quat: Optional[List[float]] = None) -> List[float]: ...
    def dry_run(self, target_angles_deg: Dict[int, float]) -> Tuple[List[float], bool, float]: ...
    def estimate_reach_envelope_m(self, num_samples: int = 300) -> Tuple[float, float]: ...
    def disconnect(self) -> None: ...


class PoseMemoryPort(Protocol):
    """What motion_validator.py needs from pose-fact persistence — it
    doesn't need to know this is a JSON file on disk (see
    adapters/driven/pose_memory.py); a different driven adapter (a real
    database, say) could implement this without motion_validator.py
    changing at all."""

    def record(self, position: List[float], outcome: str, error_code: Optional[str]) -> None: ...
    def lookup_near(self, position: List[float], radius_m: float = ...) -> Optional[object]: ...
