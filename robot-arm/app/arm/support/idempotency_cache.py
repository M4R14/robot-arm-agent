"""Caches a response by caller-supplied command_id so a retried command
replays the prior result instead of re-executing. Single responsibility:
memoize by key with a TTL and a size cap, nothing else. Self-locking so
any number of caller threads can share one instance safely.
"""

import threading
from typing import Optional

from cachetools import TTLCache

from ..constants import IDEMPOTENCY_CACHE_MAX, IDEMPOTENCY_TTL_S


class IdempotencyCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: TTLCache = TTLCache(maxsize=IDEMPOTENCY_CACHE_MAX, ttl=IDEMPOTENCY_TTL_S)

    def check(self, command_id: Optional[str]) -> Optional[dict]:
        if command_id is None:
            return None
        with self._lock:
            return self._cache.get(command_id)

    def remember(self, command_id: Optional[str], payload: dict) -> None:
        if command_id is None:
            return
        with self._lock:
            self._cache[command_id] = payload

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
