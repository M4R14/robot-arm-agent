"""Replay-or-execute wrapper for idempotent mutating routes. Single
responsibility: check the cache, build the response if missing, remember
it — works for any response model, nothing route-specific here.
"""

from typing import Callable, Optional, Type, TypeVar

from pydantic import BaseModel

from app.arm.application.arm_service import ArmService

ResponseT = TypeVar("ResponseT", bound=BaseModel)


def with_idempotency(
    service: ArmService,
    command_id: Optional[str],
    response_model: Type[ResponseT],
    build_response: Callable[[], ResponseT],
) -> ResponseT:
    cached = service.check_idempotent(command_id)
    if cached is not None:
        return response_model(**cached)
    response = build_response()
    service.remember_idempotent(command_id, response.model_dump())
    return response
