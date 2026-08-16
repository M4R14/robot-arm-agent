# RobotArmAgent

Two-container system: a PyBullet robot-arm simulator (`robot-arm/`, no
route to the internet) and a `pi` LLM agent harness (`ai-agent/`) that can
only call a fixed set of whitelisted tools mapping 1:1 to the sim's HTTP
API. See [SPEC.md](SPEC.md) for the full design and isolation
requirements.

## Run

Credentials load from `.env` at the repo root (docker compose loads it
automatically for `${VAR}` substitution in `docker-compose.yml`) — the
default provider/model (`openrouter` / `moonshotai/kimi-k2.6`) is baked
into the image at `ai-agent/settings.json`, along with a low
(`temperature: 0.2`) sampling override for more deterministic tool
calls. `.env` holds a real key and is gitignored; treat it as a secret,
don't commit or share it.

```bash
docker compose up --build
```

`sim` must pass its healthcheck before `agent` starts. Attach to the
agent's TUI in another terminal:

```bash
docker compose attach agent
```

Try: "read the arm state, then move joint 0 to 45 degrees" — expect
exactly two tool calls (`get_arm_state`, `move_joint`). The agent also
loads [`ai-agent/AGENTS.md`](ai-agent/AGENTS.md) (baked into the image as
global instructions, so it applies without a project-trust prompt) —
workflow guidance like "call `wait_for_arm` after a move before
depending on it" and worked examples for pick-and-place. Every tool call
is logged to the agent's stdout (`docker compose logs agent`) as
`[tool] <timestamp> -> name method path` / `<- name ok (Nms)` for
debugging.

The extension itself is defensive about `sim` being unreachable or slow:
every call has a 10s timeout, transient failures (network errors, 5xx)
retry twice with backoff — but a real rejection (4xx, e.g. bad
`joint_id`) never retries, since retrying an identical bad request just
fails identically. It also caches `/capabilities` on first use and
rejects obviously-invalid `joint_id`s or wildly-out-of-reach poses
client-side (logged as `CLIENT-SIDE REJECT`) before ever calling `sim`,
saving a round trip on requests that can't possibly succeed.

## Watching the arm move

`sim` runs PyBullet headless (`p.connect(p.DIRECT)`, no ports exposed —
required by [SPEC.md](SPEC.md)'s isolation rules), so there's nothing to
look at by default. `watch-arm.py` opens a local 3D viewer on your host
that mirrors the live state without breaking that isolation: it never
opens a direct network route to `sim`. On startup it fetches the URDF
path from `sim`'s own `/capabilities` (never hardcoded, so the viewer
always matches whatever model is actually loaded), then spawns a single
long-lived `docker compose exec` process that loops inside the `sim`
container polling its own `/state` and streaming one JSON line per tick
back over stdout — cheaper than re-spawning `docker compose exec` on
every poll, and self-healing (exponential-backoff restart) if the stream
ever dies.

The window shows:
- the arm's **actual** pose (solid), driven by a real position-control
  motor + `stepSimulation` so it eases into place instead of teleporting
  between updates;
- a translucent blue **ghost** of the arm at its *commanded target*
  pose, so you can see how far an in-flight move still has to go;
- a small **red sphere** at the end-effector position, plus an **RGB
  axis triad** (X red, Y green, Z blue) showing its orientation;
- a **fading red trail** of the end-effector's actual recent path (last
  3s) — not a preview of an in-flight `move_trajectory`'s upcoming
  waypoints (sim's `/state` never exposes those; the whole sequence runs
  server-side within one blocking request), just where it's actually
  been, which is what's observable from outside sim;
- each joint **tints yellow, then red** as its angle approaches that
  joint's real hardware limit (from `/capabilities`) — a visual reason
  for a move getting clamped, instead of just a number;
- a translucent **shell** around the base showing the arm's reach
  envelope (`reach_min_m`..`reach_max_m`) — makes an `UNREACHABLE_POSE`
  rejection visually obvious instead of a guess;
