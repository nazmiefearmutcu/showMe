/**
 * ALRT — Alarm list. Add / toggle / delete / test-fire.
 *
 * Local persistence (Round 16 preset filesystem on Tauri, localStorage
 * fallback).
 *
 * Evaluation is best-effort, client-side, and runs on two feeds: the live
 * quote feed for each ACTIVE alert symbol (every tick is evaluated, so a
 * crossing between REST samples is not missed), and a REST poll every
 * `POLL_MS` (paused via `useVisibilityTick` when hidden) that refreshes the
 * Current column and covers symbols without a live feed. Each observation
 * computes the alert's current value + status (armed / triggered) and fires
 * ONCE on a genuine new trigger — the not-triggered→triggered edge for
 * above/below, or an actual crossing between the previous and current
 * observed value for cross_up / cross_down.
 * A per-alert cooldown (`FIRE_COOLDOWN_MS`, derived from `last_fired_at`)
 * blocks an immediate refire. This is NOT a server-side 24/7 engine: alerts
 * only evaluate while the app is running with this pane mounted, and the UI
 * says so.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  Field,
  FieldRow,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
} from "@/design-system";
import {
  addAlert,
  deleteAlert,
  isAddingAlert,
  isAlertToggling,
  loadAlerts,
  recordFire,
  toggleAlert,
  type AlertDirection,
  type AlertRow,
} from "@/lib/alerts";
import { confirmAction } from "@/lib/confirm";
import { parseDecimalSafe } from "@/lib/validators";
import { invoke, isInTauri } from "@/lib/tauri";
import { toast } from "@/lib/toast";
import { fetchQuote, type QuoteSnapshot } from "@/lib/quotes";
import { normalizeSymbol, useLiveQuote, type QuoteView } from "@/lib/market-data";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { formatPrice, formatMissing, formatPercent, formatCompactNumber } from "@/lib/format";
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

const DIRECTIONS: { id: AlertDirection; label: string }[] = [
  { id: "above", label: "above" },
  { id: "below", label: "below" },
  { id: "cross_up", label: "cross up" },
  { id: "cross_down", label: "cross down" },
];

/** Client-side evaluation cadence. Paused while the tab is hidden. */
const POLL_MS = 45_000;
/** Don't refire the same alert within this window (uses last_fired_at). */
const FIRE_COOLDOWN_MS = 5 * 60_000;

type AlertStatus = "triggered" | "armed" | "none";

/**
 * One live-feed observation for an alert symbol. `at` is the local time the
 * value was reported, so the pane can tell whether the live feed or the REST
 * snapshot is the newer reading.
 */
interface LiveObservation {
  price: number | null;
  change_pct: number | null;
  volume: number | null;
  at: number;
}

/**
 * B1b — route-bound seed state. Reported by {@link LiveSeedBridge} (mounted
 * only when the pane was opened for a symbol, `#/symbol/<sym>/ALRT`): the
 * live value of the currently-selected alert `field`, plus the honest
 * loading/error shape so the form can say "waiting" vs "no quote" without
 * ever fabricating a number. `field` is carried along so a stale report from
 * the previous field can never seed the wrong input.
 */
interface SeedState {
  /** Symbol provenance — a stale report from the previous route symbol must
   *  never seed the next symbol's input (Workspace reuses the pane instance
   *  across symbol switches, so effects fire with the previous closure). */
  symbol: string;
  field: AlertRow["field"];
  value: number | null;
  source: string | null;
  loading: boolean;
  error: string | null;
}

/**
 * Honest per-tick evaluation. `value` is the alert's current computed value;
 * `prev` is the last observed value for this alert (null on first sight).
 * Returns the status now + whether THIS tick is a genuine new trigger
 * (an edge for above/below, an actual crossing for cross_*). The caller adds
 * the cooldown gate before actually firing.
 */
function evaluateAlert(
  direction: AlertDirection,
  threshold: number,
  value: number | null,
  prev: number | null,
): { status: AlertStatus; newTrigger: boolean } {
  if (value === null || !Number.isFinite(value)) {
    return { status: "none", newTrigger: false };
  }
  if (direction === "above" || direction === "below") {
    const now = direction === "above" ? value > threshold : value < threshold;
    const before =
      prev !== null && Number.isFinite(prev)
        ? direction === "above"
          ? prev > threshold
          : prev < threshold
        : false;
    // Edge only: fire when it flips from not-triggered → triggered. We
    // require a real previous observation so we never fire on first sight
    // (no edge can be established yet).
    const hadPrev = prev !== null && Number.isFinite(prev);
    return { status: now ? "triggered" : "armed", newTrigger: hadPrev && now && !before };
  }
  // cross_up / cross_down — a crossing needs a previous observation on the
  // opposite side of the threshold. Never fires on first sight.
  const crossed =
    prev !== null && Number.isFinite(prev)
      ? direction === "cross_up"
        ? prev < threshold && value >= threshold
        : prev > threshold && value <= threshold
      : false;
  // For the status pill, a cross alert reads "triggered" while value sits on
  // the trigger side of the threshold, "armed" otherwise. The actual fire is
  // gated on `newTrigger` (the momentary crossing), not the resting side.
  const onTriggerSide =
    direction === "cross_up" ? value >= threshold : value <= threshold;
  return { status: onTriggerSide ? "triggered" : "armed", newTrigger: crossed };
}

