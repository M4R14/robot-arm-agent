"""FastAPI dependency provider for the single ArmService instance. Route
handlers declare `service: ArmService = Depends(get_service)` instead of
each routes/*.py module manually threading a `service` parameter through
its own build_router(service) closure — FastAPI's own DI, not a new
library, since the project already depends on the framework that has it.

One process, one ArmService, for the container's lifetime — this doesn't
add per-request construction or any new lifecycle; get_service() always
returns the same instance FastAPI's dependency-caching would give it
anyway, just without needing to explicitly rely on that caching.
"""

from .arm_service import ArmService

service = ArmService()


def get_service() -> ArmService:
    return service
