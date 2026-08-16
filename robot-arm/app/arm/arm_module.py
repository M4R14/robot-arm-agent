"""Composition root for the arm feature module (NestJS-style: one module
per feature, everything the arm needs — adapter, service, routes, support
— lives under this package). Owns the single ArmService instance and
assembles the resource-scoped sub-routers. No route logic, error mapping,
or DTO shaping lives here — each of those is one file with one job.
"""

from fastapi import APIRouter

from .arm_service import ArmService
from .routes import gripper_routes, joint_routes, macro_routes, pose_routes, safety_routes, state_routes

service = ArmService()

router = APIRouter()
router.include_router(state_routes.build_router(service))
router.include_router(joint_routes.build_router(service))
router.include_router(pose_routes.build_router(service))
router.include_router(gripper_routes.build_router(service))
router.include_router(macro_routes.build_router(service))
router.include_router(safety_routes.build_router(service))
