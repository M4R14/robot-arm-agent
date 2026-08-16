#!/usr/bin/env node
// Two-agent orchestration entrypoint: `node orchestrator.js "<task>"`.
// Composition root only — CLI argument handling and the process exit
// code live here; the actual Planner/Executor/replan logic is in
// ./orchestrator/ (mirrors extensions/robot-arm-extension/index.ts's
// thin-entrypoint-plus-support-modules shape).
//
// ./orchestrator/constants.js validates QUIET/PLANNER_MODEL from
// process.env at import time (via envalid), so --quiet/--planner-model
// below set process.env and only THEN dynamically import the rest of
// the orchestrator — a plain top-level `import` is hoisted before any
// of this file's own code runs, which would read those env vars too
// early for a CLI flag to still affect them.
import { Command } from "commander";

const program = new Command();

program
  .name("orchestrator")
  .description("Two-agent (Planner/Executor) orchestration for the robot arm task")
  .argument("<task>", "high-level task description, e.g. \"wave hello\"")
  .option("-q, --quiet", "suppress [heartbeat] lines on the console (still written to the per-run log file)")
  .option("--planner-model <model>", "run the Planner on a different pi model than the Executor")
  .action(async (task, options) => {
    if (options.quiet) process.env.QUIET = "1";
    if (options.plannerModel) process.env.PLANNER_MODEL = options.plannerModel;

    const { costTracker } = await import("./orchestrator/cost-tracker.js");
    const { runOrchestrator } = await import("./orchestrator/run.js");

    try {
      await runOrchestrator(task);
    } catch (err) {
      console.error(`[orchestrator] error: ${err.message}`);
      console.error(`[orchestrator] $${costTracker.total.toFixed(4)} spent before failing.`);
      process.exitCode = 1;
    }
  });

await program.parseAsync(process.argv);
