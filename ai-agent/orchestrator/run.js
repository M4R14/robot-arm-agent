// Coordinates the Planner and Executor for one task: plan, execute each
// step, replan on failure (closed-loop, capped), log the outcome. Single
// responsibility: the control flow — the actual Planner/Executor calls
// live in planner.js/executor.js.
import { randomUUID } from "node:crypto";

import { MAX_REPLANS } from "./constants.js";
import { costTracker } from "./cost-tracker.js";
import { executeStep, statusOf } from "./executor.js";
import { closeRunLogger, openRunLogger } from "./logger.js";
import { plan, replan } from "./planner.js";
import { appendRunHistory } from "./run-history.js";

export async function runOrchestrator(task) {
  const startedAt = Date.now();
  const runId = randomUUID().slice(0, 8);
  const completed = [];
  // Richer per-run detail for run-history analysis (see stats.js):
  // which steps used a canned skill vs improvised, and what specifically
  // triggered each replan — not just a bare count.
  const stepRecords = [];
  const replanHistory = [];
  let replans = 0;
  let outcome = "failed";
  let errorMessage = null;

  // logger.js mirrors every message below into /data/runs/<runId>.log
  // in addition to the console, so runId (printed below and stored in
  // the run_history.jsonl record) is enough to find this run's full
  // trace afterwards, not just its summary.
  const logger = openRunLogger(runId);

  try {
    logger.info(`[orchestrator] run id: ${runId}`);
    logger.info(`[planner] task: ${task}`);
    let steps = await plan(task);
    logger.info(`[planner] ${steps.length} step(s):`);
    steps.forEach((s, i) => logger.info(`  ${i + 1}. ${s}`));

    let prevSummary = null;
    let i = 0;

    while (i < steps.length) {
      const step = steps[i];
      logger.info(`\n[executor] step ${i + 1}/${steps.length}: ${step}`);
      const result = await executeStep(step, i, steps.length, prevSummary);
      if (result.report) logger.info(result.report);
      const status = statusOf(result);

      if (status.ok) {
        completed.push(step);
        stepRecords.push({ step, skillUsed: status.skillUsed });
        prevSummary = `"${step}" -> done`;
        i++;
        continue;
      }

      logger.warn(`\n[orchestrator] step ${i + 1} failed: ${status.reason}`);
      if (replans >= MAX_REPLANS) {
        throw new Error(`replan limit (${MAX_REPLANS}) reached — last failure: ${status.reason}`);
      }
      replans++;
      replanHistory.push({ attempt: replans, failedStep: step, reason: status.reason, errorCode: status.errorCode });
      logger.info(`[planner] replanning (attempt ${replans}/${MAX_REPLANS})...`);
      steps = await replan(task, completed, step, status.reason, result.report, replans);
      logger.info(`[planner] revised plan, ${steps.length} step(s) remaining:`);
      steps.forEach((s, idx) => logger.info(`  ${idx + 1}. ${s}`));
      i = 0;
      prevSummary = completed.length ? `"${completed[completed.length - 1]}" -> done` : null;
    }

    outcome = "completed";
    logger.info(
      `\n[orchestrator] task completed — ${completed.length} step(s), ${replans} replan(s), ` +
        `$${costTracker.total.toFixed(4)} total.`,
    );
  } catch (err) {
    errorMessage = err.message;
    throw err;
  } finally {
    appendRunHistory({
      timestamp: new Date().toISOString(),
      runId,
      task,
      outcome,
      steps: stepRecords,
      replanHistory,
      replans,
      totalCost: costTracker.total,
      plannerCost: costTracker.planner,
      executorCost: costTracker.executor,
      durationMs: Date.now() - startedAt,
      error: errorMessage,
    });
    closeRunLogger();
  }
}
