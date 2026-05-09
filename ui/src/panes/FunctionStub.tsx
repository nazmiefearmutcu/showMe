import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import {
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type LineData,
  type Time,
  createChart,
} from "lightweight-charts";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  Field,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
} from "@/design-system";
import {
  chartResizeHandleStyle,
  measureChartElement,
  resizeChartToElement,
  terminalChartHeight,
  terminalChartHostStyle,
  terminalSvgChartStyle,
  usePersistentChartSize,
} from "@/lib/chart-layout";
import { runFunction, type FunctionCallResult } from "@/lib/functions";
import { useAppStore } from "@/lib/store";
import {
  assetClassForFunctionSymbol,
  defaultSymbolForFunction,
  inferAssetClassName,
  normalizeSymbolInput,
  pushRecentSymbol,
  quickSymbolsForFunction,
} from "@/lib/symbols";
import { isSymbolFirstFunction } from "@/functions/symbol-first";
import { useWorkspace } from "@/lib/workspace";
import { relativeTimeLabel, sortNewsNewestFirst } from "@/lib/time";
import {
  FunctionControlGroup,
  LoadStatePill,
  RowLimitControl,
  SegmentedControl,
} from "@/functions/function-controls";
import {
  ROW_LIMITS,
  type RowLimit,
  usePersistentOption,
} from "@/functions/function-control-state";
import type { FunctionEntry } from "@/lib/sidecar";

type LoadState = "idle" | "loading" | "ok" | "error";
type RecordRow = Record<string, unknown>;
type QueryParam = "query" | "topic" | "bbox" | "symbols" | "watchlist" | "universe";
type TicketSide = "BUY" | "SELL";
type TicketType = "MARKET" | "LIMIT" | "STOP" | "STOP_LIMIT";
type TicketTif = "DAY" | "GTC" | "IOC" | "FOK";
type OptionType = "CALL" | "PUT";
type OptionStrategy = "CALL_SPREAD" | "LONG_CALL" | "STRADDLE";
type BacktestStrategy = "ALL" | "sma_crossover" | "rsi_meanrev" | "buy_and_hold";
type MLHorizon = "1" | "5" | "20";
type SimpleParamSpec = { key: string; label: string; hint?: string };

const TABLE_KEYS = [
  "accounts",
  "articles",
  "bars",
  "cells",
  "constituents",
  "data",
  "events",
  "equity_curve",
  "holdings",
  "items",
  "news",
  "ohlcv",
  "orders",
  "positions",
  "records",
  "results",
  "rows",
  "securities",
  "signals",
  "surface",
  "top_10_by_sharpe",
  "trades",
  "transcripts",
];

const CHART_KEYS = [
  "equity_curve",
  "ohlcv",
  "bars",
  "history",
  "series",
  "curve",
  "drawdown",
  "efficient_frontier",
  "returns",
  "matrix",
  "risk_contributions",
  "surface",
  "rows",
  "data",
];

const TIME_KEYS = [
  "published_at",
  "publishedAt",
  "published_on",
  "published",
  "ts",
  "date",
  "datetime",
  "time",
  "timestamp",
  "period",
];
const VALUE_KEYS = [
  "change_pct",
  "changePercent",
  "daily_change_pct",
  "forecast_value",
  "forecast",
  "forward",
  "forward_rate",
  "count",
  "dark_pool_pct",
  "fair_value_per_share",
  "wacc",
  "target_price",
  "price_target",
  "actual",
  "estimate",
  "surprisePercent",
  "shares",
  "pct_outstanding",
  "importance_score",
  "relevance_score",
  "sentiment_score",
  "temp_c",
  "precip_mm",
  "correlation",
  "total_effect",
  "total_pnl",
  "total_return_pct",
  "amount_usd_bn",
  "offering_amount",
  "pd_1y_pct",
  "spread_bps_of_price",
  "allocation_effect",
  "selection_effect",
  "interaction_effect",
  "component_pct_of_portfolio_risk",
  "risk_contribution_pct",
  "risk_contribution",
  "loading",
  "shock_return",
  "loss_pct",
  "drift_pct",
  "notional_delta",
  "estimated_tax_savings",
  "market_value",
  "unrealized_pnl",
  "equity",
  "close",
  "value",
  "price",
  "return",
  "total_return",
  "drawdown",
  "pnl",
  "score",
  "sharpe",
  "calmar",
  "importance",
  "weight",
  "market_weight",
  "optimal_weight",
  "posterior_return",
  "component_var",
  "yield",
  "rate",
  "vol_pct",
  "realized_vol",
  "vol",
  "iv",
  "gex",
  "mid",
  "y",
];
const NUMERIC_X_KEYS = ["vol", "volatility", "spot", "strike", "moneyness", "window_days", "tenor_years", "shock_pct", "ytm_pct"];
const METRIC_RECORD_KEYS = [
  "metrics",
  "summary",
  "stats",
  "performance",
  "risk",
  "health",
  "best",
  "best_by_sharpe",
];

const STUB_RANGES = [
  { id: "1M", label: "1M", days: 30 },
  { id: "3M", label: "3M", days: 90 },
  { id: "6M", label: "6M", days: 180 },
  { id: "1Y", label: "1Y", days: 365 },
  { id: "3Y", label: "3Y", days: 365 * 3 },
] as const;
type StubRangeId = (typeof STUB_RANGES)[number]["id"];
const STUB_RANGE_IDS = STUB_RANGES.map((r) => r.id);

const SYNTHETIC_MARKERS = [
  "baseline",
  "model",
  "template",
  "sample",
  "placeholder",
  "synthetic",
  "continuity",
];

export function FunctionStub({
  leafId,
  code,
  symbol,
}: {
  leafId?: string;
  code: string;
  symbol?: string;
}) {
  const upperCode = code.toUpperCase();
  const setLeafTarget = useWorkspace((s) => s.setLeafTarget);
  const idx = useAppStore((s) => s.functionIndex);
  const entry = useMemo<FunctionEntry | null>(
    () => idx.find((f) => f.code === upperCode) ?? null,
    [idx, upperCode],
  );
  const [inputSymbol, setInputSymbol] = useState(symbol ?? "");
  const [state, setState] = useState<LoadState>("idle");
  const [result, setResult] = useState<FunctionCallResult<unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paramsText, setParamsText] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const symbolFirst = isSymbolFirstFunction(upperCode, entry?.category);
  const assetClasses = entry?.asset_classes ?? [];
  const assetClassKey = assetClasses.join("|");
  const defaultRunSymbol = defaultSymbolForFunction(upperCode, assetClasses);
  const quickSymbols = quickSymbolsForFunction(upperCode, assetClasses);
  const effectiveSymbol = symbolFirst
    ? normalizeSymbolInput(inputSymbol) || defaultRunSymbol
    : "";
  const [limit, setLimit] = usePersistentOption<RowLimit>(
    `showme.stub.${upperCode}.limit`,
    ROW_LIMITS,
    50,
  );
  const defaultRange = upperCode === "SAT" ? "1M" : "1Y";
  const [range, setRange] = usePersistentOption<StubRangeId>(
    `showme.stub.${upperCode}.range`,
    STUB_RANGE_IDS,
    defaultRange,
  );
  const controlProfile = useMemo(
    () => buildControlProfile(upperCode, entry?.category),
    [upperCode, entry?.category],
  );
  const [queryText, setQueryText] = useState(() => defaultQueryForFunction(upperCode, entry?.category));
  const [transcriptText, setTranscriptText] = useState("");
  const [ticketSide, setTicketSide] = useState<TicketSide>("BUY");
  const [ticketQuantity, setTicketQuantity] = useState("1");
  const [ticketType, setTicketType] = useState<TicketType>("MARKET");
  const [ticketTif, setTicketTif] = useState<TicketTif>("DAY");
  const [optionSpot, setOptionSpot] = useState("100");
  const [optionStrike, setOptionStrike] = useState("105");
  const [optionShortStrike, setOptionShortStrike] = useState("110");
  const [optionExpiry, setOptionExpiry] = useState("0.25");
  const [optionVol, setOptionVol] = useState("0.28");
  const [optionRate, setOptionRate] = useState("0.045");
  const [optionType, setOptionType] = useState<OptionType>("CALL");
  const [optionStrategy, setOptionStrategy] = useState<OptionStrategy>("CALL_SPREAD");
  const [backtestStrategy, setBacktestStrategy] = useState<BacktestStrategy>("ALL");
  const [mlHorizon, setMlHorizon] = useState<MLHorizon>("1");
  const [simpleParams, setSimpleParams] = useState<Record<string, string>>(
    () => defaultSimpleParamsForFunction(upperCode),
  );
  const optionControls = upperCode === "OVME" || upperCode === "OSA";
  const backtestControls = upperCode === "BTFW" || upperCode === "BMTX" || upperCode === "BTUNE";
  const mlSignalControls = upperCode === "MLSIG";
  const simpleControlSpecs = useMemo(() => simpleParamSpecsForFunction(upperCode), [upperCode]);
  const optionControlParams = useMemo(
    () => buildOptionControlParams(
      upperCode,
      optionSpot,
      optionStrike,
      optionShortStrike,
      optionExpiry,
      optionVol,
      optionRate,
      optionType,
      optionStrategy,
    ),
    [
      upperCode,
      optionSpot,
      optionStrike,
      optionShortStrike,
      optionExpiry,
      optionVol,
      optionRate,
      optionType,
      optionStrategy,
    ],
  );
  const backtestControlParams = useMemo(
    () => buildBacktestControlParams(upperCode, backtestStrategy),
    [upperCode, backtestStrategy],
  );
  const mlSignalControlParams = useMemo(
    () => (upperCode === "MLSIG" ? { horizon: Number(mlHorizon) } : {}),
    [upperCode, mlHorizon],
  );
  const simpleControlParams = useMemo(
    () => buildSimpleControlParams(upperCode, simpleParams),
    [upperCode, simpleParams],
  );
  const controlParams = useMemo(
    () => ({
      ...buildControlParams(controlProfile, limit, range, queryText),
      ...optionControlParams,
      ...backtestControlParams,
      ...mlSignalControlParams,
      ...simpleControlParams,
      ...(controlProfile.transcriptText && transcriptText.trim()
        ? { text: transcriptText.trim() }
        : {}),
      ...(controlProfile.tradeTicket
        ? {
            side: ticketSide,
            quantity: Number(ticketQuantity) || 0,
            type: ticketType,
            tif: ticketTif,
            submit: false,
          }
        : {}),
    }),
    [
      controlProfile,
      limit,
      range,
      queryText,
      optionControlParams,
      backtestControlParams,
      mlSignalControlParams,
      simpleControlParams,
      transcriptText,
      ticketSide,
      ticketQuantity,
      ticketType,
      ticketTif,
    ],
  );
  const internalSymbolSync = useRef<string | null>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const controlsReady = useRef(false);

  const load = async (
    signal?: AbortSignal,
    runSymbol = effectiveSymbol,
    paramsOverride?: Record<string, unknown>,
  ) => {
    const normalizedSymbol = symbolFirst
      ? compatibleRequestedSymbol(
          runSymbol || inputSymbol || defaultRunSymbol,
          entry,
        ) || defaultRunSymbol
      : "";
    const runAssetClass = symbolFirst
      ? assetClassForFunctionSymbol(normalizedSymbol, assetClasses)
      : undefined;
    setState("loading");
    setError(null);
    setResult(null);
    if (symbolFirst) {
      setInputSymbol(normalizedSymbol);
      if (leafId && normalizedSymbol) {
        internalSymbolSync.current = normalizedSymbol;
        setLeafTarget(leafId, upperCode, normalizedSymbol);
      }
    }
    try {
      const params = {
        ...defaultRuntimeParams(upperCode),
        ...(paramsOverride ?? controlParams),
        ...(parseParams(paramsText) ?? {}),
      };
      const res = await runFunction<unknown>(upperCode, {
        symbol: symbolFirst ? normalizedSymbol || undefined : undefined,
        asset_class: runAssetClass,
        params: Object.keys(params).length ? params : undefined,
        signal,
        timeoutMs: functionTimeoutMs(upperCode, entry?.category),
      });
      if (symbolFirst && normalizedSymbol) pushRecentSymbol(normalizedSymbol);
      setResult(res);
      setState("ok");
    } catch (err) {
      if (signal?.aborted) return;
      setError(err instanceof Error ? err.message : String(err));
      setState("error");
    }
  };

  const runLatest = (runSymbol = effectiveSymbol) => {
    activeRequest.current?.abort();
    const ac = new AbortController();
    activeRequest.current = ac;
    void load(ac.signal, runSymbol).finally(() => {
      if (activeRequest.current === ac) activeRequest.current = null;
    });
  };

  useEffect(() => {
    const runSymbol =
      compatibleRequestedSymbol(symbol, entry) || (symbolFirst ? defaultRunSymbol : "");
    if (symbolFirst && internalSymbolSync.current === runSymbol) {
      internalSymbolSync.current = null;
      setInputSymbol(runSymbol);
    }
    setInputSymbol(runSymbol);
    activeRequest.current?.abort();
    const ac = new AbortController();
    activeRequest.current = ac;
    const initialQuery = defaultQueryForFunction(upperCode, entry?.category);
    const initialBacktestStrategy = defaultBacktestStrategyForFunction(upperCode);
    const initialControlParams = {
      ...buildControlParams(controlProfile, limit, range, initialQuery),
      ...buildOptionDefaultsForFunction(upperCode),
      ...buildBacktestControlParams(upperCode, initialBacktestStrategy),
      ...(upperCode === "MLSIG" ? { horizon: 1 } : {}),
      ...buildSimpleControlParams(upperCode, defaultSimpleParamsForFunction(upperCode)),
      ...(controlProfile.tradeTicket
        ? {
            side: "BUY",
            quantity: 1,
            type: "MARKET",
            tif: "DAY",
            submit: false,
          }
        : {}),
    };
    setQueryText(initialQuery);
    void load(ac.signal, runSymbol, initialControlParams).finally(() => {
      if (activeRequest.current === ac) activeRequest.current = null;
    });
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [upperCode, symbol, entry?.category, assetClassKey, symbolFirst, defaultRunSymbol]);

  useEffect(() => {
    if (!controlsReady.current) {
      controlsReady.current = true;
      return;
    }
    if (!controlProfile.limit && !controlProfile.days) return;
    const timer = window.setTimeout(() => {
      runLatest(normalizeSymbolInput(inputSymbol) || effectiveSymbol);
    }, 250);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limit, range]);

  useEffect(() => {
    setQueryText(defaultQueryForFunction(upperCode, entry?.category));
  }, [upperCode, entry?.category]);

  useEffect(() => {
    setTicketSide("BUY");
    setTicketQuantity("1");
    setTicketType("MARKET");
    setTicketTif("DAY");
    setBacktestStrategy(defaultBacktestStrategyForFunction(upperCode));
    setMlHorizon("1");
    setSimpleParams(defaultSimpleParamsForFunction(upperCode));
    const optionDefaults = buildOptionDefaultsForFunction(upperCode);
    setOptionSpot(String(optionDefaults.spot ?? 100));
    setOptionStrike(String(optionDefaults.strike ?? 105));
    setOptionShortStrike(String(optionDefaults.short_strike ?? 110));
    setOptionExpiry(String(optionDefaults.years_to_expiry ?? 0.25));
    setOptionVol(String(optionDefaults.vol ?? 0.28));
    setOptionRate(String(optionDefaults.rate ?? 0.045));
    setOptionType(String(optionDefaults.type ?? "CALL") === "PUT" ? "PUT" : "CALL");
    setOptionStrategy(
      String(optionDefaults.strategy ?? "CALL_SPREAD") === "STRADDLE"
        ? "STRADDLE"
        : String(optionDefaults.strategy ?? "CALL_SPREAD") === "LONG_CALL"
          ? "LONG_CALL"
          : "CALL_SPREAD",
    );
  }, [upperCode]);

  const summary = result ? summarizeResult(result.data) : null;
  const payloadStatus = result ? getPayloadStatus(result) : null;

  return (
    <div className="showme-stub-motion" style={{ padding: 18, height: "100%", minHeight: 0 }}>
      <Pane>
        <PaneHeader
          code={upperCode}
          title={entry?.name ?? upperCode}
          subtitle={entry?.category ?? "function"}
          help={
            <FunctionHelp
              code={upperCode}
              entry={entry}
              symbolFirst={symbolFirst}
              controlProfile={controlProfile}
            />
          }
          trailing={
            <FunctionControlGroup>
              {controlProfile.limit && (
                <RowLimitControl
                  value={limit}
                  onChange={(next) => setLimit(next as RowLimit)}
                  disabled={state === "loading"}
                />
              )}
              {controlProfile.days && (
                <SegmentedControl
                  label="RANGE"
                  value={range}
                  options={STUB_RANGES.map((r) => ({ value: r.id, label: r.label }))}
                  onChange={(next) => setRange(next as StubRangeId)}
                  disabled={state === "loading"}
                />
              )}
              <LoadStatePill state={state} />
              <button
                type="button"
                className="btn btn--accent"
                onClick={() => runLatest()}
                disabled={state === "loading"}
                style={{ height: 24 }}
              >
                {state === "loading" ? "Running" : "Run"}
              </button>
            </FunctionControlGroup>
          }
        />
        <PaneBody style={functionBody}>
          <section className="showme-stub-command showme-card-reveal showme-stub-block" style={commandBar}>
            <div style={functionIdentity}>
              <div style={codeLine}>
                <span style={{ color: "var(--accent)" }}>{upperCode}</span>
                <span>{entry?.name ?? "ShowMe function"}</span>
              </div>
              <div style={identityMeta}>
                <span>{entry?.category ?? "function"}</span>
                {assetClasses.length ? <span>{assetClasses.join(" / ")}</span> : null}
              </div>
            </div>

            {optionControls ? (
              <OptionAssumptionControls
                code={upperCode}
                spot={optionSpot}
                strike={optionStrike}
                shortStrike={optionShortStrike}
                expiry={optionExpiry}
                vol={optionVol}
                rate={optionRate}
                optionType={optionType}
                strategy={optionStrategy}
                disabled={state === "loading"}
                onSpot={setOptionSpot}
                onStrike={setOptionStrike}
                onShortStrike={setOptionShortStrike}
                onExpiry={setOptionExpiry}
                onVol={setOptionVol}
                onRate={setOptionRate}
                onOptionType={setOptionType}
                onStrategy={setOptionStrategy}
              />
            ) : symbolFirst ? (
              <div style={symbolTools}>
                <Field
                  label="Symbol"
                  value={inputSymbol}
                  onChange={(e) => setInputSymbol(e.target.value.toUpperCase())}
                  placeholder={effectiveSymbol || "AAPL, BTCUSDT, EURUSD"}
                  list={`symbol-options-${upperCode}`}
                  hint="Start typing or pick a suggested symbol."
                  trailing={
                    <button
                      type="button"
                      className="btn btn--ghost"
                      onClick={() => runLatest()}
                      disabled={state === "loading"}
                      style={{ height: 22, fontSize: 10 }}
                    >
                      Go
                    </button>
                  }
                  onKeyDown={(e) => {
                    if (e.key === "Enter") runLatest();
                  }}
                />
                <datalist id={`symbol-options-${upperCode}`}>
                  {suggestedSymbolsForFunction(quickSymbols, assetClasses, entry?.category).map((s) => (
                    <option key={s} value={s} />
                  ))}
                </datalist>
                <div style={quickRow}>
                  {quickSymbols.map((s) => (
                    <button
                      key={s}
                      type="button"
                      className="btn btn--ghost"
                      onClick={() => {
                        setInputSymbol(s);
                        runLatest(s);
                      }}
                      disabled={state === "loading"}
                      style={{ height: 22, fontSize: 10 }}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : controlProfile.queryParam ? (
              <div style={symbolTools}>
                <Field
                  label={
                    controlProfile.queryLabel ??
                    (controlProfile.queryParam === "topic"
                      ? "Topic"
                      : controlProfile.queryParam === "symbols"
                        ? "Watchlist"
                        : "Query")
                  }
                  value={queryText}
                  onChange={(e) => setQueryText(e.target.value)}
                  placeholder={defaultQueryForFunction(upperCode, entry?.category)}
                  hint={controlProfile.queryHint ?? `${controlProfile.queryParam} sent to backend on Run.`}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") runLatest();
                  }}
                />
              </div>
            ) : (
              <div style={scopeBlock}>
                <span style={metaLabel}>Scope</span>
                <strong>
                  {entry?.category === "portfolio" ? "local portfolio" : "global"}
                </strong>
              </div>
            )}

            {controlProfile.tradeTicket ? (
              <TradeTicketControls
                side={ticketSide}
                quantity={ticketQuantity}
                type={ticketType}
                tif={ticketTif}
                disabled={state === "loading"}
                onSide={setTicketSide}
                onQuantity={setTicketQuantity}
                onType={setTicketType}
                onTif={setTicketTif}
              />
            ) : null}

            {backtestControls ? (
              <BacktestControls
                code={upperCode}
                value={backtestStrategy}
                disabled={state === "loading"}
                onChange={setBacktestStrategy}
              />
            ) : null}

            {mlSignalControls ? (
              <MLSignalControls
                horizon={mlHorizon}
                disabled={state === "loading"}
                onHorizon={setMlHorizon}
              />
            ) : null}

            {simpleControlSpecs.length > 0 ? (
              <SimpleParamControls
                specs={simpleControlSpecs}
                values={simpleParams}
                disabled={state === "loading"}
                onChange={(key, value) => setSimpleParams((prev) => ({ ...prev, [key]: value }))}
              />
            ) : null}

            {controlProfile.transcriptText ? (
              <section style={controlInlinePanel}>
                <span style={metaLabel}>Transcript text</span>
                <textarea
                  value={transcriptText}
                  onChange={(e) => setTranscriptText(e.target.value)}
                  placeholder="Paste earnings-call transcript text here before Run."
                  spellCheck={false}
                  style={{ ...textareaStyle, minHeight: 86 }}
                />
              </section>
            ) : null}

            <div style={commandActions}>
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => {
                  setParamsText(mergeParams(paramsText, { deep: true }));
                  setAdvancedOpen(true);
                }}
                disabled={state === "loading"}
              >
                Deep
              </button>
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => setAdvancedOpen((open) => !open)}
                disabled={state === "loading"}
              >
                {advancedOpen ? "Hide JSON" : "Advanced"}
              </button>
            </div>
          </section>

          {advancedOpen ? (
            <section className="showme-stub-advanced showme-card-reveal showme-stub-block" style={advancedPanel}>
              <div style={advancedHeader}>
                <div>
                  <strong style={{ color: "var(--text-primary)" }}>Params JSON</strong>
                  <span style={{ color: "var(--text-mute)", marginLeft: 8 }}>
                    {paramsText.trim() ? "custom override" : "default payload"}
                  </span>
                </div>
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => setParamsText("")}
                  disabled={state === "loading" || !paramsText.trim()}
                >
                  Clear
                </button>
              </div>
              <textarea
                value={paramsText}
                onChange={(e) => setParamsText(e.target.value)}
                placeholder={paramsPlaceholder(upperCode)}
                spellCheck={false}
                style={textareaStyle}
              />
            </section>
          ) : null}

          <section className="showme-stub-result" style={resultPane}>
            {state === "loading" ? (
              <div className="showme-card-reveal showme-stub-block" style={{ display: "grid", gap: 10 }}>
                <Skeleton height={24} width="38%" />
                <Skeleton height={260} />
                <Skeleton height={16} width="70%" />
                <Skeleton height={16} width="54%" />
              </div>
            ) : state === "error" ? (
              <Empty
                title="Function failed"
                body={error ?? "Unknown sidecar error"}
                icon="!"
                action={
                  <button type="button" className="btn btn--accent" onClick={() => runLatest()}>
                    Retry
                  </button>
                }
              />
            ) : result && summary && payloadStatus ? (
              <GenericResult
                result={result}
                summary={summary}
                payloadStatus={payloadStatus}
                onRetry={() => runLatest()}
              />
            ) : (
              <Empty title="No result yet" body="Run this function to fetch a live payload." />
            )}
          </section>
        </PaneBody>
        <PaneFooter>
          <span>{entry?.category ?? "unknown"}</span>
          <span>code · {upperCode}</span>
          <span>transport · /api/fn/{upperCode}</span>
          {symbolFirst && effectiveSymbol && <span>symbol · {effectiveSymbol}</span>}
          {controlProfile.limit && <span>rows · {limit}</span>}
          {controlProfile.days && <span>range · {range}</span>}
        </PaneFooter>
      </Pane>
    </div>
  );
}

