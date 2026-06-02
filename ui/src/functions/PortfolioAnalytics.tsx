import { useMemo, useState } from "react";
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
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { navigate } from "@/lib/router";
import {
  formatCompactNumber,
  formatCurrency,
  formatMissing,
  formatNumber,
  formatPercent,
  formatPrice,
} from "@/lib/format";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

type Row = Record<string, unknown>;

interface PortfolioPayload {
  status?: string;
  reason?: string;
  rows?: Row[];
  positions?: Row[];
  comparisons?: Row[];
  orders?: Row[];
  liquidations?: Row[];
  asset_returns?: Row[];
  top_loadings?: Row[];
  loadings?: Row[];
  efficient_frontier?: Row[];
  series?: Row[];
  summary?: Row;
  totals?: Row;
  field_dictionary?: Record<string, string>;
  methodology?: string;
  next_actions?: string[];
  [key: string]: unknown;
}

interface ToolConfig {
  title: string;
  subtitle: string;
  defaultSymbols?: string;
  defaultSymbol?: string;
  usesUniverse?: boolean;
  usesSymbol?: boolean;
  supportsLive?: boolean;
  modes?: readonly string[];
}

const PORTFOLIO_TOOLS = [
  "PORT",
  "PVAR",
  "RPAR",
  "PORT_OPT",
  "REBA",
  "STRS",
  "BLAK",
  "PCAS",
  "PFA",
  "PSC",
  "PORT_WHATIF",
  "MARS",
  "TRA",
] as const;

const TOOL_CONFIG: Record<string, ToolConfig> = {
  ACCT: {
    title: "Account Overview",
    subtitle: "Cash, margin, exposure, and account state",
  },
  BLAK: {
    title: "Black-Litterman",
    subtitle: "Prior, posterior return, and implied allocation",
    defaultSymbols: "SPY,QQQ,TLT,GLD",
    usesUniverse: true,
    supportsLive: true,
  },
  BMTX: {
    title: "Behavior Matrix",
    subtitle: "Portfolio behavior diagnostics",
  },
  BTFW: {
    title: "Backtest Forward",
    subtitle: "Forward-looking portfolio template run",
    defaultSymbol: "AAPL",
    usesSymbol: true,
    supportsLive: true,
  },
  BTUNE: {
    title: "Bot Tuning",
    subtitle: "Portfolio parameter tuning surface",
  },
  LOTS: {
    title: "Tax Lots",
    subtitle: "Lot-level basis and harvest candidates",
  },
  MARS: {
    title: "Multi-Asset Risk",
    subtitle: "Factor loadings, VaR, and residual risk",
    defaultSymbols: "SPY,TLT,GLD,BTCUSDT",
    usesUniverse: true,
    supportsLive: true,
  },
  MGN: {
    title: "Margin",
    subtitle: "Borrow, maintenance, and liquidation diagnostics",
  },
  MLSIG: {
    title: "ML Signals",
    subtitle: "Portfolio signal ranking",
  },
  PCAS: {
    title: "PCA Stress",
    subtitle: "Principal-component shock and P&L projection",
    supportsLive: true,
  },
  PFA: {
    title: "Performance Attribution",
    subtitle: "Allocation, selection, and interaction effects",
  },
  PORT_OPT: {
    title: "Portfolio Optimizer",
    subtitle: "Frontier, max-Sharpe, min-vol, and risk parity weights",
    defaultSymbols: "SPY,QQQ,IWM,TLT,GLD,EFA,EEM",
    usesUniverse: true,
    supportsLive: true,
    modes: ["all", "frontier", "max_sharpe", "min_vol", "risk_parity"],
  },
  PORT_WHATIF: {
    title: "Portfolio What-If",
    subtitle: "Hypothetical trade delta against current book",
    defaultSymbol: "AAPL",
    usesSymbol: true,
  },
  PSC: {
    title: "Position Sizing",
    subtitle: "Risk budget, R multiple, and Kelly sizing",
    defaultSymbol: "AAPL",
    usesSymbol: true,
  },
  PVAR: {
    title: "Position VaR",
    subtitle: "Marginal and component contribution to portfolio risk",
    supportsLive: true,
  },
  REBA: {
    title: "Rebalancer",
    subtitle: "Target weights, drift, and estimated order deltas",
  },
  RPAR: {
    title: "Risk Parity",
    subtitle: "Inverse-vol and equal-risk-contribution allocation",
    defaultSymbols: "AAPL,MSFT,BTCUSDT,EURUSD,GC=F",
    usesUniverse: true,
    supportsLive: true,
    modes: ["inverse_vol", "erc"],
  },
  STRS: {
    title: "Stress Test",
    subtitle: "Scenario P&L and stressed return ranking",
    supportsLive: true,
    modes: ["compare", "list"],
  },
  TLH: {
    title: "Tax-Loss Harvesting",
    subtitle: "Harvest candidates and wash-sale risk",
  },
  TRA: {
    title: "Total Return",
    subtitle: "TWR, IRR, CAGR, and dividend return",
    defaultSymbol: "AAPL",
    usesSymbol: true,
    supportsLive: true,
  },
};

