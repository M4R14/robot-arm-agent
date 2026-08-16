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
- a legend explaining the above, plus camera controls;
- an on-screen overlay of `sim`'s own state summary, grip force, render
  FPS, and state-stream age (to tell a slow viewer from a slow sim
  connection) — the summary line turns red, with a "STALE" warning
  showing the age in seconds, if the stream goes quiet, and briefly
  **flashes yellow** when a *new* error first appears (hard to miss even
  if you glanced away), with the last rejected command's error appended.

The overlay text and axis triad redraw at a throttled 5Hz (motion itself
still updates at the full 60Hz render rate) — no point re-uploading debug
text/lines faster than anyone can read them.

Camera: mouse drag orbits, scroll zooms, ctrl+drag pans (PyBullet's
built-in GUI navigation). Keyboard: `1`/`2`/`3`/`4` jump to
front/side/top/isometric presets, `r` resets to the startup view.

Requires `pybullet` on the host: `pip3 install --user pybullet`.

```bash
python3 watch-arm.py &
```

Leave it running, then drive the arm as usual via `docker compose attach
agent` (or any `move_joint` / `move_to_pose` / `grip` call) — the window
updates in real time. Stop it with `pkill -f watch-arm.py` (or Ctrl+C
in its terminal — either way it cleans up its `docker compose exec`
subprocess rather than leaving it orphaned).

## Tools the agent can call

| Tool | What it does |
|---|---|
| `get_arm_state` | Joint angles, velocities, applied torques, commanded targets, `reached` flags, end-effector position/orientation, grip force, summary, last error |
| `get_arm_capabilities` | Static joint limits, reach envelope, safety thresholds, timing constants |
| `wait_for_arm` | Block until the arm (or specific joints) reaches its target, or timeout |
| `move_joint` / `move_joints` | Move one or several joints to target angles (degrees, absolute or `relative`); batched moves arrive together |
| `preview_move_joint` / `preview_move_to_pose` | Dry-run validation — check if a move would succeed, without moving the arm |
| `preview_pose_candidates` | Same dry-run check for several poses in one call, instead of previewing one at a time |
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
├── watch-arm.py           local 3D viewer entrypoint (host-side, read-only)
├── viewer/
│   ├── state_stream.py     background /state polling, thread-safe snapshots
│   ├── camera.py            presets + keyboard shortcuts
│   └── overlay.py            axis triad, overlay text/color, error-flash logic
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
    ├── AGENTS.md            workflow guidance + examples, loaded as global instructions
    └── extensions/
        └── robot-arm-extension/   directory-style extension (pi's "index.ts + helpers" pattern)
            ├── index.ts             composition root — registers each tool group
            ├── support/               sim-client.ts (HTTP+retry+timeout+logging),
            │                            validation.ts (client-side pre-checks), schema.ts
            └── tools/                   one file per resource group, mirrors
                                           robot-arm/app/arm/routes/ 1:1
```
