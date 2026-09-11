/**
 * DCFS — DCF Sensitivity (WACC × terminal-growth heatmap + ±20% tornado).
 *
 * Header: wacc / fcfe overrides (0 = provider/live auto) + years control,
 * all persisted, + status pill + refresh.
 * Body: base fair-value vs live spot KPI ribbon, the WACC × g fair-value
 * grid with cells tinted positive/negative versus spot, and the ±20%
 * input tornado list (invalid perturbations rendered honestly, never as 0).
 *
 * Honesty: status "needs_input" (upstream DCF found no base fair value)
 * renders as an explicit empty state with override guidance — the pane
 * never fabricates a grid of zeros. Grid cells whose fair value is null
 * render as "—".
 */
import { useMemo, type CSSProperties } from "react";
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
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import {
  buildGridCsv,
  downloadGridCsv,
  gridCsvFilename,
  type GridCsvColumn,
} from "@/design-system/grid-csv";
import { usePersistentNumber, usePersistentOption } from "./function-control-state";
import { NumberField } from "./DDM";
import type { FunctionPaneProps } from "./registry-types";

interface DCFSGridCell {
  wacc?: number;
  g_terminal?: number;
  fair_value_per_share?: number | null;
  equity_value?: number | null;
  bucket?: string;
}

interface DCFSTornadoRow {
  input?: string;
  low_value?: number;
  high_value?: number;
  low_fv?: number | null;
  high_fv?: number | null;
  value?: number | null;
  delta?: number | null;
  status?: string;
  reason?: string;
}

interface DCFSData {
  status?: string;
  base_fair_value?: number | null;
  wacc_range?: number[];
  g_range?: number[];
  grid?: DCFSGridCell[];
  surface?: DCFSGridCell[];
  tornado?: DCFSTornadoRow[];
  methodology?: string;
}

const YEARS_OPTIONS = [
  { value: 3, label: "3y" },
  { value: 5, label: "5y" },
  { value: 7, label: "7y" },
  { value: 10, label: "10y" },
] as const;
const YEARS_IDS = YEARS_OPTIONS.map((o) => o.value);