- a legend explaining the above, plus camera controls;
- an on-screen overlay of `sim`'s own state summary, grip force, render
  FPS, and state-stream age (to tell a slow viewer from a slow sim
  connection) — the summary line turns red, with a "STALE" warning
  showing the age in seconds, if the stream goes quiet, and briefly
  **flashes yellow** when a *new* error first appears (hard to miss even
  if you glanced away), with the last rejected command's error appended,
  plus the last few entries from `sim`'s own `/rejected_history`.

The overlay text, axis triad, trail, and joint-limit coloring redraw at
a throttled 5Hz (motion itself still updates at the full 60Hz render
rate) — no point re-uploading debug text/lines faster than anyone can
read them.

Camera: mouse drag orbits, scroll zooms, ctrl+drag pans (PyBullet's
built-in GUI navigation). Keyboard: `1`/`2`/`3`/`4` jump to
front/side/top/isometric presets, `r` resets to the startup view, `c`
saves the current view as a custom slot (persisted to
`~/.cache/watch-arm/camera.json`, so it survives a restart), `5` recalls
it, and `p` saves a screenshot PNG to `~/watch-arm-screenshots/`.

Requires a few packages on the host: `pip3 install --user -r
viewer/requirements.txt` (`pybullet` for the GUI itself; `loguru` for
leveled/formatted logging instead of bare `print()`; `tenacity` for the
stream's reconnect-with-backoff loop; `typer` for the CLI below;
`pydantic` to validate `/state`/`/capabilities` payloads at the viewer's
own boundary, same as `sim`'s own FastAPI layer already does
server-side; `Pillow` to save screenshots as PNGs).

```bash
python3 watch-arm.py &
python3 watch-arm.py --render-hz 30 --poll-interval-s 0.1 --quiet &   # tunable via CLI, no source edits needed
python3 watch-arm.py --help
```

Leave it running, then drive the arm as usual via `docker compose attach
agent` (or any `move_joint` / `move_to_pose` / `grip` call) — the window
updates in real time. Stop it with `pkill -f watch-arm.py` (or Ctrl+C
in its terminal — either way it cleans up its `docker compose exec`
subprocess rather than leaving it orphaned).

## Two-agent mode: Planner + Executor

Besides the interactive single-session mode above, `orchestrator.js`
runs the same task as a **Planner** (no tools, decomposes a high-level
task into an ordered list of atomic, coordinate-free steps — see
[`ai-agent/PLANNER.md`](ai-agent/PLANNER.md)) followed by a fresh
**Executor** `pi` process per step (the same tool set and workflow as
above, from [`ai-agent/AGENTS.md`](ai-agent/AGENTS.md), including its
"canned skills" section for a few pre-tuned gestures like waving or
bowing). Each Executor run gets only a one-line summary of the previous
step, not the whole task's history — so long plans don't accumulate
context the way a single long-lived session would. It ends its reply
with `STATUS: DONE` or `STATUS: FAILED - <reason>` (missing that line
counts as failure — fail-closed).

