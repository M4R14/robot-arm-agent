# SPEC: RobotArmAgent — Isolated Robot Arm Sim + AI Agent (2-Container System)

## 1. Objective

Build a system where an LLM agent can control a simulated robot arm, with
a hard isolation boundary between the two:

- **Environment 1 — `sim`**: runs the physics simulation. Must never
  execute arbitrary code sent from outside. Exposes only a fixed,
  validated HTTP API.
- **Environment 1 — `agent`**: runs the LLM agent harness. Must never
  read, write, or edit files, and must never run shell commands. It may
  only call a fixed set of whitelisted tools that map 1:1 to the sim's
  HTTP API.

The two run as separate Docker containers connected only by an internal
Docker network. `sim` has no route to the internet. `agent` reaches the
LLM provider's API over a separate egress network.

This is a hard security/architecture requirement, not a style preference.
Do not introduce any endpoint or tool that accepts a script, shell
command, file path, or arbitrary code payload.

## 2. Non-goals

- Real hardware integration (out of scope for this spec; interface is
  designed so a future `real-arm` service could implement the same HTTP
  API as `sim` and be swapped in without changing `agent`).
- Multi-arm / multi-agent coordination.
- Authentication between containers (network isolation is the boundary
  for this phase; add mTLS or a shared secret later if `sim` is ever
  exposed beyond the internal Docker network).

## 3. Architecture

```
Container A: sim                  Container B: agent
------------------                 -------------------
PyBullet physics engine             pi coding-agent harness
FastAPI HTTP server                 (--no-builtin-tools)
Fixed, validated endpoints only     Custom extension registers
                                     ONLY whitelisted tools

        ▲
        │ "control" network (Docker bridge, internal: true — no egress)
        │
        └────────────────────────────────────┘
                                               │
                                               │ "egress" network (NAT out)
                                               ▼
                                     LLM provider API
                                     (api.anthropic.com / api.openai.com)
```

- `control` network: internal only, no route to the internet. `sim` is
  attached only here.
- `egress` network: normal bridge with NAT. `agent` is attached to both
  `control` (to reach `sim`) and `egress` (to reach the LLM provider).
- No shared filesystem or volume mount between the two containers.

## 4. Component: `sim` (Container A)

### 4.1 Stack
- Python 3.11
- PyBullet (physics)
- FastAPI + Uvicorn (HTTP server)
- Pydantic (request/response schemas)

### 4.2 Responsibilities
- Load a robot arm URDF at startup (configurable path, placeholder:
  `kuka_iiwa/model.urdf` from `pybullet_data`).
