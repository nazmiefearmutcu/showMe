/**
 * ALRT — Alarm list. Add / toggle / delete / test-fire.
 *
 * Local persistence (Round 16 preset filesystem on Tauri, localStorage
 * fallback).
 *
 * Evaluation is best-effort, client-side polling: while this pane is open
 * (and the app is foreground — paused via `useVisibilityTick` when hidden)
 * it fetches one quote per unique symbol across the ACTIVE alerts every
 * `POLL_MS`, computes each alert's current value + status (armed /
 * triggered), and fires ONCE on a genuine new trigger — the
 * not-triggered→triggered edge for above/below, or an actual crossing
 * between the previous and current observed value for cross_up / cross_down.
 * A per-alert cooldown (`FIRE_COOLDOWN_MS`, derived from `last_fired_at`)
 * blocks an immediate refire. This is NOT a server-side 24/7 engine: alerts
 * only evaluate while the app is running with this pane mounted, and the UI
 * says so.
 */
import { useEffect, useMemo, useRef, useState } from "react";
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
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { formatPrice, formatMissing } from "@/lib/format";
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

export function ALRTPane({ code }: FunctionPaneProps) {
  const [rows, setRows] = useState<AlertRow[] | null>(null);
  const [symbol, setSymbol] = useState("");
  const [threshold, setThreshold] = useState("");
  const [direction, setDirection] = useState<AlertDirection>("above");
  const [field, setField] = useState<AlertRow["field"]>("price");
  const [note, setNote] = useState("");
  const [quote, setQuote] = useState<QuoteSnapshot | null>(null);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  // Round 24 HIGH 8 — threshold validation tracks the parsed shape so
  // we can show a TR-language error instead of silently coercing "1e500"
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
  // Previous observed value per alert id, for cross detection + above/below
  // edge tracking. A ref (not state) so updating it never re-triggers render.
  const prevValuesRef = useRef<Map<string, number>>(new Map());
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
      toast.error("Sembol gerekli");
      return;
    }
    if (!parsed.ok) {
      toast.error(
        parsed.reason === "empty"
          ? "Threshold gerekli"
          : parsed.reason === "not_finite"
            ? "Threshold sonlu bir sayı olmalı (Infinity reddedildi)"
            : "Threshold geçerli bir sayı değil",
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
      setSymbol("");
      setThreshold("");
      setNote("");
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

  // P1 MARQUEE — the real evaluation loop. On every (visibility-gated) tick:
  // fetch one quote per unique ACTIVE symbol, compute each alert's current
  // value + status, and fire ONCE on a genuine new trigger (edge / crossing)
  // subject to the per-alert cooldown. Best-effort + client-side: only runs
  // while this pane is mounted and the app is foreground.
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
      for (const row of activeRows) {
        const snap = fresh[row.symbol];
        if (!snap) continue;
        const value = quoteValue(snap, row.field);
        const prev = prevValuesRef.current.get(row.id) ?? null;
        const { newTrigger } = evaluateAlert(row.direction, row.threshold, value, prev);
        // Record the observation for the next tick BEFORE the cooldown gate so
        // we always track crossings even when a fire is suppressed.
        if (value !== null && Number.isFinite(value)) {
          prevValuesRef.current.set(row.id, value);
        }
        if (!newTrigger) continue;
        const lastFired = row.last_fired_at ? Date.parse(row.last_fired_at) : NaN;
        const inCooldown =
          Number.isFinite(lastFired) && now - lastFired < FIRE_COOLDOWN_MS;
        if (inCooldown) continue;
        await fireAlert(row);
        if (cancelled) break;
      }
    })();

    return () => {
      cancelled = true;
    };
    // evalTick is the trigger; rows feed via rowsRef to avoid re-arming the
    // loop on every CRUD-driven re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [evalTick]);

  const currentValue = quote ? quoteValue(quote, field) : null;
  const conditionPreview =
    currentValue !== null && Number.isFinite(Number(threshold))
      ? previewCondition(currentValue, direction, Number(threshold))
      : null;

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
        render: (r) => (
          <span className="terminal-grid-numeric" style={numericCellStyle}>
            {formatPrice(r.threshold)}
          </span>
        ),
      },
      {
        key: "_current",
        header: "Current",
        numeric: true,
        width: 100,
        render: (r) => {
          const snap = quotes[r.symbol];
          const value = snap ? quoteValue(snap, r.field) : null;
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
          const snap = quotes[r.symbol];
          const value = snap ? quoteValue(snap, r.field) : null;
          const { status } = evaluateAlert(
            r.direction,
            r.threshold,
            value,
            prevValuesRef.current.get(r.id) ?? null,
          );
          if (status === "none") {
            return <span style={{ color: "var(--text-mute)" }}>{formatMissing}</span>;
          }
          return (
            <Pill tone={status === "triggered" ? "warn" : "muted"} withDot>
              {status}
            </Pill>
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
    // `quotes` drives the live Current + Status columns; the handler closures
    // recreated each render ride along.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [quotes],
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
              onChange={(e) => setThreshold(e.target.value)}
              placeholder="e.g. 200"
              aria-invalid={thresholdInvalid || undefined}
              aria-describedby={thresholdInvalid ? "alrt-threshold-error" : undefined}
            />
          </FieldRow>
          {thresholdInvalid && (
            <div
              id="alrt-threshold-error"
              data-testid="alrt-threshold-error"
              role="alert"
              style={{ color: "var(--negative)", fontSize: 11, marginTop: 4 }}
            >
              {thresholdParsed.ok
                ? "Threshold 0 olamaz."
                : thresholdParsed.reason === "not_finite"
                  ? "Sonlu bir sayı gir (Infinity reddedildi)."
                  : "Geçerli bir sayı gir."}
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
              eval · client-side poll every {Math.round(POLL_MS / 1000)}s while
              this pane is open (foreground)
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
  fontSize: 12,
  height: 28,
  padding: "0 8px",
};

const dtStyle: React.CSSProperties = {
  fontSize: 10,
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
  fontSize: 11,
  fontFamily: "var(--font-mono)",
  lineHeight: 1.6,
};

const numericCellStyle: React.CSSProperties = {
  display: "block",
  textAlign: "right",
};

function quoteValue(quote: QuoteSnapshot, field: AlertRow["field"]): number | null {
  if (field === "price") return quote.price ?? quote.last ?? null;
  if (field === "change_pct") return quote.change_pct ?? quote.regularMarketChangePercent ?? null;
  if (field === "volume") return quote.volume ?? null;
  return null;
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
    ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
    : value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}