export function PortfolioAnalyticsPane({ code, symbol }: FunctionPaneProps) {
  const upper = code.toUpperCase();
  const config = TOOL_CONFIG[upper] ?? {
    title: upper,
    subtitle: "Portfolio analytics",
  };
  const [symbols, setSymbols] = useState(config.defaultSymbols ?? "SPY,QQQ,TLT,GLD");
  const [targetText, setTargetText] = useState("SPY:40, QQQ:25, TLT:20, GLD:15");
  const [symbolInput, setSymbolInput] = useState(symbol ?? config.defaultSymbol ?? "AAPL");
  const [live, setLive] = useState(false);
  const [mode, setMode] = useState(config.modes?.[0] ?? "all");
  const [account, setAccount] = useState("10000");
  const [entry, setEntry] = useState("100");
  const [stop, setStop] = useState("95");
  const [target, setTarget] = useState("115");

  const effectiveSymbol = config.usesSymbol ? (symbol || symbolInput || config.defaultSymbol) : symbol;
  const params = useMemo(
    () =>
      buildParams(upper, {
        symbols,
        targetText,
        live,
        mode,
        account,
        entry,
        stop,
        target,
      }),
    [upper, symbols, targetText, live, mode, account, entry, stop, target],
  );
  const { state, data, error, refetch } = useFunction<PortfolioPayload>({
    code: upper,
    symbol: effectiveSymbol,
    params,
  });

  const payload = data?.data;
  const rows = useMemo(() => extractRows(payload), [payload]);
  const columns = useMemo(() => columnsForRows(rows), [rows]);
  const metrics = useMemo(() => deriveMetrics(payload), [payload]);
  const status = payload?.status ?? data?.status ?? "ok";
  const warnings = data?.warnings ?? [];

  const body =
    state === "loading" || state === "idle" ? (
      <div className="portfolio-analytics-loading">
        <Skeleton height={70} />
        <Skeleton height={180} />
        <Skeleton height={26} width="60%" />
      </div>
    ) : state === "error" ? (
      <Empty
        title="Function error"
        body={error?.message ?? "—"}
        icon="!"
        action={<button className="btn" onClick={refetch}>Retry</button>}
      />
    ) : (
      <PortfolioAnalyticsView
        code={upper}
        payload={payload}
        rows={rows}
        columns={columns}
        metrics={metrics}
        warnings={warnings}
        refetch={refetch}
      />
    );

  return (
    <div className="portfolio-analytics-host">
      <Pane>
        <PaneHeader
          code={upper}
          title={config.title}
          subtitle={config.subtitle}
          trailing={
            <FunctionControlGroup>
              {config.supportsLive ? (
                <button
                  type="button"
                  className={`btn btn--ghost portfolio-analytics-live${live ? " portfolio-analytics-live--on" : ""}`}
                  onClick={() => setLive((v) => !v)}
                  aria-pressed={live}
                  title="Toggle live provider mode"
                >
                  {live ? "LIVE" : "MODEL"}
                </button>
              ) : null}
              {config.modes ? (
                <SegmentedControl
                  label="MODE"
                  value={mode}
                  options={config.modes}
                  onChange={setMode}
                />
              ) : null}
              <LoadStatePill state={state} status={status} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <PaneBody className="portfolio-analytics-body">
          <PortfolioToolStrip active={upper} />
          <PortfolioControls
            config={config}
            code={upper}
            symbols={symbols}
            setSymbols={setSymbols}
            targetText={targetText}
            setTargetText={setTargetText}
            symbolInput={symbolInput}
            setSymbolInput={setSymbolInput}
            account={account}
            setAccount={setAccount}
            entry={entry}
            setEntry={setEntry}
            stop={stop}
            setStop={setStop}
            target={target}
            setTarget={setTarget}
          />
          {body}
        </PaneBody>
        <PaneFooter>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span>sources · {data?.sources?.join(", ") || "—"}</span>
          <span>rows · {rows.length}</span>
          {warnings.length ? <span>{warnings.length} warn</span> : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

function PortfolioToolStrip({ active }: { active: string }) {
  return (
    <nav className="portfolio-tool-strip" aria-label="Portfolio tools">
      {PORTFOLIO_TOOLS.map((tool) => (
        <button
          key={tool}
          type="button"
          className={`portfolio-tool-strip__btn${tool === active ? " portfolio-tool-strip__btn--active" : ""}`}
          onClick={() => navigate(`/fn/${tool}`)}
          disabled={tool === active}
        >
          {tool}
        </button>
      ))}
    </nav>
  );
}

function PortfolioControls({
  config,
  code,
  symbols,
  setSymbols,
  targetText,
  setTargetText,
  symbolInput,
  setSymbolInput,
  account,
  setAccount,
  entry,
  setEntry,
  stop,
  setStop,
  target,
  setTarget,
}: {
  config: ToolConfig;
  code: string;
  symbols: string;
  setSymbols: (value: string) => void;
  targetText: string;
  setTargetText: (value: string) => void;
  symbolInput: string;
  setSymbolInput: (value: string) => void;
  account: string;
  setAccount: (value: string) => void;
  entry: string;
  setEntry: (value: string) => void;
  stop: string;
  setStop: (value: string) => void;
  target: string;
  setTarget: (value: string) => void;
}) {
  if (!config.usesUniverse && !config.usesSymbol && code !== "REBA" && code !== "PSC") {
    return null;
  }
  return (
    <div className="portfolio-controls">
      {config.usesUniverse ? (
        <label className="portfolio-control-field portfolio-control-field--wide">
          <span>Universe</span>
          <input
            value={symbols}
            onChange={(e) => setSymbols(e.target.value.toUpperCase())}
            spellCheck={false}
          />
        </label>
      ) : null}
      {config.usesSymbol ? (
        <label className="portfolio-control-field">
          <span>Symbol</span>
          <input
            value={symbolInput}
            onChange={(e) => setSymbolInput(e.target.value.toUpperCase())}
            spellCheck={false}
          />
        </label>
      ) : null}
      {code === "REBA" ? (
        <label className="portfolio-control-field portfolio-control-field--wide">
          <span>Targets</span>
          <input value={targetText} onChange={(e) => setTargetText(e.target.value.toUpperCase())} />
        </label>
      ) : null}
      {code === "PSC" || code === "PORT_WHATIF" ? (
        <>
          <label className="portfolio-control-field">
            <span>{code === "PSC" ? "Account" : "Quantity"}</span>
            <input value={account} onChange={(e) => setAccount(e.target.value)} inputMode="decimal" />
          </label>
          <label className="portfolio-control-field">
            <span>Entry</span>
            <input value={entry} onChange={(e) => setEntry(e.target.value)} inputMode="decimal" />
          </label>
          {code === "PSC" ? (
            <>
              <label className="portfolio-control-field">
                <span>Stop</span>
                <input value={stop} onChange={(e) => setStop(e.target.value)} inputMode="decimal" />
              </label>
              <label className="portfolio-control-field">
                <span>Target</span>
                <input value={target} onChange={(e) => setTarget(e.target.value)} inputMode="decimal" />
              </label>
            </>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function PortfolioAnalyticsView({
  code,
  payload,
  rows,
  columns,
  metrics,
  warnings,
  refetch,
}: {
  code: string;
  payload: PortfolioPayload | undefined;
  rows: Row[];
  columns: DataGridColumn<Row>[];
  metrics: Array<{ key: string; label: string; value: unknown }>;
  warnings: string[];
  refetch: () => void;
}) {
  const nextActions = payload?.next_actions ?? [];
  const emptyReason = payload?.reason ?? nextActions[0];

  const isStatusEmptyOrError =
    payload?.status === "ready_no_positions" ||
    payload?.status === "input_error" ||
    payload?.status === "input_required" ||
    payload?.status === "empty" ||
    payload?.status === "empty_portfolio" ||
    payload?.status === "not_configured" ||
    payload?.status === "provider_unavailable";

  if (rows.length === 0 || isStatusEmptyOrError) {
    let title = "No data available";
    let icon = "∅";
    let body = emptyReason ?? "This portfolio function returned no data.";
    let action: React.ReactNode = null;

    if (
      payload?.status === "ready_no_positions" ||
      payload?.status === "empty_portfolio" ||
      payload?.status === "empty" ||
      (!payload?.status && rows.length === 0)
    ) {
      title = "No portfolio positions";
      icon = "∅";
      body = emptyReason ?? "You do not have any open positions in your portfolio. Connect a broker account or use Portfolio What-If to simulate trades.";
      action = (
        <div className="empty-actions" style={{ display: "flex", gap: "8px" }}>
          <button type="button" className="btn btn--accent" onClick={() => navigate("/fn/CONN")}>
            Connect Broker
          </button>
          <button type="button" className="btn" onClick={() => navigate("/fn/PORT_WHATIF")}>
            Open What-If
          </button>
        </div>
      );
    } else if (payload?.status === "input_error") {
      title = "Invalid Parameters";
      icon = "!";
      body = emptyReason ?? "Please check the input parameters and try again.";
    } else if (payload?.status === "input_required") {
      title = "Input Required";
      icon = "⌖";
      body = emptyReason ?? "This function requires additional inputs to run.";
    } else if (payload?.status === "provider_unavailable") {
      title = "Provider Unavailable";
      icon = "!";
      body = emptyReason ?? "The required data provider is currently offline or unavailable. Please check your credentials or try again later.";
      action = (
        <button type="button" className="btn btn--accent" onClick={() => refetch()}>
          Retry
        </button>
      );
    } else if (payload?.status === "not_configured") {
      title = "Not Configured";
      icon = "⚙️";
      body = emptyReason ?? "This function has not been configured yet.";
      action = (
        <button type="button" className="btn btn--accent" onClick={() => navigate("/fn/CONN")}>
          Configure Connection
        </button>
      );
    }

    return (
      <Empty
        title={title}
        body={body}
        icon={icon}
        action={action}
      />
    );
  }

  return (
    <div className="portfolio-analytics-view">
      <section className="portfolio-analytics-summary">
        <div className="portfolio-analytics-summary__hero">
          <span className="portfolio-analytics-label">{code}</span>
          <strong>{heroValue(metrics)}</strong>
          <span>{payload?.status ?? "ready"}</span>
        </div>
        <div className="portfolio-analytics-summary__metrics">
          {metrics.slice(0, 6).map((metric) => (
            <div key={metric.key} className="portfolio-analytics-metric">
              <span>{metric.label}</span>
              <strong>{formatSmart(metric.key, metric.value)}</strong>
            </div>
          ))}
        </div>
      </section>

      {warnings.length ? (
        <div className="portfolio-warning-strip">
          {warnings.slice(0, 3).map((warning) => (
            <Pill key={warning} tone="warn" variant="soft" withDot={false}>
              {warning}
            </Pill>
          ))}
        </div>
      ) : null}

      <div className="portfolio-analytics-grid">
        <section className="portfolio-table-panel">
          <header className="port-section-head">
            <div>
              <h3>Matrix</h3>
              <span>{rows.length} row(s)</span>
            </div>
          </header>
          <DataGrid
            columns={columns}
            rows={rows}
            rowKey={(row, idx) => row.symbol ? `${String(row.symbol)}-${idx}` : idx}
            density="compact"
            ariaLabel={`${code} portfolio analytics matrix`}
          />
        </section>

        <aside className="portfolio-analytics-rail">
          <PortfolioVisual payload={payload} rows={rows} />
          {payload?.methodology ? (
            <section className="portfolio-method-panel">
              <h3>Method</h3>
              <p>{payload.methodology}</p>
            </section>
          ) : null}
        </aside>
      </div>
    </div>
  );
}

function PortfolioVisual({
  payload,
  rows,
}: {
  payload: PortfolioPayload | undefined;
  rows: Row[];
}) {
  const frontier = arrayOfRecords(payload?.efficient_frontier);
  if (frontier.length > 1) {
    return <FrontierChart points={frontier} />;
  }
  const ladderRows = rows
    .map((row) => {
      const label = String(row.symbol ?? row.sector ?? row.factor ?? row.metric ?? row.scenario ?? row.action ?? "row");
      const raw =
        numberValue(row.weight_pct) ??
        numberValue(row.component_pct_of_portfolio_risk) ??
        numberValue(row.risk_contribution_pct) ??
        numberValue(row.total_effect) ??
        numberValue(row.total_pnl) ??
        numberValue(row.notional_delta) ??
        numberValue(row.value);
      return raw == null ? null : { label, value: raw };
    })
    .filter((row): row is { label: string; value: number } => Boolean(row))
    .slice(0, 8);

  return (
    <section className="portfolio-visual-panel">
      <h3>Exposure</h3>
      {ladderRows.length ? (
        <div className="portfolio-ladder">
          {ladderRows.map((row) => {
            const max = Math.max(...ladderRows.map((r) => Math.abs(r.value)), 1);
            const width = Math.min(100, Math.abs(row.value) / max * 100);
            return (
              <div key={`${row.label}-${row.value}`} className="portfolio-ladder__row">
                <span>{row.label}</span>
                <div className="portfolio-ladder__track">
                  <i
                    className={row.value < 0 ? "portfolio-ladder__bar portfolio-ladder__bar--neg" : "portfolio-ladder__bar"}
                    style={{ ["--u-width" as string]: `${width}%` }}
                  />
                </div>
                <strong>{formatSmart("weight_pct", row.value)}</strong>
              </div>
            );
          })}
        </div>
      ) : (
        <span className="portfolio-analytics-muted">No visual series.</span>
      )}
    </section>
  );
}

function FrontierChart({ points }: { points: Row[] }) {
  const clean = points.flatMap((p) => {
    const x = numberValue(p.vol) ?? numberValue(p.volatility);
    const y = numberValue(p.return) ?? numberValue(p.expected_return);
    if (x == null || y == null) return [];
    return [{ x, y, sharpe: numberValue(p.sharpe) }];
  });
  if (clean.length < 2) {
    return (
      <section className="portfolio-visual-panel">
        <h3>Efficient frontier</h3>
        <span className="portfolio-analytics-muted">No plottable frontier points.</span>
      </section>
    );
  }
  const minX = Math.min(...clean.map((p) => p.x));
  const maxX = Math.max(...clean.map((p) => p.x));
  const minY = Math.min(...clean.map((p) => p.y));
  const maxY = Math.max(...clean.map((p) => p.y));
  const path = clean
    .map((p, idx) => {
      const x = scale(p.x, minX, maxX, 10, 210);
      const y = scale(p.y, minY, maxY, 112, 10);
      return `${idx === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <section className="portfolio-visual-panel">
      <h3>Efficient frontier</h3>
      <svg viewBox="0 0 220 124" className="portfolio-frontier">
        <path d={path} />
        {clean.map((p, idx) => (
          <circle
            key={`${p.x}-${p.y}-${idx}`}
            cx={scale(p.x, minX, maxX, 10, 210)}
            cy={scale(p.y, minY, maxY, 112, 10)}
            r={p.sharpe && p.sharpe > 1 ? 3.4 : 2.4}
          />
        ))}
      </svg>
      <div className="portfolio-frontier__axis">
        <span>vol {formatPercent(minX, { fromFraction: true })}</span>
        <span>return {formatPercent(maxY, { fromFraction: true })}</span>
      </div>
    </section>
  );
}

function columnsForRows(rows: Row[]): DataGridColumn<Row>[] {
  const keys = prioritizedKeys(rows).slice(0, 9);
  if (keys.length === 0) {
    return [{ key: "value", header: "Value", render: () => formatMissing }];
  }
  return keys.map((key) => ({
    key,
    header: humanLabel(key),
    numeric: rows.some((row) => typeof row[key] === "number"),
    width: key === "symbol" || key === "sector" || key === "metric" ? 116 : 128,
    render: (row) => renderCell(key, row[key]),
  }));
}

function prioritizedKeys(rows: Row[]): string[] {
  const present = new Set<string>();
  for (const row of rows) {
    for (const key of Object.keys(row)) present.add(key);
  }
  const priority = [
    "symbol",
    "sector",
    "factor",
    "metric",
    "action",
    "side",
    "weight_pct",
    "market_weight",
    "optimal_weight",
    "risk_contribution_pct",
    "component_pct_of_portfolio_risk",
    "current_weight_pct",
    "target_weight_pct",
    "drift_pct",
    "notional_delta",
    "total_pnl",
    "pnl",
    "return",
    "vol",
    "sharpe",
    "value",
  ];
  const ordered = priority.filter((key) => present.has(key));
  const rest = Array.from(present)
    .filter((key) => !ordered.includes(key) && !isLowSignalKey(key))
    .sort();
  return [...ordered, ...rest];
}

function renderCell(key: string, value: unknown) {
  if (key === "symbol" && typeof value === "string") {
    return (
      <button type="button" className="u-symbol-link" onClick={() => navigate(`/symbol/${value}/DES`)}>
        {value}
      </button>
    );
  }
  if (key === "action" || key === "side") {
    const text = String(value ?? formatMissing);
    const tone = /buy|long/i.test(text) ? "positive" : /sell|short/i.test(text) ? "negative" : "muted";
    return <Pill tone={tone} variant="soft" withDot={false}>{text}</Pill>;
  }
  if (typeof value === "boolean") return value ? "yes" : "no";
  return <span className={numberValue(value) != null ? "portfolio-analytics-num" : undefined}>{formatSmart(key, value)}</span>;
}

function extractRows(payload: PortfolioPayload | undefined): Row[] {
  if (!payload) return [];
  const candidates = [
    payload.rows,
    payload.positions,
    payload.comparisons,
    payload.orders,
    payload.liquidations,
    payload.asset_returns,
    payload.top_loadings,
    payload.loadings,
    payload.series,
  ];
  for (const candidate of candidates) {
    const rows = arrayOfRecords(candidate);
    if (rows.length) return rows;
  }
  const summary = recordValue(payload.summary ?? payload.totals);
  if (summary) {
    return Object.entries(summary).map(([metric, value]) => ({ metric, value }));
  }
  return [];
}

function deriveMetrics(payload: PortfolioPayload | undefined): Array<{ key: string; label: string; value: unknown }> {
  if (!payload) return [];
  const merged = {
    ...(recordValue(payload.totals) ?? {}),
    ...(recordValue(payload.summary) ?? {}),
  };
  for (const [key, value] of Object.entries(payload)) {
    if (Object.keys(merged).length >= 8) break;
    if (isMetricValue(value) && !isLowSignalKey(key)) merged[key] = value;
  }
  return Object.entries(merged)
    .filter(([, value]) => isMetricValue(value))
    .slice(0, 8)
    .map(([key, value]) => ({ key, label: humanLabel(key), value }));
}

function buildParams(
  code: string,
  state: {
    symbols: string;
    targetText: string;
    live: boolean;
    mode: string;
    account: string;
    entry: string;
    stop: string;
    target: string;
  },
): Record<string, unknown> {
  const symbols = splitSymbols(state.symbols);
  switch (code) {
    case "BLAK":
      return { symbols, live: state.live };
    case "MARS":
      return { symbols, live: state.live };
    case "PORT_OPT":
      return { symbols, mode: state.mode, live: state.live, days: 756 };
    case "RPAR":
      return { symbols, method: state.mode, live_risk: state.live, model: !state.live };
    case "REBA":
      return { targets: parseTargets(state.targetText), max_notional: 100000 };
    case "STRS":
      return { action: state.mode, refresh_prices: state.live };
    case "PVAR":
      return { confidence: 0.95, max_positions: 12, live_risk: state.live };
    case "PCAS":
      return { live: state.live, live_prices: state.live, include_legacy: true };
    case "PSC":
      return {
        account: num(state.account, 10000),
        entry: num(state.entry, 100),
        stop: num(state.stop, 95),
        target: num(state.target, 115),
        risk_pct: 0.01,
      };
    case "PORT_WHATIF":
      return { quantity: num(state.account, 10), cost: num(state.entry, 100) };
    case "TRA":
      return { years: 5, live_return: state.live };
    case "BTFW":
      return { live: state.live };
    default:
      return {};
  }
}

function splitSymbols(raw: string): string[] {
  return raw
    .split(/[,\s]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
}

function parseTargets(raw: string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const part of raw.split(",")) {
    const [symbol, value] = part.split(":").map((s) => s.trim());
    if (!symbol || !value) continue;
    const pct = Number(value);
    if (Number.isFinite(pct) && pct > 0) out[symbol.toUpperCase()] = pct / 100;
  }
  return out;
}

function heroValue(metrics: Array<{ key: string; label: string; value: unknown }>): string {
  const first = metrics.find((metric) => typeof metric.value === "number") ?? metrics[0];
  return first ? formatSmart(first.key, first.value) : formatMissing;
}

function formatSmart(key: string, value: unknown): string {
  if (value == null || value === "") return formatMissing;
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value !== "number" || !Number.isFinite(value)) return String(value);
  const k = key.toLowerCase();
  if (k.includes("pct") || k.includes("percent")) return formatPercent(value);
  if (k === "weight" || k.endsWith("_weight") || k.includes("fraction")) {
    return formatPercent(value, { fromFraction: Math.abs(value) <= 1 });
  }
  if (k.includes("return") || k.includes("vol") || k.includes("rate") || k.includes("alpha")) {
    return formatPercent(value, { fromFraction: Math.abs(value) <= 2 });
  }
  if (
    k.includes("pnl") ||
    k.includes("notional") ||
    k.includes("market_value") ||
    k.includes("cash") ||
    k.includes("equity") ||
    k.includes("account") ||
    k.includes("dollar") ||
    k.includes("cost")
  ) {
    return formatCurrency(value, { compact: Math.abs(value) >= 100000 });
  }
  if (k.includes("price") || k === "entry" || k === "stop" || k === "target") return formatPrice(value);
  if (Math.abs(value) >= 1000000) return formatCompactNumber(value);
  return formatNumber(value, Math.abs(value) < 10 && value % 1 !== 0 ? 4 : 2);
}

function humanLabel(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\bpct\b/gi, "%")
    .replace(/\bvar\b/gi, "VaR")
    .replace(/\bpnl\b/gi, "P&L")
    .replace(/\b([a-z])/g, (m) => m.toUpperCase());
}

function arrayOfRecords(value: unknown): Row[] {
  if (!Array.isArray(value)) return [];
  return value.filter((row): row is Row => row != null && typeof row === "object" && !Array.isArray(row));
}

function recordValue(value: unknown): Row | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Row;
}

function isMetricValue(value: unknown): boolean {
  return ["string", "number", "boolean"].includes(typeof value) && value !== "";
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function num(raw: string, fallback: number): number {
  const value = Number(raw);
  return Number.isFinite(value) ? value : fallback;
}

function scale(value: number, min: number, max: number, low: number, high: number): number {
  if (max === min) return (low + high) / 2;
  return low + ((value - min) / (max - min)) * (high - low);
}

function isLowSignalKey(key: string): boolean {
  return [
    "methodology",
    "field_dictionary",
    "next_actions",
    "warnings",
    "sources",
    "metadata",
    "live_fetch_errors",
    "status",
    "reason",
    "error",
    "message",
  ].includes(key);
}

export default PortfolioAnalyticsPane;
