"""Background polling of sim's /state, exposing thread-safe snapshots to
the render loop. Single responsibility: own the background thread, the
reconnect-with-backoff loop, and the lock-guarded latest StateSnapshot —
the wire format lives in schemas.py, the snapshot shape in snapshot.py,
and how to actually reach sim in sim_exec.py.

Self-heals via `tenacity`'s exponential backoff if the stream dies.
"""

import math
import subprocess
import threading
import time
from typing import Optional

from loguru import logger
from pydantic import ValidationError
from tenacity import RetryCallState, retry, stop_never, wait_exponential

from viewer.schemas import PolledPayload, StreamError
from viewer.sim_exec import build_poll_stream_cmd
from viewer.snapshot import StateSnapshot

POLL_INTERVAL_S = 0.05
RESTART_BACKOFF_INITIAL_S = 1.0
RESTART_BACKOFF_MAX_S = 15.0


def _log_before_sleep(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception()
    logger.warning(
        "stream ended ({}), restarting in {:.1f}s (attempt {})...",
        exc, retry_state.next_action.sleep, retry_state.attempt_number,
    )


class StreamEndedError(Exception):
    """Raised when the docker-exec stream process exits, so tenacity's
    @retry sees it as a normal retryable condition rather than the loop
    having to hand-check an exit code."""


class StateStream:
    """Owns the background streaming thread and the latest state, behind
    a lock. `snapshot()` returns an immutable-enough copy safe to read
    from the render loop without holding any lock."""

    def __init__(self, poll_interval_s: float = POLL_INTERVAL_S) -> None:
        self._poll_interval_s = poll_interval_s
        self._lock = threading.Lock()
        self._snapshot = StateSnapshot()
        self._process: Optional[subprocess.Popen] = None
        self._parse_error_count = 0
        self._stopped = False

    def snapshot(self) -> StateSnapshot:
        with self._lock:
            s = self._snapshot
            return StateSnapshot(
                angles_rad=dict(s.angles_rad),
                targets_rad=dict(s.targets_rad),
                ee_position=s.ee_position,
                ee_orientation=s.ee_orientation,
                summary=s.summary,
                grip_force=s.grip_force,
                last_error=dict(s.last_error) if s.last_error else None,
                rejected_history=list(s.rejected_history),
                updated_at=s.updated_at,
            )

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self) -> None:
        self._stopped = True
        if self._process is not None:
            self._process.terminate()

    def _handle_line(self, line: str) -> None:
        try:
            error = StreamError.model_validate_json(line)
            logger.warning("sim-side poll failed: {}", error.error)
            return
        except ValidationError:
            pass

        try:
            payload = PolledPayload.model_validate_json(line)
        except ValidationError as exc:
            self._parse_error_count += 1
            if self._parse_error_count % 20 == 1:
                logger.warning(
                    "{} malformed/unexpected stream line(s) so far, last: {!r} ({})",
                    self._parse_error_count, line[:80], exc.errors()[0]["msg"] if exc.errors() else exc,
                )
            return

        state = payload.state
        with self._lock:
            s = self._snapshot
            for joint in state.joints:
                s.angles_rad[joint.joint_id] = math.radians(joint.angle_deg)
                if joint.target_angle_deg is not None:
                    s.targets_rad[joint.joint_id] = math.radians(joint.target_angle_deg)
                else:
                    s.targets_rad.pop(joint.joint_id, None)
            s.ee_position = state.end_effector_position
            s.ee_orientation = state.end_effector_orientation
            s.summary = state.summary
            s.grip_force = state.grip_force
            s.last_error = state.last_error.model_dump() if state.last_error else None
            s.rejected_history = [entry.model_dump() for entry in payload.rejected_history]
            s.updated_at = time.monotonic()

    # Note: tenacity's backoff is keyed by attempt number within this one
    # long-lived call, and never resets — unlike the old hand-rolled
    # version, which reset to RESTART_BACKOFF_INITIAL_S after any
    # successfully-parsed line. In practice this only matters for a
    # viewer session with many disconnects spread over hours; a later
    # blip after the backoff has already saturated at
    # RESTART_BACKOFF_MAX_S reconnects a bit slower than it strictly
    # needs to. Accepted as a reasonable trade-off for using tenacity's
    # idiomatic retry pattern instead of re-implementing reset-on-success
    # bookkeeping by hand.
    @retry(
        wait=wait_exponential(multiplier=RESTART_BACKOFF_INITIAL_S, max=RESTART_BACKOFF_MAX_S),
        stop=stop_never,
        before_sleep=_log_before_sleep,
    )
    def _connect_and_stream(self) -> None:
        stream_cmd = build_poll_stream_cmd(self._poll_interval_s)
        self._process = subprocess.Popen(stream_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        for line in iter(self._process.stdout.readline, ""):
            self._handle_line(line)
        self._process.wait()
        if self._stopped:
            return
        raise StreamEndedError("stream process exited unexpectedly")

    def _loop(self) -> None:
        try:
            self._connect_and_stream()
        except StreamEndedError:
            pass  # only reachable if @retry's stop_never is ever changed
