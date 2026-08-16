"""Maps a domain exception onto the standard HTTP error shape. Single
responsibility: exception -> HTTPException, nothing else. Firmly part of
the HTTP driving adapter — domain code never raises HTTPException, only
its own domain.exceptions types.
"""

from typing import NoReturn

from fastapi import HTTPException


def raise_http(exc: Exception, status_code: int) -> NoReturn:
    error_code = getattr(exc, "error_code", "ERROR")
    detail = {"error_code": error_code, "message": str(exc)}
    detail.update(getattr(exc, "details", {}))
    raise HTTPException(status_code=status_code, detail=detail)
