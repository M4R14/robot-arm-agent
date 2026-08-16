from typing import Optional

from pydantic import BaseModel


class GripRequest(BaseModel):
    force: float
    command_id: Optional[str] = None
