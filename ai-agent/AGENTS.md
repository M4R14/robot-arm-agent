# Working with the robot arm

You control a simulated robot arm through the tools below. Follow this
workflow — moves return immediately (the arm keeps moving asynchronously
after the call returns), so sequencing matters:

1. Before planning unfamiliar moves, call `get_arm_capabilities` once to
   learn joint limits, `reach_min_m`/`reach_max_m` (the arm's Cartesian
   reach from its base — an (x, y, z) target much beyond `reach_max_m`
   from the origin will just be rejected), max force, and timing
   constants — don't guess values that will just get clamped or
   rejected.
2. Before committing to a move you're unsure about, call
   `preview_move_joint` or `preview_move_to_pose` first. Same validation,
   no motion. `preview_move_to_pose`/`preview_pose_candidates` responses
   may include `previously_tried` — a fact recorded from an earlier call
   near that same point, possibly from a past session (this persists
   across resets and restarts). Trust it; you don't need to re-derive
   what's already known.
3. After `move_joint`, `move_joints`, `move_to_pose`, or
   `move_trajectory`, call `wait_for_arm` before any dependent next step
   (e.g. before gripping at a pose you just moved to).
4. If a command is rejected, don't retry the identical call — read
   `error_code` and call `get_error_recovery_hints` for structured
   guidance on what to do about that specific code (e.g.
   `UNREACHABLE_POSE` responses include `closest_achievable_position`;
   `RATE_LIMITED` responses include `retry_after_s`). If you've hit a
   few rejections in a row, call `get_rejected_history` to see exactly
   what you've already tried and why it failed, instead of guessing
   whether you're repeating yourself.
5. For a plain pick-and-place, use `pick_and_place` instead of chaining
   move→wait→grip→move→wait→release by hand — one call, and it reports
   whether each leg actually reached.
6. If a move looks wrong mid-flight, call `stop_arm` immediately rather
   than waiting for it to finish.
7. Comparing several candidate poses? Call `preview_pose_candidates`
   once with all of them, not `preview_move_to_pose` in a loop — one
   round trip either way.

## Before a multi-step task

For anything with more than ~3 moves, write your plan as plain text (not
a tool call) in this shape before executing anything, so it's inspectable
before you commit to it:

```
plan:
1. check: get_arm_capabilities — confirm reach/limits before picking targets
2. move: move_to_pose(x=..., y=..., z=...) — reason: <why this pose>
   risk: <UNREACHABLE_POSE / SELF_COLLISION / none expected, and why>
3. wait: wait_for_arm — block until step 2 lands
4. move: grip(force=...) — reason: <why>
...
```

Then:
1. Call `get_arm_capabilities` once.
2. If several candidate poses are plausible, narrow them down with one
   `preview_pose_candidates` call instead of previewing one at a time.
3. Execute the plan, using `wait_for_arm` between dependent steps.
4. If you hit repeated rejections, call `get_rejected_history` before
   trying yet another guess.
5. Before reporting a task as done, call `get_arm_state` (or
   `wait_for_arm`) one more time and check `reached`/`summary` against
   what you *intended* — don't report success from memory of a call
   that returned `ok: true`; `ok: true` on `move_*` only means the
   command was accepted, not that the arm has arrived yet.

## Example: manual pick and place

```
move_to_pose({ x: 0.4, y: 0.1, z: 0.7 })
wait_for_arm({})
grip({ force: 60 })
move_to_pose({ x: 0.3, y: -0.2, z: 0.6 })
wait_for_arm({})
release_gripper({})
```

## Example: same task, one call

```
pick_and_place({
  pick: { x: 0.4, y: 0.1, z: 0.7 },
  place: { x: 0.3, y: -0.2, z: 0.6 },
  grip_force: 60
})
```

## Example: checking an uncertain target before committing

```
preview_move_to_pose({ x: 0.9, y: 0.9, z: 0.9 })
// -> { ok: false, reason: "target [...] is outside the arm's reach ..." }
// pick a different, reachable target instead of calling move_to_pose blind
```

## Example: recovering from a real rejection (verified pattern)

This is what actually happens, not a hypothetical — `move_to_pose` was
called with a wildly out-of-range target, and the second call used the
sim's own suggested correction, not a guess:

```
move_to_pose({ x: 5, y: 5, z: 5 })
// -> 400 UNREACHABLE_POSE: "target [5,5,5] is outside the arm's reach
//    (closest achievable ~[-0.041, 0.392, 1.125])"

move_to_pose({ x: -0.041, y: 0.392, z: 1.125 })
// -> ok: true
wait_for_arm({})
// -> reached: true
```

## Example: triaging several candidates before committing (verified pattern)

```
preview_pose_candidates({
  candidates: [
    { x: 0.4, y: 0.1, z: 0.7 },
    { x: 100, y: 100, z: 100 },
    { x: 0.35, y: -0.15, z: 0.65 }
  ]
})
// -> results: [
//      { index: 0, ok: true },
//      { index: 1, ok: false, reason: "outside the arm's reach ..." },
//      { index: 2, ok: true }
//    ]
// move_to_pose only the candidates that came back ok: true
```

## Example: nudging a joint instead of recomputing an absolute angle

```
move_joint({ joint_id: 0, target_angle_deg: 10, relative: true })
wait_for_arm({ joint_ids: [0] })
// joint 0 is now current_angle + 10deg — no need to read state first
// to compute the new absolute target
```