export function DCFSPane({ code, symbol }: FunctionPaneProps) {
  // 0 = no override (backend falls back to live WACC / provider FCFE).
  const [wacc, setWacc] = usePersistentNumber("showme.dcfs.wacc", 0);
  const [fcfe, setFcfe] = usePersistentNumber("showme.dcfs.fcfe", 0);
  const [years, setYears] = usePersistentOption<number>(
    "showme.dcfs.years",
    YEARS_IDS,
    5,
  );
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY"]);
  const params = useMemo(
    () => ({
      years,
      ...(wacc > 0 ? { wacc } : {}),
      ...(fcfe > 0 ? { fcfe } : {}),
    }),
    [years, wacc, fcfe],
  );
  const { state, data, error, refetch } = useFunction<DCFSData>({
    code,
    symbol: effectiveSymbol,
    params,
    enabled: !!effectiveSymbol,
  });
  const quote = useLiveQuote(effectiveSymbol);

  const payload = data?.data;
  const status = payload?.status ?? "—";
  const isLive = state === "ok" && status === "ok";
  const hasBase =
    typeof payload?.base_fair_value === "number" && payload.base_fair_value > 0;
  const price = quote.price;
  const upsidePct =
    hasBase && typeof price === "number" && price > 0
      ? ((payload!.base_fair_value as number) - price) / price * 100
      : null;
  const warnings = data?.warnings ?? [];

  // Audit A3 DCFS [OPP]: CSV export of the sensitivity grid. Exporters get
  // the RAW payload numbers (spreadsheets should not receive "$1,234.50").
  const gridRows: DCFSGridCell[] = useMemo(
    () => payload?.grid ?? payload?.surface ?? [],
    [payload],
  );
  const csvColumns = useMemo<GridCsvColumn<DCFSGridCell>[]>(
    () => [
      { key: "wacc", header: "WACC", value: (r) => r.wacc ?? "" },
      {
        key: "g_terminal",
        header: "Terminal growth",
        value: (r) => r.g_terminal ?? "",
      },
      {
        key: "fair_value_per_share",
        header: "Fair value / share",
        value: (r) => r.fair_value_per_share ?? "",
      },
      {
        key: "equity_value",
        header: "Equity value",
        value: (r) => r.equity_value ?? "",
      },
      { key: "bucket", header: "Bucket", value: (r) => r.bucket ?? "" },
    ],
    [],
  );
  const exportCsv = () => {
    const csv = buildGridCsv(csvColumns, gridRows);
    downloadGridCsv(gridCsvFilename(`dcfs-${effectiveSymbol || "grid"}`), csv);
  };

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="DCFS needs an equity ticker." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={56} />
      <Skeleton height={160} />
      <Skeleton height={120} />
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
  ) : !hasBase ? (
    <Empty
      title="Needs provider input"
      body={
        "Upstream DCF produced no base fair value (free cash flow or share count unavailable). Enter a wacc / fcfe override above to run the model offline, or retry."
      }
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {warnings.length > 0 && (
        <div style={noteStyle} role="note">
          {warnings.map((w, i) => (
            <span key={i}>{w}</span>
          ))}
        </div>
      )}
      <section style={kpiGridStyle} aria-label="DCFS KPI ribbon">
        <StatCard
          label="Base fair value"
          value={fmtMoney(payload?.base_fair_value)}
          caption={`DCF engine · ${years}y explicit window`}
          tone="neutral"
        />
        <StatCard
          label="Spot"
          value={fmtMoney(price)}
          caption={price != null ? "live quote" : "no quote"}
          tone="neutral"
        />
        <StatCard
          label="Upside / (downside)"
          value={upsidePct == null ? "—" : fmtSignedPct(upsidePct)}
          caption={upsidePct == null ? "needs base fair value + spot" : "base fair value vs market"}
          tone={upsidePct == null ? "neutral" : upsidePct >= 0 ? "positive" : "negative"}
        />
        <StatCard
          label="Overrides"
          value={`${wacc > 0 ? fmtPct(wacc) : "auto"} · ${fcfe > 0 ? fmtMoney(fcfe) : "auto"}`}
          caption="wacc · fcfe (persisted)"
          tone="neutral"
        />
      </section>
      <Heatmap payload={payload} spot={price} />
      <Tornado rows={payload?.tornado ?? []} />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`DCF Sensitivity — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · WACC × terminal-growth grid + ±20% tornado`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : status}
              </Pill>
              <NumberField
                label="wacc"
                ariaLabel="WACC override"
                value={wacc}
                min={0}
                max={1}
                step={0.005}
                onCommit={setWacc}
              />
              <NumberField
                label="fcfe"
                ariaLabel="FCFE override"
                value={fcfe}
                min={0}
                max={1e12}
                step={1}
                onCommit={setFcfe}
              />
              <SegmentedControl
                label="YRS"
                value={years}
                options={YEARS_OPTIONS}
                onChange={setYears}
                title="Explicit forecast years"
              />
              <button
                type="button"
                className="btn"
                onClick={exportCsv}
                disabled={gridRows.length === 0}
                title="Download CSV"
                aria-label={`Download ${gridRows.length} sensitivity cells as CSV`}
              >
                CSV
              </button>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Recompute DCF sensitivity"
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
          <StatusSection label="years" value={String(years)} tone="accent" />
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

/* ── WACC × g fair-value heatmap ───────────────────────────────────── */

function Heatmap({ payload, spot }: { payload: DCFSData | undefined; spot: number | null | undefined }) {
  const { waccs, gs, cells } = useMemo(() => {
    const grid = payload?.grid ?? payload?.surface ?? [];
    const ws = Array.from(
      new Set(grid.map((c) => c.wacc).filter((v): v is number => typeof v === "number")),
    ).sort((a, b) => a - b);
    const gvals = Array.from(
      new Set(grid.map((c) => c.g_terminal).filter((v): v is number => typeof v === "number")),
    ).sort((a, b) => a - b);
    const map = new Map<string, DCFSGridCell>();
    for (const cell of grid) {
      if (typeof cell.wacc === "number" && typeof cell.g_terminal === "number") {
        map.set(`${cell.wacc}|${cell.g_terminal}`, cell);
      }
    }
    return { waccs: ws, gs: gvals, cells: map };
  }, [payload]);

  if (!waccs.length || !gs.length) {
    return (
      <section aria-label="DCFS heatmap">
        <SectionTitle>Heatmap — fair value across WACC × terminal growth</SectionTitle>
        <span className="u-text-mute">No sensitivity grid returned.</span>
      </section>
    );
  }

  return (
    <section aria-label="DCFS heatmap">
      <SectionTitle>Heatmap — fair value across WACC × terminal growth</SectionTitle>
      <div
        className="dcfs-heatmap"
        role="grid"
        aria-label="Fair value heatmap, WACC rows by terminal-growth columns"
        style={{
          ...gridStyle,
          gridTemplateColumns: `72px repeat(${gs.length}, minmax(84px, 1fr))`,
        }}
      >
        <div style={headStyle}>WACC \ g</div>
        {gs.map((gv) => (
          <div key={`h-${gv}`} style={headStyle}>
            {fmtPct(gv)}
          </div>
        ))}
        {waccs.map((wv) => (
          <HeatmapRow
            key={`w-${wv}`}
            wv={wv}
            gs={gs}
            cells={cells}
            spot={spot}
          />
        ))}
      </div>
    </section>
  );
}

