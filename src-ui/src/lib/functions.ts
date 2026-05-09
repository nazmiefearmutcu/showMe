/**
 * Typed wrapper around the sidecar's `/api/fn/{code}` endpoint.
 *
 * Round 14 keeps this HTTP-based; Round 18 will swap the underlying
 * transport for a proper Tauri command without touching the call sites.
 */
import { waitForSidecarReady } from "./sidecar";
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
const FETCH_RETRY_DELAYS_MS = [250, 1_000];

/**
 * GET when there are only primitive params, POST otherwise (handles arrays /
 * nested objects). The sidecar accepts either.
 */
export async function runFunction<TData = unknown>(
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

  const fetchOnce = () => {
    if (hasComplex) {
      return fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(params),
        signal: ac.signal,
      });
    }
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v == null) continue;
      qs.set(k, String(v));
    }
    return fetch(`${url}${qs.size ? `?${qs}` : ""}`, { signal: ac.signal });
  };

  let res: Response | undefined;
  try {
    for (let attempt = 0; attempt <= FETCH_RETRY_DELAYS_MS.length; attempt += 1) {
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
        if (attempt >= FETCH_RETRY_DELAYS_MS.length) {
          throw err;
        }
        await wait(FETCH_RETRY_DELAYS_MS[attempt]);
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
  return payload;
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