- Step the physics simulation.
- Expose the fixed endpoint set below. **No other endpoints.**
- Validate every request server-side (never trust the caller's ranges).
- Never accept or execute a request body containing code, a script, or
  a shell command.

### 4.3 API contract

All request/response bodies are typed Pydantic models. No endpoint may
accept a free-form string that gets executed, evaluated, or interpreted
as code.

| Method | Path                   | Request body | Response | Notes |
|--------|------------------------|--------------|----------|-------|
| GET    | `/health`              | — | `{ ok: bool }` | for `docker compose` healthcheck |
| GET    | `/state`               | — | `{ joints: [{joint_id, angle_deg, velocity_deg_s, applied_torque, target_angle_deg, reached}], end_effector_position: [x,y,z], end_effector_orientation: [x,y,z,w] (quaternion), grip_force: float, last_error?: {error_code, message}, summary: str }` | read-only; `last_error` clears on the next successful mutating command |
| GET    | `/capabilities`        | — | `{ urdf_path, joint_ids, joint_limits: [{joint_id, min_deg, max_deg}], reach_min_m, reach_max_m, max_force, max_joint_velocity_deg_s, singularity_condition_threshold, ik_reachable_tolerance_m, min_command_interval_s, default_wait_timeout_s, max_wait_timeout_s, home_pose_deg }` | read-only; static limits/tuning, so a caller can plan instead of guessing. `reach_min_m`/`reach_max_m` are estimated by sampling random valid joint configurations (no closed-form workspace boundary for a 7-DoF arm), cached until the next `/reset` |
| POST   | `/wait_reached`        | `{ joint_ids?: int[], timeout_s?: float }` | `{ reached: bool, timed_out: bool, joints: [...] }` | read-only; blocks (server-clamped timeout) until all named joints reach their commanded target |
| POST   | `/move_joint`          | `{ joint_id: int, target_angle_deg: float, relative?: bool, command_id?: str }` | `{ ok: bool, message: str }` | clamp to the tighter of `[JOINT_ANGLE_MIN_DEG, JOINT_ANGLE_MAX_DEG]` and the joint's real URDF limit; validate `joint_id` in range; reject on self-collision or near-singularity; `relative` adds to the joint's current angle instead of an absolute target |
| POST   | `/move_joints`         | `{ targets: [{joint_id, target_angle_deg}], relative?: bool, command_id?: str }` | `{ ok: bool, message: str }` | batch of `/move_joint`, validated as one resulting pose, synchronized arrival |
| POST   | `/preview_move_joint`  | `{ joint_id: int, target_angle_deg: float, relative?: bool }` | `{ ok: bool, reason?: str }` | read-only; runs the same validation as `/move_joint` without moving the arm |
| POST   | `/move_to_pose`        | `{ x, y, z, roll_deg?, pitch_deg?, yaw_deg?, relative?: bool, command_id? }` | `{ ok: bool, message: str }` | inverse kinematics; reject if unreachable, self-colliding, or near-singular; `relative` adds (x,y,z) to the current end-effector position (orientation stays absolute) |
| POST   | `/preview_move_to_pose`| `{ x, y, z, roll_deg?, pitch_deg?, yaw_deg?, relative?: bool }` | `{ ok: bool, reason?: str, previously_tried?: {outcome, error_code?, recorded_at} }` | read-only; runs the same validation as `/move_to_pose` without moving the arm; `previously_tried` is the nearest recorded pose-memory fact within `POSE_MEMORY_LOOKUP_RADIUS_M`, if any (see §6 persistent pose memory) |
| POST   | `/preview_candidates`  | `{ candidates: PoseTarget[] }` | `{ results: [{index, ok, reason?, previously_tried?}] }` | read-only; runs `/preview_move_to_pose` validation (incl. pose-memory lookup) on several poses in one call — evaluating options is one HTTP call, not N |
| POST   | `/move_trajectory`     | `{ waypoints: PoseTarget[], command_id? }` | `{ ok: bool, waypoints: [{index, ok, reached, reason?}], message: str }` | moves through poses in order, waiting for each; stops at the first waypoint that fails validation rather than skipping it |
| POST   | `/grip`                | `{ force: float, command_id?: str }` | `{ ok: bool, message: str }` | clamp `force` to `[0, MAX_FORCE]`; current placeholder URDF has no gripper actuator |
| POST   | `/release`             | — | `{ ok: bool, message: str }` | alias for `/grip` with `force: 0` |
| POST   | `/pick_and_place`      | `{ pick: PoseTarget, place: PoseTarget, grip_force: float, command_id? }` | `{ ok, reached_pick, reached_place, message }` | composite: move to pick → grip → move to place → release; blocks until done |
| POST   | `/stop`                | `{ joint_ids?: int[] }` (body optional) | `{ ok: bool, message: str }` | halts named joints (or all, if omitted) at their current position; never rate-limited |
| POST   | `/reset`               | — | `{ ok: bool, message: str }` | reset simulation to `HOME_POSE_DEG`; also clears `/rejected_history` |
| GET    | `/rejected_history`    | — | `{ entries: [{error_code, message, details}] }` | read-only; last `REJECTED_HISTORY_MAX` (10) rejected commands, oldest first, so a caller can check what it already tried before repeating a mistake |
| GET    | `/error_recovery_hints`| — | `{ hints: {error_code: str} }` | read-only; static, structured recovery guidance per `error_code` — single-sourced here rather than duplicated in caller instructions |
| GET    | `/metrics`             | — | `{ accepted: int, rejected: int, rejected_by_code: {error_code: int}, rejection_rate: float }` | read-only; in-memory running counters (`adapters/driven/metrics.py`), reset to zero on container restart (a tally, not a record — unlike `/rejected_history` and pose memory, nothing about it needs to survive one). **Not part of §5.3's agent tool set** — human-debugging only, same "not read by any LLM" carve-out as the agent side's `run_history.jsonl`; never called by the extension or orchestrator |

All mutating endpoints accept an optional `command_id: str`; a repeated
`command_id` within a short TTL replays the cached response instead of
re-executing (idempotency for caller retries) — `adapters/driven/idempotency_cache.py`
is `cachetools.TTLCache` under the hood, not a hand-rolled dict+eviction
loop. Every accept/reject also logs via `loguru`
(`adapters/driven/metrics.py`/`application/arm_service.py`'s `_note_error`/`_note_success`,
the same choke point `/rejected_history` and `/metrics` are populated
from) — `docker compose logs sim` now shows structured
`command rejected: <error_code> — <message>` /
`command accepted` lines, not just uvicorn's own access log.

A hand-rolled cooldown (`domain/rate_limiter.py`, rejects a mutating
call within `MIN_COMMAND_INTERVAL_S` of the last one) was evaluated
against `pyrate_limiter` and kept as-is: `pyrate_limiter`'s `Rate`/
`Limiter` are built around window/bucket rate limiting (N requests per
window), and its default `try_acquire` blocks the calling thread until a
slot frees up rather than rejecting immediately — wrong shape for this
service (a request thread blocking would stall `ArmService`'s single
lock for every other caller, not just the one being rate-limited) and
for the exact-`retry_after_s` contract `RATE_LIMITED` already promises
callers. `blocking=False` gets closer but still doesn't expose a clean
remaining-cooldown value without extra plumbing. The existing 20-line
class is simple, correct, and already covered by this project's
extensive live testing — not worth the fit mismatch.

Error responses use `{ detail: { error_code: str, message: str, ...details } }`
with `error_code` one of `JOINT_OUT_OF_RANGE`, `UNREACHABLE_POSE`,
`SELF_COLLISION`, `NEAR_SINGULARITY`, `RATE_LIMITED`. Some errors add
actionable fields beyond `message`: `UNREACHABLE_POSE` adds
`closest_achievable_position: [x,y,z]`; `RATE_LIMITED` adds
`retry_after_s: float`.

### 4.4 Safety limits (server-side constants, not caller-supplied)
- `JOINT_ANGLE_MIN_DEG` / `JOINT_ANGLE_MAX_DEG`: generic safety ceiling,
  `-170` / `170`; every move is additionally clamped to the joint's own
  real URDF hardware limit (read from the model, e.g. the KUKA iiwa's
  elbow joints are physically limited to ±120°), whichever is tighter.
- `MAX_FORCE`: cap motor force / grip force; placeholder `200`.
- `MAX_JOINT_VELOCITY_DEG_S`, `POSITION_GAIN`, `VELOCITY_GAIN`: motor
  tuning so joints slew at a bounded, realistic rate.
- `SINGULARITY_CONDITION_THRESHOLD`: reject moves whose resulting pose's
  end-effector Jacobian condition number exceeds this (near-singular).
- `MIN_COMMAND_INTERVAL_S`: minimum spacing between mutating commands.
- Reject (`HTTP 400`) any `joint_id` outside `[0, num_joints)`.

Every mutating endpoint validates the *resulting* pose server-side
(kinematic dry-run, restored before replying) for self-collision and
singularity before ever commanding a motor — never trust the caller's
target, even one that looks in-range.

### 4.5 Explicitly forbidden
- No `/exec`, `/run_script`, `/eval`, or any endpoint that accepts code.
- No endpoint that writes to or reads from the container filesystem based
  on caller input.
- No endpoint that shells out based on caller input.

## 5. Component: `agent` (Container B)

### 5.1 Stack
- Node.js 22
- `@earendil-works/pi-coding-agent` (pi), installed globally
- A single TypeScript extension registering the tool set (pi supports
  the "directory with index.ts" extension style for multi-file
  extensions — see `docs/extensions.md` — so internal code organization
  across files is fine; what matters is exactly one extension is loaded)

### 5.2 Responsibilities
- Run `pi` with `--no-builtin-tools` (strips `read`, `write`, `edit`,
  `bash`, `grep`, `find`, `ls` entirely — these must not exist for the
  LLM under any configuration).
- Load exactly one extension (`robot-arm-extension/index.ts`) that
  registers the tool set in §5.3.
- Each tool implementation must do nothing except: validate its typed
  input against its schema, make one HTTP call to `sim` at
  `SIM_URL` (env var, default `http://sim:8000`), and return the result.
- No tool may take a free-form string parameter intended for
  code/script/shell execution.
- LLM provider is swappable via env var / `pi` provider config
  (Anthropic and OpenAI both supported by `pi`); no change to tool
  definitions or to `sim` required when swapping.

### 5.3 Tool set (LLM-facing, must match `sim`'s endpoints 1:1)

| Tool name              | Parameters | Calls |
|------------------------|------------|-------|
| `get_arm_state`        | *(none)* | `GET /state` |
| `get_arm_capabilities` | *(none)* | `GET /capabilities` |
| `wait_for_arm`         | `{ joint_ids?: int[], timeout_s?: number }` | `POST /wait_reached` |
| `move_joint`           | `{ joint_id: int, target_angle_deg: number, relative?: boolean }` | `POST /move_joint` |
| `move_joints`          | `{ targets: [{joint_id, target_angle_deg}], relative?: boolean }` | `POST /move_joints` |
| `preview_move_joint`   | `{ joint_id: int, target_angle_deg: number, relative?: boolean }` | `POST /preview_move_joint` |
| `move_to_pose`         | `{ x, y, z, roll_deg?, pitch_deg?, yaw_deg?, relative?: boolean }` | `POST /move_to_pose` |
| `preview_move_to_pose` | `{ x, y, z, roll_deg?, pitch_deg?, yaw_deg?, relative?: boolean }` | `POST /preview_move_to_pose` |
| `preview_pose_candidates` | `{ candidates: PoseTarget[] }` | `POST /preview_candidates` |
| `pose_toward_reach_limit` | `{ x, y, z, roll_deg?, pitch_deg?, yaw_deg? }` | `POST /pose_toward_reach_limit` |
| `move_trajectory`      | `{ waypoints: PoseTarget[] }` | `POST /move_trajectory` |
| `grip`                 | `{ force: number }` | `POST /grip` |
| `release_gripper`      | *(none)* | `POST /release` |
| `pick_and_place`       | `{ pick: PoseTarget, place: PoseTarget, grip_force: number }` | `POST /pick_and_place` |
| `stop_arm`             | `{ joint_ids?: int[] }` | `POST /stop` |
| `reset_environment`    | *(none)* | `POST /reset` |
| `get_rejected_history` | *(none)* | `GET /rejected_history` |
| `get_error_recovery_hints` | *(none)* | `GET /error_recovery_hints` |

`move_joint`, `move_joints`, `move_to_pose`, `move_trajectory`, `grip`, and
`pick_and_place` also pass the harness's `toolCallId` as `command_id` for
idempotent retries — never LLM-supplied, so it can't be spoofed or
omitted by the model. The extension prefixes it with a random ID
generated once per `pi` process (`commandId()` in `sim-client.ts`):
`toolCallId` alone is only unique within one process, and §5.5's
orchestrator spawns a fresh process per step, so without the prefix two
different steps' calls could collide on the same `command_id` string
within sim's 5s idempotency TTL — sim would then silently replay one
step's cached response for another step's different request instead of
executing it.

No tool beyond this set may be registered without updating this spec.

### 5.4 Explicitly forbidden
- No built-in `bash`/`read`/`write`/`edit`/`grep`/`find`/`ls` tools
  active, under any circumstances.
- No tool that accepts arbitrary code, shell commands, or file paths.
- No shared volume/mount between `agent` and `sim`.
- No tool that lets the LLM change its own tool whitelist at runtime.

### 5.5 Optional invocation mode: Planner + Executor orchestration

`orchestrator.js` (plain Node, no build step) is an alternative entry
point run via `docker compose exec agent node orchestrator.js "<task>"`
(or with flags — `--quiet`, `--planner-model <model>`, `--help`; parsed
by `commander`) instead of the interactive `pi` session — it is not a
new service, port, or network path, and it adds no tools beyond §5.3. A
CLI flag sets its matching env var (`orchestrator.js` dynamically
imports the rest of `./orchestrator/` only after doing so, since a
static top-level `import` would already have evaluated
`orchestrator/constants.js` — which validates `SIM_URL`/`PLANNER_MODEL`/
`QUIET` via `envalid`, failing fast with a clear message on an invalid
value — before any of `orchestrator.js`'s own code runs). It spawns `pi`
as a subprocess twice per task:

- **Planner**: `pi -p --no-tools --no-context-files --thinking low
  --offline --system-prompt <PLANNER.md>` — zero tools, decomposes the
  task into an ordered list of coordinate-free natural-language steps
  (JSON output). Never talks to `sim` directly or indirectly.
  `--thinking low` (vs. the Executor's inherited `medium` default, or
  `high` for complex steps) matches its lighter job — pure text
  decomposition, no tool-use/geometry reasoning. `--offline` skips pi's
  own startup checks (model catalog refresh, update check); the actual
  inference request still goes out over the network as normal, this
  only trims fixed per-process overhead the Planner has no use for.
- **Executor**: one fresh `pi -p --no-builtin-tools --no-extensions -e
  robot-arm-extension/index.ts` process per step, identical tool set and
  `AGENTS.md` workflow to interactive mode, with a short
  `--append-system-prompt` addendum carrying only the current step text
  and a one-line summary of the previous step (not the full task
  history). Each Executor process ends its reply with a `STATUS: DONE`
  / `STATUS: FAILED - <reason>` line; a missing line counts as failure.

On failure, the orchestrator calls the Planner again (same
`--no-tools --no-context-files` invocation) with the original task, the
already-completed steps, and the failure reason, and replaces the
remaining plan with its response — closed-loop, capped at
`MAX_REPLANS = 3` attempts so a persistently-failing step can't loop
forever.

Before each Executor step, `orchestrator.js` also makes one direct
read-only `GET /state` call to `sim` itself (not through a registered
tool) to fold a current-state summary into that step's context — this
is the orchestrator script's own trusted call, at the same trust level
as the Dockerfile's `CMD`, not a capability exposed to the LLM; the
Executor's tool set is unchanged.

Every orchestrator-issued `pi` process (Planner, each replan, each
Executor step) also gets `--no-session` (added once, in
`pi-runner.js`'s `runPiOnce()`, so every call site gets it automatically
rather than each remembering to add it) — each is single-shot and
already fully tracked by `run_history.jsonl`/`/data/runs/`, so pi's own
session mechanism would just accumulate unpruned files under
`~/.pi/agent/sessions` for the container's entire `restart:
unless-stopped` lifetime otherwise. The interactive `CMD` (§5.2) is the
one legitimate exception — it's meant to be resumable — so it instead
points `--session-dir` at `/data/pi-sessions` (the same `agent_logs`
volume, so it survives a container restart instead of living in the
writable layer).

Each Executor process is bounded by a per-step timeout and tool-call
ceiling, killed and treated as a normal step failure (triggering a
replan) if either is exceeded — so one stuck or runaway step can't hang
the whole run. The budget scales with whether the step text looks like
it needs real geometric reasoning (`COMPLEX_STEP_PATTERN`, also what
decides the `--thinking high` bump): 2 min / 15 tool calls for a plain
step, 10 min / 40 tool calls for a complex one — a plain step that blows
through the tight budget is almost certainly stuck, not just slow, so it
fails fast rather than waiting as long as a genuinely hard step is
allowed to.

The Planner's own output is capped at `MAX_STEPS = 20` — decomposing a
task far more granularly than intended fails the whole run immediately
with a clear message, rather than silently spawning dozens of sequential
Executor processes. `PLANNER.md` also documents the same named canned
skills as `AGENTS.md`'s "Canned skills" section (kept in sync by hand),
so the Planner phrases a matching step using the exact catalog name and
the Executor's fast pre-tuned path actually gets hit instead of being
missed by wording mismatch.

`PLANNER_MODEL` (env var, passed through in `docker-compose.yml`,
unset/empty by default) lets the Planner run on a different `--model`
than the Executor, which always uses `settings.json`'s default — pure
decomposition is a lighter task than tool-use/geometry reasoning, so a
cheaper or faster model is a reasonable choice there without touching
the Executor. Cost is tracked regardless: every `pi` invocation's
`message_end` events are summed (`extractCost()`), including partial
cost from a run killed by the timeout/tool-call caps above, and the
total is both printed at the end and included in the run-history record
below.

A `pi` process that exits non-zero on its own (a crash — network blip,
provider hiccup — as opposed to one we killed ourselves via the
timeout/tool-call caps above, which resolves normally with a
`killedReason` instead of rejecting) is retried once, via `p-retry`
(`retries: 1`, fixed `CRASH_RETRY_DELAY_MS` delay — no exponential
backoff), before propagating as a real failure — a second consecutive
crash is treated as a persistent problem, not bad luck. Replanning also
gets the Executor's full final report, not just
the short failure reason, since sim's own rejection messages often carry
detail (e.g. `closest_achievable_position`) worth acting on. The
Planner's JSON response is extracted via a balanced-brace scan for the
first complete top-level object (`extractFirstJsonObject()`), not a
greedy first-`{`-to-last-`}` regex — the latter would swallow anything
after the JSON if the Planner ever appended trailing text containing a
brace.

Every `orchestrator.js` run — whether it completes or fails — appends
one JSON line to `/data/run_history.jsonl` on a new `agent_logs` Docker
volume, mounted only into `agent` (mirroring `sim_memory`'s
one-container-only mounting on the other side — never mounted into
`sim`, so this doesn't weaken the isolation boundary either direction).
Purely a human-facing audit trail (`docker compose exec agent cat
/data/run_history.jsonl`); no LLM reads it, and a write failure there is
non-fatal to the run it's describing. The file rotates once it crosses
5MB (current file renamed to `.1`, a fresh one started) — single
generation, not a retained history, just enough to stop unbounded
growth.

Each record carries: a short `runId` (also the filename, under
`/data/runs/<runId>.log` on the same volume, of that run's complete
structured log — every `[tool]`/`[heartbeat]`/`[planner]`/`[executor]`
line, via a `pino` logger opened for the run's duration in `logger.js`
and closed in the same `finally` as the summary record — not just what
`run_history.jsonl` itself keeps). `pino.multistream` fans each message
out to two destinations at different levels: the file gets everything
(`trace`) as pino's normal structured JSON; the console gets a custom
`Writable` that reformats each record back to the plain
`[label] message` text this project has always shown (`warn`/`error`
records to stderr, everything else to stdout) — `QUIET=1` raises the
console stream's minimum level to `info`, dropping `[heartbeat]` (logged
at `debug`) from the terminal without affecting the file, which stays at
`trace` regardless. `pi` children's stderr is piped (not inherited) and
logged line-by-line so their `[tool]` output reaches the same file.

Beyond the log itself, each record also carries: cost split by role
(`plannerCost`/`executorCost`, not just `totalCost`); `steps`, each with
`skillUsed: { reported, canonical }` — `canonical` is the Executor's
`SKILL:` line matched case-insensitively against `KNOWN_SKILLS`
(constants.js, kept in sync with `AGENTS.md`/`PLANNER.md`'s catalog),
`null` with `reported` still set if the name doesn't match anything
known (surfaced by `stats.js` as a possible typo/hallucination rather
than silently counted as that skill), both `null` if the step was
improvised; and `replanHistory`, one entry per replan attempt with the
failed step, failure reason, and (best-effort) `error_code` recovered by
scanning the Executor's report text for one of sim's known codes —
`null` when the rejection never reached sim at all (e.g. the extension's
own client-side reach check in `validation.ts`, which doesn't echo
sim's code names).

`QUIET=1` (env var) suppresses `[heartbeat]` lines on the live
console only — they're still written to the run's `/data/runs/` log
file regardless, so quieting the terminal never loses detail from the
persisted trace. `node orchestrator/stats.js` aggregates the whole
`run_history.jsonl` log (run/outcome counts, cost breakdown, replan
rate, error_code frequency, canned-skill usage including unrecognized
names) instead of everyone re-deriving the same numbers by hand each
time.

This keeps §5.2's per-tool contract ("validate, one HTTP call, return")
and §5.3's tool set completely untouched — the orchestration lives
entirely in how `pi` is invoked, not in new tools or new `sim` surface.

## 6. Docker Compose

- Two services: `sim`, `agent`.
- Two networks:
  - `control`: `driver: bridge`, `internal: true`. Both services attach
    here; this is the only path between them.
  - `egress`: `driver: bridge` (normal NAT). Only `agent` attaches here.
- `sim` has **no** `ports:` mapping to the host (only reachable from
  `agent` via the internal network, by service name `sim`).
- `agent` depends on `sim`'s healthcheck (`GET /health`) before starting.
- LLM credentials passed via env vars (`ANTHROPIC_API_KEY` and/or
  `OPENAI_API_KEY`), not baked into the image.
- `sim` mounts one named volume (`sim_memory:/data`) for persistent pose
  memory (§4.3 `previously_tried`) — **exclusively its own**, never
  mounted into `agent`, so the "no shared volume/mount between `agent`
  and `sim`" rule (§5.4) stays intact. This is the one deliberate
  exception to `sim`'s otherwise fully ephemeral state: it records every
  Cartesian pose validated (via `/move_to_pose` or any preview endpoint)
  and its outcome, survives `/reset` and container restarts, and is
  invalidated only when the recorded `urdf_path` no longer matches
  `URDF_PATH` (a different model has different geometry).

## 7. Acceptance criteria

1. `docker compose up --build` starts both containers; `sim` passes its
   healthcheck before `agent` starts.
2. From inside `agent`, `curl http://sim:8000/health` succeeds.
3. From inside `agent`, there is no route to any host on the public
   internet via the `control` network (verify: a request to any external
   host over that network path fails/times out — confirms `internal: true`
   is enforced).
4. Prompting the agent to "read the arm state, then move joint 0 to 45
   degrees" results in exactly two tool calls (`get_arm_state`,
   `move_joint`) and a corresponding change in `/state` output.
5. Sending an out-of-range `target_angle_deg` (e.g. 999) via `move_joint`
   results in the sim clamping it, not erroring or executing it as-is.
6. `pi --no-builtin-tools` confirmed active: attempting to get the agent
   to read or write a file (via prompt injection or direct instruction)
   fails because no such tool is registered.
7. Swapping `ANTHROPIC_API_KEY` for `OPENAI_API_KEY` (+ provider config)
   requires no changes to `sim/` or to the tool definitions in
   `robot-arm-extension/`.

## 8. Reference implementation

A working reference implementation of this spec lives in this repo:

```
ai-arm/
├── docker-compose.yml
├── robot-arm/            (sim, Container A)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── server.py
├── ai-agent/              (agent, Container B)
│   ├── Dockerfile
│   ├── package.json
│   └── extensions/robot-arm-extension/
│       ├── index.ts       composition root
│       ├── support/         sim-client.ts, validation.ts, schema.ts
│       └── tools/            one file per resource group
└── README.md
```

## 9. Follow-up work (not required for this spec, listed for context)

- Swap the placeholder `kuka_iiwa/model.urdf` for the target arm's real
  URDF; update `JOINT_ANGLE_MIN_DEG` / `MAX_DEG` / `MAX_FORCE` to match.
- Add a `real-arm` service implementing the same API as `sim`, gated
  behind an explicit human approval step before any command reaches
  physical hardware (matches existing human-approval-gate pattern used
  elsewhere in this project's agent pipeline).
- Consider mTLS or a shared secret on the `control` network if `sim` is
  ever deployed somewhere the network boundary alone isn't sufficient.
