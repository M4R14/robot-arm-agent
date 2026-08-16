"""Composition root for the arm feature module (NestJS-style: one module
per feature, everything the arm needs lives here). Assembles each
domain's router into one; the single ArmService instance itself lives in
dependencies.py (FastAPI's own Depends() — each domain route declares it
directly, rather than this module threading a `service` parameter
through every domain). No route logic, error mapping, or DTO shaping
lives here — each of those belongs to its own domains/<name>/.
"""

from fastapi import APIRouter

from .dependencies import service
from .domains.capabilities import routes as capabilities_routes
from .domains.gripper import routes as gripper_routes
from .domains.joint import routes as joint_routes
from .domains.macro import routes as macro_routes
from .domains.metrics import routes as metrics_routes
from .domains.pose import routes as pose_routes
from .domains.safety import routes as safety_routes
from .domains.state import routes as state_routes
from .domains.trajectory import routes as trajectory_routes

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
