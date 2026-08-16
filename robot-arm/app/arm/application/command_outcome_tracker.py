"""Tracks what happened to past commands: idempotent-replay lookup, the
last error (surfaced via get_state()), a bounded rejection history, and
accept/reject metrics. Also owns the guarded-command wrapper every
mutating command runs through so success/failure gets recorded uniformly.

Stays in application/ (not domain/) alongside ArmService: it wraps
IdempotencyCache/Metrics, which — like ArmService's own binding of ports
to adapters — have no formal Port since nothing under domain/ depends on
them and there's only one real implementation each.
"""

from typing import Dict, List, Optional

from loguru import logger

from ..adapters.driven.idempotency_cache import IdempotencyCache
from ..adapters.driven.metrics import Metrics
from ..constants import ERROR_RECOVERY_HINTS, REJECTED_HISTORY_MAX


class CommandOutcomeTracker:
    def __init__(self, lock, idempotency_cache: IdempotencyCache, metrics: Metrics) -> None:
        self._lock = lock
        self._idempotency_cache = idempotency_cache
        self._metrics = metrics
        self._last_error: Optional[Dict[str, str]] = None
        self._rejected_history: List[Dict] = []

    # --- idempotency (delegated) ------------------------------------------

    def check_idempotent(self, command_id: Optional[str]) -> Optional[dict]:
        return self._idempotency_cache.check(command_id)

    def remember_idempotent(self, command_id: Optional[str], payload: dict) -> None:
        self._idempotency_cache.remember(command_id, payload)

    # --- outcome recording ---------------------------------------------------
    # Self-locking so they're safe to call from outside any `with lock` block
    # (e.g. right after a locked block raises and releases the lock).

    def note_error(self, exc: Exception) -> None:
        entry = {
            "error_code": getattr(exc, "error_code", "ERROR"),
            "message": str(exc),
            "details": getattr(exc, "details", {}),
        }
        with self._lock:
            self._last_error = {"error_code": entry["error_code"], "message": entry["message"]}
            self._rejected_history.append(entry)
            if len(self._rejected_history) > REJECTED_HISTORY_MAX:
                self._rejected_history.pop(0)
        self._metrics.note_rejected(entry["error_code"])
        logger.warning("command rejected: {} — {}", entry["error_code"], entry["message"])

    def note_success(self) -> None:
        with self._lock:
            self._last_error = None
        self._metrics.note_accepted()
        logger.debug("command accepted")

    def guarded(self, fn):
        try:
            result = fn()
        except Exception as exc:
            self.note_error(exc)
            raise
        self.note_success()
        return result

    # --- reads -----------------------------------------------------------------

    def get_metrics(self) -> Dict:
        return self._metrics.snapshot()

    def get_last_error(self) -> Optional[Dict[str, str]]:
        with self._lock:
            return dict(self._last_error) if self._last_error else None

    def get_rejected_history(self) -> List[Dict]:
        with self._lock:
            return [dict(entry) for entry in self._rejected_history]

    def get_error_recovery_hints(self) -> Dict[str, str]:
        return dict(ERROR_RECOVERY_HINTS)

    # --- reset -----------------------------------------------------------------

    def clear(self) -> None:
        with self._lock:
            self._last_error = None
            self._rejected_history.clear()
        self._idempotency_cache.clear()
