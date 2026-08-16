// Registers the fixed, whitelisted tool set that maps 1:1 to sim's HTTP API.
// See ../../SPEC.md sections 5.3 and 5.4 — no tool here may take a
// free-form string parameter intended for code/script/shell execution,
// and no tool beyond this set may be added without updating the spec.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const SIM_URL = process.env.SIM_URL ?? "http://sim:8000";

async function callSim(path: string, method: "GET" | "POST", body: unknown, signal?: AbortSignal) {
  const response = await fetch(`${SIM_URL}${path}`, {
    method,
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(`sim ${path} returned ${response.status}: ${JSON.stringify(payload)}`);
  }
  return payload;
}

function jsonResult(payload: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(payload) }],
    details: payload,
  };
}

const PoseFields = {
  x: Type.Number({ description: "Target end-effector X position, meters" }),
  y: Type.Number({ description: "Target end-effector Y position, meters" }),
  z: Type.Number({ description: "Target end-effector Z position, meters" }),
  roll_deg: Type.Optional(Type.Number({ description: "Target end-effector roll, degrees" })),
  pitch_deg: Type.Optional(Type.Number({ description: "Target end-effector pitch, degrees" })),
  yaw_deg: Type.Optional(Type.Number({ description: "Target end-effector yaw, degrees" })),
};

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "get_arm_state",
    label: "Get Arm State",
    description:
      "Read the robot arm's current joint angles, velocities, applied torques, commanded targets, and whether each joint has reached its target, plus the end-effector position, a one-line summary, and the error (if any) from the last rejected command.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      return jsonResult(await callSim("/state", "GET", undefined, signal));
    },
  });

  pi.registerTool({
    name: "get_arm_capabilities",
    label: "Get Arm Capabilities",
    description:
      "Read the arm's static limits and tuning: per-joint hardware angle limits (tighter than any generic ceiling), max grip force, max joint velocity, the singularity/reachability thresholds used to reject moves, command rate limit, and the home pose. Use this to plan moves that won't just get clamped or rejected.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      return jsonResult(await callSim("/capabilities", "GET", undefined, signal));
    },
  });

  pi.registerTool({
    name: "wait_for_arm",
    label: "Wait For Arm",
    description:
      "Block until the arm (or a specific set of joints) reaches its commanded target, or until timeout. Use this instead of polling get_arm_state in a loop after a move.",
    parameters: Type.Object({
      joint_ids: Type.Optional(Type.Array(Type.Integer(), { description: "Only wait on these joint ids; omit to wait on all joints" })),
      timeout_s: Type.Optional(Type.Number({ description: "Max seconds to wait (server caps this)" })),
    }),
    async execute(_toolCallId, params, signal) {
      return jsonResult(await callSim("/wait_reached", "POST", params, signal));
    },
  });

  pi.registerTool({
    name: "move_joint",
    label: "Move Joint",
    description:
      "Move a single robot arm joint to a target angle in degrees. Out-of-range angles are clamped, not rejected — but a move that would cause a self-collision or a near-singular pose is rejected (error_code SELF_COLLISION / NEAR_SINGULARITY). Returns immediately; use wait_for_arm to block until it arrives.",
    parameters: Type.Object({
      joint_id: Type.Integer({ description: "Index of the joint to move" }),
      target_angle_deg: Type.Number({ description: "Target joint angle in degrees" }),
      relative: Type.Optional(Type.Boolean({ description: "If true, target_angle_deg is added to the joint's current angle instead of being an absolute target" })),
    }),
    async execute(toolCallId, params, signal) {
      return jsonResult(await callSim("/move_joint", "POST", { ...params, command_id: toolCallId }, signal));
    },
  });

  pi.registerTool({
    name: "move_joints",
    label: "Move Joints",
    description:
      "Move several joints at once, each to its own target angle in degrees. All joints are validated together (as one resulting pose) and start moving together, arriving at roughly the same time.",
    parameters: Type.Object({
      targets: Type.Array(
        Type.Object({
          joint_id: Type.Integer({ description: "Index of the joint to move" }),
          target_angle_deg: Type.Number({ description: "Target joint angle in degrees" }),
        }),
        { description: "One entry per joint to move" }
      ),
      relative: Type.Optional(Type.Boolean({ description: "If true, each target_angle_deg is added to that joint's current angle instead of being an absolute target" })),
    }),
    async execute(toolCallId, params, signal) {
      return jsonResult(await callSim("/move_joints", "POST", { ...params, command_id: toolCallId }, signal));
    },
  });

  pi.registerTool({
    name: "preview_move_joint",
    label: "Preview Move Joint",
    description:
      "Check whether move_joint with these parameters would succeed (no self-collision, no near-singular pose) WITHOUT actually moving the arm. Use before a move you're unsure about.",
    parameters: Type.Object({
      joint_id: Type.Integer({ description: "Index of the joint to check" }),
      target_angle_deg: Type.Number({ description: "Target joint angle in degrees" }),
      relative: Type.Optional(Type.Boolean({ description: "If true, target_angle_deg is added to the joint's current angle instead of being an absolute target" })),
    }),
    async execute(_toolCallId, params, signal) {
      return jsonResult(await callSim("/preview_move_joint", "POST", params, signal));
    },
  });

  pi.registerTool({
    name: "move_to_pose",
    label: "Move To Pose",
    description:
      "Move the robot arm's end effector toward an (x, y, z) position in meters using inverse kinematics. Optionally set a target orientation (roll/pitch/yaw, degrees); omit all three to let the solver pick one. If relative is true, (x, y, z) is added to the current end-effector position instead of being an absolute target (orientation is always absolute). Rejected if the target is outside the arm's reach, would self-collide, or is near a kinematic singularity. Returns immediately; use wait_for_arm to block until it arrives.",
    parameters: Type.Object({
      ...PoseFields,
      relative: Type.Optional(Type.Boolean({ description: "If true, (x, y, z) is added to the current end-effector position" })),
    }),
    async execute(toolCallId, params, signal) {
      return jsonResult(await callSim("/move_to_pose", "POST", { ...params, command_id: toolCallId }, signal));
    },
  });

  pi.registerTool({
    name: "preview_move_to_pose",
    label: "Preview Move To Pose",
    description:
      "Check whether move_to_pose with these parameters would succeed (reachable, no self-collision, no near-singular pose) WITHOUT actually moving the arm. Use before a move you're unsure about.",
    parameters: Type.Object({
      ...PoseFields,
      relative: Type.Optional(Type.Boolean({ description: "If true, (x, y, z) is added to the current end-effector position" })),
    }),
    async execute(_toolCallId, params, signal) {
      return jsonResult(await callSim("/preview_move_to_pose", "POST", params, signal));
    },
  });

  pi.registerTool({
    name: "move_trajectory",
    label: "Move Trajectory",
    description:
      "Move the end effector through a sequence of poses, in order, waiting for each to be reached before starting the next. Stops at the first waypoint that's unreachable, self-colliding, or near-singular rather than skipping it — check the per-waypoint result to see how far it got.",
    parameters: Type.Object({
      waypoints: Type.Array(Type.Object(PoseFields), { description: "Poses to visit in order" }),
    }),
    async execute(toolCallId, params, signal) {
      return jsonResult(await callSim("/move_trajectory", "POST", { ...params, command_id: toolCallId }, signal));
    },
  });

  pi.registerTool({
    name: "grip",
    label: "Grip",
    description:
      "Set the gripper force. Out-of-range force is clamped by the sim, not rejected. Note: the current placeholder URDF has no gripper actuator, so this records the value but doesn't move a physical jaw.",
    parameters: Type.Object({
      force: Type.Number({ description: "Requested grip force" }),
    }),
    async execute(toolCallId, params, signal) {
      return jsonResult(await callSim("/grip", "POST", { ...params, command_id: toolCallId }, signal));
    },
  });

  pi.registerTool({
    name: "release_gripper",
    label: "Release Gripper",
    description: "Release the gripper (equivalent to grip with force 0), named for clarity.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      return jsonResult(await callSim("/release", "POST", undefined, signal));
    },
  });

  pi.registerTool({
    name: "pick_and_place",
    label: "Pick And Place",
    description:
      "Composite action: move to the pick pose, grip, move to the place pose, then release. Blocks until the whole sequence finishes (or a step times out) and reports whether each move actually reached its target.",
    parameters: Type.Object({
      pick: Type.Object(PoseFields, { description: "Pose to move to before gripping" }),
      place: Type.Object(PoseFields, { description: "Pose to move to before releasing" }),
      grip_force: Type.Number({ description: "Grip force to apply at the pick pose" }),
    }),
    async execute(toolCallId, params, signal) {
      return jsonResult(await callSim("/pick_and_place", "POST", { ...params, command_id: toolCallId }, signal));
    },
  });

  pi.registerTool({
    name: "stop_arm",
    label: "Stop Arm",
    description:
      "Immediately halt joint motion, holding each affected joint at its current position. Use this to cancel an in-flight move. Omit joint_ids to stop the whole arm; pass specific joint_ids to stop only those joints while others keep moving.",
    parameters: Type.Object({
      joint_ids: Type.Optional(Type.Array(Type.Integer(), { description: "Only stop these joints; omit to stop all joints" })),
    }),
    async execute(_toolCallId, params, signal) {
      return jsonResult(await callSim("/stop", "POST", params, signal));
    },
  });

  pi.registerTool({
    name: "reset_environment",
    label: "Reset Environment",
    description: "Reset the simulation to its initial (home) pose.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      return jsonResult(await callSim("/reset", "POST", undefined, signal));
    },
  });
}
