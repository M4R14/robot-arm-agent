from typing import List, Optional

from pydantic import BaseModel


class StopRequest(BaseModel):
    joint_ids: Optional[List[int]] = None