On failure, the orchestrator doesn't just stop: it calls the Planner
again with the original task, the steps already completed, and why the
next one failed, and gets back a revised list of remaining steps —
closed-loop, up to `MAX_REPLANS` (3) attempts before giving up for
good. A vague replanned step can itself fail (a fresh Executor process
has no memory of earlier numeric detail, only the step's text — asking
a clarifying question with no tool calls also counts as failure, since
there's no `STATUS` line), which just triggers another replan attempt.

Both agents carry a few more safety valves: the Planner's own plan is
capped at `MAX_STEPS` (20) — a task decomposed far more granularly than
intended fails fast with a clear message instead of quietly spawning
dozens of processes — and each Executor step gets a timeout and
tool-call ceiling scaled to whether it looks geometry-heavy (2 min / 15
calls for a plain step, 10 min / 40 for a complex one, also what decides
the `--thinking high` bump), so a plain step that blows its tight budget
is treated as stuck rather than made to wait as long as a hard one.
`PLANNER.md` also knows the same named canned skills as `AGENTS.md`, so
it phrases a matching step with the exact catalog name the Executor
looks for, instead of missing the fast path by wording it differently.

A few more quality-of-life pieces: every `pi` invocation (Planner,
each replan, each Executor step) logs a `[heartbeat]` line every 15s
while it's still working, so a long silent stretch (the LLM thinking,
not calling tools) doesn't look indistinguishable from a hang. The final
line reports the run's total cost, summed across every invocation.
`PLANNER_MODEL` (env var, or `--planner-model` on the CLI, unset by
default) lets the Planner run on a different — e.g. cheaper/faster —
model than the Executor, since decomposing a task into plain-language
steps is a much lighter job than reasoning about tool calls and
geometry. And every run, whether it
completes or fails, appends one line to
`/data/run_history.jsonl` — an agent-exclusive volume (`agent_logs`,
mirroring `sim_memory`'s pattern on the other container, never mounted
into `sim`) purely for a human to audit afterwards, not read by any LLM.
The file rotates (single backup generation) past 5MB.

