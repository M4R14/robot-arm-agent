// Appends one JSON line per orchestrator run to a human-facing audit
// trail. Single responsibility: persist a record — callers decide what
// goes in it.
import { appendFileSync, renameSync, statSync } from "node:fs";

import { RUN_HISTORY_PATH } from "./constants.js";

// Single-generation rotation: once the log crosses this size, the
// current file becomes the one backup and a fresh file starts. Simple
// on purpose — this is a human-facing audit trail, not something that
// needs a long retained history to stay useful; one rotation is enough
// to stop unbounded growth on the volume.
const MAX_RUN_HISTORY_BYTES = 5 * 1024 * 1024;

function rotateIfNeeded() {
  try {
    const { size } = statSync(RUN_HISTORY_PATH);
    if (size >= MAX_RUN_HISTORY_BYTES) {
      renameSync(RUN_HISTORY_PATH, `${RUN_HISTORY_PATH}.1`);
    }
  } catch {
    // ENOENT on first-ever run — nothing to rotate yet.
  }
}

export function appendRunHistory(record) {
  try {
    rotateIfNeeded();
    appendFileSync(RUN_HISTORY_PATH, JSON.stringify(record) + "\n");
  } catch (err) {
    // Best-effort audit trail, not load-bearing for correctness — a
    // write failure here (e.g. volume not mounted in some other
    // environment) shouldn't take down the run it's trying to record.
    console.error(`[orchestrator] could not write run history: ${err.message}`);
  }
}
