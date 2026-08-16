from typing import Dict

from pydantic import BaseModel


class MetricsResponse(BaseModel):
    accepted: int
    rejected: int
    rejected_by_code: Dict[str, int]
    rejection_rate: float
