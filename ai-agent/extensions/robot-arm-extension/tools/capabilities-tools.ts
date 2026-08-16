// Static reference-data tools — mirrors sim's capabilities_routes.py
// (/capabilities, /error_recovery_hints).

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { callSim, jsonResult } from "../support/sim-client";
import { getCachedCapabilities } from "../support/validation";

export function registerCapabilitiesTools(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "get_arm_capabilities",
    label: "Get Arm Capabilities",
    description: "Read joint limits, safety thresholds, and timing constants. Call before planning unfamiliar moves.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      return jsonResult((await getCachedCapabilities(signal)) ?? (await callSim("get_arm_capabilities", "/capabilities", "GET", undefined, signal)));
    },
  });

  pi.registerTool({
    name: "get_error_recovery_hints",
    label: "Get Error Recovery Hints",
    description: "Read structured recovery guidance for each error_code (SELF_COLLISION, UNREACHABLE_POSE, NEAR_SINGULARITY, RATE_LIMITED, JOINT_OUT_OF_RANGE).",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal) {
      return jsonResult(await callSim("get_error_recovery_hints", "/error_recovery_hints", "GET", undefined, signal));
    },
  });
}
