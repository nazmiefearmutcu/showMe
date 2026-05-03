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
            className="btn btn--ghost"
            style={{ height: 18, fontSize: 10, padding: "0 6px" }}
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
          <span style={{ color: "var(--accent)", fontWeight: 700 }}>
            {r.symbol}
          </span>
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
          <span style={{ display: "flex", gap: 4 }}>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => onTestFire(r)}
              style={{ height: 18, fontSize: 10, padding: "0 6px" }}
              title="Fire a test notification"
            >
              test
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => onDelete(r)}
              style={{ height: 18, fontSize: 10, padding: "0 6px" }}
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

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="Alerts"
          subtitle={`${rows?.length ?? 0} alarm(s)`}
          trailing={
            <FunctionControlGroup>
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
            />
            <label
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 4,
                width: "100%",
              }}
            >
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
            <label
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 4,
                width: "100%",
              }}
            >
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
          <FieldRow>
            <Field
              label="Note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="optional rationale"
            />
            <div style={{ display: "flex", alignItems: "flex-end", height: 50 }}>
              <button
                type="button"
                className="btn btn--accent"
                onClick={onAdd}
                disabled={!symbol.trim() || !threshold}
                style={{ height: 28 }}
              >
                Add alert
              </button>
            </div>
          </FieldRow>

          <div style={{ marginTop: 12 }}>
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
  background: "var(--bg-elev-2)",
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
