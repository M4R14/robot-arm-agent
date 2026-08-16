"""FastAPI dependency provider for the single ArmService instance. Route
handlers declare `service: ArmService = Depends(get_service)` instead of
each route module manually threading a `service` parameter through its
own build_router(service) closure — FastAPI's own DI, not a new library,
since the project already depends on the framework that has it.

This is the HTTP driving adapter's composition point (Hexagonal / Ports
& Adapters): it's where the one ArmService (application layer) instance
gets created and handed to every route. One process, one ArmService, for
the container's lifetime.
"""

from app.arm.application.arm_service import ArmService

service = ArmService()


def get_service() -> ArmService:
    return service
