"""Paces mutating commands. Single responsibility: enforce a minimum
interval between calls to `check()`, nothing else. Self-locking so any
number of caller threads can share one instance safely.
"""

import threading
import time
from typing import Optional

from ..constants import MIN_COMMAND_INTERVAL_S
from .exceptions import RateLimitedError


class RateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_command_time: Optional[float] = None

    def check(self) -> None:
        with self._lock:
            now = time.monotonic()
            if self._last_command_time is not None:
                elapsed = now - self._last_command_time
                if elapsed < MIN_COMMAND_INTERVAL_S:
                    raise RateLimitedError(MIN_COMMAND_INTERVAL_S - elapsed)
            self._last_command_time = now