/** The last value observed for one alert, and when it was observed. */
export interface AlertObservation {
  value: number;
  at: number;
}

/**
 * ALRT#5 — record one observation for an alert, ordered by observation time.
 * An observation older than the newest one already recorded for that alert is
 * reported as `stale` and ignored, so it can never move the edge state back.
 */
export function observeAlertEdge(
  seen: Map<string, AlertObservation>,
  alertId: string,
  direction: AlertDirection,
  threshold: number,
  value: number | null,
  at: number,
): { newTrigger: boolean; stale: boolean } {
  const last = seen.get(alertId);
  if (last && at < last.at) return { newTrigger: false, stale: true };
  const prev = last ? last.value : null;
  const { newTrigger } = evaluateAlert(direction, threshold, value, prev);
  if (value !== null && Number.isFinite(value)) seen.set(alertId, { value, at });
  return { newTrigger, stale: false };
}

/**
 * ALRT#5 — cooldown gate. True when the alert fired within FIRE_COOLDOWN_MS,
 * either per its persisted `last_fired_at` or per `inFlight`, the time this pane
 * started firing it (recorded before the async fire is awaited, so a second
 * evaluation cannot pass while `rows` still shows the old value).
 */
export function isInFireCooldown(
  lastFiredAt: string | null | undefined,
  inFlight: number | undefined,
  now: number,
): boolean {
  const persisted = lastFiredAt ? Date.parse(lastFiredAt) : NaN;
  const latest = Math.max(
    Number.isFinite(persisted) ? persisted : -Infinity,
    inFlight ?? -Infinity,
  );
  return Number.isFinite(latest) && now - latest < FIRE_COOLDOWN_MS;
}

