/**
 * useFunction — minimal data-fetching hook around `runFunction`.
 *
 * Re-fetches when `code`, `symbol`, or any param value changes. Returns a
 * tagged-union state so callers can render skeletons / errors / data without
 * a third dependency.
 */
import { useEffect, useState } from "react";
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
  state: "idle" | "loading" | "ok" | "error";
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

  // Stringify params for stable dep — small objects, fine.
  const paramsKey = JSON.stringify(params ?? {});

  useEffect(() => {
    if (!enabled) {
      setState("idle");
      return;
    }
    if (waitingForSidecar) {
      setState("loading");
      setError(undefined);
      setData(undefined);
      return;
    }
    const ac = new AbortController();
    setState("loading");
    setError(undefined);
    setData(undefined);
    runFunction<T>(code, {
      symbol,
      params,
      signal: ac.signal,
    })
      .then((res) => {
        setData(res);
        setState("ok");
      })
      .catch((err: Error) => {
        if (ac.signal.aborted) return;
        setError(err);
        setState("error");
      });
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, symbol, paramsKey, enabled, tick, waitingForSidecar, sidecarPort]);

  return { state, data, error, refetch: () => setTick((t) => t + 1) };
}
