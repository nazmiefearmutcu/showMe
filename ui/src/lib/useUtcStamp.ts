/**
 * useUtcStamp — re-read the wall clock when a freshness signal advances.
 *
 * Panes label their data with "AS OF HH:MM UTC". The stamp has to mean
 * "when we last polled", not "when React last rendered": a sort click or a
 * hover that re-renders the pane must NOT bump the label, or the cockpit
 * claims data is fresher than it is.
 *
 * The signal is normally the `useVisibilityTick` counter (which is also fed
 * into the fetch params, so a new tick *is* a new poll), or the payload
 * object itself when the pane wants the stamp pinned to data arrival:
 *
 *   const tick = useVisibilityTick(REFRESH_MS);
 *   const utcStamp = useUtcStamp(tick);   // re-stamps once per poll
 *   const utcStamp = useUtcStamp(data);   // re-stamps when data arrives
 *
 * `precision` picks HH:MM (default) or HH:MM:SS — MICRO wants seconds
 * because order-book snapshots turn over faster than a minute.
 *
 * `exhaustive-deps` cannot express this. It sees a callback that reads no
 * reactive value and calls the dependency unnecessary — but `new Date()` is
 * exactly the impure read the dependency exists to re-trigger. Dropping it
 * would freeze the stamp at mount; omitting the memo would tie it to render
 * time. Both are wrong, so the rule is silenced here, once, instead of at
 * each of the ~17 call sites.
 */
import { useMemo } from "react";

export function useUtcStamp(
  signal: unknown,
  precision: "minute" | "second" = "minute",
): string {
  const end = precision === "second" ? 19 : 16;
  // `signal` is a cache-buster for the wall-clock read, not a value the
  // callback closes over — see the note above on why the rule is off here.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useMemo(() => new Date().toISOString().slice(11, end), [signal, end]);
}
