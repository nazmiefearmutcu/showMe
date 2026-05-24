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
      })
      .catch((err: Error) => {
        if (ac.signal.aborted) return;
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