export function ALRTPane({ code, symbol: routeSymbol }: FunctionPaneProps) {
  // B1b (campaign 2026-09-11 double) — route-bound opening. `PaneChrome`'s
  // "set alert" action navigates to `#/symbol/<sym>/ALRT`, so the pane
  // receives the bound symbol as a prop. We prefill the symbol field and
  // seed the threshold from the same live quote source the pane chrome
  // header uses (`useLiveQuote`); with no quote the threshold stays blank
  // and the hint says so (never a fabricated price).
  const routeSym = normalizeSymbol(routeSymbol);
  const [rows, setRows] = useState<AlertRow[] | null>(null);
  const [symbol, setSymbol] = useState(routeSym);
  const [threshold, setThreshold] = useState("");
  const [direction, setDirection] = useState<AlertDirection>("above");
  const [field, setField] = useState<AlertRow["field"]>("price");
  const [note, setNote] = useState("");
  const [quote, setQuote] = useState<QuoteSnapshot | null>(null);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  // B1b — manual-edit seal: once the trader types in the threshold we never
  // overwrite it with a later quote tick. `seededKeyRef` remembers which
  // (symbol|field) already got its one seed, so a 1 Hz quote stream cannot
  // keep re-filling the input.
  const [thresholdTouched, setThresholdTouched] = useState(false);
  const seededKeyRef = useRef("");
  const [seed, setSeed] = useState<SeedState | null>(null);
  // Round 24 HIGH 8 — threshold validation tracks the parsed shape so
  // we can show an explicit error instead of silently coercing "1e500"
  // to Infinity and writing a bogus row.
  const thresholdParsed = parseDecimalSafe(threshold);
  const thresholdInvalid =
    threshold.trim() !== "" &&
    (!thresholdParsed.ok || thresholdParsed.value === 0);
  // Round 24 HIGH 10 — local in-flight flag so the Add button can disable
  // even during the (very brief) gap between click + the alerts store
  // setting `_addingAlert=true`. The store-level isAddingAlert() is the
  // canonical seal but a re-render is needed to pick it up.
  const [adding, setAdding] = useState(false);
  // Round 24 HIGH 9 — re-render trigger for per-row toggle pills. We
  // can't subscribe to the global Set from React directly without zustand,
  // but the toggle handler awaits, then we setRows — so the pill state
  // update naturally rides along with the row reload.

  // Latest quote per unique symbol, populated by the client-side eval loop.
  const [quotes, setQuotes] = useState<Record<string, QuoteSnapshot>>({});
  // Audit A5 ALRT [OPP]: the eval loop's OWN real evaluation timestamps per
  // symbol. Alerts are client-side only (no backend payload carries an eval
  // timestamp — verified against `lib/alerts.ts`), so a row renders the age
  // chip only after this pane genuinely fetched its quote; never fabricated.
  const [evalStamps, setEvalStamps] = useState<Record<string, number>>({});
  // Latest live-feed observation per symbol (ALRT#5). Only changed values
  // update it, so a quiet feed never re-renders the pane.
  const [liveObs, setLiveObs] = useState<Record<string, LiveObservation>>({});
  // Time of the last live report per symbol, even when the value is unchanged
  // (a ref: it feeds the stalled-evaluation check without re-rendering).
  const liveSeenRef = useRef<Record<string, number>>({});
  // Previous observed value per alert id (and when it was observed), for cross
  // detection + above/below edge tracking. A ref (not state) so updating it
  // never re-triggers render.
  const prevValuesRef = useRef<Map<string, AlertObservation>>(new Map());
  // Time each alert was last fired by this pane, recorded before the async fire
  // is awaited, so overlapping evaluations honour the cooldown (ALRT#5).
  const firedAtRef = useRef<Map<string, number>>(new Map());
  // Always-fresh `rows` for the polling callback (closure would otherwise
  // capture a stale snapshot across ticks).
  const rowsRef = useRef<AlertRow[] | null>(null);
  rowsRef.current = rows;
  // Visibility-aware poll tick — pauses while the tab is hidden (PERF-04).
  const evalTick = useVisibilityTick(POLL_MS);

  // CTA target — `Field` isn't a forwardRef (shared DS component, untouched),
  // so focus the symbol input by id from the empty-state button.
  const focusSymbolInput = () => {
    if (typeof document === "undefined") return;
    (document.getElementById("alrt-symbol-input") as HTMLInputElement | null)?.focus();
  };

  useEffect(() => {
    loadAlerts().then(setRows);
  }, []);

  // B1b — (re)prefill when the route hands a symbol to this pane. Workspace
  // reuses the mounted component across symbol switches, so this is an
  // effect on the prop, not just initial state. The old threshold belonged
  // to the previous symbol; clearing it lets the new symbol's quote seed
  // cleanly (and keeps the honest-blank contract when no quote exists).
  useEffect(() => {
    if (!routeSym) return;
    setSymbol(routeSym);
    setThreshold("");
    setThresholdTouched(false);
    seededKeyRef.current = "";
    // R1-1 — kill a stale seed from the previous symbol during the
    // transition. Symbol-aware: on mount (and after the bridge already
    // reported the NEW symbol's state before this effect runs) the fresh
    // seed is kept, so the one-shot seeding still works on arrival.
    setSeed((prev) => (prev && prev.symbol !== routeSym ? null : prev));
  }, [routeSym]);

  // Stable collector for the seed bridge — the functional update bails out
  // when nothing changed, so the 1 Hz quote clock never re-renders the pane.
  const onSeed = useCallback((next: SeedState) => {
    setSeed((prev) =>
      prev &&
      prev.symbol === next.symbol &&
      prev.field === next.field &&
      prev.value === next.value &&
      prev.source === next.source &&
      prev.loading === next.loading &&
      prev.error === next.error
        ? prev
        : next,
    );
  }, []);

  // One seed per (symbol, field), and only while the trader hasn't taken
  // over the input. A null value (no quote / no such field on the quote)
  // seeds nothing — the hint reports the honest state instead. The symbol
  // provenance gate (R1-1) makes the previous closure's seed inert.
  useEffect(() => {
    if (!routeSym || thresholdTouched) return;
    if (seed == null || seed.symbol !== routeSym || seed.field !== field) return;
    if (seed.value == null || !Number.isFinite(seed.value)) return;
    const key = `${routeSym}|${field}`;
    if (seededKeyRef.current === key) return;
    setThreshold(seedThresholdText(seed.value, field));
    seededKeyRef.current = key;
  }, [routeSym, thresholdTouched, seed, field]);

  const reload = async () => {
    setRows(null);
    setRows(await loadAlerts());
  };

  const onAdd = async () => {
    // Round 24 HIGH 10 — local + store guards. Prevents Enter-spam from
    // queuing duplicate addAlert calls before the store flag flips.
    if (adding || isAddingAlert()) return;
    const sym = symbol.trim().toUpperCase();
    // Round 24 HIGH 8 — parseDecimalSafe rejects "1e500" / "Infinity" /
    // "" instead of silently coercing to a non-finite number.
    const parsed = parseDecimalSafe(threshold);
    if (!sym) {
      toast.error("Symbol required");
      return;
    }
    if (!parsed.ok) {
      toast.error(
        parsed.reason === "empty"
          ? "Threshold required"
          : parsed.reason === "not_finite"
            ? "Threshold must be a finite number (Infinity rejected)"
            : "Threshold is not a valid number",
      );
      return;
    }
    setAdding(true);
    try {
      await addAlert({
        symbol: sym,
        field,
        direction,
        threshold: parsed.value,
        note: note.trim() || undefined,
      });
      setSymbol(routeSym || "");
      setThreshold("");
      setNote("");
      // A route-bound form goes back to a fresh seeded state after Add
      // (re-arms the one-shot seed); without a route this is the exact
      // pre-B1b reset (blank form).
      setThresholdTouched(false);
      seededKeyRef.current = "";
      setRows(await loadAlerts());
      toast.success("Alert added", `${sym} ${direction} ${parsed.value}`);
    } finally {
      setAdding(false);
    }
  };

  const onCheckQuote = async () => {
    const sym = symbol.trim().toUpperCase();
    if (!sym) return;
    setQuoteLoading(true);
    setQuoteError(null);
    try {
      setQuote(await fetchQuote(sym));
    } catch (err) {
      setQuote(null);
      setQuoteError(err instanceof Error ? err.message : String(err));
    } finally {
      setQuoteLoading(false);
    }
  };

  // Shared fire path — recordFire (persist) + toast + native notify. Used by
  // both the manual "test fire" button and the real evaluation loop. `test`
  // tags the notification copy so a manual fire reads distinctly.
  const fireAlert = async (row: AlertRow, opts?: { test?: boolean }) => {
    setRows(await recordFire(row.id));
    const tag = opts?.test ? " (test)" : "";
    if (isInTauri()) {
      try {
        await invoke("notify", {
          args: {
            title: `Alert · ${row.symbol}`,
            body: `${row.field} ${row.direction} ${row.threshold}${tag}`,
            thread: `alerts:${row.symbol}`,
            severity: "warn",
          },
        });
      } catch (err) {
        toast.warn("Native notify failed", String(err));
      }
    } else {
      toast.info(
        `Alert${opts?.test ? " test" : ""} · ${row.symbol}`,
        `${row.field} ${row.direction} ${row.threshold}`,
      );
    }
  };

  // Shared evaluation for one symbol's observation — a live tick or a REST
  // sample — against that symbol's active alerts. Each alert observes the value
  // once: the observation is recorded BEFORE the cooldown gate so crossings
  // are tracked even when a fire is suppressed, and a fire needs a genuine new
  // trigger (edge / crossing). An alert whose level is already passed when it
  // is first observed records that state and does not fire until a new
  // crossing, so arming never fires on the first tick.
  const evaluateSymbolRows = async (
    rowsForSym: AlertRow[],
    readValue: (field: AlertRow["field"]) => number | null,
    now: number,
    isStopped: () => boolean,
    observedAt: number,
  ): Promise<void> => {
    for (const row of rowsForSym) {
      const { newTrigger, stale } = observeAlertEdge(
        prevValuesRef.current,
        row.id,
        row.direction,
        row.threshold,
        readValue(row.field),
        observedAt,
      );
      // A reading older than one already observed for this alert (e.g. a REST
      // snapshot fetched before a live tick) never moves the edge state.
      if (stale || !newTrigger) continue;
      if (isInFireCooldown(row.last_fired_at, firedAtRef.current.get(row.id), now)) continue;
      firedAtRef.current.set(row.id, now);
      await fireAlert(row);
      if (isStopped()) break;
    }
  };
  // The live feed's callback is stable (it must not re-arm the bridges on
  // every render), so it reaches the latest evaluator through a ref.
  const evaluateRef = useRef(evaluateSymbolRows);
  evaluateRef.current = evaluateSymbolRows;

  // P1 MARQUEE — the real evaluation loop, REST side. On every
  // (visibility-gated) tick: fetch one quote per unique ACTIVE symbol, refresh
  // the Current column, and evaluate each symbol's alerts. Best-effort +
  // client-side: only runs while this pane is mounted and the app is foreground.
  useEffect(() => {
    let cancelled = false;
    const current = rowsRef.current;
    if (!current) return;
    const activeRows = current.filter((r) => r.active);
    if (activeRows.length === 0) return;
    const uniqueSymbols = Array.from(new Set(activeRows.map((r) => r.symbol)));

    (async () => {
      // One fetch per unique symbol (batch). Failures leave that symbol's
      // quote untouched so a transient outage never fabricates a status.
      const results = await Promise.all(
        uniqueSymbols.map(async (sym) => {
          try {
            return [sym, await fetchQuote(sym)] as const;
          } catch {
            return [sym, null] as const;
          }
        }),
      );
      if (cancelled) return;

      const fresh: Record<string, QuoteSnapshot> = {};
      for (const [sym, snap] of results) if (snap) fresh[sym] = snap;
      setQuotes((prev) => ({ ...prev, ...fresh }));

      const now = Date.now();
      // Record this pass as the pane's own "last evaluated" stamp for every
      // symbol that actually returned a quote (audit A5 ALRT OPP).
      setEvalStamps((prev) => {
        const next = { ...prev };
        for (const sym of uniqueSymbols) {
          if (fresh[sym]) next[sym] = now;
        }
        return next;
      });
      for (const sym of uniqueSymbols) {
        const snap = fresh[sym];
        if (!snap) continue;
        const snapAt = Date.parse(snap.fetched_at);
        // Through the ref (refreshed every render) so the tick effect neither
        // re-arms on each render nor calls a stale closure.
        await evaluateRef.current(
          activeRows.filter((r) => r.symbol === sym),
          (field) => quoteValue(snap, field),
          now,
          () => cancelled,
          Number.isFinite(snapAt) ? snapAt : now,
        );
        if (cancelled) break;
      }
    })();

    return () => {
      cancelled = true;
    };
    // evalTick is the trigger; rows feed via rowsRef to avoid re-arming the
    // loop on every CRUD-driven re-render.
  }, [evalTick]);

  // ALRT#5 — live-tick evaluation. Each report from the live feed is recorded
  // for the Current column and evaluated against that symbol's active alerts
  // right away, so a crossing that starts and returns between REST samples is
  // still seen.
  const onLiveObservation = useCallback((sym: string, obs: LiveObservation) => {
    liveSeenRef.current[sym] = obs.at;
    setLiveObs((prev) => {
      const p = prev[sym];
      if (
        p &&
        p.price === obs.price &&
        p.change_pct === obs.change_pct &&
        p.volume === obs.volume
      ) {
        return prev;
      }
      return { ...prev, [sym]: obs };
    });
    const rowsForSym = (rowsRef.current ?? []).filter(
      (r) => r.active && r.symbol === sym,
    );
    if (rowsForSym.length === 0) return;
    void evaluateRef.current(
      rowsForSym,
      (field) => liveValue(obs, field),
      obs.at,
      () => false,
      obs.at,
    );
  }, []);

  // Symbols that currently need a live feed for evaluation.
  const liveSymbols = useMemo(
    () => Array.from(new Set((rows ?? []).filter((r) => r.active).map((r) => r.symbol))),
    [rows],
  );

  const currentValue = quote ? quoteValue(quote, field) : null;
  const conditionPreview =
    currentValue !== null && Number.isFinite(Number(threshold))
      ? previewCondition(currentValue, direction, Number(threshold))
      : null;

  // B1b seed hint — honest copy for the route-bound form. It never claims a
  // seeded value before one exists, and it never says "no quote" while the
  // provider is still loading. Untouched only: after a manual edit the
  // trader owns the input and the hint retires.
  const fieldLabel = field === "change_pct" ? "change %" : field;
  const seedHint =
    routeSym &&
    !thresholdTouched &&
    seed != null &&
    seed.symbol === routeSym &&
    seed.field === field
      ? seed.value != null && Number.isFinite(seed.value)
        ? `seeded from the live ${routeSym} ${fieldLabel}${seed.source ? ` (${seed.source})` : ""} — edit freely`
        : seed.error
          ? `no live ${routeSym} ${fieldLabel} (${seed.error}) — the threshold stays blank; enter it manually`
          : seed.loading
            ? `waiting for the live ${routeSym} ${fieldLabel} — the threshold seeds on arrival`
            : `no live ${routeSym} ${fieldLabel} — the threshold stays blank; enter it manually`
      : undefined;

  const onToggle = async (id: string, active: boolean) => {
    // Round 24 HIGH 9 — store-level `isAlertToggling()` is the canonical
    // race guard; this re-checks for cheap short-circuit + lets the row
    // pill render its busy state on the next setRows.
    if (isAlertToggling(id)) return;
    setRows(await toggleAlert(id, active));
  };

  const onDelete = async (row: AlertRow) => {
    const ok = await confirmAction({
      title: "Delete alert",
      body: `${row.symbol} ${row.direction} ${row.threshold} — this can't be undone.`,
      primary: "Delete",
      destructive: true,
    });
    if (!ok) return;
    setRows(await deleteAlert(row.id));
    toast.warn("Alert deleted", row.symbol);
  };

  const onTestFire = async (row: AlertRow) => {
    await fireAlert(row, { test: true });
  };

  const cols = useMemo<DataGridColumn<AlertRow>[]>(
    () => [
      {
        key: "active",
        header: "On",
        width: 50,
        render: (r) => {
          // Round 24 HIGH 9 — local toggling check guards the rapid
          // double-tap. The store-level Set is what protects the storage
          // write; this is just the UI affordance.
          const busy = isAlertToggling(r.id);
          return (
            <button
              type="button"
              role="switch"
              aria-checked={r.active}
              aria-label={`${r.symbol} alert active`}
              data-testid={`alrt-toggle-${r.id}`}
              onClick={() => onToggle(r.id, !r.active)}
              disabled={busy}
              className="btn btn--ghost u-btn-mini watch-remove-btn"
              title={busy ? "..." : r.active ? "Disable" : "Enable"}
            >
              {busy ? "…" : r.active ? "●" : "○"}
            </button>
          );
        },
      },
      {
        key: "symbol",
        header: "Symbol",
        width: 100,
        render: (r) => (
          <span className="alrt-symbol">{r.symbol}</span>
        ),
      },
      { key: "field", header: "Field", width: 90 },
      {
        key: "direction",
        header: "Dir",
        width: 90,
        render: (r) => (
          <Pill
            tone={
              r.direction.startsWith("cross")
                ? "accent"
                : r.direction === "above"
                  ? "positive"
                  : "negative"
            }
            withDot={false}
          >
            {r.direction.replace("_", " ")}
          </Pill>
        ),
      },
      {
        key: "threshold",
        header: "Level",
        numeric: true,
        width: 100,
        // Thresholds are unsigned targets, not signed deltas — render plainly
        // in tabular mono so they don't reflow and don't carry a +/- sign.
        // Unit follows the alert field: % for change_pct, compact for volume,
        // price formatting otherwise.
        render: (r) => (
          <span className="terminal-grid-numeric" style={numericCellStyle}>
            {r.field === "change_pct"
              ? formatPercent(r.threshold, { digits: 2 })
              : r.field === "volume"
                ? formatCompactNumber(r.threshold)
                : formatPrice(r.threshold)}
          </span>
        ),
      },
      {
        key: "_current",
        header: "Current",
        numeric: true,
        width: 100,
        render: (r) => {
          const value = observedValue(liveObs[r.symbol], quotes[r.symbol], r.field);
          return (
            <span className="terminal-grid-numeric" style={numericCellStyle}>
              {value === null ? formatMissing : formatPrice(value)}
            </span>
          );
        },
      },
      {
        key: "_status",
        header: "Status",
        width: 90,
        render: (r) => {
          const value = observedValue(liveObs[r.symbol], quotes[r.symbol], r.field);
          const { status } = evaluateAlert(
            r.direction,
            r.threshold,
            value,
            prevValuesRef.current.get(r.id)?.value ?? null,
          );
          if (status === "none") {
            return <span style={{ color: "var(--text-mute)" }}>{formatMissing}</span>;
          }
          // Audit A5 ALRT [OPP]: stalled-poll edge state — the pane's own
          // last successful evaluation age surfaces on the row; nothing is
          // shown until this pane has actually evaluated the symbol. A live
          // tick counts as an evaluation (ALRT#5).
          const liveAt = liveSeenRef.current[r.symbol] ?? 0;
          const lastAt = Math.max(evalStamps[r.symbol] ?? 0, liveAt);
          const ageMs = lastAt > 0 ? Date.now() - lastAt : null;
          const stalled = ageMs != null && ageMs > POLL_MS * 3;
          return (
            <span
              className="u-flex"
              style={statusCellStyle}
              data-testid="alrt-eval-status"
              data-stalled={stalled ? "true" : "false"}
              title={
                stalled
                  ? `Evaluation stalled — last quote ${fmtAge(ageMs ?? 0)} ago`
                  : undefined
              }
            >
              <Pill
                tone={status === "triggered" || stalled ? "warn" : "muted"}
                withDot
              >
                {status}
              </Pill>
              {ageMs != null && (
                <span
                  data-testid="alrt-eval-age"
                  data-stalled={stalled ? "true" : "false"}
                  style={{
                    ...evalAgeStyle,
                    ...(stalled ? evalAgeStalledStyle : null),
                  }}
                >
                  {fmtAge(ageMs)}
                </span>
              )}
            </span>
          );
        },
      },
      {
        key: "fired_count",
        header: "Fired",
        numeric: true,
        width: 70,
      },
      {
        key: "last_fired_at",
        header: "Last fire",
        width: 100,
        render: (r) =>
          r.last_fired_at
            ? new Date(r.last_fired_at).toISOString().slice(11, 16) + " UTC"
            : "—",
      },
      { key: "note", header: "Note" },
      {
        key: "_actions",
        header: "",
        width: 100,
        render: (r) => (
          <span className="u-flex u-gap-4">
            <button
              type="button"
              className="btn btn--ghost u-btn-mini watch-remove-btn"
              onClick={() => onTestFire(r)}
              aria-label={`Test fire ${r.symbol} alert`}
              title="Fire a test notification"
            >
              test
            </button>
            <button
              type="button"
              className="btn btn--ghost u-btn-mini watch-remove-btn"
              onClick={() => onDelete(r)}
              aria-label={`Delete ${r.symbol} alert`}
              title="Delete alert"
            >
              ✕
            </button>
          </span>
        ),
      },
    ],
    // `quotes` and `liveObs` drive the Current + Status columns; `evalStamps`
    // drives the per-row "last evaluated" age; the handler closures recreated
    // each render ride along.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [quotes, evalStamps, liveObs],
  );

  const activeCount = rows?.filter((r) => r.active).length ?? 0;
  const firedCount = rows?.filter((r) => r.fired_count > 0).length ?? 0;

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Alerts"
          subtitle={`${activeCount} active · ${rows?.length ?? 0} total`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="positive" variant="soft" withDot={activeCount > 0}>
                {activeCount} on
              </Pill>
              {firedCount > 0 && (
                <Pill tone="warn" variant="soft" withDot>
                  {firedCount} fired
                </Pill>
              )}
              <Pill tone={isInTauri() ? "accent" : "muted"} variant="soft" withDot={false}>
                {isInTauri() ? "native" : "browser"}
              </Pill>
              <LoadStatePill state={rows == null ? "loading" : "ok"} />
              <RefreshButton
                loading={rows == null}
                onClick={reload}
                title="Refresh alerts"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              onAdd();
            }}
          >
          <FieldRow>
            <Field
              label="Symbol"
              id="alrt-symbol-input"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              placeholder="AAPL"
              list="alrt-symbol-suggestions"
              trailing={
                <button
                  type="button"
                  className="btn btn--ghost alrt-check-btn"
                  onClick={onCheckQuote}
                  disabled={!symbol.trim() || quoteLoading}
                >
                  check
                </button>
              }
            />
            <datalist id="alrt-symbol-suggestions">
              {["AAPL", "MSFT", "NVDA", "SPY", "QQQ", "BTCUSDT", "ETHUSDT", "EURUSD", "GC=F"].map((sym) => (
                <option key={sym} value={sym} />
              ))}
            </datalist>
            <label className="migration-mode-label" htmlFor="alrt-field-select">
              <span style={dtStyle}>Field</span>
              <select
                id="alrt-field-select"
                aria-label="Alert field"
                value={field}
                onChange={(e) => setField(e.target.value as AlertRow["field"])}
                style={selectStyle}
              >
                <option value="price">price</option>
                <option value="change_pct">change %</option>
                <option value="volume">volume</option>
              </select>
            </label>
            <label className="migration-mode-label" htmlFor="alrt-direction-select">
              <span style={dtStyle}>Direction</span>
              <select
                id="alrt-direction-select"
                aria-label="Alert direction"
                value={direction}
                onChange={(e) => setDirection(e.target.value as AlertDirection)}
                style={selectStyle}
              >
                {DIRECTIONS.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.label}
                  </option>
                ))}
              </select>
            </label>
            <Field
              label="Threshold"
              type="number"
              value={threshold}
              onChange={(e) => {
                setThreshold(e.target.value);
                // Manual edit wins from here on — a later quote tick never
                // clobbers what the trader typed.
                setThresholdTouched(true);
              }}
              placeholder="e.g. 200"
              hint={seedHint}
              aria-invalid={thresholdInvalid || undefined}
              aria-describedby={thresholdInvalid ? "alrt-threshold-error" : undefined}
            />
          </FieldRow>
          {/* B1b — mounts only when the pane is route-bound; unbound panes
              (sidebar `#/fn/ALRT`) pay no extra quote subscription. */}
          {routeSym && (
            <LiveSeedBridge symbol={routeSym} field={field} onSeed={onSeed} />
          )}
          {/* ALRT#5 — one live feed per active alert symbol; each tick is
              evaluated against that symbol's alerts (renders nothing). */}
          {liveSymbols.map((sym) => (
            <LiveEvalBridge key={sym} symbol={sym} onObservation={onLiveObservation} />
          ))}
          {thresholdInvalid && (
            <div
              id="alrt-threshold-error"
              data-testid="alrt-threshold-error"
              role="alert"
              style={{ color: "var(--negative)", fontSize: "var(--font-size-sm)", marginTop: 4 }}
            >
              {thresholdParsed.ok
                ? "Threshold cannot be 0."
                : thresholdParsed.reason === "not_finite"
                  ? "Enter a finite number (Infinity rejected)."
                  : "Enter a valid number."}
            </div>
          )}
          <div style={previewStyle}>
            <span style={quoteError ? { color: "var(--negative)" } : undefined}>
              quote ·{" "}
              {quote
                ? `${quote.symbol} ${field} ${formatPreviewValue(currentValue)} (${quote.source})`
                : quoteError || "not checked"}
            </span>
            <span>
              preview ·{" "}
              {conditionPreview
                ? `${conditionPreview.state} by ${formatPreviewValue(conditionPreview.distance)}`
                : "enter symbol, threshold, then check quote"}
            </span>
            <span>
              eval · live quote ticks plus a {Math.round(POLL_MS / 1000)}s REST
              poll while this pane is open (foreground); an alert already past
              its level on first observation does not fire until a new crossing
            </span>
          </div>
          <FieldRow>
            <Field
              label="Note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="optional rationale"
            />
            <div className="alrt-add-row">
              <button
                type="submit"
                data-testid="alrt-add-btn"
                className="btn btn--accent u-btn-28"
                disabled={
                  // Round 24 HIGH 10 — disable on validity + in-flight.
                  // Local `adding` is the React-render flag; isAddingAlert()
                  // is the canonical store seal that survives across mounts.
                  adding ||
                  !symbol.trim() ||
                  !threshold ||
                  thresholdInvalid
                }
              >
                {adding ? "..." : "Add alert"}
              </button>
            </div>
          </FieldRow>
          </form>

          <div className="u-mt-12">
            {rows == null ? (
              <Skeleton height={120} />
            ) : rows.length === 0 ? (
              <Empty
                title="No alerts yet"
                body="Add a row above — active alerts evaluate while this pane is open and notify on a real trigger."
                action={
                  <button
                    type="button"
                    data-testid="alrt-empty-cta"
                    className="btn btn--accent u-btn-28"
                    onClick={focusSymbolInput}
                  >
                    Create first alert
                  </button>
                }
              />
            ) : (
              <DataGrid
                columns={cols}
                rows={rows}
                rowKey={(r) => r.id}
                density="compact"
                ariaLabel="Alerts"
              />
            )}
          </div>
        </PaneBody>
        <PaneFooter>
          <span>storage · preset filesystem (or localStorage)</span>
          <span>
            tauri-notify · {isInTauri() ? "available" : "browser fallback"}
          </span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

