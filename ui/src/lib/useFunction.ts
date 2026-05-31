/**
 * useFunction — minimal data-fetching hook around `runFunction`.
 *
 * Re-fetches when `code`, `symbol`, or any param value changes. Returns a
 * tagged-union state so callers can render skeletons / errors / data without
 * a third dependency.
 *
 * 2026-05-24 — flicker fix. The hook used to call `setData(undefined)` +
 * force `state: "loading"` on every refetch (e.g. the 30s WEI/MOST/PORT/HP
 * auto-poll or a manual `refetch()`), which made charts flash an empty
 * skeleton each cycle. The fix mirrors `panes/function_stub/index.tsx:276`:
 *
 *   - Track the previous fetch key (`code|symbol|paramsKey`) in a ref.
 *   - If the next fetch reuses that key AND we already have `data`, this is
 *     a *refresh*: keep `data` on screen, set state to `"refreshing"`, and
 *     only swap it once the new payload lands (or roll back to `"error"`
 *     on failure — `data` still stays visible so users see stale + the
 *     error pill instead of a hard wipe).
 *   - When the key actually changes (symbol switch, interval change), keep
 *     the old behaviour: clear data + flip to `"loading"`.
 *
 * Contract is additive: existing consumers that only branch on
 * `"loading" | "ok" | "error"` keep working; new consumers can opt in to
 * `"refreshing"` for a subtle "updating…" indicator without re-rendering
 * the skeleton.
 */
import { useEffect, useRef, useState } from "react";
import {
  runFunction,
  type FunctionCallResult,
  type FunctionCallError,
} from "./functions";
import { recordPaneContract } from "./pane-contract-store";
import { useAppStore } from "./store";
import { isInTauri } from "./tauri";

interface Args {
  code: string;
  symbol?: string;
  params?: Record<string, unknown>;
  enabled?: boolean;
}

export interface UseFunctionResult<T = unknown> {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: FunctionCallResult<T>;
  error?: FunctionCallError | Error;
  refetch: () => void;
}

export function useFunction<T = unknown>({
  code,
  symbol,
  params,
  enabled = true,
}: Args): UseFunctionResult<T> {
  const [tick, setTick] = useState(0);
  const [state, setState] = useState<UseFunctionResult<T>["state"]>("idle");
  const [data, setData] = useState<FunctionCallResult<T>>();
  const [error, setError] = useState<Error>();
  const sidecarPort = useAppStore((s) => s.sidecarPort);
  const waitingForSidecar = enabled && isInTauri() && sidecarPort == null;

  // HIGH FIX (audit S11): JSON.stringify({a,b}) ≠ JSON.stringify({b,a}) which
  // caused the effect dep to flip every time a parent re-rendered with a new
  // object literal whose keys happened to enumerate in a different order
  // (e.g. spread + override). The "same" call would refetch on every render.
  // stableStringify sorts top-level keys so the fingerprint is order-invariant.
  const paramsKey = _stableStringify(params ?? {});

  // Tracks the (code|symbol|paramsKey) of the last fetch so we can tell a
  // refresh (same key, data already on screen) from an initial / key-changing
  // load. Persists across `tick`-only re-runs so `refetch()` is treated as a
  // refresh too.
  const previousFetchKey = useRef<string>("");
  // Bundle D / STALE-01. The refetch effect previously closed over the
  // `data` from the *render that scheduled it*, not the latest one. If two
  // refetches landed back-to-back (e.g. `refetch()` clicked while a poll
  // tick scheduled another fetch on the same microtask) the second effect
  // saw `data === undefined` even after the first one had populated state,
  // and mis-classified the call as `"loading"` (full skeleton flash) instead
  // of `"refreshing"`. Mirroring `data` into a ref keeps the latest value
  // visible inside the effect without re-triggering it.
  const dataRef = useRef<FunctionCallResult<T> | undefined>(undefined);
  useEffect(() => {
    dataRef.current = data;
  }, [data]);

  useEffect(() => {
    if (!enabled) {
      setState("idle");
      return;
    }
    if (waitingForSidecar) {
      setState("loading");
      setError(undefined);
      setData(undefined);
      // Sidecar boot is a fresh start — clear the fingerprint so the first
      // real fetch is treated as initial-load (not a refresh).
      previousFetchKey.current = "";
      return;
    }
    const ac = new AbortController();
    const fetchKey = `${code}|${symbol ?? ""}|${paramsKey}`;
    const isRefresh = fetchKey === previousFetchKey.current && dataRef.current !== undefined;
    if (isRefresh) {
      setState("refreshing");
      // Keep `data` + previous `error` visible. Don't clear either.
    } else {
      setState("loading");
      setError(undefined);
      setData(undefined);
    }
    previousFetchKey.current = fetchKey;
    runFunction<T>(code, {
      symbol,
      params,
      signal: ac.signal,
    })
      .then((res) => {
        setData(res);
        setError(undefined);
        setState("ok");
        // 2026-05-25 rebuild contract: surface manifest-declared envelope
        // fields (data_mode / as_of / sources / latency / warnings /
        // next_actions) into the pane-contract-store so PaneChrome can
        // render the same mode-pill + sources + warnings + next-actions
        // strip on every pane — bespoke or ManifestPane.
        _recordContractFromResult(code, symbol, res);
      })
      .catch((err: Error) => {
        if (ac.signal.aborted) return;
        if (isAbortLikeError(err)) {
          window.setTimeout(() => setTick((t) => t + 1), 0);
          return;
        }
        setError(err);
        // On error during a refresh we deliberately *keep* the previous
        // `data` on screen so the UI shows stale + an error pill rather
        // than wiping the chart. `data` was never cleared in the refresh
        // branch above, so just flipping state is enough.
        setState("error");
      });
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, symbol, paramsKey, enabled, tick, waitingForSidecar, sidecarPort]);

  return { state, data, error, refetch: () => setTick((t) => t + 1) };
}

