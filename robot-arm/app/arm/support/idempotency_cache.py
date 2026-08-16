"""Caches a response by caller-supplied command_id so a retried command
replays the prior result instead of re-executing. Single responsibility:
memoize by key with a TTL and a size cap, nothing else. Self-locking so
any number of caller threads can share one instance safely.
"""

import threading
import time
from typing import Dict, Optional, Tuple

from ..constants import IDEMPOTENCY_CACHE_MAX, IDEMPOTENCY_TTL_S


class IdempotencyCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: Dict[str, Tuple[float, dict]] = {}

    def check(self, command_id: Optional[str]) -> Optional[dict]:
        if command_id is None:
            return None
        with self._lock:
            entry = self._entries.get(command_id)
            if entry is None:
                return None
            timestamp, payload = entry
            if time.monotonic() - timestamp > IDEMPOTENCY_TTL_S:
                del self._entries[command_id]
                return None
            return payload

    def remember(self, command_id: Optional[str], payload: dict) -> None:
        if command_id is None:
            return
        with self._lock:
            if len(self._entries) >= IDEMPOTENCY_CACHE_MAX:
                oldest_key = min(self._entries, key=lambda k: self._entries[k][0])
                del self._entries[oldest_key]
            self._entries[command_id] = (time.monotonic(), payload)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
