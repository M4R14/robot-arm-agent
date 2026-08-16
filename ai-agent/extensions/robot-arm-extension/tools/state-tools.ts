// Read/telemetry tools — mirrors sim's state_routes.py (/state,
// /wait_reached, /rejected_history).

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { callSim, jsonResult } from "../support/sim-client";

export function registerStateTools(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "get_arm_state",
    label: "Get Arm State",
    description: "Read current joint angles/velocities/torques/targets, end-effector position, grip force, summary, and last error.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      return jsonResult(await callSim("get_arm_state", "/state", "GET", undefined, signal));
    },
  });

  pi.registerTool({
    name: "wait_for_arm",
    label: "Wait For Arm",
    description: "Block until the arm (or given joints) reaches its target, or timeout.",
    parameters: Type.Object({
      joint_ids: Type.Optional(Type.Array(Type.Integer(), { description: "Only wait on these joint ids; omit to wait on all joints" })),
      timeout_s: Type.Optional(Type.Number({ description: "Max seconds to wait (server caps this)" })),
    }),
    async execute(_toolCallId, params, signal) {
      return jsonResult(await callSim("wait_for_arm", "/wait_reached", "POST", params, signal));
    },
  });

  pi.registerTool({
    name: "get_rejected_history",
    label: "Get Rejected History",
    description: "Read the last 10 rejected commands (error_code, message, details), oldest first. Check this before repeating a move that might already be known to fail.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      return jsonResult(await callSim("get_rejected_history", "/rejected_history", "GET", undefined, signal));
    },
  });
}
