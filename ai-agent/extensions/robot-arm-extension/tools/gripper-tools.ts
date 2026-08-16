// Gripper force tools — mirrors sim's gripper_routes.py (/grip, /release).

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { callSim, jsonResult } from "../support/sim-client";

export function registerGripperTools(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "grip",
    label: "Grip",
    description: "Set gripper force. The current placeholder URDF has no gripper actuator, so this only records the value.",
    parameters: Type.Object({
      force: Type.Number({ description: "Requested grip force" }),
    }),
    async execute(toolCallId, params, signal) {
      return jsonResult(await callSim("grip", "/grip", "POST", { ...params, command_id: toolCallId }, signal));
    },
  });

  pi.registerTool({
    name: "release_gripper",
    label: "Release Gripper",
    description: "Release the gripper (grip with force 0), named for clarity.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      return jsonResult(await callSim("release_gripper", "/release", "POST", undefined, signal));
    },
  });
}
