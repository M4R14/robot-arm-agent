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
| POST   | `/preview_move_to_pose`| `{ x, y, z, roll_deg?, pitch_deg?, yaw_deg?, relative?: bool }` | `{ ok: bool, reason?: str }` | read-only; runs the same validation as `/move_to_pose` without moving the arm |
| POST   | `/preview_candidates`  | `{ candidates: PoseTarget[] }` | `{ results: [{index, ok, reason?}] }` | read-only; runs `/preview_move_to_pose` validation on several poses in one call — evaluating options is one HTTP call, not N |
| POST   | `/move_trajectory`     | `{ waypoints: PoseTarget[], command_id? }` | `{ ok: bool, waypoints: [{index, ok, reached, reason?}], message: str }` | moves through poses in order, waiting for each; stops at the first waypoint that fails validation rather than skipping it |
| POST   | `/grip`                | `{ force: float, command_id?: str }` | `{ ok: bool, message: str }` | clamp `force` to `[0, MAX_FORCE]`; current placeholder URDF has no gripper actuator |
| POST   | `/release`             | — | `{ ok: bool, message: str }` | alias for `/grip` with `force: 0` |
| POST   | `/pick_and_place`      | `{ pick: PoseTarget, place: PoseTarget, grip_force: float, command_id? }` | `{ ok, reached_pick, reached_place, message }` | composite: move to pick → grip → move to place → release; blocks until done |
| POST   | `/stop`                | `{ joint_ids?: int[] }` (body optional) | `{ ok: bool, message: str }` | halts named joints (or all, if omitted) at their current position; never rate-limited |
| POST   | `/reset`               | — | `{ ok: bool, message: str }` | reset simulation to `HOME_POSE_DEG`; also clears `/rejected_history` |
| GET    | `/rejected_history`    | — | `{ entries: [{error_code, message, details}] }` | read-only; last `REJECTED_HISTORY_MAX` (10) rejected commands, oldest first, so a caller can check what it already tried before repeating a mistake |
| GET    | `/error_recovery_hints`| — | `{ hints: {error_code: str} }` | read-only; static, structured recovery guidance per `error_code` — single-sourced here rather than duplicated in caller instructions |

All mutating endpoints accept an optional `command_id: str`; a repeated
`command_id` within a short TTL replays the cached response instead of
re-executing (idempotency for caller retries).

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
omitted by the model.

No tool beyond this set may be registered without updating this spec.

### 5.4 Explicitly forbidden
- No built-in `bash`/`read`/`write`/`edit`/`grep`/`find`/`ls` tools
  active, under any circumstances.
- No tool that accepts arbitrary code, shell commands, or file paths.
- No shared volume/mount between `agent` and `sim`.
- No tool that lets the LLM change its own tool whitelist at runtime.

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
