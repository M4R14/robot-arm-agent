// The Planner half: decomposes a task (or revises a partial plan after
// a failure) into an ordered list of steps. No tool-use, no sim
// awareness beyond what PLANNER.md tells it.
import { readFileSync } from "node:fs";

import { MAX_STEPS, PLANNER_MODEL, PLANNER_PROMPT_PATH, PLANNER_TIMEOUT_MS } from "./constants.js";
import { costTracker } from "./cost-tracker.js";
import { extractCost, lastAssistantText, runPi } from "./pi-runner.js";

// Finds the first complete top-level {...} object by tracking brace
// depth (and skipping braces inside strings), instead of a greedy regex
// from the first "{" to the very last "}" in the whole text — which
// would grab everything up to and including any brace the Planner
// happens to mention afterward (an example, a stray aside), not just
// the JSON object itself.
function extractFirstJsonObject(text) {
  const start = text.indexOf("{");
  if (start === -1) return null;
  let depth = 0;
  let inString = false;
  let escapeNext = false;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (inString) {
      if (escapeNext) escapeNext = false;
      else if (ch === "\\") escapeNext = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') inString = true;
    else if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return text.slice(start, i + 1);
    }
  }
  return null;
}

function parsePlan(text) {
  const jsonText = extractFirstJsonObject(text);
  if (!jsonText) throw new Error(`Planner did not return JSON:\n${text}`);
  const parsed = JSON.parse(jsonText);
  if (!Array.isArray(parsed.steps) || parsed.steps.length === 0) {
    throw new Error(`Planner returned no steps:\n${text}`);
  }
  if (parsed.steps.length > MAX_STEPS) {
    throw new Error(
      `Planner produced ${parsed.steps.length} steps, over the ${MAX_STEPS} cap — likely ` +
        `the task was decomposed far more granularly than intended. Try rephrasing it as a ` +
        `smaller task, or break it into separate orchestrator.js runs yourself.`,
    );
  }
  return parsed.steps;
}

async function runPlanner(message, label) {
  const plannerPrompt = readFileSync(PLANNER_PROMPT_PATH, "utf8");
  const modelArgs = PLANNER_MODEL ? ["--model", PLANNER_MODEL] : [];
  const { text, killedReason } = await runPi(
    [
      "-p", "--mode", "json",
      "--no-tools", "--no-context-files",
      // Pure text decomposition, no tool-use reasoning — a lighter
      // thinking level than the Executor's default is plenty, and
      // --offline skips pi's own startup checks (model catalog
      // refresh, update check) that a Planner call has no use for; the
      // actual inference request still goes out over the network same
      // as always, this only trims fixed per-process overhead.
      "--thinking", "low",
      "--offline",
      ...modelArgs,
      "--system-prompt", plannerPrompt,
      "--approve",
      message,
    ],
    { timeoutMs: PLANNER_TIMEOUT_MS, label },
  );
  const cost = extractCost(text);
  costTracker.total += cost;
  costTracker.planner += cost;
  if (killedReason) throw new Error(`Planner ${killedReason}`);
  return parsePlan(lastAssistantText(text));
}

export async function plan(task) {
  return runPlanner(task, "planner");
}

// `failureReport` is the Executor's full final report when it has one
// (null for a killed step — timeout/tool-call cap — which has no report
// to give), not just the short one-line reason: sim's rejection messages
// often carry detail worth a different approach (e.g.
// closest_achievable_position on UNREACHABLE_POSE) that the terse reason
// string alone drops.
export async function replan(task, completedSteps, failedStep, failureReason, failureReport, attempt) {
  const message = [
    `Original task: ${task}`,
    "",
    completedSteps.length
      ? `Completed steps so far:\n${completedSteps.map((s, i) => `${i + 1}. ${s}`).join("\n")}`
      : "No steps have completed yet.",
    "",
    `The next step, "${failedStep}", failed: ${failureReason}`,
    failureReport ? `\nExecutor's full report on that attempt:\n${failureReport}` : null,
    "",
    "Revise the plan: output the remaining steps still needed to complete the original " +
      "task, accounting for this failure (try a different approach for it, or skip/adjust " +
      "if appropriate). Same JSON format as before — only the steps still to be done from " +
      "now on, not the ones already completed.",
  ].filter((line) => line !== null).join("\n");
  return runPlanner(message, `planner (replan ${attempt})`);
}
