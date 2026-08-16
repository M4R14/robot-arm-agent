// Whole-arm safety tools — mirrors sim's safety_routes.py (/stop, /reset).

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { callSim, jsonResult } from "../support/sim-client";

export function registerSafetyTools(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "stop_arm",
    label: "Stop Arm",
    description: "Immediately halt joint motion, holding position. Omit joint_ids to stop everything; pass joint_ids to stop only those.",
    parameters: Type.Object({
      joint_ids: Type.Optional(Type.Array(Type.Integer(), { description: "Only stop these joints; omit to stop all joints" })),
    }),
    async execute(_toolCallId, params, signal) {
      return jsonResult(await callSim("stop_arm", "/stop", "POST", params, signal));
    },
  });

  pi.registerTool({
    name: "reset_environment",
    label: "Reset Environment",
    description: "Reset the simulation to its home pose. Also clears rejected-command history.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      return jsonResult(await callSim("reset_environment", "/reset", "POST", undefined, signal));
    },
  });
}
