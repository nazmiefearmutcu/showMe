/**
 * DDM — Dividend Discount Model (Gordon growth).
 *
 * Header: r / g assumption inputs (persisted) + status pill + refresh.
 * Body: fair-value vs price KPI ribbon, P = D1/(r-g) step table, and the
 * backend r×g sensitivity surface rendered as a compact grid with the
 * current-assumption cell highlighted.
 *
 * Honesty: the backend returns fair_value_per_share = 0 when no TTM dividend
 * is available (non-payer or feed down); the pane then hides the misleading
 * premium/discount figure and surfaces the provider warning verbatim. The
 * r <= g error envelope is shown as a validation state, never as a number.
 */
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { defaultSymbolForFunction } from "@/lib/symbols";
import { useLiveQuote } from "@/lib/market-data";
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "./function-controls";
import { usePersistentNumber } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface DMMSurfaceCell {
  required_return?: number;
  growth?: number;
  value?: number | null;
  bucket?: string;
}

interface DMMStepRow {
  metric?: string;
  value?: number;
  formula?: string;
}

interface DDMData {
  status?: string;
  error?: string;
  dividend_ttm?: number;
  next_dividend?: number;
  growth?: number;
  required_return?: number;
  fair_value_per_share?: number;
  rows?: DMMStepRow[];
  surface?: DMMSurfaceCell[];
  methodology?: string;
}

