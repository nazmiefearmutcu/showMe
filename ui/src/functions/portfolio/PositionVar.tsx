/**
 * PVAR — Position-level VaR / MCR (specialized portfolio pane, wave-2 lane L8).
 *
 * Purpose-built risk screen for `portfolio/pvar.py`: headline VaR / ES at a
 * chosen confidence + horizon, the Euler component-contribution ladder, the
 * empirical P&L loss histogram (`series[]`), and the per-position component
 * table. All figures come from the payload; LIVE vs MODEL selects real
 * yfinance return history vs the labelled template series (`live_risk`).
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
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "../function-controls";
import type { FunctionPaneProps } from "../registry-types";
import {
  asRows,
  BarRow,
  DataQualityBadge,
  emptyCopy,
  fmtMoney,
  fmtNum,
  fmtPct,
  MetricStrip,
  PaneGate,
  PortfolioEmpty,
  SectionHead,
  sortByField,
  str,
  WarningStrip,
  type Row,
} from "./shared";

interface PvarPayload {
  status?: string;
  reason?: string;
  var?: number | null;
  expected_shortfall?: number | null;
  var_pct?: number | null;
  expected_shortfall_pct?: number | null;
  parametric_var_dollar?: number | null;
  historical_var_dollar?: number | null;
  portfolio_total_notional?: number | null;
  portfolio_annualized_vol?: number | null;
  positions_analyzed?: number;
  samples?: number;
  confidence_level?: number;
  method?: string;
  horizon?: string;
  rows?: Row[];
  series?: Row[];
  methodology?: string;
  [key: string]: unknown;
}

const COMPONENT_COLUMNS: DataGridColumn<Row>[] = [
  {
    key: "symbol",
    header: "Symbol",
    width: 104,
    render: (row) => <span className="portfolio-analytics-num">{str(row.symbol) ?? "—"}</span>,
  },
  {
    key: "weight",
    header: "Weight",
    width: 84,
    align: "right",
    numeric: true,
    render: (row) => <span className="portfolio-analytics-num">{fmtPct(row.weight_pct ?? row.weight)}</span>,
  },
  {
    key: "annualized_vol",
    header: "Ann Vol",
    width: 84,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className="portfolio-analytics-num">
        {fmtPct(row.annualized_vol, { fromFraction: true })}
      </span>
    ),
  },
  {
    key: "component_pct_of_portfolio_risk",
    header: "% of Risk",
    width: 88,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className="portfolio-analytics-num">
        {fmtPct(row.component_pct_of_portfolio_risk)}
      </span>
    ),
  },
  {
    key: "component_var",
    header: "Component VaR",
    width: 118,
    align: "right",
    numeric: true,
    render: (row) => <span className="portfolio-analytics-num">{fmtMoney(row.component_var)}</span>,
  },
  {
    key: "marginal_var",
    header: "Marginal VaR",
    width: 112,
    align: "right",
    numeric: true,
    render: (row) => <span className="portfolio-analytics-num">{fmtMoney(row.marginal_var)}</span>,
  },
  {
    key: "notional_usd",
    header: "Notional",
    width: 112,
    align: "right",
    numeric: true,
    render: (row) => <span className="portfolio-analytics-num">{fmtMoney(row.notional_usd)}</span>,
  },
];

export function PositionVarPane({ code }: FunctionPaneProps) {
  const [method, setMethod] = useState<"parametric" | "historical">("parametric");
  const [confidence, setConfidence] = useState<0.95 | 0.99>(0.95);
  const [live, setLive] = useState(true);

  const params = useMemo(
    () => ({ confidence, method, max_positions: 12, live_risk: live }),
    [confidence, method, live],
  );
  const { state, data, error, refetch } = useFunction<PvarPayload>({ code, params });
  const payload = data?.data;
  const rows = useMemo(
    () => sortByField(asRows(payload?.rows), "component_pct_of_portfolio_risk"),
    [payload],
  );
  const histogram = useMemo(
    () =>
      asRows(payload?.series)
        .map((row) => ({
          pnl: typeof row.pnl === "number" && Number.isFinite(row.pnl) ? row.pnl : null,
          density: typeof row.density === "number" && Number.isFinite(row.density) ? row.density : null,
        }))
        .filter((row): row is { pnl: number; density: number } => row.pnl != null && row.density != null),
    [payload],
  );
  const warnings = data?.warnings ?? [];
  const status = str(payload?.status) ?? data?.status ?? "ok";
  const isEmpty = !payload || rows.length === 0;

  const varDollar = typeof payload?.var === "number" ? payload.var : null;
  const esDollar = typeof payload?.expected_shortfall === "number" ? payload.expected_shortfall : null;
  const confidenceLabel =
    typeof payload?.confidence_level === "number" ? `${Math.round(payload.confidence_level * 100)}%` : "—";
  const horizon = str(payload?.horizon) ?? "—";

  const riskMax = useMemo(
    () =>
      Math.max(
        ...rows.map((row) => (typeof row.component_pct_of_portfolio_risk === "number" ? row.component_pct_of_portfolio_risk : 0)),
        1e-9,
      ),
    [rows],
  );

  const badge = (
    <DataQualityBadge
      payload={payload as Row | undefined}
      metadata={data?.metadata}
      sources={data?.sources}
    />
  );
  const empty = emptyCopy(payload as Row | undefined);

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
                VaR {confidenceLabel} · {horizon} ({str(payload?.method) ?? method})
              </span>
              <strong>{fmtMoney(varDollar)}</strong>
              <span>
                {fmtPct(payload?.var_pct, { fromFraction: true })} of {fmtMoney(payload?.portfolio_total_notional)} notional
              </span>
            </div>
            <MetricStrip
              metrics={[
                { key: "es", label: "Expected shortfall", value: fmtMoney(esDollar) },
                {
                  key: "es_pct",
                  label: "ES",
                  value: fmtPct(payload?.expected_shortfall_pct, { fromFraction: true }),
                },
                {
                  key: "vol",
                  label: "Portfolio vol (ann.)",
                  value: fmtPct(payload?.portfolio_annualized_vol, { fromFraction: true }),
                },
                {
                  key: "parametric",
                  label: "Parametric VaR",
                  value: fmtMoney(payload?.parametric_var_dollar),
                },
                {
                  key: "historical",
                  label: "Historical VaR",
                  value: fmtMoney(payload?.historical_var_dollar),
                },
                {
                  key: "positions",
                  label: "Positions / samples",
                  value: `${payload?.positions_analyzed ?? rows.length} / ${payload?.samples ?? "—"}`,
                  title: "Positions analyzed / return observations used",
                },
              ]}
            />
          </section>

          <WarningStrip warnings={warnings} />

          <div className="portfolio-analytics-grid">
            <section className="portfolio-table-panel">
              <SectionHead title="Component VaR" meta={`${rows.length} position(s) · Euler decomposition`} />
              <DataGrid
                columns={COMPONENT_COLUMNS}
                rows={rows}
                rowKey={(row, idx) => `${String(row.symbol ?? idx)}-${idx}`}
                density="compact"
                ariaLabel="PVAR component contribution table"
              />
            </section>

            <aside className="portfolio-analytics-rail">
              <section className="portfolio-visual-panel">
                <SectionHead title="Risk contribution" meta="% of portfolio risk" />
                <div className="portfolio-ladder u-mt-4">
                  {rows.slice(0, 8).map((row) => {
                    const pct = typeof row.component_pct_of_portfolio_risk === "number" ? row.component_pct_of_portfolio_risk : 0;
                    return (
                      <BarRow
                        key={`${String(row.symbol)}-rc`}
                        label={str(row.symbol) ?? "—"}
                        value={pct}
                        max={riskMax}
                        text={`${fmtPct(pct)} · ${fmtMoney(row.component_var)}`}
                      />
                    );
                  })}
                </div>
              </section>

              <section className="portfolio-visual-panel">
                <SectionHead title="P&L distribution" meta="empirical loss histogram" />
                <LossHistogram bars={histogram} />
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
          title="Position VaR"
          subtitle="Marginal and component contribution to portfolio risk"
          trailing={
            <FunctionControlGroup>
              <SegmentedControl
                label="METHOD"
                value={method}
                options={["parametric", "historical"]}
                onChange={setMethod}
              />
              <SegmentedControl
                label="CONF"
                value={confidence}
                options={[
                  { value: 0.95, label: "95%" },
                  { value: 0.99, label: "99%" },
                ]}
                onChange={setConfidence}
              />
              <button
                type="button"
                className={`btn btn--ghost portfolio-analytics-live${live ? " portfolio-analytics-live--on" : ""}`}
                onClick={() => setLive((value) => !value)}
                aria-pressed={live}
                title="Toggle live yfinance return history vs the labelled template series"
              >
                {live ? "LIVE" : "MODEL"}
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
          <span>positions · {rows.length}</span>
          {warnings.length ? <span>{warnings.length} warn</span> : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

function LossHistogram({ bars }: { bars: Array<{ pnl: number; density: number }> }) {
  if (bars.length < 2) {
    return <span className="portfolio-analytics-muted">No distribution series returned.</span>;
  }
  const width = 320;
  const height = 120;
  const padX = 10;
  const padY = 10;
  const pnlMin = Math.min(...bars.map((bar) => bar.pnl));
  const pnlMax = Math.max(...bars.map((bar) => bar.pnl));
  const maxDensity = Math.max(...bars.map((bar) => bar.density), 1);
  const span = pnlMax - pnlMin || 1;
  const barWidth = Math.max(1, (width - padX * 2) / bars.length - 1);
  const zeroX = padX + ((0 - pnlMin) / span) * (width - padX * 2);
  return (
    <div className="u-mt-4">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="portfolio-frontier"
        role="img"
        aria-label={`Loss distribution histogram, ${bars.length} bins, P&L range ${fmtNum(pnlMin, 0)} to ${fmtNum(pnlMax, 0)}`}
        style={{ height: 150 }}
      >
        {bars.map((bar, index) => {
          const x = padX + (index / bars.length) * (width - padX * 2);
          const barHeight = (bar.density / maxDensity) * (height - padY * 2);
          return (
            <rect
              key={`${bar.pnl}-${index}`}
              x={x}
              y={height - padY - barHeight}
              width={barWidth}
              height={barHeight}
              style={{ fill: bar.pnl < 0 ? "var(--negative)" : "var(--positive)", opacity: 0.75, stroke: "none" }}
            />
          );
        })}
        {zeroX >= padX && zeroX <= width - padX ? (
          <line
            x1={zeroX}
            y1={padY}
            x2={zeroX}
            y2={height - padY}
            stroke="var(--text-mute)"
            strokeWidth={1}
            strokeDasharray="3 3"
          />
        ) : null}
      </svg>
      <div className="portfolio-frontier__axis">
        <span>{fmtMoney(pnlMin, true)}</span>
        <span>zero line · dashed</span>
        <span>{fmtMoney(pnlMax, true)}</span>
      </div>
    </div>
  );
}

export default PositionVarPane;
