#!/usr/bin/env node
// Standalone summary of run_history.jsonl — `node orchestrator/stats.js`.
// Single responsibility: read the log and print an aggregate view,
// instead of everyone re-deriving the same numbers with an ad-hoc
// one-off script each time. Tolerant of older records that predate a
// given field (e.g. plannerCost, steps) — this file is append-only, so
// old and new shapes coexist.
import { readFileSync } from "node:fs";

import { RUN_HISTORY_PATH } from "./constants.js";

function loadRows() {
  let text;
  try {
    text = readFileSync(RUN_HISTORY_PATH, "utf8");
  } catch {
    console.log(`No run history yet at ${RUN_HISTORY_PATH}.`);
    process.exit(0);
  }
  return text
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line));
}

function fmt(n) {
  return `$${n.toFixed(4)}`;
}

function main() {
  const rows = loadRows();
  const n = rows.length;
  const completed = rows.filter((r) => r.outcome === "completed");
  const failed = rows.filter((r) => r.outcome === "failed");
  const totalCost = rows.reduce((sum, r) => sum + (r.totalCost ?? 0), 0);
  const plannerCost = rows.reduce((sum, r) => sum + (r.plannerCost ?? 0), 0);
  const executorCost = rows.reduce((sum, r) => sum + (r.executorCost ?? 0), 0);
  const avgDurationS = completed.length
    ? completed.reduce((sum, r) => sum + r.durationMs, 0) / completed.length / 1000
    : 0;
  const runsWithReplan = rows.filter((r) => (r.replans ?? 0) > 0).length;

  console.log(`Runs: ${n} (${completed.length} completed, ${failed.length} failed)`);
  console.log(`Total cost: ${fmt(totalCost)}  (planner ${fmt(plannerCost)} / executor ${fmt(executorCost)})`);
  console.log(`Avg duration (completed runs): ${avgDurationS.toFixed(1)}s`);
  console.log(`Runs needing at least one replan: ${runsWithReplan}/${n}`);

  const errorCodeCounts = {};
  for (const row of rows) {
    for (const attempt of row.replanHistory ?? []) {
      const code = attempt.errorCode ?? "(no error_code detected)";
      errorCodeCounts[code] = (errorCodeCounts[code] ?? 0) + 1;
    }
  }
  const errorCodeEntries = Object.entries(errorCodeCounts).sort((a, b) => b[1] - a[1]);
  if (errorCodeEntries.length) {
    console.log("\nReplan triggers by error_code:");
    for (const [code, count] of errorCodeEntries) console.log(`  ${code}: ${count}`);
  }

  // step.skillUsed shape has changed over time: older records have a
  // plain string (name, or absent) — treated here as already-canonical,
  // since it predates validation; newer records have { reported,
  // canonical }, where a reported-but-non-canonical name means the
  // Executor claimed a skill that doesn't match anything in
  // KNOWN_SKILLS (typo, or hallucinated) and is counted separately
  // rather than silently trusted.
  const skillCounts = {};
  let improvisedCount = 0;
  let unrecognizedCount = 0;
  for (const row of rows) {
    for (const step of row.steps ?? []) {
      const skill = step.skillUsed;
      if (typeof skill === "string") {
        skillCounts[skill] = (skillCounts[skill] ?? 0) + 1;
      } else if (skill?.canonical) {
        skillCounts[skill.canonical] = (skillCounts[skill.canonical] ?? 0) + 1;
      } else if (skill?.reported) {
        unrecognizedCount++;
      } else {
        improvisedCount++;
      }
    }
  }
  const skillEntries = Object.entries(skillCounts).sort((a, b) => b[1] - a[1]);
  if (skillEntries.length || improvisedCount || unrecognizedCount) {
    console.log("\nCanned-skill usage:");
    for (const [skill, count] of skillEntries) console.log(`  ${skill}: ${count}`);
    console.log(`  (improvised, no catalog match): ${improvisedCount}`);
    if (unrecognizedCount) {
      console.log(`  (reported a skill name not in KNOWN_SKILLS — check for typos): ${unrecognizedCount}`);
    }
  }
}

main();
