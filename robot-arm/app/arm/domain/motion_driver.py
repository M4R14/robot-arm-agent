"""Turns an already-validated candidate pose into real joint motion.
Single responsibility: scale each joint's speed so every joint in the
batch arrives at roughly the same time, then issue the motor commands and
record the new commanded targets.

Depends only on domain.ports.ArmPhysicsPort — never imports the PyBullet
adapter concretely (Hexagonal / Ports & Adapters).

Not thread-safe on its own — touches the shared physics port via
`set_joint_target_deg`. Callers must hold the same lock the port's
concrete adapter requires.
"""

from typing import Dict

from ..constants import MAX_JOINT_VELOCITY_DEG_S
from .ports import ArmPhysicsPort


class SynchronizedMotionDriver:
    def __init__(self, adapter: ArmPhysicsPort) -> None:
        self._adapter = adapter

    def drive(
        self,
        candidate: Dict[int, float],
        current_angles_deg: Dict[int, float],
        target_angles_deg: Dict[int, float],
    ) -> None:
        """Commands each joint in `candidate` toward its target, mutating
        `target_angles_deg` (the caller's shared tracking dict) in place."""
        deltas_deg = {jid: abs(deg - current_angles_deg[jid]) for jid, deg in candidate.items()}
        max_delta = max(deltas_deg.values()) if deltas_deg else 0.0
        slowest_time_s = max_delta / MAX_JOINT_VELOCITY_DEG_S
        for joint_id, clamped_deg in candidate.items():
            velocity_deg_s = deltas_deg[joint_id] / slowest_time_s if slowest_time_s > 0 else MAX_JOINT_VELOCITY_DEG_S
            self._adapter.set_joint_target_deg(joint_id, clamped_deg, max_velocity_deg_s=velocity_deg_s)
            target_angles_deg[joint_id] = clamped_deg
