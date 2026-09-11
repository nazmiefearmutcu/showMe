/**
 * PORT_OPT — Portfolio Optimizer (specialized portfolio pane, wave-2 lane L8).
 *
 * Keeps the efficient-frontier visual and adds the real missing screen: a
 * per-symbol weight matrix across max-Sharpe / min-volatility / risk-parity,
 * per-mode return / vol / Sharpe summary tiles, and the optimum points marked
 * on the frontier itself. Universe + LIVE/MODEL controls map to the exact
 * backend params (`symbols`, `live`, `days`, `mode`) verified in
 * wave2-targets §3.
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
import { usePersistentNumber } from "../function-control-state";
import type { FunctionPaneProps } from "../registry-types";
import {
  asRecord,
  asRows,
  DataQualityBadge,
  emptyCopy,
  fmtNum,
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

interface PortOptPayload {
  status?: string;
  reason?: string;
  symbols?: string[];
  samples?: number;
  efficient_frontier?: Row[];
  max_sharpe?: Row;
  min_volatility?: Row;
  risk_parity?: Row;
  rows?: Row[];
  summary?: Row;
  methodology?: string;
  [key: string]: unknown;
}

type OptimizerModeKey = "max_sharpe" | "min_volatility" | "risk_parity";

const MODE_DEFS: Array<{ key: OptimizerModeKey; label: string }> = [
  { key: "max_sharpe", label: "Max Sharpe" },
  { key: "min_volatility", label: "Min Vol" },
  { key: "risk_parity", label: "Risk Parity" },
];

interface WeightCell {
  symbol: string;
  weights: Array<number | null>;
}

export function PortfolioOptimizerPane({ code }: FunctionPaneProps) {
  const [symbolsInput, setSymbolsInput] = useState("SPY,QQQ,IWM,TLT,GLD,EFA,EEM");
  const [mode, setMode] = useState<"all" | "frontier">("all");
  const [live, setLive] = useState(true);
  // Backend param `risk_free` is a FRACTION (port_opt.py:38 default 0.04);
  // the control is percent-persisted and converted on the wire.
  const [riskFreePct, setRiskFreePct] = usePersistentNumber(
    "showme.port_opt.risk_free",
    4,
  );

  const symbols = useMemo(
    () =>
      symbolsInput
        .split(/[,\s]+/)
        .map((entry) => entry.trim().toUpperCase())
        .filter(Boolean),
    [symbolsInput],
  );
  const params = useMemo(
    () => ({
      symbols,
      mode,
      live,
      days: 756,
      risk_free: riskFreePct / 100,
    }),
    [symbols, mode, live, riskFreePct],
  );
  const { state, data, error, refetch } = useFunction<PortOptPayload>({ code, params });
  const payload = data?.data;

  const frontier = useMemo(
    () =>
      asRows(payload?.efficient_frontier)
        .map((point) => ({
          vol: typeof point.vol === "number" ? point.vol : null,
          ret: typeof point.return === "number" ? point.return : null,
          sharpe: typeof point.sharpe === "number" ? point.sharpe : null,
        }))
        .filter((point): point is { vol: number; ret: number; sharpe: number | null } => point.vol != null && point.ret != null),
    [payload],
  );

  const modeResults = useMemo(
    () =>
      MODE_DEFS.map((def) => ({
        ...def,
        result: asRecord(payload?.[def.key]),
      })),
    [payload],
  );
  const availableModeResults = useMemo(
    () => modeResults.filter((entry) => entry.result != null),
    [modeResults],
  );

  const weightCells = useMemo<WeightCell[]>(() => {
    const universe = Array.isArray(payload?.symbols)
      ? payload.symbols.filter((symbol): symbol is string => typeof symbol === "string")
      : [];
    const rowsUniverse = asRows(payload?.rows)
      .map((row) => str(row.symbol))
      .filter((symbol): symbol is string => symbol != null);
    const ordered = Array.from(new Set([...universe, ...rowsUniverse]));
    return ordered.map((symbol) => ({
      symbol,
      weights: modeResults.map((entry) => {
        const weights = asRecord(entry.result?.weights);
        const value = weights?.[symbol];
        return typeof value === "number" && Number.isFinite(value) ? value : null;
      }),
    }));
  }, [payload, modeResults]);

  const weightColumns = useMemo<DataGridColumn<WeightCell>[]>(
    () => [
      {
        key: "symbol",
        header: "Symbol",
        width: 108,
        render: (cell) => <span className="portfolio-analytics-num">{cell.symbol}</span>,
      },
      ...MODE_DEFS.map((def, index) => ({
        key: def.key,
        header: `${def.label} Wt`,
        width: 108,
        align: "right" as const,
        numeric: true,
        render: (cell: WeightCell) => (
          <span className="portfolio-analytics-num">
            {cell.weights[index] == null
              ? "—"
              : fmtPct(cell.weights[index], { fromFraction: true })}
          </span>
        ),
      })),
    ],
    [],
  );

  const bestSharpe = useMemo(
    () =>
      frontier.reduce<number | null>(
        (best, point) => (best == null || (point.sharpe ?? -Infinity) > best ? point.sharpe : best),
        null,
      ),
    [frontier],
  );

  const warnings = data?.warnings ?? [];
  const status = str(payload?.status) ?? data?.status ?? "ok";
  const isEmpty = !payload || (frontier.length === 0 && availableModeResults.length === 0 && weightCells.length === 0);
  const allowShort = asRecord(payload?.summary)?.allow_short === true;

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
                Efficient frontier · best Sharpe
              </span>
              <strong>{fmtNum(bestSharpe, 2)}</strong>
              <span>
                {payload?.symbols?.length ?? weightCells.length} symbol(s) · {payload?.samples ?? "—"} samples
                {allowShort ? " · short allowed" : " · long-only"}
              </span>
            </div>
            <MetricStrip
              metrics={availableModeResults.flatMap((entry) => [
                {
                  key: `${entry.key}_sharpe`,
                  label: `${entry.label} Sharpe`,
                  value: fmtNum(entry.result?.sharpe, 2),
                  tone: toneClass(typeof entry.result?.sharpe === "number" ? entry.result.sharpe : null),
                },
                {
                  key: `${entry.key}_return`,
                  label: `${entry.label} Ret`,
                  value: fmtPct(entry.result?.return, { fromFraction: true, signed: true }),
                  tone: toneClass(typeof entry.result?.return === "number" ? entry.result.return : null),
                },
                {
                  key: `${entry.key}_vol`,
                  label: `${entry.label} Vol`,
                  value: fmtPct(entry.result?.vol, { fromFraction: true }),
                },
              ]).slice(0, 6)}
            />
          </section>

          <WarningStrip warnings={warnings} />

          <div className="portfolio-analytics-grid">
            <div className="u-flex-col u-gap-5">
              <section className="portfolio-table-panel">
                <SectionHead title="Optimizer weights" meta="per-symbol allocation by mode" />
                <DataGrid
                  columns={weightColumns}
                  rows={weightCells}
                  rowKey={(cell) => cell.symbol}
                  density="compact"
                  ariaLabel="PORT_OPT optimizer weight matrix"
                  empty={
                    <span className="portfolio-analytics-muted">
                      FRONTIER mode returns the curve only — switch mode to ALL to fetch optimizer weights.
                    </span>
                  }
                />
              </section>

              <section className="portfolio-table-panel">
                <SectionHead title="Mode summary" meta="annualized" />
                <DataGrid
                  columns={MODE_SUMMARY_COLUMNS}
                  rows={availableModeResults.map((entry) => ({
                    mode: entry.label,
                    return: entry.result?.return ?? null,
                    vol: entry.result?.vol ?? null,
                    sharpe: entry.result?.sharpe ?? null,
                  }))}
                  rowKey={(row, idx) => `${String(row.mode ?? idx)}-${idx}`}
                  density="compact"
                  ariaLabel="PORT_OPT mode summary"
                />
              </section>
            </div>

            <aside className="portfolio-analytics-rail">
              <section className="portfolio-visual-panel">
                <SectionHead title="Efficient frontier" meta={`${frontier.length} point(s)`} />
                <FrontierChart points={frontier} />
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
          title="Portfolio Optimizer"
          subtitle="Frontier, max-Sharpe, min-vol, and risk parity weights"
          trailing={
            <FunctionControlGroup>
              <label className="portfolio-control-field portfolio-control-field--wide" htmlFor={`popt-${code}-universe`}>
                <span>Universe</span>
                <input
                  id={`popt-${code}-universe`}
                  value={symbolsInput}
                  onChange={(event) => setSymbolsInput(event.target.value.toUpperCase())}
                  spellCheck={false}
                />
              </label>
              <SegmentedControl
                label="MODE"
                value={mode}
                options={[
                  { value: "all", label: "ALL" },
                  { value: "frontier", label: "FRONTIER" },
                ]}
                onChange={setMode}
              />
              <label
                className="portfolio-control-field"
                htmlFor={`popt-${code}-rf`}
              >
                <span>RF %</span>
                <input
                  id={`popt-${code}-rf`}
                  type="number"
                  min={0}
                  max={100}
                  step={0.25}
                  value={riskFreePct}
                  onChange={(event) => {
                    const next = Number(event.target.value);
                    if (!Number.isFinite(next)) return;
                    setRiskFreePct(Math.min(Math.max(next, 0), 100));
                  }}
                  title="Annualized risk-free rate used by the Sharpe ratio (percent)"
                />
              </label>
              <button
                type="button"
                className={`btn btn--ghost portfolio-analytics-live${live ? " portfolio-analytics-live--on" : ""}`}
                onClick={() => setLive((value) => !value)}
                aria-pressed={live}
                title="Toggle live yfinance returns vs the labelled template returns"
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
          <span>symbols · {weightCells.length}</span>
          <span>rf · {riskFreePct.toFixed(2)}%</span>
          {warnings.length ? <span>{warnings.length} warn</span> : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

const MODE_SUMMARY_COLUMNS: DataGridColumn<Row>[] = [
  {
    key: "mode",
    header: "Mode",
    width: 120,
    render: (row) => str(row.mode) ?? "—",
  },
  {
    key: "return",
    header: "Return (ann.)",
    width: 116,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className={`portfolio-analytics-num ${toneClass(typeof row.return === "number" ? row.return : null) ?? ""}`}>
        {fmtPct(row.return, { fromFraction: true, signed: true })}
      </span>
    ),
  },
  {
    key: "vol",
    header: "Vol (ann.)",
    width: 106,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className="portfolio-analytics-num">{fmtPct(row.vol, { fromFraction: true })}</span>
    ),
  },
  {
    key: "sharpe",
    header: "Sharpe",
    width: 88,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className="portfolio-analytics-num">{fmtNum(row.sharpe, 2)}</span>
    ),
  },
];

function FrontierChart({
  points,
}: {
  points: Array<{ vol: number; ret: number; sharpe: number | null }>;
}) {
  if (points.length < 2) {
    return <span className="portfolio-analytics-muted">No plottable frontier points.</span>;
  }
  const sorted = [...points].sort((a, b) => a.vol - b.vol);
  const minX = Math.min(...sorted.map((point) => point.vol));
  const maxX = Math.max(...sorted.map((point) => point.vol));
  const minY = Math.min(...sorted.map((point) => point.ret));
  const maxY = Math.max(...sorted.map((point) => point.ret));
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const width = 320;
  const height = 150;
  const toX = (value: number) => 12 + ((value - minX) / spanX) * (width - 24);
  const toY = (value: number) => height - 16 - ((value - minY) / spanY) * (height - 32);
  const path = sorted
    .map((point, index) => `${index === 0 ? "M" : "L"}${toX(point.vol).toFixed(1)},${toY(point.ret).toFixed(1)}`)
    .join(" ");
  return (
    <div className="u-mt-4">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="portfolio-frontier"
        role="img"
        aria-label={`Efficient frontier, ${sorted.length} points, vol ${fmtPct(minX, { fromFraction: true })} to ${fmtPct(maxX, { fromFraction: true })}`}
      >
        <path d={path} />
        {sorted.map((point, index) => (
          <circle
            key={`${point.vol}-${point.ret}-${index}`}
            cx={toX(point.vol)}
            cy={toY(point.ret)}
            r={point.sharpe != null && point.sharpe > 1 ? 3.4 : 2.2}
          />
        ))}
      </svg>
      <div className="portfolio-frontier__axis">
        <span>vol {fmtPct(minX, { fromFraction: true })}</span>
        <span>return {fmtPct(maxY, { fromFraction: true })}</span>
      </div>
    </div>
  );
}

export default PortfolioOptimizerPane;
