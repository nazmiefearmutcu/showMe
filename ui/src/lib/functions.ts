/**
 * Typed wrapper around the sidecar's `/api/fn/{code}` endpoint.
 *
 * Round 14 keeps this HTTP-based; Round 18 will swap the underlying
 * transport for a proper Tauri command without touching the call sites.
 */
import { recordPaneContract } from "./pane-contract-store";
import { loadSidecarAuthToken, waitForSidecarReady } from "./sidecar";
import { useAppStore } from "./store";

export interface FunctionCallResult<TData = unknown> {
  code: string;
  instrument: { symbol?: string; asset_class?: string } | null;
  data: TData;
  metadata: Record<string, unknown>;
  fetched_at: string;
  sources: string[];
  warnings: string[];
  elapsed_ms: number | null;
  status?: "ok" | "empty" | "input_error" | "provider_unavailable" | "calc_error";
  asOf?: string;
  inputEcho?: Record<string, unknown>;
  payload?: unknown;
  rows?: Record<string, unknown>[];
  series?: Record<string, unknown>[];
  cards?: Record<string, unknown>[];
  rowCount?: number;
  seriesCount?: number;
  cardCount?: number;
  sourceDetails?: Array<{ name: string; url?: string; asOf?: string; status: string }>;
  reason?: string;
  nextAction?: string;
}

export interface RunFunctionOptions {
  symbol?: string;
  asset_class?: string;
  params?: Record<string, unknown>;
  signal?: AbortSignal;
  timeoutMs?: number;
}

const DEFAULT_FUNCTION_TIMEOUT_MS = 50_000;
// HIGH FIX (audit S10): retries had no jitter, so when 9+ panes hit a cold
// sidecar simultaneously each one fired the same 0→250ms→1000ms sequence in
// lockstep and produced 27 concurrent fetches on the second retry burst.
// Adding random spread per attempt staggers the burst.
const FETCH_RETRY_BASE_DELAYS_MS = [250, 1_000];

function _jitteredDelay(attempt: number): number {
  const base = FETCH_RETRY_BASE_DELAYS_MS[attempt] ?? 1_500;
  // Spread up to ±50% so identical callers desync after the first retry.
  return base + Math.floor(Math.random() * base);
}

/**
 * Module-level in-flight dedupe. Two panes mounting at the same instant with
 * identical (code, symbol, asset_class, params) used to fire two GETs in
 * parallel; we now share the underlying Promise. Aborted callers don't kill
 * the shared request — they just stop observing it (their own AbortSignal
 * detaches via the abort listener).
 */
const _inflightFunctions = new Map<string, Promise<unknown>>();

function _inflightKey(
  code: string,
  symbol: string | undefined,
  asset_class: string | undefined,
  params: Record<string, unknown>,
): string {
  // Stable JSON: sort top-level keys so {a,b} and {b,a} produce the same key.
  const sortedKeys = Object.keys(params).sort();
  const stable: Record<string, unknown> = {};
  for (const k of sortedKeys) stable[k] = params[k];
  return [
    code.toUpperCase(),
    symbol ?? "",
    asset_class ?? "",
    JSON.stringify(stable),
  ].join("|");
}

/**
 * GET when there are only primitive params, POST otherwise (handles arrays /
 * nested objects). The sidecar accepts either.
 */
export async function runFunction<TData = unknown>(
  code: string,
  opts: RunFunctionOptions = {},
): Promise<FunctionCallResult<TData>> {
  // HIGH FIX (audit S10): cold-boot dedupe. If an identical call is already
  // in flight, observe its promise instead of opening a parallel fetch. We
  // do this BEFORE the retry/abort plumbing because dedupe targets identical
  // user intent regardless of distinct AbortSignals.
  const dedupeKey = _inflightKey(
    code,
    opts.symbol,
    opts.asset_class,
    opts.params ?? {},
  );
  const existing = _inflightFunctions.get(dedupeKey);
  if (existing) {
    return existing as Promise<FunctionCallResult<TData>>;
  }
  const promise = _runFunctionUnshared<TData>(code, opts);
  _inflightFunctions.set(dedupeKey, promise);
  // Detach the cleanup from the outer promise — observe rejection so the
  // dedupe-bookkeeping branch doesn't surface as an unhandled rejection on
  // top of the legitimate one already returned to the caller.
  promise.then(
    () => {
      if (_inflightFunctions.get(dedupeKey) === promise) {
        _inflightFunctions.delete(dedupeKey);
      }
    },
    () => {
      if (_inflightFunctions.get(dedupeKey) === promise) {
        _inflightFunctions.delete(dedupeKey);
      }
    },
  );
  return promise;
}

