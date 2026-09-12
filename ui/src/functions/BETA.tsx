/**
 * BETA — CAPM beta vs benchmark.
 *
 * Header: headline window + rolling-history window controls (persisted)
 * + status pill + refresh.
 * Body: beta / R² / correlation / samples headline cards for the selected
 * window, an inline-SVG rolling-beta sparkline, and the full per-window
 * regression table.
 *
 * Honesty: the backend's `computed_market_model` fallback is a SEEDED
 * baseline (static betas, no regression, no history) — the pane labels it
 * as such instead of passing it off as a live estimate. provider_unavailable
 * / input_required reasons are surfaced verbatim.
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
  Sparkline,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { formatNumberPlain } from "@/lib/format";
import { useFunction } from "@/lib/useFunction";
import { defaultSymbolForFunction } from "@/lib/symbols";
import {
  buildGridCsv,
  downloadGridCsv,
  gridCsvFilename,
  type GridCsvColumn,
} from "@/design-system/grid-csv";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface BetaWindowRow {
  window?: string;
  window_days?: number;
  beta?: number;
  correlation?: number;
  samples?: number;
  annualized_volatility_target?: number;
  annualized_volatility_bench?: number;
}

interface BetaHistoryPoint {
  date?: string;
  beta?: number;
  rolling_window?: number;
  samples?: number;
}

interface BetaData {
  status?: string;
  reason?: string;
  benchmark?: string;
  rows?: BetaWindowRow[];
  betas?: Record<string, Omit<BetaWindowRow, "window">>;
  history?: BetaHistoryPoint[];
  methodology?: string;
}

const WINDOW_OPTIONS = [
  { value: "1Y", label: "1Y" },
  { value: "2Y", label: "2Y" },
  { value: "5Y", label: "5Y" },
] as const;
const WINDOW_IDS = WINDOW_OPTIONS.map((o) => o.value);

const ROLLING_OPTIONS = [
  { value: 30, label: "30d" },
  { value: 60, label: "60d" },
  { value: 90, label: "90d" },
  { value: 120, label: "120d" },
] as const;
const ROLLING_IDS = ROLLING_OPTIONS.map((o) => o.value);

export function BetaPane({ code, symbol }: FunctionPaneProps) {
  const [window, setWindow] = usePersistentOption<string>(
    "showme.beta.window",
    WINDOW_IDS,
    "1Y",
  );
  const [rolling, setRolling] = usePersistentOption<number>(
    "showme.beta.rolling",
    ROLLING_IDS,
    60,
  );
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF", "INDEX"]);
  const { state, data, error, refetch } = useFunction<BetaData>({
    code,
    symbol: effectiveSymbol,
    params: { rolling_window: rolling },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const status = payload?.status ?? "—";
  const isLive = state === "ok" && status === "ok";
  const warnings = data?.warnings ?? [];
  // The seeded baseline returns `betas` without a `rows` array — normalize
  // both shapes into the window-row list.
  const rows: BetaWindowRow[] = useMemo(() => {
    if (payload?.rows?.length) return payload.rows;
    const betas = payload?.betas ?? {};
    return Object.entries(betas).map(([w, v]) => ({ window: w, ...v }));
  }, [payload]);
  const selected = rows.find((r) => r.window === window) ?? rows[0];
  const history = useMemo(() => payload?.history ?? [], [payload]);
  const historyValues = useMemo(
    () =>
      history
        .map((h) => h.beta)
        .filter((v): v is number => typeof v === "number"),
    [history],
  );
  const rSquared =
    typeof selected?.correlation === "number"
      ? selected.correlation * selected.correlation
      : null;
  const isBaseline = status === "computed_market_model";

  // CSV export of the per-window regression table — RAW payload numbers.
  const csvColumns = useMemo<GridCsvColumn<BetaWindowRow>[]>(
    () => [
      { key: "window", header: "Window", value: (r) => r.window ?? "" },
      { key: "window_days", header: "Window days", value: (r) => r.window_days ?? "" },
      { key: "beta", header: "Beta", value: (r) => r.beta ?? "" },
      {
        key: "correlation",
        header: "Correlation",
        value: (r) => r.correlation ?? "",
      },
      { key: "samples", header: "Samples", value: (r) => r.samples ?? "" },
      {
        key: "annualized_volatility_target",
        header: "Ann vol target",
        value: (r) => r.annualized_volatility_target ?? "",
      },
      {
        key: "annualized_volatility_bench",
        header: "Ann vol bench",
        value: (r) => r.annualized_volatility_bench ?? "",
      },
    ],
    [],
  );

  const exportCsv = () => {
    const csv = buildGridCsv(csvColumns, rows);
    downloadGridCsv(
      gridCsvFilename(`beta-${effectiveSymbol || "windows"}`),
      csv,
    );
  };

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="BETA needs a ticker to regress." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={56} />
      <Skeleton height={72} />
      <Skeleton height={140} />
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
  ) : status === "provider_unavailable" || status === "input_required" ? (
    <Empty
      title="Beta unavailable"
      body={payload?.reason ?? status}
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : !selected || typeof selected.beta !== "number" ? (
    <Empty
      title="No beta computed"
      body="Provider returned no overlapping return history for this symbol."
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {isBaseline && (
        <div style={noteStyle} role="note">
          <Pill tone="warn" variant="soft">
            baseline
          </Pill>
          <span>
            Live provider unavailable — these figures are a seeded market-model
            baseline, not a regression of real returns. Do not trade on them.
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
      <section style={kpiGridStyle} aria-label="BETA headline cards">
        <StatCard
          label={`Beta (${selected.window ?? window})`}
          value={fmtNum(selected.beta, 2)}
          caption={`vs ${payload?.benchmark ?? "SPY"} · daily returns`}
          tone={selected.beta >= 1 ? "positive" : "neutral"}
        />
        <StatCard
          label={`R² (${selected.window ?? window})`}
          value={rSquared == null ? "—" : fmtNum(rSquared, 3)}
          caption="correlation² — fit quality"
          tone="neutral"
        />
        <StatCard
          label="Correlation"
          value={
            typeof selected.correlation === "number"
              ? fmtNum(selected.correlation, 2)
              : "—"
          }
          caption={`samples ${selected.samples ?? "—"}`}
          tone="neutral"
        />
        <StatCard
          label="Ann. vol (target / bench)"
          value={`${fmtPct(selected.annualized_volatility_target)} / ${fmtPct(selected.annualized_volatility_bench)}`}
          caption="annualized σ of daily returns"
          tone="neutral"
        />
      </section>
      <section aria-label="Rolling beta sparkline">
        <SectionTitle>Rolling beta — trailing history</SectionTitle>
        {historyValues.length > 1 ? (
          <div style={sparkWrapStyle}>
            <Sparkline
              values={historyValues}
              width={420}
              height={64}
              tone="accent"
              ariaLabel="Rolling beta history sparkline"
            />
            <span className="u-text-mute" style={sparkMetaStyle}>
              {historyValues.length} points · window {history[0]?.rolling_window ?? rolling}d ·
              last {fmtNum(historyValues[historyValues.length - 1], 2)} · min{" "}
              {fmtNum(Math.min(...historyValues), 2)} · max{" "}
              {fmtNum(Math.max(...historyValues), 2)}
            </span>
          </div>
        ) : (
          <span className="u-text-mute">No rolling beta history returned.</span>
        )}
      </section>
      <WindowTable rows={rows} />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`CAPM Beta — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · β = cov(rᵢ, rₘ) / var(rₘ)`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : isBaseline ? "baseline" : status}
              </Pill>
              <SegmentedControl
                label="WINDOW"
                value={window}
                options={WINDOW_OPTIONS}
                onChange={setWindow}
                title="Headline regression window"
              />
              <SegmentedControl
                label="ROLLING"
                value={rolling}
                options={ROLLING_OPTIONS}
                onChange={setRolling}
                title="Rolling history window (days)"
              />
              <button
                type="button"
                className="btn"
                onClick={exportCsv}
                disabled={rows.length === 0}
                title="Download CSV"
                aria-label={`Download ${rows.length} regression windows as CSV`}
              >
                CSV
              </button>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Recompute beta"
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
          <StatusSection label="window" value={window} tone="accent" />
          <StatusDivider />
          <StatusSection label="rolling" value={`${rolling}d`} tone="accent" />
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

/* ── per-window regression table ───────────────────────────────────── */

