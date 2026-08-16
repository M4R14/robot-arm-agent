"""Composition root for the arm feature module (NestJS-style: one module
per feature, everything the arm needs — adapter, service, routes, support
— lives under this package). Assembles the resource-scoped sub-routers;
the single ArmService instance itself lives in dependencies.py (FastAPI's
own `Depends()` — each route declares it, rather than this module
threading a `service` parameter through every routes/*.py build_router()
call). No route logic, error mapping, or DTO shaping lives here — each of
those is one file with one job.
"""

from fastapi import APIRouter

from .dependencies import service
from .routes import (
    capabilities_routes,
    gripper_routes,
    joint_routes,
    macro_routes,
    metrics_routes,
    pose_routes,
    safety_routes,
    state_routes,
    trajectory_routes,
)

router = APIRouter()
router.include_router(state_routes.router)
router.include_router(capabilities_routes.router)
router.include_router(joint_routes.router)
router.include_router(pose_routes.router)
router.include_router(trajectory_routes.router)
router.include_router(gripper_routes.router)
router.include_router(macro_routes.router)
router.include_router(safety_routes.router)
router.include_router(metrics_routes.router)
