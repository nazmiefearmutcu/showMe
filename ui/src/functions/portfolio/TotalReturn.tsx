/**
 * TRA — Total Return Analysis (specialized portfolio pane, wave-2 lane L8).
 *
 * Purpose-built screen for `portfolio/_more.py` TRAFunction: a growth-of-$1
 * chart from the sampled `series[]`, a TWR / IRR / CAGR / price-return KPI
 * row, a client-computed max-drawdown read on that same real series, and a
 * tail observation table. Live price history is the backend default; the
 * MODEL toggle opts into the labelled template series (`reference=true`),
 * which the shared data-quality badge then discloses.
 */
import { useMemo, useState } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { formatNumber, formatPercent, formatPrice } from "@/lib/format";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "../function-controls";
import type { FunctionPaneProps } from "../registry-types";
import {
  asRows,
  DataQualityBadge,
  emptyCopy,
  fmtMoney,
  fmtPct,
  MetricStrip,
  PaneGate,
  PortfolioEmpty,
  SectionHead,
  str,
  toneClass,
  WarningStrip,
  type Row,
} from "./shared";

interface TraPayload {
  status?: string;
  reason?: string;
  price_return_total?: number | null;
  twr_total?: number | null;
  irr_annualized?: number | null;
  cagr?: number | null;
  dividends_count?: number;
  dividends_total?: number;
  n_observations?: number;
  first_date?: string;
  last_date?: string;
  series?: Row[];
  summary?: Row;
  methodology?: string;
  [key: string]: unknown;
}

interface GrowthPoint {
  date: string;
  close: number | null;
  growth: number | null;
}

const OBSERVATION_COLUMNS: DataGridColumn<Row>[] = [
  {
    key: "date",
    header: "Date",
    width: 100,
    render: (row) => <span className="portfolio-analytics-num">{str(row.date) ?? "—"}</span>,
  },
  {
    key: "close",
    header: "Close",
    width: 100,
    align: "right",
    numeric: true,
    render: (row) =>
      typeof row.close === "number" ? <span className="portfolio-analytics-num">{formatPrice(row.close)}</span> : "—",
  },
  {
    key: "growth_of_1",
    header: "Growth of 1",
    width: 104,
    align: "right",
    numeric: true,
    render: (row) =>
      typeof row.growth_of_1 === "number" ? (
        <span className="portfolio-analytics-num">{row.growth_of_1.toFixed(4)}</span>
      ) : (
        "—"
      ),
  },
];