export function DDMPane({ code, symbol }: FunctionPaneProps) {
  const [r, setR] = usePersistentNumber("showme.ddm.r", 0.09);
  const [g, setG] = usePersistentNumber("showme.ddm.g", 0.03);
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY"]);
  const { state, data, error, refetch } = useFunction<DDMData>({
    code,
    symbol: effectiveSymbol,
    params: { required_return: r, growth_rate: g },
    enabled: !!effectiveSymbol,
  });
  const quote = useLiveQuote(effectiveSymbol);

  const payload = data?.data;
  const status = payload?.error ? "model_error" : payload?.status ?? "—";
  const isLive = state === "ok" && status === "ok";
  const fairValue = payload?.fair_value_per_share;
  const dividend = payload?.dividend_ttm;
  const hasDividend = typeof dividend === "number" && dividend > 0;
  const price = quote.price;

  const premiumPct =
    hasDividend &&
    typeof fairValue === "number" &&
    fairValue > 0 &&
    typeof price === "number" &&
    price > 0
      ? ((fairValue - price) / price) * 100
      : null;

  const warnings = data?.warnings ?? [];

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="DDM needs an equity ticker." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={56} />
      <Skeleton height={20} />
      <Skeleton height={160} />
    </div>
  ) : state === "error" ? (
    <Empty
      title="Function error"
      body={error?.message ?? "—"}
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : payload?.error ? (
    <Empty
      title="Model not applicable"
      body={payload.error}
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {!hasDividend && (
        <div style={noteStyle} role="note">
          <Pill tone="warn" variant="soft">
            no dividend
          </Pill>
          <span>
            Provider returned no TTM dividend (non-payer or feed unavailable) —
            fair value and premium are not meaningful. Supply dividend_ttm
            explicitly for a tradable model.
          </span>
        </div>
      )}
      {warnings.length > 0 && (
        <div style={noteStyle} role="note">
          {warnings.map((w, i) => (
            <span key={i}>{w}</span>
          ))}
        </div>
      )}
      <section style={kpiGridStyle} aria-label="DDM KPI ribbon">
        <StatCard
          label="Fair value / share"
          value={hasDividend ? fmtMoney(fairValue) : "—"}
          caption={`D1 ${fmtMoney(payload?.next_dividend)} / (r − g)`}
          tone="neutral"
        />
        <StatCard
          label="Price"
          value={fmtMoney(price)}
          caption={price != null ? "live quote" : "no quote"}
          tone="neutral"
        />
        <StatCard
          label="Premium / (discount)"
          value={premiumPct == null ? "—" : fmtSignedPct(premiumPct)}
          caption={premiumPct == null ? "needs dividend + price" : "fair vs market"}
          tone={premiumPct == null ? "neutral" : premiumPct >= 0 ? "positive" : "negative"}
        />
        <StatCard
          label="Assumptions"
          value={`r ${fmtPct(r)} · g ${fmtPct(g)}`}
          caption="persisted inputs"
          tone="neutral"
        />
      </section>
      <SensitivitySurface payload={payload} />
      <StepTable rows={payload?.rows ?? []} />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Dividend Discount Model — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · P = D1 / (r − g)`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : status}
              </Pill>
              <NumberField
                label="r"
                ariaLabel="Required return"
                value={r}
                min={0.001}
                max={1}
                step={0.005}
                onCommit={setR}
              />
              <NumberField
                label="g"
                ariaLabel="Dividend growth rate"
                value={g}
                min={0}
                max={0.99}
                step={0.005}
                onCommit={setG}
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Recompute DDM"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="sources" value={data?.sources?.join(", ") || "—"} />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="r" value={fmtPct(r)} tone="accent" />
          <StatusDivider />
          <StatusSection label="g" value={fmtPct(g)} tone="accent" />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── sensitivity surface ───────────────────────────────────────────── */

function SensitivitySurface({ payload }: { payload: DDMData | undefined }) {
  const { rows, cols, cells, center } = useMemo(() => {
    const surface = payload?.surface ?? [];
    const rs = Array.from(
      new Set(
        surface
          .map((c) => c.required_return)
          .filter((v): v is number => typeof v === "number"),
      ),
    ).sort((a, b) => a - b);
    const gs = Array.from(
      new Set(
        surface
          .map((c) => c.growth)
          .filter((v): v is number => typeof v === "number"),
      ),
    ).sort((a, b) => a - b);
    const map = new Map<string, DMMSurfaceCell>();
    for (const cell of surface) {
      if (typeof cell.required_return === "number" && typeof cell.growth === "number") {
        map.set(`${cell.required_return}|${cell.growth}`, cell);
      }
    }
    const cr = payload?.required_return;
    const cg = payload?.growth;
    return {
      rows: rs,
      cols: gs,
      cells: map,
      center: { r: cr, g: cg },
    };
  }, [payload]);

  if (!rows.length || !cols.length) {
    return (
      <section aria-label="DDM sensitivity surface">
        <SectionTitle>Sensitivity — fair value across r × g</SectionTitle>
        <span className="u-text-mute">No sensitivity surface returned.</span>
      </section>
    );
  }

  return (
    <section aria-label="DDM sensitivity surface">
      <SectionTitle>Sensitivity — fair value across r × g</SectionTitle>
      <div
        className="ddm-surface"
        role="grid"
        aria-label="Fair value sensitivity grid"
        style={{
          ...surfaceStyle,
          gridTemplateColumns: `72px repeat(${cols.length}, minmax(76px, 1fr))`,
        }}
      >
        <div style={surfaceHeadStyle}>r \ g</div>
        {cols.map((gv) => (
          <div key={`h-${gv}`} style={surfaceHeadStyle}>
            {fmtPct(gv)}
          </div>
        ))}
        {rows.map((rv) => (
          <SurfaceRow
            key={`r-${rv}`}
            rv={rv}
            cols={cols}
            cells={cells}
            center={center}
          />
        ))}
      </div>
    </section>
  );
}

function SurfaceRow({
  rv,
  cols,
  cells,
  center,
}: {
  rv: number;
  cols: number[];
  cells: Map<string, DMMSurfaceCell>;
  center: { r?: number; g?: number };
}) {
  const isCenterRow = typeof center.r === "number" && Math.abs(center.r - rv) < 1e-9;
  return (
    <>
      <div style={surfaceHeadStyle}>{fmtPct(rv)}</div>
      {cols.map((gv) => {
        const cell = cells.get(`${rv}|${gv}`);
        const isCenter =
          isCenterRow && typeof center.g === "number" && Math.abs(center.g - gv) < 1e-9;
        const value = typeof cell?.value === "number" ? cell.value : null;
        return (
          <div
            key={`c-${rv}-${gv}`}
            role="gridcell"
            title={cell?.bucket}
            aria-label={`fair value at r ${fmtPct(rv)} g ${fmtPct(gv)}: ${
              value == null ? "not defined (r ≤ g)" : fmtMoney(value)
            }${isCenter ? " (current assumptions)" : ""}`}
            style={{
              ...surfaceCellStyle,
              ...(isCenter ? surfaceCenterStyle : null),
            }}
          >
            {value == null ? "—" : fmtMoney(value)}
          </div>
        );
      })}
    </>
  );
}

/* ── step table ────────────────────────────────────────────────────── */

function StepTable({ rows }: { rows: DMMStepRow[] }) {
  const COLS: DataGridColumn<DMMStepRow>[] = useMemo(
    () => [
      {
        key: "metric",
        header: "Step",
        width: 170,
        render: (row) => <span style={monoPrimaryStyle}>{row.metric ?? "—"}</span>,
      },
      {
        key: "value",
        header: "Value",
        numeric: true,
        width: 120,
        render: (row) => (
          <span style={monoStrongStyle}>
            {typeof row.value !== "number"
              ? "—"
              : /rate|return/i.test(row.metric ?? "")
                ? fmtPct(row.value)
                : fmtMoney(row.value)}
          </span>
        ),
      },
      {
        key: "formula",
        header: "Formula",
        width: 220,
        render: (row) => <span className="u-text-mute">{row.formula ?? "—"}</span>,
      },
    ],
    [],
  );
  if (!rows.length) return null;
  return (
    <DataGrid
      columns={COLS}
      rows={rows}
      rowKey={(row, i) => `${row.metric ?? ""}-${i}`}
      density="compact"
      ariaLabel="DDM model steps"
      // Lane B4: value-descending puts the model OUTPUT (fair value/share)
      // above the D0/D1/r/g derivation rows; the step narrative is one
      // click away (cycle to "none").
      defaultSortKey="value"
      defaultSortDir="descending"
      keyboardNavigable
    />
  );
}

/* ── number input (commit on blur / Enter) ─────────────────────────── */

export function NumberField({
  label,
  ariaLabel,
  value,
  min,
  max,
  step,
  onCommit,
}: {
  label: string;
  ariaLabel: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onCommit: (next: number) => void;
}) {
  const [draft, setDraft] = useState(() => String(value));
  useEffect(() => {
    setDraft(String(value));
  }, [value]);
  const commit = () => {
    const n = Number(draft);
    if (Number.isFinite(n)) {
      const clamped = Math.min(max, Math.max(min, n));
      if (clamped !== value) {
        onCommit(clamped);
        return;
      }
    }
    setDraft(String(value));
  };
  return (
    <label className="fn-numfield" style={numFieldStyle}>
      <span style={numFieldLabelStyle}>{label}</span>
      <input
        type="number"
        aria-label={ariaLabel}
        value={draft}
        min={min}
        max={max}
        step={step}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") setDraft(String(value));
        }}
        style={numInputStyle}
      />
    </label>
  );
}

/* ── formatting + styles ───────────────────────────────────────────── */

function fmtMoney(v: unknown): string {
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtPct(v: unknown): string {
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

function fmtSignedPct(v: number): string {
  if (!Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function SectionTitle({ children }: { children: string }) {
  return (
    <div
      style={{
        fontSize: "var(--font-size-2xs)",
        letterSpacing: "0.08em",
        color: "var(--text-mute)",
        marginBottom: 6,
        textTransform: "uppercase",
      }}
    >
      {children}
    </div>
  );
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const noteStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "6px 10px",
  border: "1px solid var(--warn-soft)",
  borderRadius: 4,
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-md)",
};

const surfaceStyle: CSSProperties = {
  display: "grid",
  gap: 2,
  maxWidth: 560,
};

const surfaceHeadStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: "2px 4px",
  fontVariantNumeric: "tabular-nums",
};

const surfaceCellStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: "var(--font-size-md)",
  color: "var(--text-primary)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: "6px 4px",
  border: "1px solid var(--border-row)",
  borderRadius: 3,
  background: "var(--surface-1)",
};

const surfaceCenterStyle: CSSProperties = {
  background: "var(--accent-soft)",
  borderColor: "var(--accent)",
  fontWeight: 700,
};

const numFieldStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
};

const numFieldLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  color: "var(--text-mute)",
  letterSpacing: "0.06em",
};

const numInputStyle: CSSProperties = {
  width: 68,
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: "var(--font-size-sm)",
  padding: "2px 4px",
  border: "1px solid var(--border-row)",
  borderRadius: 3,
  background: "var(--surface-1)",
  color: "var(--text-primary)",
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const monoPrimaryStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
};
