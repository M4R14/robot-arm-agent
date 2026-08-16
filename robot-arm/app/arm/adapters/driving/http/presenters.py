"""Shapes domain data into wire schemas. Single responsibility: DTO
assembly, nothing else.
"""

from typing import Dict, List, Optional

from app.arm.adapters.driving.http.state.schemas import JointState
from app.arm.application.arm_service import ArmService
from app.arm.domain.ports import JointAngle


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


def build_summary(joint_states: List[JointState], grip_force: float, last_error: Optional[Dict[str, str]]) -> str:
    moving = [j for j in joint_states if not j.reached]
    if moving:
        status = f"arm moving — {len(moving)}/{len(joint_states)} joint(s) still in motion toward target"
    else:
        status = "arm idle at current pose"

    grip_desc = "gripper released" if grip_force <= 0 else f"grip force {grip_force:.0f}"
    parts = [status, grip_desc]

    if last_error:
        parts.append(f"last command failed: {last_error['error_code']} — {last_error['message']}")

    return "; ".join(parts)
