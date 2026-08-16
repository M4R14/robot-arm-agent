// Structured logging for one orchestrator run: every message goes to
// that run's persisted JSON-lines file (full detail, always) and a
// human-readable subset to the live console (level-filtered — QUIET
// drops 'debug', used for [heartbeat] lines, from the console only).
// Replaces the previous hand-rolled tee()/console.log monkey-patch with
// pino's multistream + level filtering, which is what it's for.
import { createWriteStream, mkdirSync } from "node:fs";
import { Writable } from "node:stream";

import pino from "pino";

import { QUIET, RUN_LOG_DIR } from "./constants.js";

// Reproduces the plain "[label] message" console format this project
// has used throughout — pino's own default output is JSON, which is
// right for the file but not for a human watching a live TUI-adjacent
// terminal. warn/error records go to stderr, everything else to stdout,
// same split `console.error`/`console.log` gave before.
function consoleStream() {
  return new Writable({
    write(chunk, _enc, callback) {
      try {
        const record = JSON.parse(chunk);
        const out = record.level >= 40 ? process.stderr : process.stdout;
        out.write(record.msg + "\n");
      } catch {
        // pino always emits valid JSON per line; a parse failure here
        // would mean something upstream is broken. Drop rather than
        // dump a raw buffer into the terminal.
      }
      callback();
    },
  });
}

let logger = null;
let fileStream = null;

export function openRunLogger(runId) {
  mkdirSync(RUN_LOG_DIR, { recursive: true });
  fileStream = createWriteStream(`${RUN_LOG_DIR}/${runId}.log`, { flags: "a" });
  logger = pino(
    { level: "trace", base: { runId } },
    pino.multistream([
      { stream: fileStream, level: "trace" },
      { stream: consoleStream(), level: QUIET ? "info" : "debug" },
    ]),
  );
  return logger;
}

export function getLogger() {
  if (!logger) throw new Error("logger not opened — call openRunLogger() first");
  return logger;
}

export function closeRunLogger() {
  if (fileStream) {
    fileStream.end();
    fileStream = null;
  }
  logger = null;
}
