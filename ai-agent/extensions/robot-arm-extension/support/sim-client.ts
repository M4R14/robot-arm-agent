// HTTP client for talking to sim: timeout, retry-on-transient-failure, and
// call logging. All tool `execute` functions in ../tools/*.ts go through
// `callSim` — nothing calls `fetch` directly.

const SIM_URL = process.env.SIM_URL ?? "http://sim:8000";
const REQUEST_TIMEOUT_MS = 10_000;
const MAX_RETRIES = 2;
const RETRY_BASE_DELAY_MS = 300;

export function log(line: string) {
  console.error(`[tool] ${new Date().toISOString()} ${line}`);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function combinedSignal(signal?: AbortSignal): AbortSignal {
  const timeoutSignal = AbortSignal.timeout(REQUEST_TIMEOUT_MS);
  return signal ? AbortSignal.any([signal, timeoutSignal]) : timeoutSignal;
}

// Retries transient failures only: network-level errors (sim unreachable,
// e.g. mid-restart) and 5xx responses (sim's own bug, not the caller's).
// Never retries 4xx — those are real, stable rejections (bad joint_id,
// unreachable pose, rate limit, ...) that retrying identically won't fix;
// the caller needs to see them and adjust.
async function fetchWithRetry(url: string, init: RequestInit): Promise<Response> {
  let lastError: unknown;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await fetch(url, init);
      if (response.status >= 500 && attempt < MAX_RETRIES) {
        lastError = new Error(`sim returned ${response.status}`);
        await sleep(RETRY_BASE_DELAY_MS * 2 ** attempt);
        continue;
      }
      return response;
    } catch (err) {
      lastError = err;
      if (attempt < MAX_RETRIES && !(init.signal as AbortSignal | undefined)?.aborted) {
        await sleep(RETRY_BASE_DELAY_MS * 2 ** attempt);
        continue;
      }
      throw err;
    }
  }
  throw lastError;
}

export async function callSim(toolName: string, path: string, method: "GET" | "POST", body: unknown, signal?: AbortSignal) {
  const startedAt = Date.now();
  log(`-> ${toolName} ${method} ${path}${body !== undefined ? " " + JSON.stringify(body) : ""}`);
  let response: Response;
  try {
    response = await fetchWithRetry(`${SIM_URL}${path}`, {
      method,
      headers: { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: combinedSignal(signal),
    });
  } catch (err) {
    log(`<- ${toolName} NETWORK ERROR (${Date.now() - startedAt}ms): ${err}`);
    throw err;
  }
  const payload = await response.json();
  const durationMs = Date.now() - startedAt;
  if (!response.ok) {
    log(`<- ${toolName} FAILED ${response.status} (${durationMs}ms): ${JSON.stringify(payload)}`);
    const detail = payload?.detail;
    const message = detail?.message ?? JSON.stringify(payload);
    const errorCode = detail?.error_code ?? "ERROR";
    throw new Error(`sim ${path} rejected (${errorCode}): ${message}`);
  }
  log(`<- ${toolName} ok (${durationMs}ms)`);
  return payload;
}

export function jsonResult(payload: unknown) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(payload) }],
    details: payload,
  };
}
