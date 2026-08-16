// The Executor half: runs exactly one plan step per fresh `pi` process,
// with the same tool set and AGENTS.md workflow as interactive mode.
import {
  COMPLEX_STEP_MAX_TOOL_CALLS,
  COMPLEX_STEP_PATTERN,
  COMPLEX_STEP_TIMEOUT_MS,
  EXTENSION_PATH,
  KNOWN_SKILLS,
  SIM_URL,
  SIMPLE_STEP_MAX_TOOL_CALLS,
  SIMPLE_STEP_TIMEOUT_MS,
} from "./constants.js";
import { costTracker } from "./cost-tracker.js";
import { extractCost, lastAssistantText, runPi } from "./pi-runner.js";

// sim's machine-readable error codes (constants.py's ERROR_RECOVERY_HINTS
// keys) — the Executor's report is free text, not structured, but sim's
// own thrown error messages (sim-client.ts's callSim) always include the
// code verbatim, so a substring scan reliably recovers it when present.
const KNOWN_ERROR_CODES = [
  "JOINT_OUT_OF_RANGE",
  "UNREACHABLE_POSE",
  "SELF_COLLISION",
  "NEAR_SINGULARITY",
  "RATE_LIMITED",
];

// Read-only, one HTTP call — same trust level as the Dockerfile's own
// CMD, not a tool the LLM can reach. Lets the next Executor step start
// grounded instead of spending its first turn re-discovering state its
// predecessor already had.
async function fetchArmStateSummary() {
  try {
    const res = await fetch(`${SIM_URL}/state`, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) return null;
    const state = await res.json();
    const [x, y, z] = state.end_effector_position ?? [];
    return `${state.summary} End-effector at (${x?.toFixed(3)}, ${y?.toFixed(3)}, ${z?.toFixed(3)}).`;
  } catch {
    return null;
  }
}

export async function executeStep(step, index, total, prevSummary) {
  const stateSummary = await fetchArmStateSummary();
  const context = [
    `You are executing step ${index + 1} of ${total} in a larger plan devised by a separate planning agent.`,
    prevSummary ? `Previous step: ${prevSummary}` : "This is the first step.",
    stateSummary ? `Current arm state (just queried, trust it): ${stateSummary}` : null,
    "This is the ONLY step you should perform right now — do not attempt later steps.",
    "Just before your STATUS line, add one line, verbatim: 'SKILL: <name>' if you used one " +
      "of AGENTS.md's named canned skills for this step, or 'SKILL: none' if you improvised " +
      "instead (this is just for our own usage tracking, not a preference either way).",
    "End your final reply with exactly one line, verbatim: 'STATUS: DONE' if the step's " +
      "intended outcome was achieved and you confirmed it (e.g. via get_arm_state or " +
      "wait_for_arm), or 'STATUS: FAILED - <short reason>' if it could not be completed.",
  ].filter(Boolean).join("\n");

  const isComplex = COMPLEX_STEP_PATTERN.test(step);
  const thinking = isComplex ? ["--thinking", "high"] : [];

  const { text, killedReason } = await runPi(
    [
      "-p", "--mode", "json",
      "--no-builtin-tools", "--no-extensions",
      "-e", EXTENSION_PATH,
      ...thinking,
      "--append-system-prompt", context,
      "--approve",
      step,
    ],
    {
      timeoutMs: isComplex ? COMPLEX_STEP_TIMEOUT_MS : SIMPLE_STEP_TIMEOUT_MS,
      maxToolCalls: isComplex ? COMPLEX_STEP_MAX_TOOL_CALLS : SIMPLE_STEP_MAX_TOOL_CALLS,
      label: `executor step ${index + 1}/${total}`,
    },
  );
  const cost = extractCost(text);
  costTracker.total += cost;
  costTracker.executor += cost;
  if (killedReason) return { report: null, killedReason };
  return { report: lastAssistantText(text), killedReason: null };
}

// Returns { reported, canonical } — canonical is the matching name from
// KNOWN_SKILLS (case-insensitive) if the Executor's self-report actually
// names a real catalog entry, null if it's "none"/absent, and null with
// `reported` still set when the name doesn't match anything known (a
// typo or hallucination) — that distinction matters for stats.js to
// flag rather than silently trust.
function skillUsedIn(report) {
  const line = report
    .split("\n")
    .map((l) => l.trim())
    .find((l) => l.startsWith("SKILL:"));
  if (!line) return { reported: null, canonical: null };
  const name = line.replace(/^SKILL:\s*/, "").trim();
  if (!name || name.toLowerCase() === "none") return { reported: null, canonical: null };
  const canonical = KNOWN_SKILLS.find((s) => s.toLowerCase() === name.toLowerCase()) ?? null;
  return { reported: name, canonical };
}

function errorCodeIn(report) {
  return KNOWN_ERROR_CODES.find((code) => report.includes(code)) ?? null;
}

export function statusOf({ report, killedReason }) {
  if (killedReason) return { ok: false, reason: killedReason, errorCode: null, skillUsed: null };
  const line = report
    .split("\n")
    .map((l) => l.trim())
    .reverse()
    .find((l) => l.startsWith("STATUS:"));
  const skillUsed = skillUsedIn(report);
  if (!line) return { ok: false, reason: "Executor did not report a STATUS line", errorCode: null, skillUsed };
  if (line.startsWith("STATUS: DONE")) return { ok: true, skillUsed };
  return {
    ok: false,
    reason: line.replace(/^STATUS:\s*FAILED\s*-?\s*/, "") || "unspecified failure",
    errorCode: errorCodeIn(report),
    skillUsed,
  };
}
