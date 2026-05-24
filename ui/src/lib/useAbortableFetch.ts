/**
 * useAbortableFetch — pair a stable AbortController with a React component's
 * lifecycle. On unmount the controller is aborted so any in-flight `fetch()`
 * (or `runFunction`/`sidecarFetch` that respect a signal) tears down cleanly
 * instead of resolving into a setState-after-unmount warning.
 *
 * The wrapped runner returns a fresh AbortController for each call (so a new
 * fetch cancels the previous one) but always wires the *outer* unmount
 * signal too — so a navigation away or a parent leaf swap kills every
 * pending request the component started.
 *
 * Usage:
 *   const { run, isMounted } = useAbortableFetch();
 *   const r = await run((signal) => runScan(req, signal));
 *
 * `isMounted()` is the post-await guard so callers can early-return without
 * a setState warning when an unmount races a resolve.
 */
import { useCallback, useEffect, useRef } from "react";

export interface AbortableFetchHandle {
  /**
   * Invoke `runner` with an AbortSignal that fires when the component
   * unmounts OR when `run()` is called again (whichever happens first).
   *
   * The runner is responsible for plumbing the signal into the actual
   * fetch / sidecarFetch / runFunction call. Returns whatever the runner
   * resolves with.
   */
  run<T>(runner: (signal: AbortSignal) => Promise<T>): Promise<T>;
  /** False once the component has unmounted. Use as a post-await guard. */
  isMounted: () => boolean;
  /** Cancel the latest in-flight request without unmounting. */
  cancel: () => void;
}

export function useAbortableFetch(): AbortableFetchHandle {
  const mountedRef = useRef(true);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, []);

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, []);

  const run = useCallback(<T>(runner: (signal: AbortSignal) => Promise<T>): Promise<T> => {
    controllerRef.current?.abort();
    const ac = new AbortController();
    controllerRef.current = ac;
    return runner(ac.signal);
  }, []);

  const isMounted = useCallback(() => mountedRef.current, []);

  return { run, isMounted, cancel };
}
