"""Thin wrapper over the raw PyBullet API. No domain rules (clamping,
validation) live here — this layer only knows how to talk to the physics
engine.

Not thread-safe on its own: PyBullet's C API is not reentrant across
concurrent calls on the same client. Callers (ArmService) must hold a lock
around every method call, including across the multi-call sequences in
move_to_pose and dry_run.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pybullet as p
import pybullet_data

from ..constants import (
    MAX_JOINT_VELOCITY_DEG_S,
    POSITION_GAIN,
    URDF_PATH,
    VELOCITY_GAIN,
)


@dataclass
class JointAngle:
    joint_id: int
    angle_deg: float
    velocity_deg_s: float
    applied_torque: float


class PyBulletAdapter:
    def __init__(self) -> None:
        self.client_id = p.connect(p.DIRECT)
        self.robot_id = 0
        self.movable_joints: List[int] = []
        self.end_effector_link = 0
        self.joint_limits_deg: Dict[int, Tuple[float, float]] = {}
        self.load()

    def load(self) -> None:
        p.resetSimulation(physicsClientId=self.client_id)
        p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=self.client_id)
        p.setGravity(0, 0, -9.8, physicsClientId=self.client_id)
        p.loadURDF("plane.urdf", physicsClientId=self.client_id)
        self.robot_id = p.loadURDF(URDF_PATH, [0, 0, 0], useFixedBase=True, physicsClientId=self.client_id)
        self.movable_joints = [
            i
            for i in range(p.getNumJoints(self.robot_id, physicsClientId=self.client_id))
            if p.getJointInfo(self.robot_id, i, physicsClientId=self.client_id)[2] != p.JOINT_FIXED
        ]
        self.end_effector_link = self.movable_joints[-1]
        # The URDF defines its own per-joint hardware limits (e.g. the KUKA
        # iiwa's elbow joints are physically limited to ±120°, tighter than
        # our generic safety ceiling). resetJointState (used by dry_run)
        # ignores these, so callers must clamp against them explicitly or a
        # "reachable" pose can turn out to be one the real motor can never
        # reach and stalls at the hard limit instead.
        self.joint_limits_deg = {
            j: (
                math.degrees(p.getJointInfo(self.robot_id, j, physicsClientId=self.client_id)[8]),
                math.degrees(p.getJointInfo(self.robot_id, j, physicsClientId=self.client_id)[9]),
            )
            for j in self.movable_joints
        }

    def step(self) -> None:
        p.stepSimulation(physicsClientId=self.client_id)

    def get_joint_angles_deg(self) -> List[JointAngle]:
        joints = []
        for j in self.movable_joints:
            position_rad, velocity_rad_s, _reaction_forces, applied_torque = p.getJointState(
                self.robot_id, j, physicsClientId=self.client_id
            )
            joints.append(JointAngle(j, math.degrees(position_rad), math.degrees(velocity_rad_s), applied_torque))
        return joints

    def get_joint_positions_rad(self) -> Dict[int, float]:
        return {
            j: p.getJointState(self.robot_id, j, physicsClientId=self.client_id)[0]
            for j in self.movable_joints
        }

    def get_end_effector_position(self) -> List[float]:
        return list(p.getLinkState(self.robot_id, self.end_effector_link, physicsClientId=self.client_id)[4])

    def set_joint_target_deg(self, joint_id: int, target_deg: float, max_velocity_deg_s: Optional[float] = None) -> None:
        p.setJointMotorControl2(
            self.robot_id,
            joint_id,
            p.POSITION_CONTROL,
            targetPosition=math.radians(target_deg),
            maxVelocity=math.radians(max_velocity_deg_s if max_velocity_deg_s is not None else MAX_JOINT_VELOCITY_DEG_S),
            positionGain=POSITION_GAIN,
            velocityGain=VELOCITY_GAIN,
            physicsClientId=self.client_id,
        )

    def euler_deg_to_quaternion(self, roll_deg: float, pitch_deg: float, yaw_deg: float) -> List[float]:
        return list(
            p.getQuaternionFromEuler([math.radians(roll_deg), math.radians(pitch_deg), math.radians(yaw_deg)])
        )

    def calculate_ik_deg(self, position: List[float], orientation_quat: Optional[List[float]] = None) -> List[float]:
        kwargs = {"targetOrientation": orientation_quat} if orientation_quat is not None else {}
        targets_rad = p.calculateInverseKinematics(
            self.robot_id,
            self.end_effector_link,
            position,
            maxNumIterations=200,
            residualThreshold=1e-4,
            physicsClientId=self.client_id,
            **kwargs,
        )
        return [math.degrees(rad) for rad in targets_rad]

    def _jacobian_condition_number(self) -> float:
        num_joints = p.getNumJoints(self.robot_id, physicsClientId=self.client_id)
        joint_positions = [0.0] * num_joints
        for j in self.movable_joints:
            joint_positions[j] = p.getJointState(self.robot_id, j, physicsClientId=self.client_id)[0]
        zero_vec = [0.0] * num_joints
        linear_jacobian, _angular_jacobian = p.calculateJacobian(
            self.robot_id,
            self.end_effector_link,
            [0, 0, 0],
            joint_positions,
            zero_vec,
            zero_vec,
            physicsClientId=self.client_id,
        )
        movable_columns = np.array(linear_jacobian)[:, self.movable_joints]
        return float(np.linalg.cond(movable_columns))

    def dry_run(self, target_angles_deg: Dict[int, float]) -> Tuple[List[float], bool, float]:
        """Temporarily poses the arm at `target_angles_deg` (kinematically,
        no motor/physics involved) to measure the resulting end-effector
        position, self-collision, and Jacobian condition number, then
        restores the original pose. Does not move the real arm.
        """
        original_rad = self.get_joint_positions_rad()
        for joint_id, angle_deg in target_angles_deg.items():
            p.resetJointState(self.robot_id, joint_id, math.radians(angle_deg), physicsClientId=self.client_id)

        p.performCollisionDetection(physicsClientId=self.client_id)
        contacts = p.getContactPoints(bodyA=self.robot_id, bodyB=self.robot_id, physicsClientId=self.client_id)
        # Adjacent links are expected to touch/overlap near their shared joint;
        # only non-adjacent contact indicates a genuine self-collision.
        collision_free = all(abs(c[3] - c[4]) <= 1 for c in contacts)
        ee_position = self.get_end_effector_position()
        condition_number = self._jacobian_condition_number()

        for joint_id, angle_rad in original_rad.items():
            p.resetJointState(self.robot_id, joint_id, angle_rad, physicsClientId=self.client_id)

        return ee_position, collision_free, condition_number

    def disconnect(self) -> None:
        p.disconnect(physicsClientId=self.client_id)
