"""Background polling of sim's /state via a persistent `docker compose
exec` stream, exposing thread-safe snapshots to the render loop.

Spawns one long-lived process (not a fresh subprocess per tick — that
used to cost ~100-300ms of exec overhead every poll) that loops *inside*
the sim container hitting its own localhost, streaming one JSON line per
tick back over stdout. Self-heals with exponential backoff if the stream
dies. Never opens a direct network route to `sim` — isolation per
SPEC.md is preserved.
"""

import json
import math
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

DOCKER_EXEC = ["/usr/bin/docker", "compose", "exec", "-T", "sim"]
POLL_INTERVAL_S = 0.05
RESTART_BACKOFF_INITIAL_S = 1.0
RESTART_BACKOFF_MAX_S = 15.0


def fetch_urdf_path() -> str:
    """One-off lookup of sim's loaded URDF path via /capabilities — never
    hardcoded here, so the viewer always matches what's actually loaded."""
    out = subprocess.run(
        DOCKER_EXEC + ["python3", "-c", "import urllib.request,json;"
                       "print(json.load(urllib.request.urlopen('http://localhost:8000/capabilities'))['urdf_path'])"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


@dataclass
class StateSnapshot:
    angles_rad: Dict[int, float] = field(default_factory=dict)
    targets_rad: Dict[int, float] = field(default_factory=dict)
    ee_position: Optional[List[float]] = None
    ee_orientation: Optional[List[float]] = None
    summary: str = ""
    grip_force: float = 0.0
    last_error: Optional[dict] = None
    updated_at: Optional[float] = None  # time.monotonic() of last update, or None if never updated


class StateStream:
    """Owns the background streaming thread and the latest state, behind
    a lock. `snapshot()` returns an immutable-enough copy safe to read
    from the render loop without holding any lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot = StateSnapshot()
        self._process: Optional[subprocess.Popen] = None
        self._parse_error_count = 0

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
                updated_at=s.updated_at,
            )

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self) -> None:
        if self._process is not None:
            self._process.terminate()

    def _handle_line(self, line: str) -> None:
        try:
            state = json.loads(line)
        except json.JSONDecodeError:
            self._parse_error_count += 1
            if self._parse_error_count % 20 == 1:
                print(f"warning: {self._parse_error_count} malformed stream line(s) so far, last: {line[:80]!r}")
            return
        if "error" in state:
            print("sim-side poll failed:", state["error"])
            return

        with self._lock:
            s = self._snapshot
            for joint in state["joints"]:
                s.angles_rad[joint["joint_id"]] = math.radians(joint["angle_deg"])
                if joint.get("target_angle_deg") is not None:
                    s.targets_rad[joint["joint_id"]] = math.radians(joint["target_angle_deg"])
                else:
                    s.targets_rad.pop(joint["joint_id"], None)
            s.ee_position = state.get("end_effector_position")
            s.ee_orientation = state.get("end_effector_orientation")
            s.summary = state.get("summary", "")
            s.grip_force = state.get("grip_force", 0.0)
            s.last_error = state.get("last_error")
            s.updated_at = time.monotonic()

    def _loop(self) -> None:
        backoff = RESTART_BACKOFF_INITIAL_S
        stream_cmd = DOCKER_EXEC + [
            "python3", "-c",
            "import urllib.request,json,time\n"
            "while True:\n"
            "    try:\n"
            "        print(json.dumps(json.load(urllib.request.urlopen('http://localhost:8000/state'))), flush=True)\n"
            "    except Exception as exc:\n"
            "        print(json.dumps({'error': str(exc)}), flush=True)\n"
            f"    time.sleep({POLL_INTERVAL_S})\n",
        ]
        while True:
            try:
                self._process = subprocess.Popen(stream_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                for line in iter(self._process.stdout.readline, ""):
                    self._handle_line(line)
                    backoff = RESTART_BACKOFF_INITIAL_S
                self._process.wait()
            except Exception as exc:
                print("stream failed:", exc)
            print(f"stream process exited, restarting in {backoff:.1f}s...")
            time.sleep(backoff)
            backoff = min(backoff * 2, RESTART_BACKOFF_MAX_S)
