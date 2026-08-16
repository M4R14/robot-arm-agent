"""GET /metrics — accepted/rejected command counters. Human-debugging
only (see support/metrics.py's docstring): not part of the agent's tool
set in SPEC.md §5.3, and never called by the extension or orchestrator.
"""

from fastapi import APIRouter, Depends

from ..arm_service import ArmService
from ..dependencies import get_service
from ..schemas import MetricsResponse

router = APIRouter()


@router.get("/metrics", response_model=MetricsResponse)
def metrics(service: ArmService = Depends(get_service)) -> MetricsResponse:
    return MetricsResponse(**service.get_metrics())
