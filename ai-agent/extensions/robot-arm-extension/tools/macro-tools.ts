// Composite multi-step tool — mirrors sim's macro_routes.py
// (/pick_and_place).

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { PoseFields } from "../support/schema";
import { callSim, commandId, jsonResult } from "../support/sim-client";
import { warnIfObviouslyUnreachable } from "../support/validation";

export function registerMacroTools(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "pick_and_place",
    label: "Pick And Place",
    description: "Move to the pick pose, grip, move to the place pose, release — one blocking call reporting whether each leg reached.",
    parameters: Type.Object({
      pick: Type.Object(PoseFields, { description: "Pose to move to before gripping" }),
      place: Type.Object(PoseFields, { description: "Pose to move to before releasing" }),
      grip_force: Type.Number({ description: "Grip force to apply at the pick pose" }),
    }),
    async execute(toolCallId, params, signal) {
      await warnIfObviouslyUnreachable("pick_and_place", params.pick.x, params.pick.y, params.pick.z, false, signal);
      await warnIfObviouslyUnreachable("pick_and_place", params.place.x, params.place.y, params.place.z, false, signal);
      return jsonResult(await callSim("pick_and_place", "/pick_and_place", "POST", { ...params, command_id: commandId(toolCallId) }, signal));
    },
  });
}
