// Single/multi-joint move tools — mirrors sim's joint_routes.py
// (/move_joint, /move_joints, /preview_move_joint).

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { callSim, commandId, jsonResult } from "../support/sim-client";
import { assertKnownJoint } from "../support/validation";

export function registerJointTools(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "move_joint",
    label: "Move Joint",
    description: "Move one joint to a target angle (degrees). Returns immediately. Rejected on self-collision or near-singular pose (see error_code).",
    parameters: Type.Object({
      joint_id: Type.Integer({ description: "Index of the joint to move" }),
      target_angle_deg: Type.Number({ description: "Target joint angle in degrees" }),
      relative: Type.Optional(Type.Boolean({ description: "If true, target_angle_deg is added to the joint's current angle instead of being an absolute target" })),
    }),
    async execute(toolCallId, params, signal) {
      await assertKnownJoint("move_joint", params.joint_id, signal);
      return jsonResult(await callSim("move_joint", "/move_joint", "POST", { ...params, command_id: commandId(toolCallId) }, signal));
    },
  });

  pi.registerTool({
    name: "move_joints",
    label: "Move Joints",
    description: "Move several joints at once as one validated pose; they arrive together.",
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
      for (const target of params.targets) {
        await assertKnownJoint("move_joints", target.joint_id, signal);
      }
      return jsonResult(await callSim("move_joints", "/move_joints", "POST", { ...params, command_id: commandId(toolCallId) }, signal));
    },
  });

  pi.registerTool({
    name: "preview_move_joint",
    label: "Preview Move Joint",
    description: "Check whether move_joint would succeed, without moving the arm.",
    parameters: Type.Object({
      joint_id: Type.Integer({ description: "Index of the joint to check" }),
      target_angle_deg: Type.Number({ description: "Target joint angle in degrees" }),
      relative: Type.Optional(Type.Boolean({ description: "If true, target_angle_deg is added to the joint's current angle instead of being an absolute target" })),
    }),
    async execute(_toolCallId, params, signal) {
      await assertKnownJoint("preview_move_joint", params.joint_id, signal);
      return jsonResult(await callSim("preview_move_joint", "/preview_move_joint", "POST", params, signal));
    },
  });
}