const selectStyle: React.CSSProperties = {
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  color: "var(--text-primary)",
  font: "inherit",
  fontSize: "var(--font-size-md)",
  height: 28,
  padding: "0 8px",
};

const dtStyle: React.CSSProperties = {
  fontSize: "var(--font-size-2xs)",
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--text-mute)",
};

const previewStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
  gap: 8,
  marginTop: 10,
  padding: "10px 12px",
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-sm)",
  fontFamily: "var(--font-mono)",
  lineHeight: 1.6,
};

const numericCellStyle: React.CSSProperties = {
  display: "block",
  textAlign: "right",
};

const statusCellStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
};

const evalAgeStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  fontVariantNumeric: "tabular-nums",
};

const evalAgeStalledStyle: React.CSSProperties = {
  color: "var(--warn, #f6c350)",
};

/** Compact age label for the per-row "last evaluated" chip. */
function fmtAge(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h`;
}

function quoteValue(quote: QuoteSnapshot, field: AlertRow["field"]): number | null {
  if (field === "price") return quote.price ?? quote.last ?? null;
  if (field === "change_pct") return quote.change_pct ?? quote.regularMarketChangePercent ?? null;
  if (field === "volume") return quote.volume ?? null;
  return null;
}

function liveValue(obs: LiveObservation, field: AlertRow["field"]): number | null {
  if (field === "price") return obs.price;
  if (field === "change_pct") return obs.change_pct;
  if (field === "volume") return obs.volume;
  return null;
}

/**
 * The value the Current / Status columns show: the newer of the live
 * observation and the REST snapshot, so a dead live feed never pins a stale
 * number once the REST poll has moved on.
 */
function observedValue(
  obs: LiveObservation | undefined,
  snap: QuoteSnapshot | undefined,
  field: AlertRow["field"],
): number | null {
  const snapAt = snap ? Date.parse(snap.fetched_at) : NaN;
  if (obs && (!Number.isFinite(snapAt) || obs.at >= snapAt)) {
    const live = liveValue(obs, field);
    if (live !== null) return live;
  }
  return snap ? quoteValue(snap, field) : null;
}

/**
 * ALRT#5 — live evaluation feed for one active alert symbol. Reports each
 * change of the live price / change % / volume to the pane, deduped on the
 * values so a quiet feed never re-renders the pane. Renders nothing.
 */
function LiveEvalBridge({
  symbol,
  onObservation,
}: {
  symbol: string;
  onObservation: (sym: string, obs: LiveObservation) => void;
}) {
  const quote = useLiveQuote(symbol);
  // Only a genuine live tick is an observation. When the hook has no fresher
  // tick it falls back to the REST snapshot price; that reading is not live
  // and is left to the 45 s poll, so it is never stamped as a fresh tick.
  const tick = quote.sourceKind === "tick" ? quote.lastTick : null;
  const price = tick?.price ?? null;
  const changePct = tick?.changePct ?? null;
  // The tick's own feed time, so ordering against REST readings is honest.
  const tickAt = tick ? quote.lastTickAt : null;
  useEffect(() => {
    if (tickAt == null) return;
    if (price == null && changePct == null) return;
    onObservation(symbol, {
      price,
      change_pct: changePct,
      // Volume is not carried by the live observation; the Current column
      // falls back to the REST snapshot volume, labelled as such.
      volume: null,
      at: tickAt,
    });
  }, [symbol, price, changePct, tickAt, onObservation]);
  return null;
}

/**
 * B1b — live seed source for the route-bound add form. Mounted only when the
 * pane was opened for a symbol; subscribes through the same multiplexed
 * `useLiveQuote` channel the pane chrome header uses and reports the current
 * value of the selected field upward. Renders nothing.
 */
function LiveSeedBridge({
  symbol,
  field,
  onSeed,
}: {
  symbol: string;
  field: AlertRow["field"];
  onSeed: (seed: SeedState) => void;
}) {
  const quote = useLiveQuote(symbol);
  const value = liveQuoteValue(quote, field);
  const { source, loading, error } = quote;
  useEffect(() => {
    onSeed({ symbol, field, value, source, loading, error });
  }, [symbol, field, value, source, loading, error, onSeed]);
  return null;
}

/** Same value projection as {@link quoteValue}, for the live QuoteView. */
function liveQuoteValue(quote: QuoteView, field: AlertRow["field"]): number | null {
  if (field === "price") return quote.price;
  if (field === "change_pct") return quote.changePct;
  if (field === "volume") return quote.snapshot?.volume ?? null;
  return null;
}

/**
 * Render a live value into an editable `<input type="number">` seed. Plain
 * decimal text (no locale separators — a number input rejects them), with
 * precision scaled to the magnitude and trailing zeros stripped. Volume
 * seeds as a whole number. Never called with a non-finite value.
 */
function seedThresholdText(value: number, field: AlertRow["field"]): string {
  if (!Number.isFinite(value)) return "";
  if (field === "volume") return String(Math.round(value));
  const abs = Math.abs(value);
  const decimals = field === "change_pct" || abs >= 1000 ? 2 : abs >= 1 ? 4 : 6;
  const text = String(Number(value.toFixed(decimals)));
  return text === "0" && value !== 0 ? String(value) : text;
}

function previewCondition(value: number, direction: AlertDirection, threshold: number): { state: string; distance: number } {
  const distance = value - threshold;
  if (direction === "above") return { state: value > threshold ? "would fire" : "waiting", distance };
  if (direction === "below") return { state: value < threshold ? "would fire" : "waiting", distance };
  if (direction === "cross_up") return { state: value > threshold ? "above trigger" : "below trigger", distance };
  return { state: value < threshold ? "below trigger" : "above trigger", distance };
}

function formatPreviewValue(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return Math.abs(value) >= 1000
    ? value.toLocaleString("en-US", { maximumFractionDigits: 2 })
    : value.toLocaleString("en-US", { maximumFractionDigits: 4 });
}
