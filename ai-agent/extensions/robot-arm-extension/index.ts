// Registers the fixed, whitelisted tool set that maps 1:1 to sim's HTTP API.
// See ../../../SPEC.md sections 5.3 and 5.4 — no tool here may take a
// free-form string parameter intended for code/script/shell execution,
// and no tool beyond this set may be added without updating the spec.
//
// This is the composition root: it wires together resource-scoped tool
// groups in ./tools/, each mirroring the equally-named route module in
// sim's app/arm/routes/. Shared HTTP client, client-side validation, and
// schema fragments live in ./support/.
//
// Tool descriptions are deliberately short (facts only: what it does,
// what makes it fail). The *why* and recommended call sequence live in
// AGENTS.md, loaded once as context instead of repeated in every tool
// schema on every request.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import { registerCapabilitiesTools } from "./tools/capabilities-tools";
import { registerGripperTools } from "./tools/gripper-tools";
import { registerJointTools } from "./tools/joint-tools";
import { registerMacroTools } from "./tools/macro-tools";
import { registerPoseTools } from "./tools/pose-tools";
import { registerSafetyTools } from "./tools/safety-tools";
import { registerStateTools } from "./tools/state-tools";
import { registerTrajectoryTools } from "./tools/trajectory-tools";

export default function (pi: ExtensionAPI) {
  registerStateTools(pi);
  registerCapabilitiesTools(pi);
  registerJointTools(pi);
  registerPoseTools(pi);
  registerTrajectoryTools(pi);
  registerGripperTools(pi);
  registerMacroTools(pi);
  registerSafetyTools(pi);
}
