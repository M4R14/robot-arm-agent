// Multi-waypoint path tool — mirrors sim's trajectory_routes.py
// (/move_trajectory).

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { PoseFields } from "../support/schema";
import { callSim, commandId, jsonResult } from "../support/sim-client";

export function registerTrajectoryTools(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "move_trajectory",
    label: "Move Trajectory",
    description: "Move through a sequence of poses in order, waiting for each. Stops at the first waypoint that fails validation.",
    parameters: Type.Object({
      waypoints: Type.Array(Type.Object(PoseFields), { description: "Poses to visit in order" }),
    }),
    async execute(toolCallId, params, signal) {
      return jsonResult(await callSim("move_trajectory", "/move_trajectory", "POST", { ...params, command_id: commandId(toolCallId) }, signal));
    },
  });
}