function GenericResult({
  result,
  summary,
  payloadStatus,
  onRetry,
}: {
  result: FunctionCallResult<unknown>;
  summary: ResultSummary;
  payloadStatus: PayloadStatus;
  onRetry: () => void;
}) {
  const chart = useMemo(
    () => extractChartSeries(result.data, summary.rows),
    [result.data, summary.rows],
  );
  const mediaItems = useMemo(() => extractMediaItems(result.data), [result.data]);
  const metricCards = useMemo(() => extractMetricCards(result.data), [result.data]);
  const methodology = useMemo(() => extractMethodology(result.data), [result.data]);
  const fieldDictionary = useMemo(() => extractFieldDictionary(result.data), [result.data]);
  const displayRows = useMemo(
    () => (summary.rows.length ? summary.rows : (chart?.rows ?? [])),
    [summary.rows, chart?.rows],
  );
  const suppressOhlcRowsTable = useMemo(
    () => Boolean(chart && rowsLookLikeOhlc(displayRows)),
    [chart, displayRows],
  );
  const displayColumns = useMemo(() => buildColumns(displayRows), [displayRows]);
  const articleRows = displayRows.filter(isArticleRow);
  const shouldRenderArticleList =
    !suppressOhlcRowsTable && articleRows.length > 0 && articleRows.length === displayRows.length;
  const hasScalarResult = metricCards.length > 0 || summary.keyValues.length > 0;
  const briefMarkdown =
    result.code?.toUpperCase() === "BRIEF" && isRecord(result.data)
      ? firstString(result.data, ["markdown"])
      : null;
  return (
    <div className="showme-stub-payload" style={{ display: "grid", gap: 12 }} data-testid="function-payload">
      {payloadStatus.state !== "live" ? (
        <StatusPanel status={payloadStatus} onRetry={onRetry} />
      ) : null}

      <ResultMetaLine result={result} summary={summary} />

      {briefMarkdown ? <BriefPanel markdown={briefMarkdown} /> : null}

      {mediaItems.length > 0 ? <MediaPreview items={mediaItems} /> : null}

      {metricCards.length > 0 ? <MetricRibbon metrics={metricCards} /> : null}

      {chart ? <SeriesChart chartId={result.code?.toUpperCase() ?? "GENERIC"} series={chart} /> : null}

      {methodology || fieldDictionary.length > 0 ? (
        <MethodologyPanel methodology={methodology} fields={fieldDictionary} />
      ) : null}

      {shouldRenderArticleList ? (
        <NewsList rows={articleRows} />
      ) : displayRows.length > 0 && !suppressOhlcRowsTable ? (
        <DataGrid
          className="showme-stub-grid showme-motion-grid"
          columns={displayColumns}
          rows={displayRows.slice(0, 500)}
          rowKey={stableRowKey}
          rowClassName={(_, idx) =>
            [
              "showme-row-reveal",
              "showme-motion-grid__row",
              motionDelayClass(idx),
            ].join(" ")
          }
          density="compact"
        />
      ) : payloadStatus.state === "live" && !hasScalarResult ? (
        <Empty
          title="No usable rows"
          body={
            result.warnings?.length
              ? "The function completed but only returned warnings or metadata."
              : "The function completed without chartable or tabular data."
          }
        />
      ) : null}

      {summary.keyValues.length > 0 && (
        <section className="showme-card-reveal showme-stub-block" style={kvPanel}>
          {summary.keyValues.map(([key, value]) => (
            <div key={key} className="showme-row-reveal showme-stub-kv-row" style={kvRow}>
              <span style={{ color: "var(--text-mute)" }}>{key}</span>
              <span style={{ color: "var(--text-primary)" }}>{formatValue(value)}</span>
            </div>
          ))}
        </section>
      )}

      <SourceStrip result={result} />

      <details className="showme-card-reveal showme-stub-block" style={detailsBox}>
        <summary style={{ cursor: "default", color: "var(--accent)" }}>
          Raw function payload
        </summary>
        <pre style={preStyle}>{JSON.stringify(result, null, 2)}</pre>
      </details>
    </div>
  );
}

function BriefPanel({ markdown }: { markdown: string }) {
  const lines = markdown.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  return (
    <section className="showme-card-reveal showme-stub-block" style={briefPanel}>
      {lines.slice(0, 34).map((line, idx) => {
        if (line.startsWith("## ")) {
          return <h3 key={`${line}-${idx}`} style={briefSubhead}>{stripMarkdown(line.slice(3))}</h3>;
        }
        if (line.startsWith("# ")) {
          return <h2 key={`${line}-${idx}`} style={briefTitle}>{stripMarkdown(line.slice(2))}</h2>;
        }
        if (line.startsWith("- ")) {
          return (
            <div key={`${line}-${idx}`} style={briefBullet}>
              <span style={briefBulletMark}>-</span>
              <span>{renderMarkdownLine(line.slice(2))}</span>
            </div>
          );
        }
        return <p key={`${line}-${idx}`} style={briefText}>{renderMarkdownLine(line)}</p>;
      })}
    </section>
  );
}

function ResultMetaLine({
  result,
  summary,
}: {
  result: FunctionCallResult<unknown>;
  summary: ResultSummary;
}) {
  const fields = summary.fields.length || summary.keyValues.length;
  const sources = result.sources?.length ?? 0;
  const warnings = result.warnings?.length ?? 0;
  return (
    <div style={resultMetaLine}>
      <span data-testid={!result.status || result.status === "ok" ? "function-status" : undefined}>
        {result.status ?? "ok"}
      </span>
      <span>{summary.shape}</span>
      <span>{summary.rows.length} rows</span>
      <span>{fields} fields</span>
      <span>{sources} sources</span>
      {warnings ? <span>{warnings} warnings</span> : null}
      <span>{formatElapsed(result.elapsed_ms)}</span>
      <span>{formatTime(result.fetched_at)}</span>
    </div>
  );
}

function FunctionHelp({
  code,
  entry,
  symbolFirst,
  controlProfile,
}: {
  code: string;
  entry: FunctionEntry | null;
  symbolFirst: boolean;
  controlProfile: ControlProfile;
}) {
  const usage = entry?.usage;
  const controls = [
    symbolFirst ? "Symbol field selects the market target." : `Scope: ${usage?.scope ?? "global"}.`,
    controlProfile.queryParam === "symbols"
      ? "WATCHLIST field sends comma-separated symbols without JSON editing."
      : controlProfile.queryParam
        ? `${controlProfile.queryParam.toUpperCase()} field changes the backend search text without JSON editing.`
        : null,
    controlProfile.limit ? "ROW controls the result count sent to the backend." : null,
    controlProfile.days ? "RANGE maps to the backend time horizon." : null,
    controlProfile.tradeTicket ? "Ticket controls set side, quantity, order type, and TIF; Run stays preview-only with submit=false." : null,
    "Advanced opens JSON overrides only when you need raw backend params.",
    "Deep inserts the broader-provider flag for functions that support it.",
  ].filter(Boolean);
  const steps = usage?.steps?.length ? usage.steps : controls;
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <strong style={{ color: "var(--accent)", fontFamily: "JetBrains Mono, monospace" }}>
        {code} · {entry?.name ?? "ShowMe function"}
      </strong>
      <span style={{ color: "var(--text-secondary)" }}>
        {usage?.purpose || entry?.description || "Run the function, inspect the source strip, then adjust inputs and rerun."}
      </span>
      {usage?.inputs?.length ? (
        <span style={{ color: "var(--text-mute)" }}>
          Inputs: {usage.inputs.join(", ")}
        </span>
      ) : null}
      <div style={{ display: "grid", gap: 4 }}>
        {steps.map((line) => (
          <span key={line} style={{ color: "var(--text-mute)" }}>
            {line}
          </span>
        ))}
      </div>
    </div>
  );
}

function TradeTicketControls({
  side,
  quantity,
  type,
  tif,
  disabled,
  onSide,
  onQuantity,
  onType,
  onTif,
}: {
  side: TicketSide;
  quantity: string;
  type: TicketType;
  tif: TicketTif;
  disabled: boolean;
  onSide: (next: TicketSide) => void;
  onQuantity: (next: string) => void;
  onType: (next: TicketType) => void;
  onTif: (next: TicketTif) => void;
}) {
  return (
    <div style={ticketControls}>
      <SegmentedControl
        label="SIDE"
        value={side}
        options={[
          { value: "BUY", label: "BUY" },
          { value: "SELL", label: "SELL" },
        ]}
        onChange={(next) => onSide(next as TicketSide)}
        disabled={disabled}
      />
      <Field
        label="Qty"
        value={quantity}
        type="number"
        min="0"
        step="any"
        inputMode="decimal"
        onChange={(e) => onQuantity(e.target.value)}
        hint="Positive quantity required."
        disabled={disabled}
      />
      <SegmentedControl
        label="TYPE"
        value={type}
        options={[
          { value: "MARKET", label: "Market" },
          { value: "LIMIT", label: "Limit" },
          { value: "STOP", label: "Stop" },
          { value: "STOP_LIMIT", label: "Stop limit" },
        ]}
        onChange={(next) => onType(next as TicketType)}
        disabled={disabled}
      />
      <SegmentedControl
        label="TIF"
        value={tif}
        options={[
          { value: "DAY", label: "Day" },
          { value: "GTC", label: "GTC" },
          { value: "IOC", label: "IOC" },
          { value: "FOK", label: "FOK" },
        ]}
        onChange={(next) => onTif(next as TicketTif)}
        disabled={disabled}
      />
    </div>
  );
}

function BacktestControls({
  code,
  value,
  disabled,
  onChange,
}: {
  code: string;
  value: BacktestStrategy;
  disabled: boolean;
  onChange: (next: BacktestStrategy) => void;
}) {
  const isMatrix = code === "BMTX";
  const current = isMatrix ? value : value === "ALL" ? "sma_crossover" : value;
  const options = [
    ...(isMatrix ? [{ value: "ALL" as const, label: "All" }] : []),
    { value: "sma_crossover" as const, label: "SMA" },
    { value: "rsi_meanrev" as const, label: "RSI" },
    { value: "buy_and_hold" as const, label: "Buy/hold" },
  ];
  return (
    <section style={controlInlinePanel}>
      <SegmentedControl
        label="STRATEGY"
        value={current}
        options={options}
        onChange={(next) => onChange(next as BacktestStrategy)}
        disabled={disabled}
        title="Backtest strategy"
      />
    </section>
  );
}

function MLSignalControls({
  horizon,
  disabled,
  onHorizon,
}: {
  horizon: MLHorizon;
  disabled: boolean;
  onHorizon: (next: MLHorizon) => void;
}) {
  return (
    <section style={controlInlinePanel}>
      <SegmentedControl
        label="HORIZON"
        value={horizon}
        options={[
          { value: "1", label: "1D" },
          { value: "5", label: "5D" },
          { value: "20", label: "20D" },
        ]}
        onChange={(next) => onHorizon(next as MLHorizon)}
        disabled={disabled}
        title="Prediction horizon"
      />
    </section>
  );
}

