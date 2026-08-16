"""GET /metrics — accepted/rejected command counters. Human-debugging
only (see support/metrics.py's docstring): not part of the agent's tool
set in SPEC.md §5.3, and never called by the extension or orchestrator.
"""

from fastapi import APIRouter

from ..arm_service import ArmService
from ..schemas import MetricsResponse


def build_router(service: ArmService) -> APIRouter:
    router = APIRouter()

    @router.get("/metrics", response_model=MetricsResponse)
    def metrics() -> MetricsResponse:
        return MetricsResponse(**service.get_metrics())

    return router
