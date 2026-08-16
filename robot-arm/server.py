"""Isolated physics sim for a robot arm. Exposes a fixed, validated HTTP API only.

Never add an endpoint that accepts code, a script, a shell command, or a file
path from the caller. See ../SPEC.md sections 4.4 and 4.5.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.arm.arm_module import router, service


@asynccontextmanager
async def lifespan(app: FastAPI):
    service.start_stepping()
    yield
    service.shutdown()


app = FastAPI(title="robot-arm-sim", lifespan=lifespan)
app.include_router(router)