Each record has a short `runId`, printed at the start of the run and
also the filename of that run's full raw output — every `[tool]`/
`[heartbeat]`/`[planner]`/`[executor]` line, not just the summary — at
`/data/runs/<runId>.log`, so a specific past run's detail is always one
`docker compose exec agent cat /data/runs/<id>.log` away instead of
being lost once it scrolls out of `docker compose logs`. Cost is broken
down by role (`plannerCost`/`executorCost`, not just a total); each step
records whether it used a named canned skill (validated against the
same catalog `AGENTS.md`/`PLANNER.md` know — a typo'd or hallucinated
name is flagged, not silently trusted) or improvised; and each replan
attempt records the failed step, why, and its `error_code` where
recoverable. `QUIET=1` (env var, or `-q`/`--quiet` on the CLI) silences
`[heartbeat]` lines on the live console — they're still written to the
run's log file either way. `docker compose exec agent node
orchestrator/stats.js` aggregates all of this across the whole log
(cost split, replan rate, which `error_code`s trigger replans most,
canned-skill usage) instead of re-deriving it by hand.

```bash
docker compose exec agent node orchestrator.js "wave hello"
docker compose exec agent node orchestrator.js "pick up the cube and place it on the tray"
docker compose exec agent node orchestrator.js --quiet --planner-model openai/gpt-mini-latest "bow"
docker compose exec agent node orchestrator.js --help
```

CLI flags (`commander`) and env vars both work — a flag sets the
matching env var internally before the rest of the orchestrator loads,
so either style configures the same underlying settings
(`orchestrator/constants.js`, validated at startup via `envalid` — an
invalid value like `QUIET=notabool` fails fast with a clear message
instead of silently misbehaving). Crash-retry (`pi-runner.js`) is
`p-retry` under the hood, kept at exactly one fixed-delay retry to match
the original design (a second consecutive crash is treated as a
persistent problem, not more attempts).

Every orchestrator-issued `pi` process also gets `--no-session`, the
Planner specifically gets `--thinking low --offline` (lighter job than
the Executor, no startup checks it needs), and the interactive `pi`
session (the one path that's actually meant to be resumable) has its
own storage pointed at `/data/pi-sessions` instead of the container's
writable layer — otherwise every single `pi -p` call the orchestrator
ever makes (there can be dozens across one long-running task's replans
and steps) would leave behind a session file nobody prunes, for as long
as the container stays up (`restart: unless-stopped`).

This adds no new services, ports, or network paths — it's a plain
Node script run inside the already-running `agent` container via
`docker compose exec`, spawning `pi` as a subprocess exactly like the
interactive CLI does.

## Tools the agent can call

| Tool | What it does |
|---|---|
| `get_arm_state` | Joint angles, velocities, applied torques, commanded targets, `reached` flags, end-effector position/orientation, grip force, summary, last error |
| `get_arm_capabilities` | Static joint limits, reach envelope, safety thresholds, timing constants |
| `wait_for_arm` | Block until the arm (or specific joints) reaches its target, or timeout |
| `move_joint` / `move_joints` | Move one or several joints to target angles (degrees, absolute or `relative`); batched moves arrive together |
| `preview_move_joint` / `preview_move_to_pose` | Dry-run validation — check if a move would succeed, without moving the arm |
| `preview_pose_candidates` | Same dry-run check for several poses in one call, instead of previewing one at a time |
| `pose_toward_reach_limit` | Given a direction (possibly unreachable), returns the farthest actually-reachable point along it — one server-side binary search instead of manually guessing points with `preview_move_to_pose` |
| `move_to_pose` | Move the end effector to (x, y, z), optional roll/pitch/yaw, via inverse kinematics |
| `move_trajectory` | Move through a sequence of poses in order, stopping at the first one that fails |
| `grip` / `release_gripper` | Set grip force / release (current placeholder URDF has no gripper actuator — records the value) |
| `pick_and_place` | Composite: move to pick pose → grip → move to place pose → release, blocking until done |
| `stop_arm` | Immediately halt joint motion in place (all joints, or a specific subset) |
| `reset_environment` | Reset the simulation to its home pose (also clears rejected-command history) |
| `get_rejected_history` | Last 10 rejected commands and why, so the agent can check what it already tried |
| `get_error_recovery_hints` | Structured, sim-sourced recovery guidance per `error_code` |

Every move is validated server-side before it ever reaches a motor: clamped to
the real per-joint hardware limits read from the URDF (not just a generic
ceiling), and rejected if it would cause a self-collision, land outside the
arm's reach, or approach a kinematic singularity. Rejections return a
machine-readable `error_code` (`SELF_COLLISION`, `UNREACHABLE_POSE`,
`NEAR_SINGULARITY`, `RATE_LIMITED`, `JOINT_OUT_OF_RANGE`). Mutating tool
calls carry an idempotency key (the harness's own `toolCallId`, not
LLM-supplied) so a retried call replays the prior result instead of
re-executing. Full endpoint/tool contract: [SPEC.md §4.3 / §5.3](SPEC.md).

`sim` is otherwise fully ephemeral (`/reset` wipes physics state, and
nothing survives a container restart) except for one deliberate
exception: a small persistent "pose memory" on its own Docker volume
(never shared with `agent`), recording every Cartesian pose it's ever
validated and whether that pose succeeded or was rejected. `preview_move_to_pose`/`preview_pose_candidates` responses include a
`previously_tried` field when a past attempt landed near the requested
point — survives `/reset` and container restarts, invalidated only if
the URDF changes.

## Swapping providers

`pi` auto-detects credentials from env vars (`ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, ...). To switch the default,
edit `defaultProvider`/`defaultModel` in
[ai-agent/settings.json](ai-agent/settings.json) (baked into the image
at `/root/.pi/agent/settings.json`, so it applies without a project-trust
prompt) and set the matching key in `.env`. No changes to `robot-arm/` or
`ai-agent/extensions/robot-arm-extension/` are needed.

## Verifying isolation

```bash
# sim has no route out (internal: true on the control network)
docker compose exec agent node -e "fetch('http://sim:8000/health').then(r=>r.json()).then(console.log)"   # succeeds
docker compose exec sim python3 -c "import socket; socket.setdefaulttimeout(3); socket.gethostbyname('api.anthropic.com')"  # fails: no route

# sim exposes only the fixed endpoint set
docker compose exec agent node -e "fetch('http://sim:8000/openapi.json').then(r=>r.json()).then(j=>console.log(Object.keys(j.paths).sort()))"
```

## Layout