function SimpleParamControls({
  specs,
  values,
  disabled,
  onChange,
}: {
  specs: SimpleParamSpec[];
  values: Record<string, string>;
  disabled: boolean;
  onChange: (key: string, value: string) => void;
}) {
  return (
    <section style={ticketControls}>
      {specs.map((spec) => (
        <Field
          key={spec.key}
          label={spec.label}
          value={values[spec.key] ?? ""}
          onChange={(e) => onChange(spec.key, e.target.value)}
          placeholder={spec.hint}
          hint={spec.hint}
          disabled={disabled}
        />
      ))}
    </section>
  );
}

function OptionAssumptionControls({
  code,
  spot,
  strike,
  shortStrike,
  expiry,
  vol,
  rate,
  optionType,
  strategy,
  disabled,
  onSpot,
  onStrike,
  onShortStrike,
  onExpiry,
  onVol,
  onRate,
  onOptionType,
  onStrategy,
}: {
  code: string;
  spot: string;
  strike: string;
  shortStrike: string;
  expiry: string;
  vol: string;
  rate: string;
  optionType: OptionType;
  strategy: OptionStrategy;
  disabled: boolean;
  onSpot: (next: string) => void;
  onStrike: (next: string) => void;
  onShortStrike: (next: string) => void;
  onExpiry: (next: string) => void;
  onVol: (next: string) => void;
  onRate: (next: string) => void;
  onOptionType: (next: OptionType) => void;
  onStrategy: (next: OptionStrategy) => void;
}) {
  const isStrategy = code === "OSA";
  return (
    <section style={controlInlinePanel}>
      <div style={ticketControls}>
        {isStrategy ? (
          <div style={optionStrategyControl}>
            <SegmentedControl
              label="STRATEGY"
              value={strategy}
              options={[
                { value: "CALL_SPREAD", label: "Call spread" },
                { value: "LONG_CALL", label: "Long call" },
                { value: "STRADDLE", label: "Straddle" },
              ]}
              onChange={(next) => onStrategy(next as OptionStrategy)}
              disabled={disabled}
            />
          </div>
        ) : (
          <SegmentedControl
            label="TYPE"
            value={optionType}
            options={[
              { value: "CALL", label: "Call" },
              { value: "PUT", label: "Put" },
            ]}
            onChange={(next) => onOptionType(next as OptionType)}
            disabled={disabled}
          />
        )}
        <Field
          label="Spot"
          value={spot}
          type="number"
          step="any"
          inputMode="decimal"
          onChange={(e) => onSpot(e.target.value)}
          disabled={disabled}
        />
        <Field
          label={isStrategy ? "Long K" : "Strike"}
          value={strike}
          type="number"
          step="any"
          inputMode="decimal"
          onChange={(e) => onStrike(e.target.value)}
          disabled={disabled}
        />
        {isStrategy ? (
          <Field
            label="Short K"
            value={shortStrike}
            type="number"
            step="any"
            inputMode="decimal"
            onChange={(e) => onShortStrike(e.target.value)}
            disabled={disabled || strategy !== "CALL_SPREAD"}
          />
        ) : null}
        <Field
          label="T years"
          value={expiry}
          type="number"
          min="0"
          step="0.01"
          inputMode="decimal"
          onChange={(e) => onExpiry(e.target.value)}
          disabled={disabled}
        />
        <Field
          label="Vol"
          value={vol}
          type="number"
          min="0"
          step="0.01"
          inputMode="decimal"
          onChange={(e) => onVol(e.target.value)}
          disabled={disabled}
        />
        <Field
          label="Rate"
          value={rate}
          type="number"
          step="0.001"
          inputMode="decimal"
          onChange={(e) => onRate(e.target.value)}
          disabled={disabled}
        />
      </div>
    </section>
  );
}

function compatibleRequestedSymbol(
  symbol: string | undefined | null,
  entry: FunctionEntry | null,
): string {
  const normalized = normalizeSymbolInput(symbol);
  if (!normalized) return "";
  const inferred = inferAssetClassName(normalized);
  const supported = (entry?.asset_classes ?? [])
    .map((item) => String(item).trim().toUpperCase())
    .filter(Boolean);
  if (supported.length) {
    if (supported.includes(inferred)) return normalized;
    if (inferred === "ETF" && supported.includes("EQUITY")) return normalized;
    if (inferred === "EQUITY" && supported.includes("ETF")) return normalized;
    return "";
  }
  const category = entry?.category?.toLowerCase();
  if (category === "equity" && !["EQUITY", "ETF"].includes(inferred)) return "";
  if (category === "fx" && inferred !== "FX") return "";
  if (category === "commodity" && inferred !== "COMMODITY") return "";
  if (category === "bond" && inferred !== "BOND") return "";
  return normalized;
}

