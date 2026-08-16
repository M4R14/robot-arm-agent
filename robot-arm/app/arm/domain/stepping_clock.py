"""Advances the physics simulation on a fixed-rate background thread. Owns
only the stepping thread's start/stop lifecycle — the caller supplies the
lock so stepping never races with a command holding it, and owns the
adapter's connect/disconnect lifecycle itself.
"""

import threading
import time

from ..constants import SIM_HZ
from .ports import ArmPhysicsPort


class SteppingClock:
    def __init__(self, lock: threading.Lock, adapter: ArmPhysicsPort) -> None:
        self._lock = lock
        self._adapter = adapter
        self._stop_event = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                self._adapter.step()
            time.sleep(1.0 / SIM_HZ)

    def stop(self) -> None:
        self._stop_event.set()