```
ai-arm/
├── SPEC.md
├── docker-compose.yml
├── watch-arm.py           local 3D viewer entrypoint (host-side, read-only), typer CLI
├── viewer/
│   ├── requirements.txt    host-side deps: pybullet, loguru, tenacity, typer, pydantic, Pillow
│   ├── schemas.py           pydantic PolledPayload/StatePayload/RejectedAttempt/Capabilities/
│   │                          JointLimit/StreamError — validates sim's wire formats, nothing else
│   ├── snapshot.py           StateSnapshot dataclass — the render-loop-facing shape
│   ├── sim_exec.py            docker-exec plumbing: fetch_capabilities(), poll command builder
│   │                            (bundles /state + /rejected_history into one polled line)
│   ├── state_stream.py         StateStream — background thread, tenacity retry,
│   │                             lock-guarded snapshot access (imports the three above)
│   ├── joint_limits.py           per-joint hardware-limit proximity -> warning color
│   ├── trail.py                   end-effector recent-position breadcrumb buffer
│   ├── screenshot.py               'p' -> PNG via Pillow
│   ├── camera.py                    presets + keyboard shortcuts + persisted custom view
│   └── overlay.py                    axis triad, overlay text/color, error-flash,
│                                       recent-rejection-history logic
├── robot-arm/            sim — Container A
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── server.py          entrypoint: builds the FastAPI app, starts stepping
│   └── app/
│       └── arm/              single feature module (NestJS-style): everything
│                              the arm needs lives here
│           ├── arm_module.py   composition root — builds ArmService, wires
│           │                    the routers below into one router
│           ├── arm_service.py  coordinates the support/ collaborators
│           ├── constants.py    safety limits, URDF path
│           ├── schemas.py      pydantic request/response models
│           ├── adapters/       raw PyBullet calls, no domain rules
│           ├── routes/         one file per resource area: state_routes.py,
│           │                    joint_routes.py, pose_routes.py,
│           │                    gripper_routes.py, macro_routes.py,
│           │                    safety_routes.py
│           └── support/        single-purpose collaborators used by both
│                                arm_service.py and routes/: exceptions.py,
│                                rate_limiter.py, idempotency_cache.py,
│                                motion_validator.py, motion_driver.py,
│                                error_mapping.py, idempotency.py, presenters.py
└── ai-agent/              agent — Container B
    ├── Dockerfile
    ├── package.json
    ├── AGENTS.md            Executor workflow guidance + examples, loaded as global instructions
    ├── PLANNER.md           Planner-only instructions (§ Two-agent mode)
    ├── orchestrator.js      thin entrypoint — commander CLI parsing + exit code only
    ├── orchestrator/
    │   ├── constants.js       tunable timeouts/caps/paths/QUIET/KNOWN_SKILLS, nothing else
    │   ├── cost-tracker.js      shared {total, planner, executor} accumulator
    │   ├── pi-runner.js           spawns/streams `pi`, extracts cost/text, crash-retries once
    │   ├── logger.js                pino: structured per-run log at /data/runs/<runId>.log +
    │   │                              plain-text console (QUIET drops [heartbeat] from console only)
    │   ├── planner.js                  plan()/replan(), talks to pi-runner
    │   ├── executor.js                   executeStep()/statusOf(), talks to pi-runner
    │   ├── run-history.js                  appendRunHistory() — writes/rotates run_history.jsonl
    │   ├── run.js                            the plan → execute → replan control loop
    │   └── stats.js                            `node orchestrator/stats.js` — aggregate summary
    └── extensions/
        └── robot-arm-extension/   directory-style extension (pi's "index.ts + helpers" pattern)
            ├── index.ts             composition root — registers each tool group
            ├── support/               sim-client.ts (HTTP+retry+timeout+logging),
            │                            validation.ts (client-side pre-checks), schema.ts
            └── tools/                   one file per resource group, mirrors
                                           robot-arm/app/arm/routes/ 1:1
```
