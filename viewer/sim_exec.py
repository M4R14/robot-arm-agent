"""Everything about reaching sim via `docker compose exec`. Single
responsibility: know the exec invocation and the small Python snippets
run inside the sim container — no threading, retry, or parsing lives
here, just how to talk to sim without opening a direct network route to
it (SPEC.md's isolation requirement).
"""

import subprocess

from viewer.schemas import Capabilities

DOCKER_EXEC = ["/usr/bin/docker", "compose", "exec", "-T", "sim"]


def fetch_capabilities() -> Capabilities:
    """One-off lookup of sim's /capabilities — URDF path (never hardcoded,
    so the viewer always matches what's actually loaded), per-joint
    hardware limits (for the joint-limit-proximity coloring), and
    reach_min_m/reach_max_m (for the reach-envelope overlay)."""
    out = subprocess.run(
        DOCKER_EXEC + ["python3", "-c", "import requests,json;"
                       "print(json.dumps(requests.get('http://localhost:8000/capabilities').json()))"],
        capture_output=True, text=True, check=True,
    )
    return Capabilities.model_validate_json(out.stdout.strip())


def build_poll_stream_cmd(poll_interval_s: float) -> list:
    """The command for a long-lived process that loops *inside* the sim
    container hitting its own localhost, streaming one JSON line per
    tick back over stdout — cheaper than a fresh `docker compose exec`
    per poll (~100-300ms of exec overhead each time). Each line bundles
    /state and /rejected_history together (schemas.PolledPayload) so the
    overlay can show recent rejections without a second stream."""
    return DOCKER_EXEC + [
        "python3", "-c",
        "import requests,json,time\n"
        "while True:\n"
        "    try:\n"
        "        state = requests.get('http://localhost:8000/state').json()\n"
        "        rejected = requests.get('http://localhost:8000/rejected_history').json()['entries']\n"
        "        print(json.dumps({'state': state, 'rejected_history': rejected}), flush=True)\n"
        "    except Exception as exc:\n"
        "        print(json.dumps({'error': str(exc)}), flush=True)\n"
        f"    time.sleep({poll_interval_s})\n",
    ]
