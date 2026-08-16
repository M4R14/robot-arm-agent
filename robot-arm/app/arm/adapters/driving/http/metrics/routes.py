"""GET /metrics — accepted/rejected command counters. Human-debugging
only (see adapters/driven/metrics.py's docstring): not part of the
agent's tool set in SPEC.md §5.3, and never called by the extension or
orchestrator.
"""

from fastapi import APIRouter, Depends

from app.arm.adapters.driving.http.dependencies import get_service
from app.arm.adapters.driving.http.metrics.schemas import MetricsResponse
from app.arm.application.arm_service import ArmService

router = APIRouter()


@router.get("/metrics", response_model=MetricsResponse)
def metrics(service: ArmService = Depends(get_service)) -> MetricsResponse:
    return MetricsResponse(**service.get_metrics())