function isAbortLikeError(err: unknown): boolean {
  if (!(err instanceof Error)) return false;
  return err.name === "AbortError" || /abort/i.test(err.message);
}

/**
 * Top-level stable stringify. Sorts top-level keys so {a:1, b:2} and {b:2, a:1}
 * produce the same string. Nested values are passed through `JSON.stringify`
 * unchanged — pane params are flat by contract so deep ordering isn't an
 * issue, and recursing would risk hashing live React refs or symbols.
 */
function _stableStringify(obj: Record<string, unknown>): string {
  const keys = Object.keys(obj).sort();
  const result: Record<string, unknown> = {};
  for (const k of keys) result[k] = obj[k];
  return JSON.stringify(result);
}

/**
 * Extract the rebuild contract envelope fields from any /api/fn/{code}
 * response and stamp them into the pane-contract-store. Tolerates legacy
 * payloads that don't expose data_mode/as_of yet — we look at common
 * legacy aliases (data_state, fetched_at, metadata.degraded) so even
 * existing bespoke panes report something useful in the new strip.
 */
function _recordContractFromResult<T>(
  code: string,
  symbol: string | undefined,
  res: FunctionCallResult<T>,
): void {
  if (!res || typeof res !== "object") return;
  const r = res as unknown as Record<string, unknown>;
  const data = (r.data ?? {}) as Record<string, unknown>;
  const metadata = (r.metadata ?? data.metadata ?? {}) as Record<string, unknown>;
  const sources = _toStringArray(r.sources ?? data.sources ?? metadata.sources);
  const warnings = _toStringArray(r.warnings ?? data.warnings ?? metadata.warnings);
  const nextActionsRaw = (data.next_actions ?? metadata.next_actions) as unknown;
  const nextActions = _toStringArray(nextActionsRaw);
  const dataMode =
    (typeof data.data_mode === "string" && data.data_mode) ||
    (typeof r.data_mode === "string" && r.data_mode) ||
    (typeof metadata.data_mode === "string" && metadata.data_mode) ||
    _legacyDataState(r, data, metadata) ||
    undefined;
  const asOf =
    (typeof data.as_of === "string" && data.as_of) ||
    (typeof r.as_of === "string" && r.as_of) ||
    (typeof r.fetched_at === "string" && r.fetched_at) ||
    undefined;
  const latencyMsRaw = r.elapsed_ms ?? r.latency_ms ?? data.latency_ms;
  const latencyMs = typeof latencyMsRaw === "number" ? latencyMsRaw : undefined;
  recordPaneContract(code, symbol, {
    dataMode,
    asOf,
    sources: sources.length > 0 ? sources : undefined,
    warnings: warnings.length > 0 ? warnings : undefined,
    nextActions: nextActions.length > 0 ? nextActions : undefined,
    latencyMs,
    receivedAt: Date.now(),
  });
}

function _toStringArray(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  return v.filter((item): item is string => typeof item === "string" && item.length > 0);
}

function _legacyDataState(
  r: Record<string, unknown>,
  data: Record<string, unknown>,
  metadata: Record<string, unknown>,
): string | undefined {
  // The pre-rebuild contract used `data_state` ∈ {live, synthetic, reference, model}
  // and a `metadata.degraded` boolean. Map those to honest DataMode values so
  // legacy payloads still light up the rebuild strip.
  const ds = (r.data_state ?? data.data_state ?? metadata.data_state) as unknown;
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