function WindowTable({ rows }: { rows: BetaWindowRow[] }) {
  const COLS: DataGridColumn<BetaWindowRow>[] = useMemo(
    () => [
      {
        key: "window",
        header: "Window",
        width: 90,
        render: (r) => <span style={monoPrimaryStyle}>{r.window ?? "—"}</span>,
      },
      {
        key: "beta",
        header: "Beta",
        numeric: true,
        width: 90,
        render: (r) => (
          <span style={monoStrongStyle}>
            {typeof r.beta === "number" ? fmtNum(r.beta, 2) : "—"}
          </span>
        ),
      },
      {
        key: "correlation",
        header: "Corr",
        numeric: true,
        width: 84,
        render: (r) => (
          <span style={monoMutedStyle}>
            {typeof r.correlation === "number" ? fmtNum(r.correlation, 2) : "—"}
          </span>
        ),
      },
      {
        key: "samples",
        header: "Samples",
        numeric: true,
        width: 90,
        render: (r) => (
          <span style={monoMutedStyle}>{r.samples ?? "—"}</span>
        ),
      },
      {
        key: "annualized_volatility_target",
        header: "Ann vol target",
        numeric: true,
        width: 120,
        render: (r) => <span style={monoMutedStyle}>{fmtPct(r.annualized_volatility_target)}</span>,
      },
      {
        key: "annualized_volatility_bench",
        header: "Ann vol bench",
        numeric: true,
        width: 120,
        render: (r) => <span style={monoMutedStyle}>{fmtPct(r.annualized_volatility_bench)}</span>,
      },
    ],
    [],
  );
  if (!rows.length) return null;
  return (
    <DataGrid
      columns={COLS}
      rows={rows}
      rowKey={(r) => r.window ?? String(r.window_days)}
      density="compact"
      ariaLabel="Beta by regression window"
    />
  );
}

/* ── formatting + styles ───────────────────────────────────────────── */

function fmtNum(v: number, digits: number): string {
  if (!Number.isFinite(v)) return "—";
  return formatNumberPlain(v, digits);
}

function fmtPct(v: unknown): string {
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(1)}%`;
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
  gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
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

const sparkWrapStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
};

const sparkMetaStyle: CSSProperties = {
  fontSize: "var(--font-size-2xs)",
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
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
