"""In-memory counters for accepted/rejected commands. Single
responsibility: count, nothing else — no logging, no HTTP. Self-locking
so any number of caller threads can share one instance safely.

Purely a human-debugging aid (GET /metrics, see
adapters/driving/http/domains/metrics/routes.py) — not part of the
agent's tool set (SPEC.md §5.3), the same "not read by any LLM" carve-out
already established for run_history.jsonl on the agent side. Resets to
zero on container restart; unlike rejected_history and pose_memory,
there's no reason for this to survive one — it's a running tally, not a
record.
"""

import threading
from collections import defaultdict
from typing import Dict


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._accepted = 0
        self._rejected_by_code: Dict[str, int] = defaultdict(int)

    def note_accepted(self) -> None:
        with self._lock:
            self._accepted += 1

    def note_rejected(self, error_code: str) -> None:
        with self._lock:
            self._rejected_by_code[error_code] += 1

    def snapshot(self) -> Dict:
        with self._lock:
            rejected_by_code = dict(self._rejected_by_code)
            total_rejected = sum(rejected_by_code.values())
            total = self._accepted + total_rejected
            return {
                "accepted": self._accepted,
                "rejected": total_rejected,
                "rejected_by_code": rejected_by_code,
                "rejection_rate": total_rejected / total if total else 0.0,
            }