export function TotalReturnPane({ code, symbol }: FunctionPaneProps) {
  const [symbolInput, setSymbolInput] = useState("AAPL");
  const [reference, setReference] = useState(false);
  const effectiveSymbol = symbol || symbolInput || "AAPL";

  const params = useMemo(
    () => ({ years: 5, reference }),
    [reference],
  );
  const { state, data, error, refetch } = useFunction<TraPayload>({
    code,
    symbol: effectiveSymbol,
    params,
  });
  const payload = data?.data;

  const points = useMemo<GrowthPoint[]>(
    () =>
      asRows(payload?.series).map((row) => ({
        date: str(row.date) ?? "",
        close: typeof row.close === "number" && Number.isFinite(row.close) ? row.close : null,
        growth:
          typeof row.growth_of_1 === "number" && Number.isFinite(row.growth_of_1)
            ? row.growth_of_1
            : null,
      })),
    [payload],
  );

  const growthValues = useMemo(
    () =>
      points
        .map((point) => point.growth ?? (point.close != null && points[0]?.close ? point.close / points[0].close : null))
        .filter((value): value is number => value != null && Number.isFinite(value)),
    [points],
  );

  const maxDrawdown = useMemo(() => {
    let peak = Number.NEGATIVE_INFINITY;
    let worst = 0;
    for (const value of growthValues) {
      if (value > peak) peak = value;
      if (peak > 0) {
        const drawdown = value / peak - 1;
        if (drawdown < worst) worst = drawdown;
      }
    }
    return growthValues.length > 1 ? worst : null;
  }, [growthValues]);

  const latestGrowth = growthValues.length ? growthValues[growthValues.length - 1] : null;
  const warnings = data?.warnings ?? [];
  const status = str(payload?.status) ?? data?.status ?? "ok";
  const isEmpty = !payload || points.length === 0;

  const badge = (
    <DataQualityBadge
      payload={payload as Row | undefined}
      metadata={data?.metadata}
      sources={data?.sources}
    />
  );
  const empty = emptyCopy(payload as Row | undefined);

  const tailRows = useMemo(() => points.slice(-15).map((point) => ({
    date: point.date,
    close: point.close,
    growth_of_1: point.growth,
  })) as Row[], [points]);

  const body = (
    <PaneGate state={state} error={error} refetch={refetch}>
      {isEmpty ? (
        <PortfolioEmpty badge={badge} title={empty.title} body={empty.body} />
      ) : (
        <div className="portfolio-analytics-view">
          {badge}
          <section className="portfolio-analytics-summary">
            <div className="portfolio-analytics-summary__hero">
              <span className="portfolio-analytics-label">
                {effectiveSymbol} · growth of 1
              </span>
              <strong>
                {latestGrowth == null ? "—" : `${latestGrowth.toFixed(3)}×`}
              </strong>
              <span>
                {payload?.first_date ?? "—"} → {payload?.last_date ?? "—"} ·{" "}
                {payload?.n_observations ?? points.length} observations
              </span>
            </div>
            <MetricStrip
              metrics={[
                {
                  key: "twr",
                  label: "TWR (total)",
                  value: fmtPct(payload?.twr_total, { fromFraction: true, signed: true }),
                  tone: toneClass(typeof payload?.twr_total === "number" ? payload.twr_total : null),
                },
                {
                  key: "irr",
                  label: "IRR (annualized)",
                  value: fmtPct(payload?.irr_annualized, { fromFraction: true, signed: true }),
                  tone: toneClass(typeof payload?.irr_annualized === "number" ? payload.irr_annualized : null),
                },
                {
                  key: "cagr",
                  label: "CAGR",
                  value: fmtPct(payload?.cagr, { fromFraction: true, signed: true }),
                  tone: toneClass(typeof payload?.cagr === "number" ? payload.cagr : null),
                },
                {
                  key: "price_return",
                  label: "Price return",
                  value: fmtPct(payload?.price_return_total, { fromFraction: true, signed: true }),
                  tone: toneClass(
                    typeof payload?.price_return_total === "number" ? payload.price_return_total : null,
                  ),
                },
                {
                  key: "max_dd",
                  label: "Max drawdown",
                  value: maxDrawdown == null ? "—" : formatPercent(maxDrawdown, { fromFraction: true }),
                  tone: toneClass(maxDrawdown),
                  title: "Computed from the growth-of-1 series",
                },
                {
                  key: "dividends",
                  label: "Dividends",
                  value: fmtMoney(payload?.dividends_total),
                  title: typeof payload?.dividends_count === "number" ? `${payload.dividends_count} payment(s)` : undefined,
                },
              ]}
            />
          </section>

          <WarningStrip warnings={warnings} />

          <div className="portfolio-analytics-grid">
            <section className="portfolio-table-panel">
              <SectionHead title="Growth of $1" meta={`${points.length} sampled point(s)`} />
              <GrowthChart points={points} symbol={effectiveSymbol} />
            </section>

            <aside className="portfolio-analytics-rail">
              <section className="portfolio-visual-panel">
                <SectionHead title="Recent observations" meta="tail 15" />
                <DataGrid
                  columns={OBSERVATION_COLUMNS}
                  rows={tailRows}
                  rowKey={(row, idx) => `${String(row.date ?? idx)}-${idx}`}
                  density="compact"
                  ariaLabel="TRA recent observations"
                />
              </section>
              {payload?.methodology ? (
                <section className="portfolio-method-panel">
                  <h3>Method</h3>
                  <p>{payload.methodology}</p>
                </section>
              ) : null}
            </aside>
          </div>
        </div>
      )}
    </PaneGate>
  );

  return (
    <div className="portfolio-analytics-host">
      <Pane>
        <PaneHeader
          code={code.toUpperCase()}
          title="Total Return"
          subtitle="TWR, IRR, CAGR, and dividend return"
          trailing={
            <FunctionControlGroup>
              <label className="portfolio-control-field" htmlFor={`tra-${code}-symbol`}>
                <span>Symbol</span>
                <input
                  id={`tra-${code}-symbol`}
                  value={symbolInput}
                  onChange={(event) => setSymbolInput(event.target.value.toUpperCase())}
                  spellCheck={false}
                />
              </label>
              <button
                type="button"
                className={`btn btn--ghost portfolio-analytics-live${reference ? "" : " portfolio-analytics-live--on"}`}
                onClick={() => setReference((value) => !value)}
                aria-pressed={!reference}
                title="Toggle live price history vs the labelled template series"
              >
                {reference ? "MODEL" : "LIVE"}
              </button>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                busy={state === "refreshing" || state === "loading"}
                onClick={refetch}
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody className="portfolio-analytics-body">{body}</PaneBody>
        <PaneFooter>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span>sources · {data?.sources?.join(", ") || "—"}</span>
          <span>points · {points.length}</span>
          {warnings.length ? <span>{warnings.length} warn</span> : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

function GrowthChart({ points, symbol }: { points: GrowthPoint[]; symbol: string }) {
  const series = points
    .map((point, index) => ({ index, value: point.growth ?? point.close }))
    .filter((point): point is { index: number; value: number } => point.value != null && Number.isFinite(point.value));
  if (series.length < 2) {
    return <span className="portfolio-analytics-muted">No plottable growth series.</span>;
  }
  const values = series.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const width = 320;
  const height = 130;
  const toX = (index: number) => 8 + (index / Math.max(series.length - 1, 1)) * (width - 16);
  const toY = (value: number) => height - 14 - ((value - min) / span) * (height - 28);
  const line = series
    .map((point, index) => `${index === 0 ? "M" : "L"}${toX(index).toFixed(1)},${toY(point.value).toFixed(1)}`)
    .join(" ");
  const area = `${line} L${toX(series.length - 1).toFixed(1)},${height - 12} L${toX(0).toFixed(1)},${height - 12} Z`;
  const first = points[0]?.date ?? "";
  const last = points[points.length - 1]?.date ?? "";
  return (
    <div className="u-mt-4">
      {/* Owner 2026-09-16: the chart rendered as a tiny letterboxed plot
          floating in a huge card (fixed viewBox + default aspect-preserve).
          preserveAspectRatio="none" stretches the series to the card and
          non-scaling strokes keep the line crisp under the non-uniform
          scale. */}
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className="portfolio-frontier"
        role="img"
        aria-label={`Growth of 1 for ${symbol}, ${first} to ${last}`}
      >
        <path
          d={area}
          vectorEffect="non-scaling-stroke"
          style={{ fill: "var(--accent-soft)", stroke: "none" }}
        />
        <path d={line} vectorEffect="non-scaling-stroke" />
        <line
          x1={8}
          y1={height - 12}
          x2={width - 8}
          y2={height - 12}
          stroke="var(--border-subtle)"
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="portfolio-frontier__axis">
        <span>{first}</span>
        <span>
          min {formatNumber(min, 3)} · max {formatNumber(max, 3)}
        </span>
        <span>{last}</span>
      </div>
    </div>
  );
}

export default TotalReturnPane;