function suggestedSymbolsForFunction(
  quickSymbols: string[],
  assetClasses: string[],
  category?: string,
): string[] {
  const supported = assetClasses.map((item) => item.toUpperCase());
  const categoryKey = category?.toUpperCase() ?? "";
  const byClass: Record<string, string[]> = {
    CRYPTO: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"],
    EQUITY: ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL", "JPM"],
    ETF: ["SPY", "QQQ", "IWM", "DIA", "TLT", "GLD"],
    FX: ["EURUSD", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X", "USDCHF=X"],
    COMMODITY: ["GC=F", "CL=F", "NG=F", "SI=F", "HG=F"],
    INDEX: ["^GSPC", "^IXIC", "^DJI", "^RUT", "^VIX"],
    BOND: ["US10Y", "US2Y", "US30Y"],
  };
  const classes = supported.length
    ? supported
    : categoryKey === "FX"
      ? ["FX"]
      : categoryKey === "COMMODITY"
        ? ["COMMODITY"]
        : categoryKey === "BOND"
          ? ["BOND"]
          : categoryKey === "NEWS"
            ? ["CRYPTO", "EQUITY"]
            : ["EQUITY", "CRYPTO", "FX"];
  return unique([
    ...quickSymbols,
    ...classes.flatMap((cls) => byClass[cls] ?? []),
  ]).slice(0, 24);
}

function StatusPanel({
  status,
  compact = false,
  onRetry,
}: {
  status: PayloadStatus;
  compact?: boolean;
  onRetry?: () => void;
}) {
  const tone = status.state === "unavailable" ? "negative" : "warn";
  return (
    <section
      className="showme-card-reveal showme-stub-block"
      style={compact ? compactStatusBox : statusBox}
      data-testid="function-status-panel"
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
        <div style={{ display: "grid", gap: 4 }}>
          <Pill tone={tone} withDot={status.state === "degraded"}>
            <span data-testid="function-status">{status.label}</span>
          </Pill>
          <strong style={{ color: "var(--text-primary)" }}>{status.title}</strong>
        </div>
        {onRetry ? (
          <button type="button" className="btn btn--ghost" onClick={onRetry}>
            Retry
          </button>
        ) : null}
      </div>
      {status.reasons.length > 0 ? (
        <div style={{ display: "grid", gap: 4 }}>
          {status.reasons.slice(0, compact ? 2 : 6).map((reason, idx) => (
            <span
              key={`${reason}-${idx}`}
              style={{ color: "var(--text-secondary)" }}
              data-testid={idx === 0 ? "function-reason" : undefined}
            >
              {reason}
            </span>
          ))}
        </div>
      ) : null}
      {status.actions.length > 0 ? (
        <div style={{ display: "grid", gap: 4 }}>
          {status.actions.slice(0, compact ? 2 : 6).map((action, idx) => (
            <span
              key={`${action}-${idx}`}
              style={{ color: "var(--text-mute)" }}
              data-testid={idx === 0 ? "function-next-action" : undefined}
            >
              {action}
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function NewsList({ rows }: { rows: RecordRow[] }) {
  const sortedRows = useMemo(
    () => sortNewsNewestFirst(rows, newsRowTimestamp),
    [rows],
  );
  return (
    <section className="showme-stub-news-list" style={newsList}>
      {sortedRows.slice(0, 40).map((row, idx) => {
        const title = firstString(row, ["headline", "title", "name"]) || `Item ${idx + 1}`;
        const url = firstString(row, ["url", "link"]);
        const source = firstString(row, ["source", "publisher", "provider"]) || "-";
        const time = newsRowTimestamp(row);
        const summary = firstString(row, ["summary", "description", "snippet"]);
        const severity = firstString(row, ["severity", "importance"]);
        const score = firstString(row, ["importance_score", "impact_score", "score"]);
        const alert = row.alert === true || severity === "critical" || severity === "high";
        const reasons = Array.isArray(row.importance_reasons)
          ? row.importance_reasons.map(String).slice(0, 3)
          : [];
        return (
          <article
            key={stableRowKey(row, idx)}
            className={`showme-card-reveal showme-stub-block ${motionDelayClass(idx)}`}
            style={newsItem}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              {url ? (
                <a href={url} target="_blank" rel="noreferrer" style={newsTitle}>
                  {title}
                </a>
              ) : (
                <strong style={newsTitle}>{title}</strong>
              )}
              <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "end", gap: 6 }}>
                {severity ? (
                  <Pill tone={alert ? "negative" : severity === "medium" ? "warn" : "muted"} withDot={alert}>
                    {severity}{score ? ` ${score}` : ""}
                  </Pill>
                ) : null}
                <span style={sourceBadge}>{source}</span>
              </div>
            </div>
            {summary ? <p style={newsSummary}>{stripHtml(summary)}</p> : null}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
              {time ? <span style={metaLabel}>{relativeTimeLabel(time) ?? time}</span> : null}
              {reasons.map((reason) => (
                <span key={reason} style={reasonBadge}>{reason}</span>
              ))}
            </div>
          </article>
        );
      })}
    </section>
  );
}

function renderMarkdownLine(text: string): ReactNode {
  const clean = stripMarkdown(text);
  const match = clean.match(/^(.*)\[([^\]]+)\]\((https?:\/\/[^)]+)\)(.*)$/);
  if (!match) return clean;
  const [, before, label, url, after] = match;
  return (
    <>
      {before}
      <a href={url} target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>
        {label}
      </a>
      {after}
    </>
  );
}

function newsRowTimestamp(row: RecordRow): string | null | undefined {
  return firstString(row, [
    "published_at",
    "publishedAt",
    "published_on",
    "published",
    "date",
    "datetime",
    "time",
    "ts",
  ]);
}

function MediaPreview({ items }: { items: MediaItem[] }) {
  return (
    <section className="showme-stub-media-grid" style={mediaGrid}>
      {items.map((item) => (
        <figure
          key={`${item.label}:${item.src.slice(0, 40)}`}
          className="showme-card-reveal showme-stub-block"
          style={mediaFigure}
        >
          <img src={item.src} alt={item.label} style={mediaImage} />
          <figcaption style={mediaCaption}>
            <span>{item.label}</span>
            {item.note ? <span style={metaLabel}>{item.note}</span> : null}
          </figcaption>
        </figure>
      ))}
    </section>
  );
}

function MetricRibbon({ metrics }: { metrics: MetricCard[] }) {
  return (
    <section className="showme-stub-metric-ribbon" style={metricRibbon}>
      {metrics.slice(0, 12).map((metric) => (
        <div
          key={metric.label}
          className="showme-card-reveal showme-stub-block showme-stub-metric"
          style={metricRibbonItem}
        >
          <span style={metaLabel}>{humanizeKey(metric.label)}</span>
          <strong style={metricRibbonValue}>{formatValue(metric.value)}</strong>
        </div>
      ))}
    </section>
  );
}

function SeriesChart({ chartId, series }: { chartId: string; series: ChartSeries }) {
  if (series.kind === "line" || series.kind === "ohlc") {
    return <LightweightSeriesChart chartId={chartId} series={series} />;
  }
  if (series.kind === "curve") {
    return <CurveChart chartId={chartId} series={series} />;
  }
  if (series.kind === "heatmap") {
    return <HeatmapChart chartId={chartId} series={series} />;
  }
  return <BarChart chartId={chartId} series={series} />;
}

function LightweightSeriesChart({ chartId, series }: { chartId: string; series: ChartSeries }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const resize = usePersistentChartSize(`${chartId}.${series.kind}`);
  const values = series.points.map((point) => point.y);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const first = series.points[0]?.y ?? 0;
  const last = series.points.at(-1)?.y ?? 0;
  const delta = last - first;
  const intradayTime = series.points.some((point) => typeof point.time === "number");

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const size = measureChartElement(el, 460);
    const chart = createChart(el, {
      layout: {
        background: { color: "transparent" },
        textColor: "rgba(240,242,245,0.85)",
        fontFamily: "JetBrains Mono, SF Mono, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      timeScale: {
        rightOffset: 8,
        barSpacing: 7,
        minBarSpacing: 0.3,
        timeVisible: intradayTime,
        borderColor: "rgba(255,255,255,0.08)",
      },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
      crosshair: { mode: 1 },
      width: size.width,
      height: size.height,
    });

    if (series.kind === "ohlc") {
      const candleSeries = chart.addCandlestickSeries({
        upColor: "#00d183",
        downColor: "#ff3b58",
        borderUpColor: "#00d183",
        borderDownColor: "#ff3b58",
        wickUpColor: "#00d183",
        wickDownColor: "#ff3b58",
      });
      candleSeries.setData(
        series.points
          .filter(hasOhlcPoint)
          .map<CandlestickData>((point) => ({
            time: point.time,
            open: point.open,
            high: point.high,
            low: point.low,
            close: point.close,
          })),
      );
      const volume = series.points
        .filter(hasVolumePoint)
        .map<HistogramData>((point) => ({
          time: point.time,
          value: Number(point.volume),
          color:
            Number(point.close) >= Number(point.open)
              ? "rgba(0,209,131,0.35)"
              : "rgba(255,59,88,0.35)",
        }));
      if (volume.length > 0) {
        const volSeries = chart.addHistogramSeries({
          priceScaleId: "volume",
          color: "rgba(160,164,171,0.35)",
          priceFormat: { type: "volume" },
        });
        chart.priceScale("volume").applyOptions({
          scaleMargins: { top: 0.78, bottom: 0 },
        });
        volSeries.setData(volume);
      }
    } else {
      const line = chart.addLineSeries({
        color: delta >= 0 ? "#00d183" : "#ff3b58",
        lineWidth: 2,
        priceLineVisible: false,
      });
      line.setData(
        series.points
          .filter(hasTimePoint)
          .map<LineData>((point) => ({
            time: point.time,
            value: point.y,
          })),
      );
    }

    focusLatestBars(chart, series.points.length, size.width);
    const ro = new ResizeObserver(() => {
      resizeChartToElement(chart, el, 460);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.remove();
    };
  }, [series, delta, intradayTime]);

  return (
    <section
      className="showme-card-reveal showme-stub-block showme-stub-chart"
      ref={resize.frameRef}
      style={{ ...chartPanel, ...resize.frameStyle }}
      data-testid="function-chart"
    >
      <ChartTitle series={series} last={last} min={min} max={max} delta={delta} />
      <div ref={containerRef} style={lightweightChartHost} />
      <div style={chartAxis}>
        <span>{series.points[0]?.xLabel ?? "-"}</span>
        <span>{series.xKey ? `${series.xKey} / ${series.yKey}` : series.yKey}</span>
        <span>{series.points.at(-1)?.xLabel ?? "-"}</span>
      </div>
      <ChartResizeButton resize={resize} />
    </section>
  );
}

function BarChart({ chartId, series }: { chartId: string; series: ChartSeries }) {
  const resize = usePersistentChartSize(`${chartId}.${series.kind}`);
  const width = 1000;
  const height = 280;
  const padX = 40;
  const padY = 26;
  const points = series.points.slice(0, 30);
  const values = points.map((point) => point.y);
  const maxAbs = Math.max(...values.map((value) => Math.abs(value)), 1);
  const barGap = 6;
  const plotWidth = width - padX * 2;
  const barWidth = Math.max(5, (plotWidth - barGap * (points.length - 1)) / points.length);
  const zeroY = padY + (height - padY * 2) / 2;
  const first = series.points[0]?.y ?? 0;
  const last = series.points.at(-1)?.y ?? 0;
  const delta = last - first;
  const min = Math.min(...values);
  const max = Math.max(...values);
  return (
    <section
      className="showme-card-reveal showme-stub-block showme-stub-chart"
      ref={resize.frameRef}
      style={{ ...chartPanel, ...resize.frameStyle }}
      data-testid="function-chart"
    >
      <ChartTitle series={series} last={last} min={min} max={max} delta={delta} />
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={chartSvg}>
        <line
          x1={padX}
          x2={width - padX}
          y1={zeroY}
          y2={zeroY}
          stroke="rgba(255,255,255,0.14)"
        />
        {points.map((point, idx) => {
          const x = padX + idx * (barWidth + barGap);
          const magnitude = (Math.abs(point.y) / maxAbs) * ((height - padY * 2) / 2);
          const y = point.y >= 0 ? zeroY - magnitude : zeroY;
          return (
            <rect
              key={`${point.xLabel}-${idx}`}
              x={x}
              y={y}
              width={barWidth}
              height={Math.max(2, magnitude)}
              rx={2}
              fill={point.y >= 0 ? "var(--positive)" : "var(--negative)"}
              opacity={0.78}
            />
          );
        })}
      </svg>
      <div style={chartAxis}>
        <span>{series.points[0]?.xLabel ?? "-"}</span>
        <span>{series.labelKey ? `${series.labelKey} / ${series.yKey}` : series.yKey}</span>
        <span>{series.points.at(-1)?.xLabel ?? "-"}</span>
      </div>
      <ChartResizeButton resize={resize} />
    </section>
  );
}

function CurveChart({ chartId, series }: { chartId: string; series: ChartSeries }) {
  const resize = usePersistentChartSize(`${chartId}.${series.kind}`);
  const width = 1000;
  const height = 280;
  const padX = 42;
  const padY = 26;
  const points = series.points.filter((point) => typeof point.x === "number");
  const values = points.map((point) => point.y);
  const xValues = points.map((point) => Number(point.x));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const first = points[0]?.y ?? 0;
  const last = points.at(-1)?.y ?? 0;
  const delta = last - first;
  const minX = Math.min(...xValues);
  const maxX = Math.max(...xValues);
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(max - min, 1e-9);
  const toX = (value: number) => padX + ((value - minX) / spanX) * (width - padX * 2);
  const toY = (value: number) => height - padY - ((value - min) / spanY) * (height - padY * 2);
  const d = points
    .map((point, idx) => {
      const x = toX(Number(point.x));
      const y = toY(point.y);
      return `${idx === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
  const zeroY = min < 0 && max > 0 ? toY(0) : null;
  return (
    <section
      className="showme-card-reveal showme-stub-block showme-stub-chart"
      ref={resize.frameRef}
      style={{ ...chartPanel, ...resize.frameStyle }}
      data-testid="function-chart"
    >
      <ChartTitle series={series} last={last} min={min} max={max} delta={delta} />
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={chartSvg}>
        {zeroY !== null ? (
          <line
            x1={padX}
            x2={width - padX}
            y1={zeroY}
            y2={zeroY}
            stroke="rgba(255,255,255,0.16)"
          />
        ) : null}
        <path
          d={d}
          fill="none"
          stroke={delta >= 0 ? "var(--positive)" : "var(--negative)"}
          strokeWidth={3}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
        {points.slice(0, 1).concat(points.slice(-1)).map((point, idx) => (
          <circle
            key={`${point.xLabel}-${idx}`}
            cx={toX(Number(point.x))}
            cy={toY(point.y)}
            r={4}
            fill={idx === 0 ? "var(--text-mute)" : "var(--accent)"}
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>
      <div style={chartAxis}>
        <span>{points[0]?.xLabel ?? "-"}</span>
        <span>{series.xKey ? `${series.xKey} / ${series.yKey}` : series.yKey}</span>
        <span>{points.at(-1)?.xLabel ?? "-"}</span>
      </div>
      <ChartResizeButton resize={resize} />
    </section>
  );
}

function HeatmapChart({ chartId, series }: { chartId: string; series: ChartSeries }) {
  const resize = usePersistentChartSize(`${chartId}.${series.kind}`);
  const values = series.points.map((point) => point.y);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const first = series.points[0]?.y ?? 0;
  const last = series.points.at(-1)?.y ?? 0;
  const delta = last - first;
  const maxAbs = Math.max(...values.map((value) => Math.abs(value)), 1);
  return (
    <section
      className="showme-card-reveal showme-stub-block showme-stub-chart"
      ref={resize.frameRef}
      style={{ ...chartPanel, ...resize.frameStyle }}
      data-testid="function-chart"
    >
      <ChartTitle series={series} last={last} min={min} max={max} delta={delta} />
      <div style={heatmapGrid}>
        {series.points.slice(0, 40).map((point, idx) => {
          const opacity = 0.22 + Math.min(Math.abs(point.y) / maxAbs, 1) * 0.58;
          const color = point.y >= 0 ? `rgba(0,209,131,${opacity})` : `rgba(255,59,88,${opacity})`;
          return (
            <div
              key={`${point.xLabel}-${idx}`}
              className={`showme-row-reveal ${motionDelayClass(idx)}`}
              style={{ ...heatmapCell, background: color }}
            >
              <strong>{point.xLabel}</strong>
              <span>{formatValue(point.y)}</span>
            </div>
          );
        })}
      </div>
      <div style={chartAxis}>
        <span>{series.points[0]?.xLabel ?? "-"}</span>
        <span>{series.labelKey ? `${series.labelKey} / ${series.yKey}` : series.yKey}</span>
        <span>{series.points.at(-1)?.xLabel ?? "-"}</span>
      </div>
      <ChartResizeButton resize={resize} />
    </section>
  );
}

type ChartResizeControls = ReturnType<typeof usePersistentChartSize>;

function ChartResizeButton({ resize }: { resize: ChartResizeControls }) {
  return (
    <button
      type="button"
      aria-label="Resize chart"
      title="Drag to resize chart. Double-click to reset."
      onPointerDown={resize.startResize}
      onDoubleClick={resize.resetSize}
      style={chartResizeHandleStyle}
    />
  );
}

function ChartTitle({
  series,
  last,
  min,
  max,
  delta,
}: {
  series: ChartSeries;
  last: number;
  min: number;
  max: number;
  delta: number;
}) {
  const kindLabel =
    series.kind === "ohlc"
      ? "Candlestick"
      : series.kind === "curve"
        ? "Curve"
      : series.kind === "line"
        ? "Time series"
        : series.kind === "heatmap"
          ? "Heatmap"
          : "Bar chart";
  return (
    <div style={chartHeader}>
      <div>
        <div style={metaLabel}>{kindLabel}</div>
        <strong style={{ color: "var(--text-primary)" }}>{series.title}</strong>
      </div>
      <div style={chartStats}>
        <Metric label="last" value={formatValue(last)} />
        <Metric label="min" value={formatValue(min)} />
        <Metric label="max" value={formatValue(max)} />
        <Metric label="delta" value={formatValue(delta)} />
      </div>
    </div>
  );
}

function SourceStrip({ result }: { result: FunctionCallResult<unknown> }) {
  const providerErrors = asStringArray(result.metadata?.provider_errors);
  return (
    <section className="showme-card-reveal showme-stub-block" style={sourceStrip} data-testid="function-source">
      <div>
        <span style={metaLabel}>Sources</span>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
          {(result.sources?.length ? result.sources : ["none"]).map((source) => (
            <Pill key={source} tone={isSyntheticText(source) ? "negative" : "muted"} withDot={false}>
              {source}
            </Pill>
          ))}
        </div>
      </div>
      {providerErrors.length > 0 ? (
        <div style={warningBox}>
          {providerErrors.slice(0, 5).map((w, i) => (
            <div key={`${w}-${i}`}>{w}</div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

interface ResultSummary {
  shape: string;
  rows: RecordRow[];
  columns: DataGridColumn<RecordRow>[];
  fields: string[];
  keyValues: Array<[string, unknown]>;
}

type ChartKind = "line" | "ohlc" | "bar" | "heatmap" | "curve";

interface ChartPoint {
  xLabel: string;
  y: number;
  x?: number;
  time?: Time;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
}

interface ChartSeries {
  kind: ChartKind;
  title: string;
  rows: RecordRow[];
  xKey: string | null;
  labelKey: string | null;
  yKey: string;
  points: ChartPoint[];
}

interface MetricCard {
  label: string;
  value: unknown;
}

interface MediaItem {
  label: string;
  src: string;
  note?: string;
  isSatellite?: boolean;
}

interface PayloadStatus {
  state: "live" | "degraded" | "unavailable" | "empty";
  label: string;
  title: string;
  reasons: string[];
  actions: string[];
}

const STABLE_ROW_ID_KEYS = [
  "id",
  "symbol",
  "ticker",
  "isin",
  "cusip",
  "headline",
  "title",
  "name",
  "date",
  "datetime",
  "time",
  "timestamp",
  "published_at",
  "period",
  "bucket",
];

function motionDelayClass(idx: number): string {
  return `showme-motion-grid__row--${Math.min(idx, 10)}`;
}

function stableRowKey(row: RecordRow, idx: number): string {
  const parts = STABLE_ROW_ID_KEYS
    .map((key) => row[key])
    .filter((value): value is string | number =>
      (typeof value === "string" && value.trim().length > 0) ||
      typeof value === "number",
    )
    .slice(0, 4)
    .map(String);
  return parts.length ? parts.join(":") : `row-${idx}`;
}

function summarizeResult(data: unknown): ResultSummary {
  const rows = extractRows(data);
  const fields = rows.length ? collectFields(rows) : [];
  const keyValues = extractKeyValues(data);
  return {
    shape: Array.isArray(data) ? "array" : isRecord(data) ? "object" : typeof data,
    rows,
    fields,
    keyValues,
    columns: buildColumns(rows, fields),
  };
}

function extractRows(data: unknown): RecordRow[] {
  if (Array.isArray(data)) return data.map(objectify);
  if (!isRecord(data)) return [];
  for (const key of TABLE_KEYS) {
    const value = data[key];
    if (Array.isArray(value) && value.length > 0) return value.map(objectify);
  }
  for (const value of Object.values(data)) {
    if (Array.isArray(value) && value.length > 0) return value.map(objectify);
  }
  for (const value of Object.values(data)) {
    if (!isRecord(value)) continue;
    const nested = Object.entries(value);
    if (!nested.length || !nested.every(([, item]) => isRecord(item))) continue;
    return nested.map(([bucket, item]) => ({ bucket, ...(item as RecordRow) }));
  }
  return [];
}

function extractKeyValues(data: unknown): Array<[string, unknown]> {
  if (!isRecord(data)) return [];
  return Object.entries(data)
    .filter(([, value]) => !Array.isArray(value) && !isNestedRecord(value))
    .slice(0, 18);
}

function getPayloadStatus(result: FunctionCallResult<unknown>): PayloadStatus {
  const metadata = result.metadata ?? {};
  const sources = result.sources ?? [];
  const explicitStatus = String(
    result.status ?? (isRecord(result.data) ? result.data.status ?? result.data.state : "") ?? "",
  ).toLowerCase();
  const reasons = [
    ...asStringArray(result.reason),
    ...asStringArray(result.warnings),
    ...asStringArray(metadata.provider_errors),
  ];
  const dataReason = dataReasonLine(result.data);
  if (dataReason) reasons.unshift(dataReason);
  const actions = unique([...asStringArray(result.nextAction), ...extractActions(result.data)]);
  const syntheticSources = sources.filter(isSyntheticText);
  const metadataSynthetic = Boolean(
    metadata.synthetic ||
      metadata.fallback ||
      metadata.degraded ||
      isSyntheticText(String(metadata.mode ?? "")) ||
      isSyntheticText(String(metadata.compatibility_mode ?? "")),
  );
  const empty = explicitStatus === "empty" || explicitStatus === "empty_portfolio";
  const unavailable =
    Boolean(metadata.fallback) ||
    dataIsUnavailable(result.data) ||
    ["provider_unavailable", "input_error", "calc_error", "unsupported_asset", "not_configured"].includes(
      explicitStatus,
    );
  const degraded = metadataSynthetic || syntheticSources.length > 0 || reasons.length > 0;

  if (empty) {
    return {
      state: "empty",
      label: "empty",
      title: "No data for this input",
      reasons: unique(reasons.length ? reasons : ["The function returned an intentional empty state."]),
      actions: unique(actions.length ? actions : defaultActions(result)),
    };
  }
  if (unavailable) {
    return {
      state: "unavailable",
      label: "needs data",
      title: "Provider or input required",
      reasons: unique(reasons.length ? reasons : ["The backend did not return usable live data."]),
      actions: unique(actions.length ? actions : defaultActions(result)),
    };
  }
  if (degraded) {
    return {
      state: "degraded",
      label: "degraded",
      title: "Payload returned with provider or source warnings",
      reasons: unique([
        ...reasons,
        ...syntheticSources.map((s) => `Synthetic source marker: ${s}`),
      ]),
      actions: unique(actions.length ? actions : ["Check sources and rerun with Live or Deep enabled."]),
    };
  }
  return {
    state: "live",
    label: "live",
    title: "Live payload",
    reasons: [],
    actions: [],
  };
}

function dataIsUnavailable(data: unknown): boolean {
  if (!isRecord(data)) return false;
  const status = String(data.status ?? data.state ?? "").toLowerCase();
  return [
    "unavailable",
    "provider_unavailable",
    "unsupported_asset",
    "empty_portfolio",
    "not_configured",
    "input_error",
    "calc_error",
  ].some((token) => status.includes(token));
}

function dataReasonLine(data: unknown): string | null {
  if (!isRecord(data)) return null;
  const status = firstString(data, ["status", "state"]);
  const reason = firstString(data, ["reason", "message", "note"]);
  const statusKey = status?.toLowerCase();
  if (statusKey && ["ok", "preview", "live", "ready"].includes(statusKey) && !reason) return null;
  if (status && reason) return `${status}: ${reason}`;
  return reason || (statusKey && ["ok", "preview", "live", "ready"].includes(statusKey) ? null : status);
}

function defaultActions(result: FunctionCallResult<unknown>): string[] {
  const symbol = result.instrument?.symbol;
  return [
    symbol ? `Verify ${symbol} is supported by this function.` : "Provide the required symbol, account, or query input.",
    "Connect the required API key or local portfolio state when this function depends on private data.",
    "Open Advanced or Raw function payload to inspect exact provider errors.",
  ];
}

function extractActions(data: unknown): string[] {
  if (!isRecord(data)) return [];
  return unique([
    ...asStringArray(data.next_actions),
    ...asStringArray(data.required_setup),
    ...asStringArray(data.actions),
  ]);
}

function parseParams(text: string): Record<string, unknown> | undefined {
  const trimmed = text.trim();
  if (!trimmed) return undefined;
  const parsed = JSON.parse(trimmed) as unknown;
  if (!isRecord(parsed)) {
    throw new Error("Params JSON must be an object");
  }
  return parsed;
}

function mergeParams(text: string, patch: Record<string, unknown>): string {
  let base: Record<string, unknown> = {};
  try {
    base = parseParams(text) ?? {};
  } catch {
    base = {};
  }
  return JSON.stringify({ ...base, ...patch }, null, 2);
}

interface ControlProfile {
  limitParam?: "limit" | "top_n";
  rangeParam?: "days" | "weeks" | "horizon_days";
  queryParam?: QueryParam;
  queryLabel?: string;
  queryHint?: string;
  tradeTicket: boolean;
  transcriptText: boolean;
  limit: boolean;
  days: boolean;
}

const LIMIT_PARAM_CODES = new Set([
  "AIM",
  "BQL",
  "DAPI",
  "EXEC",
  "FLDS",
  "ISIN",
  "NSE",
  "TOP",
  "CN",
  "NI",
  "TAUC",
]);

const TOP_N_PARAM_CODES = new Set(["HDS"]);
const LIMIT_CATEGORIES = new Set(["news", "screen", "trade"]);

const DAYS_PARAM_CODES = new Set([
  "BLAK",
  "BMTX",
  "BTFW",
  "BTUNE",
  "BGAS",
  "BOIL",
  "CHGS",
  "BQL",
  "CORR",
  "CPF",
  "GC3D",
  "HVT",
  "MARS",
  "MLSIG",
  "MOSS",
  "NGAS",
  "PORT_OPT",
  "PVAR",
  "READ",
  "RPAR",
  "SAT",
  "TECH",
]);

const WEEKS_PARAM_CODES = new Set(["DPF"]);
const HORIZON_PARAM_CODES = new Set(["TAUC"]);
const TRADE_TICKET_CODES = new Set(["BBGT", "EMSX", "FXGO", "TSOX"]);
const QUERY_PARAM_CODES = new Set([
  "AV",
  "BRIEF",
  "BQL",
  "CSRC",
  "DAPI",
  "FLDS",
  "FSRC",
  "FTS",
  "ICX",
  "ISIN",
  "MEET",
  "NSE",
  "PEOP",
  "POLY",
  "SECF",
  "SRCH",
  "TOP",
  "TSAR",
]);
const TOPIC_PARAM_CODES = new Set(["NI"]);
const SYMBOLS_PARAM_CODES = new Set(["BLAK", "BMTX", "CORR", "FRH", "MARS", "PORT_OPT", "RPAR", "TLDR"]);
const WATCHLIST_PARAM_CODES = new Set(["READ"]);
const UNIVERSE_PARAM_CODES = new Set(["MOSS"]);
const BBOX_PARAM_CODES = new Set(["SAT"]);

function buildControlProfile(code: string, category?: string): ControlProfile {
  const upper = code.toUpperCase();
  const cat = category?.toLowerCase() ?? "";
  const limitParam = TOP_N_PARAM_CODES.has(upper)
    ? "top_n"
    : LIMIT_PARAM_CODES.has(upper) || LIMIT_CATEGORIES.has(cat)
      ? "limit"
      : undefined;
  const rangeParam = WEEKS_PARAM_CODES.has(upper)
    ? "weeks"
    : HORIZON_PARAM_CODES.has(upper)
      ? "horizon_days"
      : DAYS_PARAM_CODES.has(upper)
        ? "days"
        : undefined;
  const queryParam = TOPIC_PARAM_CODES.has(upper)
    ? "topic"
    : SYMBOLS_PARAM_CODES.has(upper)
      ? "symbols"
    : WATCHLIST_PARAM_CODES.has(upper)
      ? "watchlist"
    : UNIVERSE_PARAM_CODES.has(upper)
      ? "universe"
    : BBOX_PARAM_CODES.has(upper)
      ? "bbox"
    : QUERY_PARAM_CODES.has(upper) || cat === "news"
      ? "query"
      : undefined;
  const tradeTicket = TRADE_TICKET_CODES.has(upper);
  const transcriptText = upper === "TRQA";
  const queryLabel = upper === "ICX"
    ? "Index"
    : upper === "SAT"
      ? "BBox"
      : upper === "BQL"
        ? "BQL"
      : upper === "DAPI"
        ? "Endpoint"
      : upper === "FLDS"
        ? "Field"
      : upper === "ISIN"
        ? "Identifier"
      : upper === "FTS"
        ? "Search"
      : upper === "FRH"
        ? "Symbols"
      : upper === "BLAK" || upper === "BMTX" || upper === "CORR" || upper === "PORT_OPT" || upper === "RPAR"
        ? "Universe"
      : upper === "MARS" || upper === "MOSS"
        ? "Universe"
      : upper === "TLDR" || upper === "READ"
        ? "Watchlist"
      : undefined;
  const queryHint = upper === "ICX"
    ? "Index code sent to backend, e.g. SPX, NDX, DJI."
    : upper === "SAT"
      ? "minLon,minLat,maxLon,maxLat sent to backend."
      : upper === "BQL"
        ? "Example: get(close, volume) for(['AAPL','MSFT']) by(date). Range controls the time window."
      : upper === "DAPI"
        ? "Filter actual sidecar endpoints by path or purpose, e.g. quote, order, portfolio."
      : upper === "FLDS"
        ? "Search field names, descriptions, or categories such as price, valuation, duration."
      : upper === "ISIN"
        ? "Ticker, ISIN, CUSIP, SEDOL, or FIGI. Use the ID Type control for lookup mode."
      : upper === "FTS"
        ? "SEC filing text query. Symbol context is added automatically, e.g. risk factors."
      : upper === "FRH"
        ? "Comma-separated perpetual symbols; default is the top crypto USDT watchlist."
      : upper === "BLAK"
        ? "Comma-separated symbols for Black-Litterman weights and views."
      : upper === "BMTX"
        ? "Comma-separated symbols tested across the selected strategy set."
      : upper === "CORR"
        ? "Comma-separated symbols for Pearson/Spearman/downside correlation."
      : upper === "PORT_OPT"
        ? "Comma-separated symbols for optimizer weights and efficient frontier."
      : upper === "RPAR"
        ? "Comma-separated symbols for equal-risk-contribution weights."
      : upper === "MARS"
        ? "Comma-separated symbols used to build the multi-asset portfolio return series."
      : upper === "MOSS"
        ? "Comma-separated symbols ranked by realized volatility."
      : upper === "TLDR" || upper === "READ"
        ? "Comma-separated symbols for the watchlist, e.g. AAPL, MSFT, BTCUSDT."
      : undefined;
  return {
    limitParam,
    rangeParam,
    queryParam,
    queryLabel,
    queryHint,
    tradeTicket,
    transcriptText,
    limit: Boolean(limitParam),
    days: Boolean(rangeParam),
  };
}

function buildControlParams(
  profile: ControlProfile,
  limit: RowLimit,
  range: StubRangeId,
  queryText: string,
): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  if (profile.limitParam) params[profile.limitParam] = limit;
  if (profile.rangeParam) {
    const days = STUB_RANGES.find((r) => r.id === range)?.days ?? 365;
    params[profile.rangeParam] =
      profile.rangeParam === "weeks" ? Math.max(4, Math.round(days / 7)) : days;
  }
  if (profile.queryParam && queryText.trim()) {
    params[profile.queryParam] = profile.queryParam === "symbols" ||
      profile.queryParam === "watchlist" ||
      profile.queryParam === "universe"
      ? queryText.split(",").map((item) => item.trim().toUpperCase()).filter(Boolean)
      : queryText.trim();
  }
  return params;
}

function buildOptionDefaultsForFunction(code: string): Record<string, unknown> {
  switch (code.toUpperCase()) {
    case "OVME":
      return {
        spot: 100,
        strike: 105,
        years_to_expiry: 0.25,
        vol: 0.28,
        rate: 0.045,
        type: "CALL",
      };
    case "OSA":
      return {
        spot: 100,
        strike: 100,
        short_strike: 110,
        years_to_expiry: 0.25,
        vol: 0.25,
        rate: 0.045,
        strategy: "CALL_SPREAD",
        legs: [
          { qty: 1, strike: 100, type: "CALL", expiry: 0.25, vol: 0.25 },
          { qty: -1, strike: 110, type: "CALL", expiry: 0.25, vol: 0.25 },
        ],
      };
    default:
      return {};
  }
}

function buildOptionControlParams(
  code: string,
  spotText: string,
  strikeText: string,
  shortStrikeText: string,
  expiryText: string,
  volText: string,
  rateText: string,
  optionType: OptionType,
  strategy: OptionStrategy,
): Record<string, unknown> {
  const upper = code.toUpperCase();
  if (upper !== "OVME" && upper !== "OSA") return {};
  const spot = numericInput(spotText, 100);
  const strike = numericInput(strikeText, upper === "OSA" ? 100 : 105);
  const shortStrike = numericInput(shortStrikeText, 110);
  const years = numericInput(expiryText, 0.25);
  const vol = numericInput(volText, upper === "OSA" ? 0.25 : 0.28);
  const rate = numericInput(rateText, 0.045);
  if (upper === "OVME") {
    return {
      spot,
      strike,
      years_to_expiry: years,
      vol,
      rate,
      type: optionType,
    };
  }
  const legs =
    strategy === "STRADDLE"
      ? [
          { qty: 1, strike, type: "CALL", expiry: years, vol },
          { qty: 1, strike, type: "PUT", expiry: years, vol },
        ]
      : strategy === "LONG_CALL"
        ? [{ qty: 1, strike, type: "CALL", expiry: years, vol }]
        : [
            { qty: 1, strike, type: "CALL", expiry: years, vol },
            { qty: -1, strike: shortStrike, type: "CALL", expiry: years, vol },
          ];
  return {
    spot,
    strike,
    short_strike: shortStrike,
    years_to_expiry: years,
    vol,
    rate,
    strategy,
    legs,
  };
}

function buildBacktestControlParams(code: string, strategy: BacktestStrategy): Record<string, unknown> {
  const upper = code.toUpperCase();
  if (upper !== "BTFW" && upper !== "BMTX" && upper !== "BTUNE") return {};
  const allStrategies = ["sma_crossover", "rsi_meanrev", "buy_and_hold"];
  if (upper === "BMTX") {
    return {
      strategies: strategy === "ALL" ? allStrategies : [strategy],
    };
  }
  return {
    strategy: strategy === "ALL" ? "sma_crossover" : strategy,
  };
}

function defaultBacktestStrategyForFunction(code: string): BacktestStrategy {
  return code.toUpperCase() === "BMTX" ? "ALL" : "sma_crossover";
}

function simpleParamSpecsForFunction(code: string): SimpleParamSpec[] {
  switch (code.toUpperCase()) {
    case "ALLQ":
      return [
        { key: "symbol", label: "Bond", hint: "US10Y" },
        { key: "mid", label: "Mid", hint: "99.75" },
        { key: "spread", label: "Spread", hint: "0.18" },
        { key: "size", label: "Size", hint: "1000000" },
      ];
    case "CHGS":
    case "TECH":
      return [
        { key: "interval", label: "Interval", hint: "1m/5m/15m/1h/4h/1d" },
        { key: "bars", label: "Bars", hint: "1000/3000/10000" },
        { key: "rsi_period", label: "RSI", hint: "14" },
        { key: "sma_fast", label: "SMA fast", hint: "20" },
        { key: "sma_slow", label: "SMA slow", hint: "50" },
        { key: "ema_period", label: "EMA", hint: "20" },
        { key: "bb_period", label: "BB period", hint: "20" },
        { key: "bb_std", label: "BB stdev", hint: "2" },
      ];
    case "BGAS":
    case "NGAS":
      return [
        { key: "contract", label: "Contract", hint: "NG=F" },
      ];
    case "BETA":
      return [
        { key: "benchmark", label: "Benchmark", hint: "SPY" },
        { key: "windows", label: "Windows", hint: "1Y,2Y,5Y" },
        { key: "rolling_window", label: "Rolling", hint: "60" },
      ];
    case "DCF":
      return [
        { key: "years", label: "Years", hint: "5" },
        { key: "growth_high", label: "Growth", hint: "0.08" },
        { key: "growth_terminal", label: "Terminal g", hint: "0.025" },
        { key: "wacc", label: "WACC", hint: "0.09" },
        { key: "fcfe", label: "FCFE", hint: "100000000000" },
        { key: "shares_outstanding", label: "Shares", hint: "15000000000" },
      ];
    case "DCFS":
      return [
        { key: "years", label: "Years", hint: "5" },
        { key: "growth_high", label: "Growth", hint: "0.08" },
        { key: "wacc", label: "Base WACC", hint: "0.09" },
        { key: "fcfe", label: "FCFE", hint: "100000000000" },
        { key: "shares_outstanding", label: "Shares", hint: "15000000000" },
      ];
    case "DDM":
      return [
        { key: "dividend_ttm", label: "DPS TTM", hint: "1.04" },
        { key: "growth_rate", label: "Growth", hint: "0.03" },
        { key: "required_return", label: "Req return", hint: "0.08" },
      ];
    case "WACC":
      return [
        { key: "erp", label: "ERP", hint: "0.05" },
        { key: "tax_rate", label: "Tax", hint: "0.21" },
        { key: "rf", label: "Risk-free", hint: "0.04" },
        { key: "rd", label: "Debt cost", hint: "0.05" },
        { key: "beta", label: "Beta", hint: "1.1" },
      ];
    case "EE":
      return [
        { key: "history", label: "Periods", hint: "8" },
      ];
    case "FTS":
      return [
        { key: "forms", label: "Forms", hint: "10-K,10-Q" },
        { key: "start", label: "From", hint: "2025-01-01" },
        { key: "end", label: "To", hint: "2026-05-03" },
      ];
    case "FRD":
      return [
        { key: "spot", label: "Spot", hint: "blank = live" },
        { key: "r_base", label: "Base rate", hint: "0.035" },
        { key: "r_quote", label: "Quote rate", hint: "0.045" },
        { key: "tenors", label: "Tenors", hint: "1W,1M,3M,6M,1Y" },
      ];
    case "FXFC":
      return [
        { key: "spot", label: "Spot", hint: "blank = live" },
        { key: "r_base", label: "Base rate", hint: "0.035" },
        { key: "r_quote", label: "Quote rate", hint: "0.045" },
        { key: "vol_annualized", label: "Ann vol", hint: "0.085" },
        { key: "tenors", label: "Tenors", hint: "1M,3M,6M,12M" },
      ];
    case "FXH":
      return [
        { key: "currency", label: "Exposure ccy", hint: "EUR" },
        { key: "home_currency", label: "Home ccy", hint: "USD" },
        { key: "notional", label: "Notional", hint: "1000000" },
        { key: "hedge_ratio", label: "Hedge", hint: "0.75" },
        { key: "days", label: "Days", hint: "90" },
        { key: "usd_shock_pct", label: "Shock", hint: "0.05" },
      ];
    case "FXIP":
      return [
        { key: "spot", label: "Spot", hint: "blank = live" },
        { key: "r_base", label: "Base rate", hint: "0.035" },
        { key: "r_quote", label: "Quote rate", hint: "0.045" },
        { key: "atm_vol", label: "ATM vol", hint: "0.0845" },
      ];
    case "OVDV":
      return [
        { key: "atm_vol", label: "ATM vol", hint: "0.085" },
        { key: "rr_25d", label: "25D RR", hint: "0.002" },
        { key: "bf_25d", label: "25D BF", hint: "0.0015" },
        { key: "tenors", label: "Tenors", hint: "1W,1M,3M,6M,1Y" },
      ];
    case "COUN":
      return [
        { key: "country", label: "Country", hint: "US/EU/GB/TR" },
      ];
    case "ECFC":
      return [
        { key: "country", label: "Country", hint: "USA" },
        { key: "indicators", label: "Indicators", hint: "NGDP_RPCH,PCPIPCH,LUR" },
      ];
    case "ECST":
      return [
        { key: "series_id", label: "Series", hint: "CPIAUCSL/GDPC1/UNRATE/DGS10" },
        { key: "frequency", label: "Frequency", hint: "monthly/quarterly" },
      ];
    case "GMM":
      return [
        { key: "country", label: "Country", hint: "blank = global" },
        { key: "importance", label: "Importance", hint: "all/high/medium" },
      ];
    case "REGM":
      return [
        { key: "action", label: "Mode", hint: "current/history" },
        { key: "days", label: "Days", hint: "1095" },
        { key: "window", label: "Window", hint: "60" },
      ];
    case "TRDH":
      return [
        { key: "exchanges", label: "Exchanges", hint: "NYSE,NASDAQ,LSE,TYO" },
      ];
    case "WIRP":
      return [
        { key: "central_bank", label: "Central bank", hint: "FED/ECB/BOE" },
        { key: "meetings", label: "Meetings", hint: "4" },
      ];
    case "BIO":
      return [
        { key: "reason", label: "Reason", hint: "ShowMe biometric verification" },
      ];
    case "BMC":
      return [
        { key: "module", label: "Module", hint: "Equities / Fixed Income / FX / Macro" },
      ];
    case "CDE":
      return [
        { key: "action", label: "Action", hint: "list/add/remove/evaluate" },
        { key: "name", label: "Name", hint: "large_cap_tech" },
        { key: "formula", label: "Formula", hint: 'sector = "Technology" AND marketCap > 50000000000' },
        { key: "row_json", label: "Row JSON", hint: '{"sector":"Technology","marketCap":100000000000}' },
      ];
    case "DINE":
      return [
        { key: "location", label: "Location", hint: "New York / Istanbul / London" },
        { key: "query", label: "Search", hint: "restaurant, sushi, coffee" },
      ];
    case "FLY":
      return [
        { key: "callsign", label: "Callsign", hint: "THY / UAL / blank = any" },
        { key: "country", label: "Country", hint: "Turkey / United States / blank = any" },
      ];
    case "GRAB":
      return [
        { key: "url", label: "Target", hint: "current_pane or URL" },
        { key: "recipient", label: "Recipient", hint: "draft only; sending requires confirmation" },
      ];
    case "LANG":
      return [
        { key: "lang", label: "Language", hint: "tr/en/de/fr/es/it/pt/ru/zh/ja/ko/ar" },
      ];
    case "ONCH":
      return [
        { key: "symbol", label: "Asset", hint: "BTCUSDT/ETHUSDT" },
        { key: "chain", label: "Chain", hint: "BTC/ETH" },
      ];
    case "POLY":
      return [
        { key: "include_closed", label: "Closed", hint: "false/true" },
      ];
    case "WHAL":
      return [
        { key: "symbol", label: "Symbol", hint: "BTCUSDT / AAPL / EURUSD / GC=F" },
        { key: "market", label: "Market", hint: "CRYPTO/EQUITY/ETF/FX/COMMODITY/INDEX" },
        { key: "chain", label: "Chain", hint: "BTC/ETH/SOL/BNB" },
        { key: "threshold_usd", label: "Threshold USD", hint: "1000000" },
        { key: "lookback_hours", label: "Lookback h", hint: "24" },
        { key: "interval", label: "Interval", hint: "1m/5m/15m/1d" },
      ];
    case "HFS":
      return [
        { key: "issuer", label: "Issuer", hint: "AAPL" },
        { key: "cusip", label: "CUSIP", hint: "037833100" },
        { key: "quarter", label: "Quarter", hint: "latest" },
        { key: "top_n", label: "Top", hint: "30" },
      ];
    case "RV":
      return [
        { key: "peers", label: "Peers", hint: "MSFT, GOOGL, NVDA, META" },
      ];
    case "BOIL":
      return [
        { key: "benchmark", label: "Benchmark", hint: "WTI/BRENT" },
      ];
    case "CPF":
      return [
        { key: "commodities", label: "Commodities", hint: "oil, gas, gold, copper" },
        { key: "scenario", label: "Scenario", hint: "baseline/upside/downside" },
        { key: "horizon_years", label: "Horizon", hint: "4" },
      ];
    case "WETR":
      return [
        { key: "days", label: "Days", hint: "7" },
        { key: "location", label: "Location", hint: "US_NORTHEAST" },
        { key: "commodity", label: "Commodity", hint: "natural gas and power demand" },
        { key: "lat", label: "Lat", hint: "41.01" },
        { key: "lon", label: "Lon", hint: "-74.0" },
      ];
    case "CRPR":
      return [
        { key: "issuer", label: "Issuer", hint: "US Treasury" },
      ];
    case "CRVF":
    case "GC3D":
      return [
        { key: "country", label: "Country", hint: "US" },
      ];
    case "DDIS":
      return [
        { key: "issuer", label: "Issuer", hint: "AAPL" },
      ];
    case "DEBT":
      return [
        { key: "countries", label: "Countries", hint: "US, JP, DE, TR" },
      ];
    case "SRSK":
      return [
        { key: "countries", label: "Countries", hint: "TR, US, DE, JP" },
        { key: "recovery", label: "Recovery", hint: "0.4" },
        { key: "proxy_spread_pct", label: "Fallback spread", hint: "3.25" },
      ];
    case "TAUC":
      return [
        { key: "action", label: "Action", hint: "upcoming/recent" },
        { key: "security_type", label: "Type", hint: "Bill/Note/Bond" },
      ];
    case "WB":
      return [
        { key: "countries", label: "Countries", hint: "US, DE, JP, GB, FR, IT, ES, AU" },
      ];
    case "YAS":
      return [
        { key: "price", label: "Price", hint: "99.5" },
        { key: "coupon", label: "Coupon", hint: "4.25 or 0.0425" },
        { key: "maturity_years", label: "Years", hint: "10" },
        { key: "freq", label: "Freq", hint: "2" },
        { key: "benchmark_rate", label: "Benchmark", hint: "4.45 or 0.0445" },
      ];
    case "ISIN":
      return [
        { key: "id_type", label: "ID Type", hint: "AUTO/TICKER/ID_ISIN/ID_CUSIP/ID_SEDOL" },
      ];
    case "PCAS":
      return [
        { key: "pc_index", label: "PC", hint: "0" },
        { key: "k_sigma", label: "K sigma", hint: "3" },
        { key: "top_n", label: "Top", hint: "8" },
      ];
    case "PVAR":
      return [
        { key: "confidence", label: "Confidence", hint: "0.95" },
        { key: "max_positions", label: "Positions", hint: "12" },
      ];
    case "PSC":
      return [
        { key: "account", label: "Account $", hint: "10000" },
        { key: "risk_pct", label: "Risk %", hint: "0.01" },
        { key: "entry", label: "Entry", hint: "100" },
        { key: "stop", label: "Stop", hint: "95" },
        { key: "target", label: "Target", hint: "115" },
        { key: "win_rate", label: "Win rate", hint: "0.55" },
      ];
    case "PORT_WHATIF":
      return [
        { key: "quantity", label: "Qty", hint: "1" },
        { key: "cost", label: "Cost", hint: "100" },
      ];
    case "REBA":
      return [
        { key: "targets", label: "Targets", hint: "AAPL:0.5, MSFT:0.3, GOOGL:0.2" },
        { key: "min_drift_pct", label: "Min drift", hint: "0.005" },
      ];
    case "STRS":
      return [
        { key: "scenarios", label: "Scenarios", hint: "GFC_2008, COVID_2020, RATE_SHOCK_300BP" },
        { key: "scale", label: "Scale", hint: "1" },
      ];
    case "TLH":
      return [
        { key: "tax_bracket", label: "Tax rate", hint: "0.24" },
        { key: "lt_cap_rate", label: "LT rate", hint: "0.15" },
        { key: "max_positions", label: "Positions", hint: "10" },
      ];
    case "LOTS":
      return [
        { key: "action", label: "Action", hint: "list/open/sell/summary" },
        { key: "symbol", label: "Symbol", hint: "AAPL" },
        { key: "quantity", label: "Qty", hint: "1" },
        { key: "price", label: "Price", hint: "100" },
        { key: "method", label: "Method", hint: "FIFO" },
      ];
    case "MGN":
      return [
        { key: "cash", label: "Cash", hint: "10000" },
        { key: "margin_type", label: "Margin", hint: "reg_t" },
      ];
    default:
      return [];
  }
}

function defaultSimpleParamsForFunction(code: string): Record<string, string> {
  const defaults: Record<string, Record<string, string>> = {
    ALLQ: { symbol: "US10Y", mid: "99.75", spread: "0.18", size: "1000000" },
    CHGS: { rsi_period: "14", sma_fast: "20", sma_slow: "50", ema_period: "20", bb_period: "20", bb_std: "2" },
    BGAS: { contract: "NG=F" },
    NGAS: { contract: "NG=F" },
    BETA: { benchmark: "SPY", windows: "1Y,2Y,5Y", rolling_window: "60" },
    DCF: { years: "5", growth_high: "0.08", growth_terminal: "0.025", wacc: "0.09", fcfe: "", shares_outstanding: "" },
    DCFS: { years: "5", growth_high: "0.08", wacc: "0.09", fcfe: "100000000000", shares_outstanding: "15000000000" },
    DDM: { dividend_ttm: "", growth_rate: "0.03", required_return: "0.08" },
    WACC: { erp: "0.05", tax_rate: "0.21", rf: "", rd: "", beta: "" },
    EE: { history: "8" },
    FTS: { forms: "10-K,10-Q", start: "", end: "" },
    FRD: { spot: "", r_base: "0.035", r_quote: "0.045", tenors: "1W,1M,3M,6M,1Y" },
    FXFC: { spot: "", r_base: "0.035", r_quote: "0.045", vol_annualized: "0.085", tenors: "1M,3M,6M,12M" },
    FXH: { currency: "EUR", home_currency: "USD", notional: "1000000", hedge_ratio: "0.75", days: "90", usd_shock_pct: "0.05" },
    FXIP: { spot: "", r_base: "0.035", r_quote: "0.045", atm_vol: "0.0845" },
    OVDV: { atm_vol: "0.085", rr_25d: "0.002", bf_25d: "0.0015", tenors: "1W,1M,3M,6M,1Y" },
    COUN: { country: "US" },
    ECFC: { country: "USA", indicators: "NGDP_RPCH,PCPIPCH,LUR,GGXCNL_NGDP,GGXWDG_NGDP" },
    ECST: { series_id: "CPIAUCSL", frequency: "" },
    GMM: { country: "", importance: "all" },
    REGM: { action: "current", days: "1095", window: "60" },
    TRDH: { exchanges: "NYSE,NASDAQ,LSE,FWB,TYO,HKEX,ASX,BIST,BINANCE,DERIBIT" },
    WIRP: { central_bank: "FED", meetings: "4" },
    BIO: { reason: "ShowMe biometric verification" },
    BMC: { module: "" },
    CDE: {
      action: "list",
      name: "large_cap_tech",
      formula: 'sector = "Technology" AND marketCap > 50000000000',
      row_json: '{"sector":"Technology","marketCap":100000000000,"pe":21,"beta":1.1}',
    },
    DINE: { location: "New York", query: "restaurant" },
    FLY: { callsign: "", country: "" },
    GRAB: { url: "current_pane", recipient: "" },
    LANG: { lang: "tr" },
    ONCH: { symbol: "BTCUSDT", chain: "BTC" },
    POLY: { include_closed: "false" },
    WHAL: { symbol: "BTCUSDT", market: "CRYPTO", chain: "BTC", threshold_usd: "1000000", lookback_hours: "24", interval: "1m" },
    HFS: { issuer: "AAPL", cusip: "", quarter: "", top_n: "30" },
    RV: { peers: "MSFT, GOOGL, NVDA, META, AMZN, TSLA" },
    BOIL: { benchmark: "WTI/BRENT" },
    CPF: { commodities: "oil, gas, gold, copper", scenario: "baseline", horizon_years: "4" },
    WETR: { days: "7", location: "US_NORTHEAST", commodity: "natural gas and power demand", lat: "41.01", lon: "-74.0" },
    CRPR: { issuer: "US Treasury" },
    CRVF: { country: "US" },
    GC3D: { country: "US" },
    DDIS: { issuer: "AAPL" },
    DEBT: { countries: "US, JP, DE, TR" },
    SRSK: { countries: "TR, US, DE, JP", recovery: "0.4", proxy_spread_pct: "3.25" },
    TAUC: { action: "upcoming", security_type: "" },
    WB: { countries: "US, DE, JP, GB, FR, IT, ES, AU" },
    YAS: { price: "99.5", coupon: "4.25", maturity_years: "10", freq: "2", benchmark_rate: "4.45" },
    TECH: { interval: "1d", bars: "1000", rsi_period: "14", sma_fast: "20", sma_slow: "50", ema_period: "20", bb_period: "20", bb_std: "2" },
    ISIN: { id_type: "AUTO" },
    PCAS: { pc_index: "0", k_sigma: "3", top_n: "8" },
    PVAR: { confidence: "0.95", max_positions: "12" },
    PSC: { account: "10000", risk_pct: "0.01", entry: "100", stop: "95", target: "115", win_rate: "0.55" },
    PORT_WHATIF: { quantity: "1", cost: "100" },
    REBA: { targets: "AAPL:0.5, MSFT:0.3, GOOGL:0.2", min_drift_pct: "0.005" },
    STRS: { scenarios: "GFC_2008, COVID_2020, RATE_SHOCK_300BP, CRYPTO_WINTER", scale: "1" },
    TLH: { tax_bracket: "0.24", lt_cap_rate: "0.15", max_positions: "10" },
    LOTS: { action: "list", symbol: "AAPL", quantity: "1", price: "100", method: "FIFO" },
    MGN: { cash: "10000", margin_type: "reg_t" },
  };
  return defaults[code.toUpperCase()] ?? {};
}

function buildSimpleControlParams(code: string, values: Record<string, string>): Record<string, unknown> {
  const upper = code.toUpperCase();
  const numeric = (key: string, fallback: number) => numericInput(values[key] ?? "", fallback);
  if (upper === "ALLQ") {
    return {
      symbol: (values.symbol || "US10Y").trim().toUpperCase(),
      mid: numeric("mid", 99.75),
      spread: numeric("spread", 0.18),
      size: numeric("size", 1_000_000),
    };
  }
  if (upper === "CHGS" || upper === "TECH") {
    return {
      live_chart: true,
      interval: (values.interval || "1d").trim().toLowerCase(),
      bars: Math.max(60, Math.min(5000, Math.round(numeric("bars", 1000)))),
      tail: Math.max(60, Math.min(5000, Math.round(numeric("bars", 1000)))),
      rsi_period: Math.max(2, Math.round(numeric("rsi_period", 14))),
      sma_fast: Math.max(2, Math.round(numeric("sma_fast", 20))),
      sma_slow: Math.max(2, Math.round(numeric("sma_slow", 50))),
      ema_period: Math.max(2, Math.round(numeric("ema_period", 20))),
      bb_period: Math.max(2, Math.round(numeric("bb_period", 20))),
      bb_std: numeric("bb_std", 2),
    };
  }
  if (upper === "BGAS" || upper === "NGAS") {
    return { contract: (values.contract || "NG=F").trim().toUpperCase() };
  }
  if (upper === "BETA") {
    return {
      benchmark: (values.benchmark || "SPY").trim().toUpperCase(),
      windows: splitCsv(values.windows || "1Y,2Y,5Y").map((item) => item.toUpperCase()),
      rolling_window: Math.max(30, Math.round(numeric("rolling_window", 60))),
    };
  }
  if (upper === "DCF") {
    return {
      years: Math.max(1, Math.round(numeric("years", 5))),
      growth_high: numeric("growth_high", 0.08),
      growth_terminal: numeric("growth_terminal", 0.025),
      wacc: numeric("wacc", 0.09),
      ...(values.fcfe?.trim() ? { fcfe: numeric("fcfe", 0) } : {}),
      ...(values.shares_outstanding?.trim() ? { shares_outstanding: numeric("shares_outstanding", 0) } : {}),
    };
  }
  if (upper === "DCFS") {
    return {
      years: Math.max(1, Math.round(numeric("years", 5))),
      growth_high: numeric("growth_high", 0.08),
      wacc: numeric("wacc", 0.09),
      fcfe: numeric("fcfe", 100_000_000_000),
      shares_outstanding: numeric("shares_outstanding", 15_000_000_000),
      live_valuation: true,
    };
  }
  if (upper === "DDM") {
    return {
      ...(values.dividend_ttm?.trim() ? { dividend_ttm: numeric("dividend_ttm", 0) } : {}),
      growth_rate: numeric("growth_rate", 0.03),
      required_return: numeric("required_return", 0.08),
    };
  }
  if (upper === "WACC") {
    return {
      erp: numeric("erp", 0.05),
      tax_rate: numeric("tax_rate", 0.21),
      ...(values.rf?.trim() ? { rf: numeric("rf", 0.04) } : {}),
      ...(values.rd?.trim() ? { rd: numeric("rd", 0.05) } : {}),
      ...(values.beta?.trim() ? { beta: numeric("beta", 1) } : {}),
    };
  }
  if (upper === "EE") {
    return { history: Math.max(1, Math.round(numeric("history", 8))), live_earnings: true };
  }
  if (upper === "FTS") {
    return {
      forms: splitCsv(values.forms || "10-K,10-Q"),
      ...(values.start?.trim() ? { start: values.start.trim() } : {}),
      ...(values.end?.trim() ? { end: values.end.trim() } : {}),
      live_search: true,
    };
  }
  if (upper === "FRD") {
    return {
      ...(values.spot?.trim() ? { spot: numeric("spot", 1.0835) } : {}),
      r_base: numeric("r_base", 0.035),
      r_quote: numeric("r_quote", 0.045),
      tenors: splitCsv(values.tenors || "1W,1M,3M,6M,1Y"),
      live: true,
    };
  }
  if (upper === "FXFC") {
    return {
      ...(values.spot?.trim() ? { spot: numeric("spot", 1.0835) } : {}),
      r_base: numeric("r_base", 0.035),
      r_quote: numeric("r_quote", 0.045),
      vol_annualized: numeric("vol_annualized", 0.085),
      tenors: splitCsv(values.tenors || "1M,3M,6M,12M"),
      live: true,
    };
  }
  if (upper === "FXH") {
    return {
      currency: (values.currency || "EUR").trim().toUpperCase(),
      home_currency: (values.home_currency || "USD").trim().toUpperCase(),
      notional: numeric("notional", 1_000_000),
      hedge_ratio: numeric("hedge_ratio", 0.75),
      days: Math.max(1, Math.round(numeric("days", 90))),
      usd_shock_pct: numeric("usd_shock_pct", 0.05),
      live: true,
    };
  }
  if (upper === "FXIP") {
    return {
      ...(values.spot?.trim() ? { spot: numeric("spot", 1.0835) } : {}),
      r_base: numeric("r_base", 0.035),
      r_quote: numeric("r_quote", 0.045),
      atm_vol: numeric("atm_vol", 0.0845),
      days: 90,
      live: true,
    };
  }
  if (upper === "OVDV") {
    return {
      atm_vol: numeric("atm_vol", 0.085),
      rr_25d: numeric("rr_25d", 0.002),
      bf_25d: numeric("bf_25d", 0.0015),
      tenors: splitCsv(values.tenors || "1W,1M,3M,6M,1Y"),
      live: true,
    };
  }
  if (upper === "COUN") {
    return { country: (values.country || "US").trim().toUpperCase(), live_macro: true };
  }
  if (upper === "ECFC") {
    return {
      country: (values.country || "USA").trim().toUpperCase(),
      indicators: splitCsv(values.indicators || "NGDP_RPCH,PCPIPCH,LUR,GGXCNL_NGDP,GGXWDG_NGDP"),
      live_forecast: true,
    };
  }
  if (upper === "ECST") {
    const frequency = (values.frequency || "").trim();
    return {
      series_id: (values.series_id || "CPIAUCSL").trim().toUpperCase(),
      ...(frequency ? { frequency } : {}),
    };
  }
  if (upper === "GMM") {
    const country = (values.country || "").trim().toUpperCase();
    return {
      ...(country ? { country } : {}),
      importance: (values.importance || "all").trim().toLowerCase(),
      live: true,
    };
  }
  if (upper === "REGM") {
    return {
      action: (values.action || "current").trim().toLowerCase(),
      days: Math.max(120, Math.round(numeric("days", 1095))),
      window: Math.max(20, Math.round(numeric("window", 60))),
      live: true,
    };
  }
  if (upper === "TRDH") {
    return { exchanges: splitCsv(values.exchanges || "NYSE,NASDAQ,LSE,FWB,TYO,HKEX,ASX,BIST,BINANCE,DERIBIT") };
  }
  if (upper === "WIRP") {
    return {
      central_bank: (values.central_bank || "FED").trim().toUpperCase(),
      meetings: Math.max(1, Math.round(numeric("meetings", 4))),
    };
  }
  if (upper === "BIO") {
    return { reason: values.reason || "ShowMe biometric verification" };
  }
  if (upper === "BMC") {
    return { ...(values.module?.trim() ? { module: values.module.trim() } : {}) };
  }
  if (upper === "CDE") {
    return {
      action: (values.action || "list").trim().toLowerCase(),
      ...(values.name?.trim() ? { name: values.name.trim() } : {}),
      ...(values.formula?.trim() ? { formula: values.formula.trim() } : {}),
      ...(values.row_json?.trim() ? { row_json: values.row_json.trim() } : {}),
    };
  }
  if (upper === "DINE") {
    return {
      location: values.location?.trim() || "New York",
      query: values.query?.trim() || "restaurant",
      live: true,
    };
  }
  if (upper === "FLY") {
    return {
      ...(values.callsign?.trim() ? { callsign: values.callsign.trim().toUpperCase() } : {}),
      ...(values.country?.trim() ? { country: values.country.trim() } : {}),
      live_flight: true,
    };
  }
  if (upper === "GRAB") {
    return {
      url: values.url?.trim() || "current_pane",
      ...(values.recipient?.trim() ? { recipient: values.recipient.trim() } : {}),
      send: false,
    };
  }
  if (upper === "LANG") {
    return { lang: (values.lang || "tr").trim().toLowerCase() };
  }
  if (upper === "ONCH") {
    return {
      symbol: (values.symbol || "BTCUSDT").trim().toUpperCase(),
      chain: (values.chain || "BTC").trim().toUpperCase(),
      live_onchain: true,
    };
  }
  if (upper === "POLY") {
    return { include_closed: truthyInput(values.include_closed || "false") };
  }
  if (upper === "WHAL") {
    return {
      symbol: (values.symbol || "BTCUSDT").trim().toUpperCase(),
      market: (values.market || "CRYPTO").trim().toUpperCase(),
      chain: (values.chain || "BTC").trim().toUpperCase(),
      threshold_usd: numeric("threshold_usd", 1_000_000),
      lookback_hours: Math.max(1, Math.round(numeric("lookback_hours", 24))),
      interval: (values.interval || "1m").trim().toLowerCase(),
      live_onchain: true,
    };
  }
  if (upper === "HFS") {
    return {
      issuer: (values.issuer || "AAPL").trim().toUpperCase(),
      ...(values.cusip?.trim() ? { cusip: values.cusip.trim().toUpperCase() } : {}),
      ...(values.quarter?.trim() ? { quarter: values.quarter.trim() } : {}),
      top_n: Math.max(1, Math.round(numeric("top_n", 30))),
      live_holders: true,
    };
  }
  if (upper === "RV") {
    return { peers: splitCsv(values.peers || "").map((item) => item.toUpperCase()) };
  }
  if (upper === "BOIL") {
    return { benchmark: (values.benchmark || "WTI/BRENT").trim().toUpperCase() };
  }
  if (upper === "CPF") {
    return {
      commodities: splitCsv(values.commodities || "oil, gas, gold, copper"),
      scenario: (values.scenario || "baseline").trim().toLowerCase(),
      horizon_years: Math.max(1, Math.round(numeric("horizon_years", 4))),
    };
  }
  if (upper === "WETR") {
    return {
      days: Math.max(3, Math.round(numeric("days", 7))),
      location: (values.location || "US_NORTHEAST").trim().toUpperCase(),
      commodity: (values.commodity || "natural gas and power demand").trim(),
      lat: numeric("lat", 41.01),
      lon: numeric("lon", -74.0),
    };
  }
  if (upper === "CRPR") {
    return { issuer: (values.issuer || "US Treasury").trim() };
  }
  if (upper === "CRVF" || upper === "GC3D") {
    return { country: (values.country || "US").trim().toUpperCase(), live_curve: true };
  }
  if (upper === "DDIS") {
    return { issuer: (values.issuer || "AAPL").trim().toUpperCase() };
  }
  if (upper === "DEBT") {
    return { countries: splitCsv(values.countries || "US, JP, DE, TR").map((item) => item.toUpperCase()) };
  }
  if (upper === "SRSK") {
    return {
      countries: splitCsv(values.countries || "TR, US, DE, JP").map((item) => item.toUpperCase()),
      recovery: numeric("recovery", 0.4),
      proxy_spread_pct: numeric("proxy_spread_pct", 3.25),
    };
  }
  if (upper === "TAUC") {
    const securityType = (values.security_type || "").trim();
    return {
      action: (values.action || "upcoming").trim().toLowerCase(),
      ...(securityType ? { security_type: securityType } : {}),
      live_auctions: true,
    };
  }
  if (upper === "WB") {
    return { countries: splitCsv(values.countries || "US, DE, JP, GB, FR, IT, ES, AU").map((item) => item.toUpperCase()), live_bonds: true };
  }
  if (upper === "YAS") {
    return {
      price: numeric("price", 99.5),
      coupon: numeric("coupon", 4.25),
      maturity_years: numeric("maturity_years", 10),
      freq: Math.max(1, Math.round(numeric("freq", 2))),
      benchmark_rate: numeric("benchmark_rate", 4.45),
      live_benchmark: true,
    };
  }
  if (upper === "ISIN") {
    const idType = (values.id_type || "AUTO").trim().toUpperCase();
    return idType && idType !== "AUTO" ? { id_type: idType } : {};
  }
  if (upper === "PCAS") {
    return { pc_index: Math.max(0, Math.round(numeric("pc_index", 0))), k_sigma: numeric("k_sigma", 3), top_n: Math.max(1, Math.round(numeric("top_n", 8))), include_legacy: true, live_prices: true };
  }
  if (upper === "PVAR") {
    return { confidence: numeric("confidence", 0.95), max_positions: Math.max(1, Math.round(numeric("max_positions", 12))), live_risk: true };
  }
  if (upper === "PSC") {
    return { account: numeric("account", 10000), risk_pct: numeric("risk_pct", 0.01), entry: numeric("entry", 100), stop: numeric("stop", 95), target: numeric("target", 115), win_rate: numeric("win_rate", 0.55) };
  }
  if (upper === "PORT_WHATIF") {
    return { quantity: numeric("quantity", 1), cost: numeric("cost", 100) };
  }
  if (upper === "REBA") {
    return { targets: parseTargetWeights(values.targets ?? ""), min_drift_pct: numeric("min_drift_pct", 0.005), live_portfolio: true, include_legacy: true };
  }
  if (upper === "STRS") {
    return { action: "compare", scenarios: splitCsv(values.scenarios ?? ""), scale: numeric("scale", 1) };
  }
  if (upper === "TLH") {
    return { tax_bracket: numeric("tax_bracket", 0.24), lt_cap_rate: numeric("lt_cap_rate", 0.15), max_positions: Math.max(1, Math.round(numeric("max_positions", 10))), live_tax: true, include_legacy: true };
  }
  if (upper === "LOTS") {
    return {
      action: (values.action || "list").trim().toLowerCase(),
      symbol: (values.symbol || "AAPL").trim().toUpperCase(),
      quantity: numeric("quantity", 1),
      price: numeric("price", 100),
      method: (values.method || "FIFO").trim().toUpperCase(),
    };
  }
  if (upper === "MGN") {
    return { cash: numeric("cash", 10000), margin_type: values.margin_type || "reg_t", include_saved: true, include_legacy: true };
  }
  return {};
}

function parseTargetWeights(text: string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const token of text.split(",")) {
    const [rawSymbol, rawWeight] = token.split(":");
    const symbol = rawSymbol?.trim().toUpperCase();
    const weight = Number(rawWeight);
    if (symbol && Number.isFinite(weight)) out[symbol] = weight;
  }
  return Object.keys(out).length ? out : { AAPL: 0.5, MSFT: 0.3, GOOGL: 0.2 };
}

function splitCsv(text: string): string[] {
  return text.split(",").map((item) => item.trim()).filter(Boolean);
}

function numericInput(value: string, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function truthyInput(value: string): boolean {
  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
}

function defaultQueryForFunction(code: string, category?: string): string {
  switch (code.toUpperCase()) {
    case "BQL":
      return "get(close, volume) for(['AAPL','MSFT']) by(date)";
    case "DAPI":
      return "quote";
    case "FLDS":
      return "price";
    case "ISIN":
      return "AAPL";
    case "FTS":
      return "risk factors";
    case "NSE":
      return "bitcoin";
    case "BLAK":
      return "AAPL, MSFT, NVDA";
    case "BMTX":
      return "SPY, QQQ, IWM, AAPL, MSFT, TSLA, NVDA, AMZN";
    case "CORR":
      return "AAPL, SPX, EURUSD, BTCUSDT, GC=F, US10Y, CDXIG";
    case "PORT_OPT":
      return "SPY, QQQ, IWM, TLT, GLD, EFA, EEM, VNQ, DBC";
    case "RPAR":
      return "AAPL, MSFT, BTCUSDT, EURUSD, GC=F";
    case "READ":
      return "AAPL, MSFT, BTCUSDT";
    case "TOP":
    case "BRIEF":
      return "bitcoin market";
    case "NI":
      return "crypto markets";
    case "TLDR":
      return "AAPL, MSFT, BTCUSDT";
    case "FRH":
      return "BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, AVAXUSDT, LINKUSDT, TRXUSDT, DOTUSDT, MATICUSDT, ARBUSDT, OPUSDT, INJUSDT, TIAUSDT, SUIUSDT, APTUSDT, NEARUSDT, FILUSDT, ATOMUSDT, LTCUSDT, ETCUSDT, BCHUSDT, UNIUSDT";
    case "MOSS":
      return "AAPL, TSLA, NVDA, META, AMZN, MSFT, GOOGL, BTCUSDT, ETHUSDT, SOLUSDT";
    case "MARS":
      return "AAPL, MSFT, BTCUSDT, EURUSD, GC=F";
    case "TSAR":
      return "revenue guidance";
    case "TRQA":
      return "What changed in guidance?";
    case "SAT":
      return "-122.55,37.70,-122.30,37.85";
    case "ICX":
      return "SPX";
    case "SECF":
      return "technology";
    case "SRCH":
      return "yield >= 4 AND duration <= 10";
    case "FSRC":
      return "expenseRatio < 0.01 AND aum_usd > 10000000000";
    case "CSRC":
      return 'sector = "Energy"';
    case "MEET":
    case "PEOP":
      return "Apple management";
    case "POLY":
      return "crypto";
    default:
      return category?.toLowerCase() === "news" ? "market news" : "";
  }
}

function defaultRuntimeParams(code: string): Record<string, unknown> {
  switch (code.toUpperCase()) {
    case "NALRT":
      return { live: true, health: true, threshold: 70, news_timeout: 6 };
    case "BETA":
      return { benchmark: "^GSPC", live: true, yfinance_timeout: 4 };
    case "CORR":
      return {
        live: true,
        days: 365,
        return_method: "log",
        frequency: "daily",
        missing_data_policy: "pairwise",
        impactor: true,
      };
    case "GEX":
      return { live: true, live_options: true, max_expiries: 2, yfinance_timeout: 4 };
    case "HVT":
      return { live: true, live_vol: true, days: 365, yfinance_timeout: 5 };
    case "IVOL":
      return { live: true, live_options: true, max_expiries: 3, yfinance_timeout: 5 };
    case "OMON":
      return { live: true, live_options: true, yfinance_timeout: 5 };
    case "SAT":
      return { live: true, width: 512, height: 512, timeout: 8 };
    default:
      return { live: true, timeout: 4, yfinance_timeout: 4, quote_timeout: 4, news_timeout: 4 };
  }
}

function functionTimeoutMs(code: string, category?: string): number {
  const upper = code.toUpperCase();
  if (upper === "NALRT" || upper === "CN" || upper === "NI" || upper === "NSE" || upper === "TOP") {
    return 18_000;
  }
  if (category?.toLowerCase() === "news") return 18_000;
  return 35_000;
}

function paramsPlaceholder(code: string): string {
  switch (code.toUpperCase()) {
    case "BQL":
      return "{\"query\":\"get(close, volume) for(['AAPL','MSFT']) by(date)\",\"days\":90,\"live\":true}";
    case "DAPI":
      return '{"query":"portfolio"}';
    case "FLDS":
      return '{"query":"valuation","limit":25}';
    case "ISIN":
      return '{"query":"AAPL","id_type":"TICKER","limit":20}';
    case "BETA":
      return '{"benchmark":"^GSPC","windows":["1Y","2Y","5Y"]}';
    case "BLAK":
    case "RPAR":
    case "PORT_OPT":
      return '{"symbols":["AAPL","MSFT","NVDA"]}';
    case "DPF":
      return '{"weeks":12}';
    case "EQS":
      return '{"universe":"sp500","limit":25}';
    case "NSE":
      return '{"query":"BTCUSDT","limit":25}';
    case "NEWS":
    case "TOP":
      return '{"query":"AAPL","limit":10}';
    case "OVME":
      return '{"spot":100,"strike":105,"years_to_expiry":0.25,"vol":0.28,"rate":0.045,"type":"CALL"}';
    case "OSA":
      return '{"spot":100,"legs":[{"qty":1,"strike":100,"type":"CALL","expiry":0.25,"vol":0.25}]}';
    default:
      return "{}";
  }
}

function buildColumns(
  rows: RecordRow[],
  fields = rows.length ? collectFields(rows) : [],
): DataGridColumn<RecordRow>[] {
  return fields.slice(0, 14).map((field) => ({
    key: field,
    header: field,
    numeric: rows.some((row) => toFiniteNumber(row[field]) !== null),
    render: (row) => formatCellValue(field, row[field]),
  }));
}

function extractMetricCards(data: unknown): MetricCard[] {
  if (!isRecord(data)) return [];
  const cards: MetricCard[] = [];
  const seen = new Set<string>();
  const add = (label: string, value: unknown) => {
    if (seen.has(label) || !isMetricValue(value)) return;
    seen.add(label);
    cards.push({ label, value });
  };

  for (const key of METRIC_RECORD_KEYS) {
    const value = data[key];
    if (!isRecord(value)) continue;
    for (const [metricKey, metricValue] of Object.entries(value)) {
      add(metricKey, metricValue);
    }
  }

  for (const [key, value] of Object.entries(data)) {
    if (Array.isArray(value) || isRecord(value)) continue;
    if (/equity|return|sharpe|drawdown|vol|beta|alpha|score|pnl|cagr|yield|price|alert_count|ok_rate/i.test(key)) {
      add(key, value);
    }
  }

  return cards;
}

function extractMethodology(data: unknown): string | null {
  if (!isRecord(data)) return null;
  const value = data.methodology ?? data.formula ?? data.method;
  if (typeof value === "string" && value.trim()) return value.trim();
  if (Array.isArray(value)) {
    const lines = value
      .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
      .map((item) => item.trim());
    return lines.length ? lines.join("\n") : null;
  }
  return null;
}

function extractFieldDictionary(data: unknown): Array<[string, string]> {
  if (!isRecord(data)) return [];
  const value = data.field_dictionary ?? data.field_definitions ?? data.glossary;
  if (!isRecord(value)) return [];
  return Object.entries(value)
    .map<[string, string]>(([key, description]) => [
      key,
      typeof description === "string" ? description : JSON.stringify(description),
    ])
    .filter(([, description]) => description.length > 0)
    .slice(0, 16);
}

function MethodologyPanel({
  methodology,
  fields,
}: {
  methodology: string | null;
  fields: Array<[string, string]>;
}) {
  return (
    <section className="showme-card-reveal showme-stub-block" style={methodologyPanel}>
      {methodology ? (
        <div>
          <div style={metaLabel}>Methodology</div>
          <p style={methodologyText}>{methodology}</p>
        </div>
      ) : null}
      {fields.length > 0 ? (
        <div>
          <div style={metaLabel}>Field dictionary</div>
          <div style={fieldDictionaryGrid}>
            {fields.map(([field, description]) => (
              <div key={field} className="showme-row-reveal showme-stub-kv-row" style={fieldDictionaryRow}>
                <span style={{ color: "var(--text-primary)" }}>{field}</span>
                <span>{description}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function extractMediaItems(data: unknown): MediaItem[] {
  if (!isRecord(data)) return [];
  const items: MediaItem[] = [];
  const addDataUrl = (label: string, value: unknown, note?: string, isSatellite?: boolean) => {
    if (typeof value !== "string" || !value.trim()) return;
    const src = value.startsWith("data:") ? value : `data:image/png;base64,${value}`;
    items.push({ label, src, note, isSatellite });
  };
  const trueColor = data.true_color_png;
  if (isRecord(trueColor)) {
    addDataUrl(
      firstString(trueColor, ["label"]) ?? "True-color image",
      trueColor.data_url ?? trueColor.png_base64,
      "Sentinel-2 true-color output",
      true,
    );
  }
  const preview = data.preview;
  if (isRecord(preview)) {
    const previewIsSatellite = Boolean(preview.is_satellite);
    addDataUrl(
      firstString(preview, ["label"]) ?? "Preview",
      preview.data_url,
      previewIsSatellite ? undefined : "Preview only; not satellite imagery.",
      previewIsSatellite,
    );
  }
  addDataUrl("PNG image", data.png_data_url ?? data.image_data_url ?? data.png_base64, undefined, true);
  return items.slice(0, 3);
}

function extractChartSeries(data: unknown, fallbackRows: RecordRow[]): ChartSeries | null {
  const candidates = collectChartCandidates(data);
  if (fallbackRows.length > 1) candidates.push({ title: "rows", rows: fallbackRows });

  const ranked = candidates
    .map((candidate) => {
      const series = rowsToChartSeries(candidate.rows, candidate.title);
      if (!series) return null;
      const priority = CHART_KEYS.indexOf(candidate.title);
      const surfaceLike = /heat|map|surface|matrix/i.test(candidate.title);
      const score =
        (series.kind === "ohlc" ? 80 : series.kind === "curve" ? 72 : series.kind === "line" ? 60 : series.kind === "heatmap" ? 48 : 30) +
        (priority >= 0 ? 30 - priority : 0) +
        (surfaceLike && series.kind === "heatmap" ? 40 : 0) +
        (candidate.rows.length > 20 ? 12 : 0) +
        (VALUE_KEYS.includes(series.yKey) ? 10 : 0);
      return { series, score };
    })
    .filter((item): item is { series: ChartSeries; score: number } => Boolean(item))
    .sort((a, b) => b.score - a.score);

  return ranked[0]?.series ?? null;
}

function collectChartCandidates(data: unknown): Array<{ title: string; rows: RecordRow[] }> {
  const candidates: Array<{ title: string; rows: RecordRow[] }> = [];
  const visit = (value: unknown, title: string, depth: number) => {
    if (depth > 4) return;
    if (Array.isArray(value)) {
      if (value.length > 1) {
        const rows = value.map(objectify);
        if (rows.some((row) => Object.values(row).some((item) => toFiniteNumber(item) !== null))) {
          candidates.push({ title, rows });
        }
      }
      return;
    }
    if (!isRecord(value)) return;
    for (const key of CHART_KEYS) {
      if (key in value) visit(value[key], key, depth + 1);
    }
    for (const [key, nested] of Object.entries(value)) {
      if (CHART_KEYS.includes(key)) continue;
      if (Array.isArray(nested) || isRecord(nested)) visit(nested, key, depth + 1);
    }
  };
  visit(data, "payload", 0);
  return candidates;
}

function rowsToChartSeries(rows: RecordRow[], title: string): ChartSeries | null {
  if (rows.length < 2) return null;
  const fields = collectFields(rows);
  const xKey = TIME_KEYS.find((key) => fields.includes(key)) ?? null;
  const labelKey = pickLabelKey(fields);
  const numericKeys = fields.filter((field) =>
    rows.some((row) => toFiniteNumber(row[field]) !== null),
  );
  const yKey =
    VALUE_KEYS.find((key) => numericKeys.includes(key)) ??
    numericKeys.find((key) => key !== xKey) ??
    null;
  if (!yKey) return null;
  const ohlc = rowsHaveOhlc(fields);
  const timePoints = xKey ? rowsToTimePoints(rows, xKey, yKey, ohlc) : [];
  const titleLabel = title.toLowerCase() === "rows" && xKey ? humanizeKey(xKey) : humanizeKey(title);
  if (/heat|map|surface|matrix/i.test(title)) {
    const surfaceLabelKey =
      ["exchange", "market", "name", "tenor", "tenor_years", "maturity", "country", "sector", "bucket", "symbol", "scenario", "metric"].find((key) =>
        fields.includes(key),
      ) ??
      labelKey ??
      xKey;
    const points = rows
      .map((row, idx) => {
        const y = toFiniteNumber(row[yKey]);
        if (y === null) return null;
        const timeLabel = xKey ? formatAxisLabel(row[xKey], idx) : null;
        const surfaceLabel = surfaceLabelKey ? formatAxisLabel(row[surfaceLabelKey], idx) : String(idx + 1);
        const xLabel = timeLabel && surfaceLabelKey && surfaceLabelKey !== xKey
          ? `${timeLabel} · ${surfaceLabel}`
          : surfaceLabel;
        return { xLabel, y };
      })
      .filter((point): point is ChartPoint => Boolean(point));
    if (points.length >= 2) {
      return {
        kind: "heatmap",
        title: `${humanizeKey(title)} · ${humanizeKey(yKey)}`,
        rows,
        xKey: null,
        labelKey: surfaceLabelKey,
        yKey,
        points,
      };
    }
  }
  if (ohlc && timePoints.length >= 2) {
    return {
      kind: "ohlc",
      title: `${titleLabel} · OHLC`,
      rows,
      xKey,
      labelKey,
      yKey: "close",
      points: timePoints,
    };
  }
  if (timePoints.length >= 2) {
    return {
      kind: "line",
      title: `${titleLabel} · ${humanizeKey(yKey)}`,
      rows,
      xKey,
      labelKey,
      yKey,
      points: timePoints,
    };
  }
  const numericXKey =
    NUMERIC_X_KEYS.find((key) => key !== yKey && fields.includes(key) && numericKeys.includes(key)) ??
    null;
  if (numericXKey && /curve|frontier|sensitivity|pnl/i.test(title)) {
    const points: Array<ChartPoint & { x: number }> = rows
      .map((row) => {
        const x = toFiniteNumber(row[numericXKey]);
        const y = toFiniteNumber(row[yKey]);
        if (x === null || y === null) return null;
        return { x, xLabel: formatValue(x), y };
      })
      .filter((point): point is ChartPoint & { x: number } => point !== null)
      .sort((a, b) => Number(a.x) - Number(b.x));
    if (points.length >= 3) {
      return {
        kind: "curve",
        title: `${humanizeKey(title)} · ${humanizeKey(yKey)}`,
        rows,
        xKey: numericXKey,
        labelKey,
        yKey,
        points,
      };
    }
  }
  if (!labelKey) return null;
  const points = rows
    .map((row, idx) => {
      const y = toFiniteNumber(row[yKey]);
      if (y === null) return null;
      const xRaw = row[labelKey];
      return { xLabel: formatAxisLabel(xRaw, idx), y };
    })
    .filter((point): point is ChartPoint => Boolean(point));
  if (points.length < 2) return null;
  const heatmap =
    /heat|map|sector|surface|matrix/i.test(title) ||
    ["country", "sector"].includes(labelKey.toLowerCase());
  return {
    kind: heatmap ? "heatmap" : "bar",
    title: `${humanizeKey(title)} · ${humanizeKey(yKey)}`,
    rows,
    xKey: null,
    labelKey,
    yKey,
    points,
  };
}

function rowsToTimePoints(
  rows: RecordRow[],
  xKey: string,
  yKey: string,
  ohlc: boolean,
): ChartPoint[] {
  const points: Array<ChartPoint | null> = rows
    .map((row, idx) => {
      const time = normalizeChartTime(row[xKey]);
      if (!time) return null;
      if (ohlc) {
        const open = toFiniteNumber(row.open);
        const high = toFiniteNumber(row.high);
        const low = toFiniteNumber(row.low);
        const close = toFiniteNumber(row.close);
        if (open === null || high === null || low === null || close === null) return null;
        return {
          xLabel: formatAxisLabel(row[xKey], idx),
          y: close,
          time,
          open,
          high,
          low,
          close,
          volume: toFiniteNumber(row.volume) ?? undefined,
        };
      }
      const y = toFiniteNumber(row[yKey]);
      if (y === null) return null;
      return { xLabel: formatAxisLabel(row[xKey], idx), y, time };
    })
  return points
    .filter((point): point is ChartPoint => point !== null)
    .sort((a, b) => chartTimeSortValue(a.time) - chartTimeSortValue(b.time));
}

function rowsHaveOhlc(fields: string[]): boolean {
  return ["open", "high", "low", "close"].every((field) => fields.includes(field));
}

function rowsLookLikeOhlc(rows: RecordRow[]): boolean {
  return rows.length > 0 && rowsHaveOhlc(collectFields(rows));
}

function pickLabelKey(fields: string[]): string | null {
  const labels = [
    "label",
    "symbol",
    "ticker",
    "country",
    "sector",
    "scenario",
    "account",
    "pair",
    "tenor",
    "strike",
    "expiry",
    "option_type",
    "leg",
    "feature",
    "factor",
    "component",
    "risk_factor",
    "window_days",
    "name",
    "asset",
    "etf",
    "metric",
    "bucket",
    "base",
    "quote",
  ];
  return labels.find((field) => fields.includes(field)) ?? null;
}

function normalizeChartTime(value: unknown): Time | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return (value > 10_000_000_000 ? Math.floor(value / 1000) : value) as Time;
  }
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const date = new Date(trimmed);
  if (Number.isNaN(date.getTime())) return null;
  if (trimmed.includes("T")) return Math.floor(date.getTime() / 1000) as Time;
  return trimmed.slice(0, 10) as Time;
}

function chartTimeSortValue(value: Time | null | undefined): number {
  if (typeof value === "number") return value;
  if (!value) return 0;
  return Date.parse(String(value)) || 0;
}

function hasOhlcPoint(
  point: ChartPoint,
): point is ChartPoint & {
  time: Time;
  open: number;
  high: number;
  low: number;
  close: number;
} {
  return Boolean(
    point.time != null &&
      Number.isFinite(Number(point.open)) &&
      Number.isFinite(Number(point.high)) &&
      Number.isFinite(Number(point.low)) &&
      Number.isFinite(Number(point.close)),
  );
}

function hasTimePoint(point: ChartPoint): point is ChartPoint & { time: Time } {
  return point.time != null;
}

function hasVolumePoint(
  point: ChartPoint,
): point is ChartPoint & { time: Time; volume: number } {
  return point.time != null && Number.isFinite(Number(point.volume));
}

function collectFields(rows: RecordRow[]): string[] {
  const fields = new Set<string>();
  for (const row of rows.slice(0, 50)) {
    for (const key of Object.keys(row)) fields.add(key);
  }
  return [...fields];
}

function objectify(value: unknown): RecordRow {
  if (isRecord(value)) return value;
  return { value };
}

function focusLatestBars(chart: IChartApi, count: number, width: number): void {
  if (count <= 0) return;
  const visible = Math.max(80, Math.min(220, Math.floor(width / 7)));
  chart.timeScale().setVisibleLogicalRange({
    from: Math.max(0, count - visible),
    to: count + 8,
  });
}

function isRecord(value: unknown): value is RecordRow {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNestedRecord(value: unknown): boolean {
  return isRecord(value) && Object.values(value).some((item) => isRecord(item));
}

function isArticleRow(row: RecordRow): boolean {
  return Boolean(firstString(row, ["headline", "title"]) && firstString(row, ["source", "url", "link"]));
}

function firstString(row: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
  }
  return null;
}

function stripHtml(value: string): string {
  return value
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

function stripMarkdown(value: string): string {
  return value
    .replace(/\*\*/g, "")
    .replace(/`/g, "")
    .trim();
}

function asStringArray(value: unknown): string[] {
  if (typeof value === "string") return value.trim() ? [value.trim()] : [];
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter(Boolean);
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function isSyntheticText(value: unknown): boolean {
  const text = String(value ?? "").toLowerCase();
  return SYNTHETIC_MARKERS.some((marker) => text.includes(marker));
}

function isMetricValue(value: unknown): boolean {
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "string") return value.trim().length > 0 && value.length < 80;
  if (typeof value === "boolean") return true;
  return false;
}

function toFiniteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const cleaned = value.replace(/[%,$\s]/g, "");
  if (!cleaned) return null;
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatAxisLabel(value: unknown, idx: number): string {
  if (typeof value === "string" && value.trim()) {
    const date = new Date(value);
    if (!Number.isNaN(date.getTime()) && /\d{4}-\d{2}-\d{2}|T/.test(value)) {
      return date.toLocaleDateString(undefined, { month: "short", day: "2-digit" });
    }
    return value.length > 18 ? value.slice(0, 18) : value;
  }
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return String(idx + 1);
}

function humanizeKey(value: string): string {
  return value.replace(/_/g, " ");
}

function formatValue(value: unknown): string {
  if (value == null || value === "") return "-";
  if (typeof value === "number") {
    return value.toLocaleString(undefined, { maximumFractionDigits: 6 });
  }
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return `${value.length} items`;
  if (isRecord(value)) return formatRecordPreview(value);
  return String(value);
}

function formatCellValue(field: string, value: unknown): ReactNode {
  if (typeof value === "string" && /^https?:\/\//i.test(value)) {
    return (
      <a href={value} target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>
        open
      </a>
    );
  }
  if (Array.isArray(value)) return `${value.length} ${field}`;
  return formatValue(value);
}

function formatRecordPreview(value: RecordRow): string {
  const entries = Object.entries(value)
    .filter(([, item]) => item == null || ["number", "string", "boolean"].includes(typeof item))
    .slice(0, 3);
  if (!entries.length) return `${Object.keys(value).length} fields`;
  return entries.map(([key, item]) => `${key}: ${formatValue(item)}`).join(" · ");
}

function formatElapsed(ms: number | null | undefined): string {
  if (ms == null) return "-";
  if (ms < 1000) return `${ms.toFixed(0)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function formatTime(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={metricBox}>
      <div style={metaLabel}>{label}</div>
      <div style={{ color: "var(--text-primary)", fontFamily: "JetBrains Mono, monospace" }}>
        {value}
      </div>
    </div>
  );
}

const functionBody: CSSProperties = {
  display: "grid",
  gridTemplateRows: "auto auto minmax(0, 1fr)",
  minHeight: 0,
  padding: 0,
};

const commandBar: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
  gap: 10,
  alignItems: "stretch",
  padding: "12px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "rgba(255,255,255,0.018)",
  minWidth: 0,
};

const resultPane: CSSProperties = {
  padding: 14,
  overflow: "auto",
  minWidth: 0,
  minHeight: 0,
};

const functionIdentity: CSSProperties = {
  display: "grid",
  gap: 6,
  alignContent: "center",
  minWidth: 0,
};

const metaLabel: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: 10,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const codeLine: CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "center",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 13,
  fontWeight: 700,
};

const identityMeta: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  textTransform: "uppercase",
};

const symbolTools: CSSProperties = {
  display: "grid",
  gridTemplateRows: "auto auto",
  gap: 6,
  minWidth: 0,
};

const ticketControls: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(118px, 1fr))",
  gap: 8,
  alignItems: "end",
  minWidth: 0,
};

const optionStrategyControl: CSSProperties = {
  gridColumn: "span 2",
  minWidth: 0,
  maxWidth: "100%",
};

const controlInlinePanel: CSSProperties = {
  display: "grid",
  gap: 6,
  gridColumn: "1 / -1",
};

const resultMetaLine: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "6px 12px",
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  textTransform: "uppercase",
};

const quickRow: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
};

const scopeBlock: CSSProperties = {
  display: "grid",
  gap: 4,
  alignContent: "center",
  minWidth: 0,
  color: "var(--text-secondary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
};

const commandActions: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
  gap: 6,
  alignContent: "center",
};

const advancedPanel: CSSProperties = {
  display: "grid",
  gap: 8,
  padding: "10px 14px 12px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "rgba(0,0,0,0.18)",
  minWidth: 0,
};

const advancedHeader: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: 12,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
};

const metricBox: CSSProperties = {
  padding: "8px 10px",
  background: "rgba(0,0,0,0.22)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
};

const metricRibbon: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
  gap: 8,
};

const metricRibbonItem: CSSProperties = {
  display: "grid",
  gap: 4,
  padding: "8px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(255,255,255,0.018)",
  minWidth: 0,
};

const metricRibbonValue: CSSProperties = {
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 13,
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
};

const chartPanel: CSSProperties = {
  position: "relative",
  display: "grid",
  gap: 10,
  gridTemplateRows: "auto minmax(0, 1fr) auto",
  height: terminalChartHeight,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  padding: 12,
  background: "rgba(0,0,0,0.16)",
  minWidth: 0,
  overflow: "hidden",
};

const chartHeader: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  flexWrap: "wrap",
  gap: 16,
  alignItems: "start",
  minWidth: 0,
};

const chartStats: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(84px, 1fr))",
  gap: 6,
  flex: "1 1 320px",
  minWidth: 0,
  width: "min(460px, 100%)",
};

const chartSvg: CSSProperties = {
  ...terminalSvgChartStyle,
};

const lightweightChartHost: CSSProperties = {
  ...terminalChartHostStyle,
};

const heatmapGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(118px, 1fr))",
  gap: 8,
  alignContent: "start",
  minHeight: 0,
  overflow: "auto",
};

const heatmapCell: CSSProperties = {
  minHeight: 62,
  border: "1px solid rgba(255,255,255,0.08)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
  display: "grid",
  alignContent: "space-between",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  overflow: "hidden",
};

const chartAxis: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
};

const warningBox: CSSProperties = {
  padding: 10,
  border: "1px solid rgba(255,181,71,0.35)",
  background: "rgba(255,181,71,0.08)",
  color: "var(--warn)",
  borderRadius: "var(--radius-sm)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  display: "grid",
  gap: 4,
};

const statusBox: CSSProperties = {
  padding: 12,
  border: "1px solid rgba(255,181,71,0.35)",
  background: "rgba(255,181,71,0.08)",
  borderRadius: "var(--radius-sm)",
  display: "grid",
  gap: 10,
};

const compactStatusBox: CSSProperties = {
  ...statusBox,
  padding: 10,
};

const textareaStyle: CSSProperties = {
  minHeight: 68,
  resize: "vertical",
  background: "var(--bg-elev-3)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  lineHeight: 1.4,
  padding: "7px 8px",
  outline: "none",
};

const kvPanel: CSSProperties = {
  display: "grid",
  gap: 1,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  overflow: "hidden",
};

const kvRow: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "180px 1fr",
  gap: 12,
  padding: "6px 10px",
  background: "rgba(255,255,255,0.018)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
};

const newsList: CSSProperties = {
  display: "grid",
  gap: 8,
};

const methodologyPanel: CSSProperties = {
  display: "grid",
  gap: 10,
  border: "1px solid rgba(44,204,255,0.22)",
  borderRadius: "var(--radius-md)",
  padding: "10px 12px",
  background: "rgba(44,204,255,0.045)",
};

const methodologyText: CSSProperties = {
  margin: "4px 0 0",
  color: "var(--text-secondary)",
  lineHeight: 1.45,
};

const fieldDictionaryGrid: CSSProperties = {
  display: "grid",
  gap: 1,
  marginTop: 6,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  overflow: "hidden",
};

const fieldDictionaryRow: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "180px 1fr",
  gap: 12,
  padding: "6px 8px",
  background: "rgba(0,0,0,0.14)",
  color: "var(--text-secondary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
};

const briefPanel: CSSProperties = {
  display: "grid",
  gap: 8,
  border: "1px solid rgba(44,204,255,0.28)",
  borderRadius: "var(--radius-md)",
  padding: "12px 14px",
  background: "rgba(44,204,255,0.055)",
};

const briefTitle: CSSProperties = {
  margin: 0,
  color: "var(--text-primary)",
  fontSize: 18,
  lineHeight: 1.2,
};

const briefSubhead: CSSProperties = {
  margin: "4px 0 0",
  color: "var(--accent)",
  fontSize: 12,
  fontFamily: "JetBrains Mono, monospace",
  textTransform: "uppercase",
  letterSpacing: 0,
};

const briefText: CSSProperties = {
  margin: 0,
  color: "var(--text-secondary)",
  lineHeight: 1.45,
};

const briefBullet: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "10px 1fr",
  gap: 8,
  color: "var(--text-secondary)",
  lineHeight: 1.45,
};

const briefBulletMark: CSSProperties = {
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
};

const newsItem: CSSProperties = {
  display: "grid",
  gap: 6,
  padding: "10px 12px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(255,255,255,0.018)",
};

const newsTitle: CSSProperties = {
  color: "var(--text-primary)",
  fontWeight: 700,
  textDecoration: "none",
};

const sourceBadge: CSSProperties = {
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  whiteSpace: "nowrap",
};

const reasonBadge: CSSProperties = {
  color: "var(--text-secondary)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "2px 6px",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  background: "rgba(255,255,255,0.018)",
};

const newsSummary: CSSProperties = {
  margin: 0,
  color: "var(--text-secondary)",
  lineHeight: 1.45,
};

const mediaGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
  gap: 10,
};

const mediaFigure: CSSProperties = {
  margin: 0,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  overflow: "hidden",
  background: "rgba(0,0,0,0.18)",
};

const mediaImage: CSSProperties = {
  display: "block",
  width: "100%",
  aspectRatio: "16 / 9",
  objectFit: "cover",
  background: "#05080d",
};

const mediaCaption: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 10,
  padding: "8px 10px",
  color: "var(--text-primary)",
  fontSize: 11,
};

const sourceStrip: CSSProperties = {
  display: "grid",
  gap: 10,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: 10,
  background: "rgba(0,0,0,0.16)",
};

const detailsBox: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  padding: 10,
  background: "rgba(0,0,0,0.18)",
};

const preStyle: CSSProperties = {
  margin: "10px 0 0",
  maxHeight: 260,
  overflow: "auto",
  color: "var(--text-secondary)",
  fontSize: 11,
  lineHeight: 1.45,
};