async function _runFunctionUnshared<TData = unknown>(
  code: string,
  opts: RunFunctionOptions = {},
): Promise<FunctionCallResult<TData>> {
  const baseUrl = await waitForSidecarReady();
  const url = `${baseUrl}/api/fn/${encodeURIComponent(code.toUpperCase())}`;
  const params = { ...(opts.params ?? {}) } as Record<string, unknown>;
  if (opts.symbol) params.symbol = opts.symbol;
  if (opts.asset_class) params.asset_class = opts.asset_class;
  const timeoutMs = opts.timeoutMs ?? DEFAULT_FUNCTION_TIMEOUT_MS;
  const ac = new AbortController();
  let timedOut = false;
  const timeout = window.setTimeout(() => {
    timedOut = true;
    ac.abort();
  }, timeoutMs);
  const onAbort = () => ac.abort();
  opts.signal?.addEventListener("abort", onAbort, { once: true });
  if (opts.signal?.aborted) ac.abort();

  const hasComplex = Object.values(params).some(
    (v) => typeof v === "object" && v !== null,
  );
  const requestStartedAt = Date.now();

  const fetchOnce = async () => {
    // 2026-05-11 hotfix: runFunction used to bypass sidecarFetch and never
    // attached the X-ShowMe-Token header, so every `useFunction(...)` call
    // hit the auth middleware and returned 401 on the live signed build.
    // Welcome's portfolio panel + PORT pane both went silent because of
    // this. Pull the token here so /api/fn/{code} always carries it.
    const token = await loadSidecarAuthToken();
    const headers: Record<string, string> = {};
    if (token) headers["X-ShowMe-Token"] = token;
    if (hasComplex) {
      headers["content-type"] = "application/json";
      return fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(params),
        signal: ac.signal,
      });
    }
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v == null) continue;
      qs.set(k, String(v));
    }
    return fetch(`${url}${qs.size ? `?${qs}` : ""}`, {
      headers,
      signal: ac.signal,
    });
  };

  let res: Response | undefined;
  try {
    for (let attempt = 0; attempt <= FETCH_RETRY_BASE_DELAYS_MS.length; attempt += 1) {
      try {
        res = await fetchOnce();
        break;
      } catch (err) {
        if (timedOut) {
          throw new FunctionCallError(
            `${code}: timed out after ${timeoutMs}ms`,
            0,
            "timeout",
          );
        }
        if (isAbortError(err) || ac.signal.aborted || opts.signal?.aborted) {
          throw err;
        }
        if (attempt >= FETCH_RETRY_BASE_DELAYS_MS.length) {
          throw err;
        }
        await wait(_jitteredDelay(attempt));
      }
    }
  } catch (err) {
    if (timedOut) {
      throw new FunctionCallError(
        `${code}: timed out after ${timeoutMs}ms`,
        0,
        "timeout",
      );
    }
    throw err;
  } finally {
    window.clearTimeout(timeout);
    opts.signal?.removeEventListener("abort", onAbort);
  }

  if (!res) throw new Error(`${code}: request failed`);
  if (!res.ok) {
    const body = await res.text();
    throw new FunctionCallError(
      `${code}: ${res.status} ${res.statusText}`,
      res.status,
      body,
    );
  }
  const payload = (await res.json()) as FunctionCallResult<TData>;
  if (typeof payload.elapsed_ms !== "number" || !Number.isFinite(payload.elapsed_ms)) {
    payload.elapsed_ms = Math.max(0, Date.now() - requestStartedAt);
  }
  useAppStore.getState().setSidecarStatus("healthy");
  // 2026-05-25 rebuild: stamp the manifest contract envelope into the
  // pane-contract-store for EVERY /api/fn/{code} response — not just the
  // ones routed through useFunction. Bespoke panes (WATCH, PORT, MIS,
  // etc.) that ship their own fetch wrappers still trigger the strip.
  try {
    _stampContract(code, opts.symbol, payload);
  } catch {
    /* never let the contract recorder crash a function call */
  }
  return payload;
}

function _stampContract<T>(
  code: string,
  symbol: string | undefined,
  res: FunctionCallResult<T>,
): void {
  if (!res || typeof res !== "object") return;
  const r = res as unknown as Record<string, unknown>;
  const data = (r.data ?? {}) as Record<string, unknown>;
  const metadata = (r.metadata ?? data.metadata ?? {}) as Record<string, unknown>;
  const sources = _stringList(r.sources ?? data.sources ?? metadata.sources);
  const warnings = _stringList(r.warnings ?? data.warnings ?? metadata.warnings);
  const nextActions = _stringList(data.next_actions ?? metadata.next_actions);
  const dataMode =
    _str(data.data_mode) ||
    _str(r.data_mode) ||
    _str(metadata.data_mode) ||
    _legacyDataState(r, data, metadata);
  const asOf =
    _str(data.as_of) ||
    _str(r.as_of) ||
    _str(r.fetched_at);
  const latency =
    _num(r.elapsed_ms) ?? _num(r.latency_ms) ?? _num(data.latency_ms);
  recordPaneContract(code, symbol, {
    dataMode,
    asOf,
    sources: sources.length ? sources : undefined,
    warnings: warnings.length ? warnings : undefined,
    nextActions: nextActions.length ? nextActions : undefined,
    latencyMs: latency,
    receivedAt: Date.now(),
  });
}

function _str(v: unknown): string | undefined {
  return typeof v === "string" && v.length > 0 ? v : undefined;
}
function _num(v: unknown): number | undefined {
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
}
function _stringList(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  return v.filter((x): x is string => typeof x === "string" && x.length > 0);
}
function _legacyDataState(
  r: Record<string, unknown>,
  data: Record<string, unknown>,
  metadata: Record<string, unknown>,
): string | undefined {
  const ds = r.data_state ?? data.data_state ?? metadata.data_state;
  if (typeof ds === "string") {
    const map: Record<string, string> = {
      live: "live_exchange",
      reference: "delayed_reference",
      model: "modeled",
      synthetic: "modeled",
    };
    if (ds in map) return map[ds];
  }
  if (metadata.degraded === true) return "provider_unavailable";
  return undefined;
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function isAbortError(err: unknown): boolean {
  return err instanceof Error && err.name === "AbortError";
}

export class FunctionCallError extends Error {
  constructor(
    message: string,
    public status: number,
    public body: string,
  ) {
    super(message);
    this.name = "FunctionCallError";
  }
}

/** Convenience hook-style result holder. Use inside a useEffect. */
export interface FunctionCallState<TData = unknown> {
  data?: FunctionCallResult<TData>;
  error?: FunctionCallError | Error;
  loading: boolean;
}
