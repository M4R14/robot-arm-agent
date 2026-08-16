"""Composition root for the HTTP driving adapter (Hexagonal / Ports &
Adapters): assembles each domain's router into one. The single
ArmService (application layer) instance lives in dependencies.py —
FastAPI's own Depends(), each domain route declares it directly.
"""

from fastapi import APIRouter

from app.arm.adapters.driving.http.capabilities import routes as capabilities_routes
from app.arm.adapters.driving.http.gripper import routes as gripper_routes
from app.arm.adapters.driving.http.joint import routes as joint_routes
from app.arm.adapters.driving.http.macro import routes as macro_routes
from app.arm.adapters.driving.http.metrics import routes as metrics_routes
from app.arm.adapters.driving.http.pose import routes as pose_routes
from app.arm.adapters.driving.http.safety import routes as safety_routes
from app.arm.adapters.driving.http.state import routes as state_routes
from app.arm.adapters.driving.http.trajectory import routes as trajectory_routes

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
