// Spawns and streams `pi` subprocesses, and extracts data from its
// NDJSON event stream (--mode json). Single responsibility: run a `pi`
// process and hand back its raw output — no Planner/Executor-specific
// logic lives here.
import { spawn } from "node:child_process";

import pRetry from "p-retry";

import { CRASH_RETRY_DELAY_MS, HEARTBEAT_INTERVAL_MS } from "./constants.js";
import { getLogger } from "./logger.js";

// Runs `pi`, streaming stdout to watch for tool_execution_start events
// (to enforce maxToolCalls) without buffering the whole run in memory
// twice. Returns { text, killedReason } — killedReason is set instead of
// throwing when we killed the process ourselves (timeout or tool-call
// cap), so callers can turn that into a normal step failure instead of
// crashing the whole orchestrator run. A non-zero exit we did NOT
// trigger ourselves still rejects — that's runPi()'s (the retrying
// wrapper below) job to catch. `label`, if given, gets a heartbeat line
// every HEARTBEAT_INTERVAL_MS, logged at 'debug' (logger.js drops that
// from the console under QUIET, but it always lands in the per-run
// file) so a human watching a long silent stretch (the LLM thinking,
// not calling tools) can tell the run is still alive rather than hung.
// stderr is piped (not inherited) and logged line-by-line so the
// extension's own [tool] logs land in that same per-run file too,
// instead of only ever appearing live.
function runPiOnce(args, { timeoutMs, maxToolCalls, label } = {}) {
  return new Promise((resolve, reject) => {
    // Every orchestrator-issued pi process is single-shot and already
    // tracked by our own run_history.jsonl/run-log.js — there's never a
    // reason to resume one of these, so --no-session here (added once,
    // for every caller) stops them from silently accumulating unpruned
    // session files under ~/.pi/agent/sessions for the container's
    // entire lifetime (unlike the interactive CMD's own session, which
    // is a deliberate, prunable exception — see docker-compose.yml).
    const child = spawn("pi", [...args, "--no-session"], { stdio: ["ignore", "pipe", "pipe"] });
    const startedAt = Date.now();
    const logger = getLogger();
    let out = "";
    let lineBuffer = "";
    let stderrLineBuffer = "";
    let toolCallCount = 0;
    let killedReason = null;

    function handleLine(line) {
      if (!line.trim()) return;
      let event;
      try { event = JSON.parse(line); } catch { return; }
      if (event.type === "tool_execution_start") {
        toolCallCount++;
        if (maxToolCalls && toolCallCount > maxToolCalls && !killedReason) {
          killedReason = `exceeded ${maxToolCalls} tool calls in one step without finishing`;
          child.kill("SIGTERM");
        }
      }
    }

    const timer = timeoutMs
      ? setTimeout(() => {
          if (!killedReason) {
            killedReason = `timed out after ${Math.round(timeoutMs / 1000)}s`;
            child.kill("SIGTERM");
          }
        }, timeoutMs)
      : null;

    const heartbeat = label
      ? setInterval(() => {
          const elapsedS = Math.round((Date.now() - startedAt) / 1000);
          logger.debug(`[heartbeat] ${label}: ${elapsedS}s elapsed, ${toolCallCount} tool call(s) so far`);
        }, HEARTBEAT_INTERVAL_MS)
      : null;

    child.stdout.on("data", (chunk) => {
      out += chunk;
      lineBuffer += chunk;
      const lines = lineBuffer.split("\n");
      lineBuffer = lines.pop();
      for (const line of lines) handleLine(line);
    });
    child.stderr.on("data", (chunk) => {
      stderrLineBuffer += chunk;
      const lines = stderrLineBuffer.split("\n");
      stderrLineBuffer = lines.pop();
      for (const line of lines) if (line) logger.info(line);
    });
    child.on("error", (err) => {
      if (timer) clearTimeout(timer);
      if (heartbeat) clearInterval(heartbeat);
      reject(err);
    });
    child.on("close", (code) => {
      if (timer) clearTimeout(timer);
      if (heartbeat) clearInterval(heartbeat);
      if (stderrLineBuffer) logger.info(stderrLineBuffer);
      if (killedReason) return resolve({ text: out, killedReason });
      if (code !== 0) return reject(new Error(`pi exited with code ${code}`));
      resolve({ text: out, killedReason: null });
    });
  });
}

// Public entry point: runs `pi` once, and if it crashes on its own
// (rejects — not a timeout/tool-call kill, those resolve) retries once
// after a fixed CRASH_RETRY_DELAY_MS via p-retry (retries: 1, no
// exponential backoff — a second consecutive crash is more likely a
// real, persistent problem than bad luck, so more attempts wouldn't
// help). p-retry treats any rejection from runPiOnce as retryable,
// which is what we want here — a non-zero exit or spawn error are both
// exactly the "transient crash" case this exists for.
export async function runPi(args, opts = {}) {
  return pRetry(() => runPiOnce(args, opts), {
    retries: 1,
    minTimeout: CRASH_RETRY_DELAY_MS,
    maxTimeout: CRASH_RETRY_DELAY_MS,
    onFailedAttempt: (error) => {
      // Fires after every failed attempt, including the last one (where
      // there's nothing left to retry) — retriesLeft distinguishes them
      // so the log doesn't claim it's retrying when it's actually about
      // to give up and let the final error propagate.
      const message = error.retriesLeft > 0
        ? `[orchestrator] pi crashed (${error.message}) — retrying once in ${CRASH_RETRY_DELAY_MS / 1000}s...`
        : `[orchestrator] pi crashed again (${error.message}) — giving up, this looks persistent.`;
      getLogger().warn(message);
    },
  });
}

// Sums cost across every assistant message in the run, not just the
// final one — a step with several tool-call turns has one usage.cost
// per turn. Scans message_end events directly (not just agent_end's
// final message list) so a run we killed ourselves mid-stream (timeout
// / tool-call cap) still contributes whatever cost it incurred before
// being cut off, instead of silently reporting zero.
export function extractCost(ndjson) {
  let total = 0;
  for (const line of ndjson.split("\n")) {
    if (!line.trim()) continue;
    let event;
    try { event = JSON.parse(line); } catch { continue; }
    if (event.type === "message_end" && event.message?.role === "assistant") {
      total += event.message.usage?.cost?.total ?? 0;
    }
  }
  return total;
}

export function lastAssistantText(ndjson) {
  let lastMessages = null;
  for (const line of ndjson.split("\n")) {
    if (!line.trim()) continue;
    let event;
    try { event = JSON.parse(line); } catch { continue; }
    if (event.type === "agent_end") lastMessages = event.messages;
  }
  if (!lastMessages) throw new Error(`no agent_end event in pi output:\n${ndjson}`);
  const lastAssistant = [...lastMessages].reverse().find((m) => m.role === "assistant");
  if (!lastAssistant) throw new Error("no assistant message in pi output");
  return lastAssistant.content
    .filter((c) => c.type === "text")
    .map((c) => c.text)
    .join("\n")
    .trim();
}
