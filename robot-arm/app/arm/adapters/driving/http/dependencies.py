"""FastAPI dependency provider for the single ArmService instance. Route
handlers declare `service: ArmService = Depends(get_service)` instead of
each route module manually threading a `service` parameter through its
own build_router(service) closure — FastAPI's own DI, not a new library,
since the project already depends on the framework that has it.

This is the HTTP driving adapter's composition point (Hexagonal / Ports
& Adapters): every concrete driven adapter and domain collaborator
ArmService needs is constructed and wired together here, then injected
into ArmService's constructor — ArmService itself no longer decides what
its dependencies are, only what it does with them. One process, one
ArmService, for the container's lifetime.
"""

from app.arm.adapters.driven.idempotency_cache import IdempotencyCache
from app.arm.adapters.driven.metrics import Metrics
from app.arm.adapters.driven.pose_memory import PoseMemory
from app.arm.adapters.driven.pybullet_physics_adapter import PyBulletAdapter
from app.arm.application.arm_service import ArmService
from app.arm.domain.motion_driver import SynchronizedMotionDriver
from app.arm.domain.motion_validator import MotionValidator
from app.arm.domain.rate_limiter import RateLimiter

_adapter = PyBulletAdapter()
_pose_memory = PoseMemory()

service = ArmService(
    adapter=_adapter,
    rate_limiter=RateLimiter(),
    idempotency_cache=IdempotencyCache(),
    pose_memory=_pose_memory,
    validator=MotionValidator(_adapter, _pose_memory),
    driver=SynchronizedMotionDriver(_adapter),
    metrics=Metrics(),
)


def get_service() -> ArmService:
    return service
