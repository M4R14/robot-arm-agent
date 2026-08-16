"""Shapes domain data into wire schemas. Single responsibility: DTO
assembly, nothing else.
"""

from typing import Dict, List

from ..adapters.pybullet_adapter import JointAngle
from ..arm_service import ArmService
from ..schemas import JointState


def build_joint_states(service: ArmService, joints: List[JointAngle], targets: Dict[int, float]) -> List[JointState]:
    return [
        JointState(
            joint_id=j.joint_id,
            angle_deg=j.angle_deg,
            velocity_deg_s=j.velocity_deg_s,
            applied_torque=j.applied_torque,
            target_angle_deg=targets.get(j.joint_id),
            reached=service.is_reached(j.joint_id, j.angle_deg, targets),
        )
        for j in joints
    ]
