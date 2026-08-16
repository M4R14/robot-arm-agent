// Client-side pre-checks using sim's own /capabilities, cached for the
// life of this process (joint limits and reach don't change between
// resets of the same URDF). Only blocks calls that are *certain* to be
// rejected (bad joint_id) or *very likely* to be (way outside reach) —
// saving a round trip for those, while anything less than certain still
// goes to sim, which is the real authority.

import { callSim, log } from "./sim-client";

type Capabilities = {
  joint_ids: number[];
  reach_max_m: number;
};

let capabilitiesCache: Capabilities | null = null;

export async function getCachedCapabilities(signal?: AbortSignal): Promise<Capabilities | null> {
  if (capabilitiesCache) return capabilitiesCache;
  try {
    capabilitiesCache = (await callSim("get_arm_capabilities", "/capabilities", "GET", undefined, signal)) as Capabilities;
    return capabilitiesCache;
  } catch {
    return null; // validation is best-effort; if this fails, just skip it and let sim be the judge
  }
}

export class ClientValidationError extends Error {}

export async function assertKnownJoint(toolName: string, jointId: number, signal?: AbortSignal): Promise<void> {
  const caps = await getCachedCapabilities(signal);
  if (caps && !caps.joint_ids.includes(jointId)) {
    const message = `joint_id ${jointId} is not one of ${JSON.stringify(caps.joint_ids)} (from cached /capabilities; not sent to sim)`;
    log(`-> ${toolName} CLIENT-SIDE REJECT: ${message}`);
    throw new ClientValidationError(message);
  }
}

export async function warnIfObviouslyUnreachable(
  toolName: string,
  x: number, y: number, z: number, relative: boolean | undefined,
  signal?: AbortSignal,
): Promise<void> {
  if (relative) return; // relative targets are offsets from the current pose; can't sanity-check without it
  const caps = await getCachedCapabilities(signal);
  if (!caps) return;
  const distance = Math.sqrt(x * x + y * y + z * z);
  if (distance > caps.reach_max_m) {
    const message = `target is ${distance.toFixed(2)}m from the base, beyond the arm's estimated max reach of ${caps.reach_max_m.toFixed(2)}m (from cached /capabilities; not sent to sim) — pick a closer target`;
    log(`-> ${toolName} CLIENT-SIDE REJECT: ${message}`);
    throw new ClientValidationError(message);
  }
}
