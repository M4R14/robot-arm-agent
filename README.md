# RobotArmAgent

Two-container system: a PyBullet robot-arm simulator (`robot-arm/`, no
route to the internet) and a `pi` LLM agent harness (`ai-agent/`) that can
only call a fixed set of whitelisted tools mapping 1:1 to the sim's HTTP
API. See [SPEC.md](SPEC.md) for the full design and isolation
requirements.

## Run

Credentials load from `.env` at the repo root (docker compose loads it
automatically for `${VAR}` substitution in `docker-compose.yml`) — the
default provider/model (`openrouter` / `google/gemma-4-31b-it:free`) is
baked into the image at `ai-agent/settings.json`. `.env` holds a real key
and is gitignored; treat it as a secret, don't commit or share it.

```bash
docker compose up --build
```

`sim` must pass its healthcheck before `agent` starts. Attach to the
agent's TUI in another terminal:

```bash
docker compose attach agent
```

Try: "read the arm state, then move joint 0 to 45 degrees" — expect
exactly two tool calls (`get_arm_state`, `move_joint`). Note: OpenRouter's
free Gemma model is shared/rate-limited upstream — retries happen
automatically, but for reliable use, set `defaultModel` in
`ai-agent/settings.json` to a paid model or your own provider key.

## Watching the arm move

`sim` runs PyBullet headless (`p.connect(p.DIRECT)`, no ports exposed —
required by [SPEC.md](SPEC.md)'s isolation rules), so there's nothing to
look at by default. `watch-arm.py` opens a local 3D viewer on your host
that mirrors the live joint state without breaking that isolation: it
polls `sim`'s own `/state` endpoint via `docker compose exec` (never a
direct network route to `sim`) and drives a second, host-side PyBullet
GUI window with the same URDF using real motor control, so the arm eases
into position instead of teleporting.

Requires `pybullet` on the host: `pip3 install --user pybullet`.

```bash
python3 watch-arm.py &
```

Leave it running, then drive the arm as usual via `docker compose attach
agent` (or any `move_joint` / `move_to_pose` / `grip` call) — the window
updates in real time. Stop it with `pkill -f watch-arm.py`.

## Tools the agent can call

| Tool | What it does |
|---|---|
| `get_arm_state` | Joint angles, velocities, applied torques, commanded targets, `reached` flags, end-effector position |
| `wait_for_arm` | Block until the arm (or specific joints) reaches its target, or timeout |
| `move_joint` / `move_joints` | Move one or several joints to target angles (degrees); batched moves arrive together |
| `preview_move_joint` / `preview_move_to_pose` | Dry-run validation — check if a move would succeed, without moving the arm |
| `move_to_pose` | Move the end effector to (x, y, z), optional roll/pitch/yaw, via inverse kinematics |
| `grip` / `release_gripper` | Set grip force / release (current placeholder URDF has no gripper actuator — records the value) |
| `pick_and_place` | Composite: move to pick pose → grip → move to place pose → release, blocking until done |
| `stop_arm` | Immediately halt all joint motion in place |
| `reset_environment` | Reset the simulation to its home pose |

Every move is validated server-side before it ever reaches a motor: clamped to
the real per-joint hardware limits read from the URDF (not just a generic
ceiling), and rejected if it would cause a self-collision, land outside the
arm's reach, or approach a kinematic singularity. Rejections return a
machine-readable `error_code` (`SELF_COLLISION`, `UNREACHABLE_POSE`,
`NEAR_SINGULARITY`, `RATE_LIMITED`, `JOINT_OUT_OF_RANGE`). Mutating tool
calls carry an idempotency key (the harness's own `toolCallId`, not
LLM-supplied) so a retried call replays the prior result instead of
re-executing. Full endpoint/tool contract: [SPEC.md §4.3 / §5.3](SPEC.md).

## Swapping providers

`pi` auto-detects credentials from env vars (`ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, ...). To switch the default,
edit `defaultProvider`/`defaultModel` in
[ai-agent/settings.json](ai-agent/settings.json) (baked into the image
at `/root/.pi/agent/settings.json`, so it applies without a project-trust
prompt) and set the matching key in `.env`. No changes to `robot-arm/` or
`ai-agent/extensions/robot-arm-extension.ts` are needed.

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
├── watch-arm.py           local 3D viewer (host-side, read-only)
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
    └── extensions/robot-arm-extension.ts
```