function HeatmapRow({
  wv,
  gs,
  cells,
  spot,
}: {
  wv: number;
  gs: number[];
  cells: Map<string, DCFSGridCell>;
  spot: number | null | undefined;
}) {
  return (
    <>
      <div style={headStyle}>{fmtPct(wv)}</div>
      {gs.map((gv) => {
        const cell = cells.get(`${wv}|${gv}`);
        const value = typeof cell?.fair_value_per_share === "number" ? cell.fair_value_per_share : null;
        const above = value != null && typeof spot === "number" && value >= spot;
        const below = value != null && typeof spot === "number" && value < spot;
        return (
          <div
            key={`c-${wv}-${gv}`}
            role="gridcell"
            title={cell?.bucket}
            aria-label={`fair value at WACC ${fmtPct(wv)} terminal growth ${fmtPct(gv)}: ${
              value == null ? "not available" : `${fmtMoney(value)} (${above ? "above" : "below"} spot)`
            }`}
            style={{
              ...cellStyle,
              ...(above ? cellAboveStyle : null),
              ...(below ? cellBelowStyle : null),
            }}
          >
            {value == null ? "—" : fmtMoney(value)}
          </div>
        );
      })}
    </>
  );
}

/* ── ±20% tornado list ─────────────────────────────────────────────── */

function Tornado({ rows }: { rows: DCFSTornadoRow[] }) {
  const COLS: DataGridColumn<DCFSTornadoRow>[] = useMemo(
    () => [
      {
        key: "input",
        header: "Input (±20%)",
        width: 130,
        render: (row) => <span style={monoPrimaryStyle}>{row.input ?? "—"}</span>,
      },
      {
        key: "low_fv",
        header: "Low FV",
        numeric: true,
        width: 96,
        render: (row) => (
          <span style={monoMutedStyle}>{row.low_fv == null ? "—" : fmtMoney(row.low_fv)}</span>
        ),
      },
      {
        key: "high_fv",
        header: "High FV",
        numeric: true,
        width: 96,
        render: (row) => (
          <span style={monoMutedStyle}>{row.high_fv == null ? "—" : fmtMoney(row.high_fv)}</span>
        ),
      },
      {
        key: "delta",
        header: "Spread",
        numeric: true,
        width: 200,
        render: (row) =>
          row.status === "invalid_perturbation" ? (
            <span className="u-text-mute" title={row.reason}>
              invalid — {row.reason ?? "perturbation produced no fair value"}
            </span>
          ) : (
            <span style={monoStrongStyle}>
              {typeof row.delta !== "number" ? "—" : fmtMoney(Math.abs(row.delta))}
            </span>
          ),
      },
    ],
    [],
  );
  if (!rows.length) {
    return (
      <section aria-label="DCFS tornado">
        <SectionTitle>Tornado — ±20% input perturbation impact</SectionTitle>
        <span className="u-text-mute">No tornado rows returned.</span>
      </section>
    );
  }
  return (
    <section aria-label="DCFS tornado">
      <SectionTitle>Tornado — ±20% input perturbation impact</SectionTitle>
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(row, i) => `${row.input ?? ""}-${i}`}
        density="compact"
        ariaLabel="DCF input tornado ranking"
      />
    </section>
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

const gridStyle: CSSProperties = {
  display: "grid",
  gap: 2,
  maxWidth: 620,
};

const headStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: "2px 4px",
  fontVariantNumeric: "tabular-nums",
};

const cellStyle: CSSProperties = {
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

const cellAboveStyle: CSSProperties = {
  background: "var(--positive-soft-hex)",
};

const cellBelowStyle: CSSProperties = {
  background: "var(--negative-soft-hex)",
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

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
};
