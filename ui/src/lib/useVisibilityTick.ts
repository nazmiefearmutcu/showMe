/**
 * useVisibilityTick — interval timer that pauses while the tab is hidden.
 *
 * Bundle D / PERF-04. Background tabs were running every pane's 30-60s
 * refresh poll forever, fanning out into the sidecar even when the user
 * was deep in another desktop space. Pausing on `document.visibilityState
 * === "hidden"` reduces both sidecar load and React re-render cost; when
 * the tab returns we restart the interval immediately (callers can read
 * the tick to re-fetch right away if they want, since the returned value
 * also bumps on the visibility transition via the `start()` path).
 *
 * The hook returns an ever-increasing counter so consumers can mirror the
 * existing `useState<number>(0)` + `setTick(t => t + 1)` pattern with no
 * other changes:
 *
 *   const tick = useVisibilityTick(REFRESH_MS);
 *   useEffect(() => { ... }, [tick]);
 */
import { useEffect, useState } from "react";

export function useVisibilityTick(intervalMs: number): number {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (typeof window === "undefined") return;
    let timer: number | null = null;
    // HNT-12: set by stop(), consumed by the next start() — the tick bump
    // below must fire only on a visibility RETURN, never on first mount
    // (mount already runs consumer effects with tick=0; a bump there would
    // double-fire every fetch).
    let resumePending = false;

    const start = () => {
      if (timer != null) return;
      if (resumePending) {
        resumePending = false;
        setTick((t) => t + 1);
      }
      timer = window.setInterval(() => {
        setTick((t) => t + 1);
      }, intervalMs);
    };

    const stop = () => {
      if (timer != null) {
        window.clearInterval(timer);
        timer = null;
        resumePending = true;
      }
    };

    const onVis = () => {
      if (typeof document === "undefined") return;
      if (document.visibilityState === "hidden") stop();
      else start();
    };

    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVis);
    }
    onVis();

    return () => {
      stop();
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVis);
      }
    };
  }, [intervalMs]);

  return tick;
}
