/**
 * ALRT — Alarm list. Add / toggle / delete / test-fire.
 *
 * Local persistence (Round 16 preset filesystem on Tauri, localStorage
 * fallback). Round 24+ wires a polling loop that fires the OS-level
 * notification via Round 16's `notify` Tauri command when a threshold
 * trips.
 */
import { useEffect, useMemo, useState } from "react";
import {
  ChangeText,
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
  loadAlerts,
  recordFire,
  toggleAlert,
  type AlertDirection,
  type AlertRow,
} from "@/lib/alerts";
import { confirmAction } from "@/lib/confirm";
import { invoke, isInTauri } from "@/lib/tauri";
import { toast } from "@/lib/toast";
import { fetchQuote, type QuoteSnapshot } from "@/lib/quotes";
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

const DIRECTIONS: { id: AlertDirection; label: string }[] = [
  { id: "above", label: "above" },
  { id: "below", label: "below" },
  { id: "cross_up", label: "cross up" },
  { id: "cross_down", label: "cross down" },
];

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

  useEffect(() => {
    loadAlerts().then(setRows);
  }, []);

  const reload = async () => {
    setRows(null);
    setRows(await loadAlerts());
  };

  const onAdd = async () => {
    const sym = symbol.trim().toUpperCase();
    const t = Number(threshold);
    if (!sym || !Number.isFinite(t)) return;
    await addAlert({
      symbol: sym,
      field,
      direction,
      threshold: t,
      note: note.trim() || undefined,
    });
    setSymbol("");
    setThreshold("");
    setNote("");
    setRows(await loadAlerts());
    toast.success("Alert added", `${sym} ${direction} ${t}`);
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

  const currentValue = quote ? quoteValue(quote, field) : null;
  const conditionPreview =
    currentValue !== null && Number.isFinite(Number(threshold))
      ? previewCondition(currentValue, direction, Number(threshold))
      : null;

  const onToggle = async (id: string, active: boolean) => {
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
    setRows(await recordFire(row.id));
    if (isInTauri()) {
      try {
        await invoke("notify", {
          args: {
            title: `Alert · ${row.symbol}`,
            body: `${row.field} ${row.direction} ${row.threshold} (test)`,
            thread: `alerts:${row.symbol}`,
            severity: "warn",
          },
        });
      } catch (err) {
        toast.warn("Native notify failed", String(err));
      }
    } else {
      toast.info(`Alert test · ${row.symbol}`, `${row.field} ${row.direction} ${row.threshold}`);
    }
  };

  const cols = useMemo<DataGridColumn<AlertRow>[]>(
    () => [
      {
        key: "active",
        header: "On",
        width: 50,
        render: (r) => (
          <button
            type="button"
            onClick={() => onToggle(r.id, !r.active)}
            className="btn btn--ghost u-btn-mini watch-remove-btn"
            
            title={r.active ? "Disable" : "Enable"}
          >
            {r.active ? "●" : "○"}
          </button>
        ),
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
        render: (r) => <ChangeText value={r.threshold} digits={4} signed={false} />,
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
              
              title="Fire a test notification"
            >
              test
            </button>
            <button
              type="button"
              className="btn btn--ghost u-btn-mini watch-remove-btn"
              onClick={() => onDelete(r)}
              
              title="Delete alert"
            >
              ✕
            </button>
          </span>
        ),
      },
    ],
    [],
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
          <FieldRow>
            <Field
              label="Symbol"
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
            <label className="migration-mode-label">
              <span style={dtStyle}>Field</span>
              <select
                value={field}
                onChange={(e) => setField(e.target.value as AlertRow["field"])}
                style={selectStyle}
              >
                <option value="price">price</option>
                <option value="change_pct">change %</option>
                <option value="volume">volume</option>
              </select>
            </label>
            <label className="migration-mode-label">
              <span style={dtStyle}>Direction</span>
              <select
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
            />
          </FieldRow>
          <div style={previewStyle}>
            <span>
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
            <span>polling · local alert poller / native notification</span>
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
                type="button"
                className="btn btn--accent u-btn-28"
                onClick={onAdd}
                disabled={!symbol.trim() || !threshold}
              >
                Add alert
              </button>
            </div>
          </FieldRow>

          <div className="u-mt-12">
            {rows == null ? (
              <Skeleton height={120} />
            ) : rows.length === 0 ? (
              <Empty title="No alerts yet" body="Add a row above to receive a native notification." />
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
  fontFamily: "JetBrains Mono, monospace",
  lineHeight: 1.6,
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
