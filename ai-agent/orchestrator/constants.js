// Tunable constants and paths for the Planner/Executor orchestration.
// Nothing here does anything on its own — single responsibility is just
// "the numbers other modules read." Env vars are validated up front via
// envalid (fails fast with a clear message on startup if e.g. QUIET
// isn't a recognized boolean spelling) instead of each one silently
// coercing whatever it's given.
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { bool, cleanEnv, str } from "envalid";

const __dirname = dirname(fileURLToPath(import.meta.url));
// This file lives in ai-agent/orchestrator/; extensions/ and PLANNER.md
// live one level up, at the ai-agent/ root.
const ROOT = join(__dirname, "..");

const env = cleanEnv(process.env, {
  SIM_URL: str({ default: "http://sim:8000" }),
  // Optional: a separate, e.g. cheaper/faster, model for the Planner
  // (pure decomposition, no tool-use reasoning) — empty means it uses
  // the same default as the Executor, from settings.json.
  PLANNER_MODEL: str({ default: "" }),
  // Suppresses [heartbeat] lines on the console (they still land in the
  // per-run log file either way) — for scripting/piping the live output
  // somewhere that doesn't want a line every 15s of silence.
  QUIET: bool({ default: false }),
});

export const EXTENSION_PATH = join(ROOT, "extensions/robot-arm-extension/index.ts");
export const PLANNER_PROMPT_PATH = join(ROOT, "PLANNER.md");
export const SIM_URL = env.SIM_URL;
export const PLANNER_MODEL = env.PLANNER_MODEL || null;
export const RUN_HISTORY_PATH = "/data/run_history.jsonl";
export const RUN_LOG_DIR = "/data/runs";
export const HEARTBEAT_INTERVAL_MS = 15_000;
export const QUIET = env.QUIET;
// Canonical canned-skill names, kept in sync by hand with AGENTS.md's
// "Canned skills" section and PLANNER.md's "Known canned skills" list —
// used to validate the Executor's self-reported SKILL: line rather than
// trusting it verbatim (a typo'd or hallucinated name would otherwise
// misattribute silently in run-history stats).
export const KNOWN_SKILLS = ["wave hello", "bow"];
// A `pi` process exiting non-zero on its own (not killed by our timeout
// or tool-call cap) is treated as a transient crash — network blip,
// provider hiccup — and retried once after this delay, rather than
// failing the whole task over something a single retry would likely
// clear. Deliberately not more than one retry: a second consecutive
// crash is more likely a real, persistent problem than bad luck.
export const CRASH_RETRY_DELAY_MS = 3_000;

export const MAX_REPLANS = 3;
export const PLANNER_TIMEOUT_MS = 120_000;
// A pathological decomposition (task misread as far bigger than
// intended) shouldn't be allowed to silently turn into dozens of
// sequential pi processes — fail fast and let the caller rephrase.
export const MAX_STEPS = 20;

// Steps that look like they need real geometric reasoning (vs. a plain
// named move) get more budget on every axis: higher thinking level (to
// cut down wrong guesses instead of just tolerating more of them),
// longer timeout, and a higher tool-call ceiling. A plain step like
// "close the gripper" that goes this far off budget is almost certainly
// stuck, not just slow, so it should fail fast rather than wait as long
// as a genuinely hard geometry step is allowed to.
export const COMPLEX_STEP_PATTERN = /reach|extend|boundary|singular|distance|calculate|comput|align|farthest|maxim|limit/i;
export const SIMPLE_STEP_TIMEOUT_MS = 120_000;
export const COMPLEX_STEP_TIMEOUT_MS = 600_000;
export const SIMPLE_STEP_MAX_TOOL_CALLS = 15;
// Generous headroom above the ~27 tool calls a legitimately slow (but
// working) complex step has been observed to take — this is a safety
// valve for a genuinely runaway step, not a latency optimization.
export const COMPLEX_STEP_MAX_TOOL_CALLS = 40;
