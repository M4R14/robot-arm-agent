// Cartesian end-effector move tools — mirrors sim's pose_routes.py
// (/move_to_pose, /preview_move_to_pose, /preview_candidates).

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { PoseFields } from "../support/schema";
import { callSim, jsonResult } from "../support/sim-client";
import { warnIfObviouslyUnreachable } from "../support/validation";

export function registerPoseTools(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "move_to_pose",
    label: "Move To Pose",
    description: "Move the end effector to (x, y, z) meters via inverse kinematics, with optional roll/pitch/yaw. Returns immediately. Rejected if unreachable, colliding, or near-singular.",
    parameters: Type.Object({
      ...PoseFields,
      relative: Type.Optional(Type.Boolean({ description: "If true, (x, y, z) is added to the current end-effector position" })),
    }),
    async execute(toolCallId, params, signal) {
      await warnIfObviouslyUnreachable("move_to_pose", params.x, params.y, params.z, params.relative, signal);
      return jsonResult(await callSim("move_to_pose", "/move_to_pose", "POST", { ...params, command_id: toolCallId }, signal));
    },
  });

  pi.registerTool({
    name: "preview_move_to_pose",
    label: "Preview Move To Pose",
    description: "Check whether move_to_pose would succeed, without moving the arm.",
    parameters: Type.Object({
      ...PoseFields,
      relative: Type.Optional(Type.Boolean({ description: "If true, (x, y, z) is added to the current end-effector position" })),
    }),
    async execute(_toolCallId, params, signal) {
      await warnIfObviouslyUnreachable("preview_move_to_pose", params.x, params.y, params.z, params.relative, signal);
      return jsonResult(await callSim("preview_move_to_pose", "/preview_move_to_pose", "POST", params, signal));
    },
  });

  pi.registerTool({
    name: "preview_pose_candidates",
    label: "Preview Pose Candidates",
    description: "Check several candidate (x, y, z) poses in one call — which are reachable/collision-free, without moving the arm. Use this instead of calling preview_move_to_pose once per candidate.",
    parameters: Type.Object({
      candidates: Type.Array(Type.Object(PoseFields), { description: "Poses to check, in the same order as the results" }),
    }),
    async execute(_toolCallId, params, signal) {
      return jsonResult(await callSim("preview_pose_candidates", "/preview_candidates", "POST", params, signal));
    },
  });
}
