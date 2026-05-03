import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
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
  "returns",
  "rows",
  "data",
];

const TIME_KEYS = ["ts", "date", "datetime", "time", "timestamp", "period"];
const VALUE_KEYS = [
  "importance_score",
  "relevance_score",
  "equity",
  "close",
  "value",
  "price",
  "return",
  "total_return",
  "drawdown",
  "pnl",
  "score",
  "y",
];
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
  const defaultRunSymbol = defaultSymbolForFunction(entry?.category ?? upperCode, assetClasses);
  const quickSymbols = quickSymbolsForFunction(entry?.category ?? upperCode, assetClasses);
  const effectiveSymbol = symbolFirst
    ? normalizeSymbolInput(inputSymbol) || defaultRunSymbol
    : "";
  const [limit, setLimit] = usePersistentOption<RowLimit>(
    `showme.stub.${upperCode}.limit`,
    ROW_LIMITS,
    50,
  );
  const [range, setRange] = usePersistentOption<StubRangeId>(
    `showme.stub.${upperCode}.range`,
    STUB_RANGE_IDS,
    "1Y",
  );
  const controlProfile = useMemo(
    () => buildControlProfile(upperCode, entry?.category),
    [upperCode, entry?.category],
  );
  const controlParams = useMemo(
    () => buildControlParams(controlProfile, limit, range),
    [controlProfile, limit, range],
  );
  const internalSymbolSync = useRef<string | null>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const controlsReady = useRef(false);

  const load = async (signal?: AbortSignal, runSymbol = effectiveSymbol) => {
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
        ...controlParams,
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
    void load(ac.signal, runSymbol).finally(() => {
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

  const summary = result ? summarizeResult(result.data) : null;
  const payloadStatus = result ? getPayloadStatus(result) : null;

  return (
    <div style={{ padding: 18, height: "100%", minHeight: 0 }}>
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
          <section style={commandBar}>
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

            {symbolFirst ? (
              <div style={symbolTools}>
                <Field
                  label="Symbol"
                  value={inputSymbol}
                  onChange={(e) => setInputSymbol(e.target.value.toUpperCase())}
                  placeholder={effectiveSymbol || "AAPL, BTCUSDT, EURUSD"}
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
            ) : (
              <div style={scopeBlock}>
                <span style={metaLabel}>Scope</span>
                <strong>
                  {entry?.category === "portfolio" ? "local portfolio" : "global"}
                </strong>
              </div>
            )}

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
            <section style={advancedPanel}>
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

          <section style={resultPane}>
            {state === "loading" ? (
              <div style={{ display: "grid", gap: 10 }}>
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
  const metricCards = useMemo(() => extractMetricCards(result.data), [result.data]);
  const displayRows = summary.rows.length ? summary.rows : (chart?.rows ?? []);
  const displayColumns = useMemo(() => buildColumns(displayRows), [displayRows]);
  const articleRows = displayRows.filter(isArticleRow);
  const hasScalarResult = metricCards.length > 0 || summary.keyValues.length > 0;
  return (
    <div style={{ display: "grid", gap: 12 }} data-testid="function-payload">
      {payloadStatus.state !== "live" ? (
        <StatusPanel status={payloadStatus} onRetry={onRetry} />
      ) : null}

      <ResultMetaLine result={result} summary={summary} />

      {metricCards.length > 0 ? <MetricRibbon metrics={metricCards} /> : null}

      {chart ? <SeriesChart series={chart} /> : null}

      {articleRows.length > 0 ? (
        <NewsList rows={articleRows} />
      ) : displayRows.length > 0 ? (
        <DataGrid
          columns={displayColumns}
          rows={displayRows.slice(0, 500)}
          rowKey={(_, idx) => idx}
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
        <section style={kvPanel}>
          {summary.keyValues.map(([key, value]) => (
            <div key={key} style={kvRow}>
              <span style={{ color: "var(--text-mute)" }}>{key}</span>
              <span style={{ color: "var(--text-primary)" }}>{formatValue(value)}</span>
            </div>
          ))}
        </section>
      )}

      <SourceStrip result={result} />

      <details style={detailsBox}>
        <summary style={{ cursor: "default", color: "var(--accent)" }}>
          Raw function payload
        </summary>
        <pre style={preStyle}>{JSON.stringify(result, null, 2)}</pre>
      </details>
    </div>
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
    controlProfile.limit ? "ROW controls the result count sent to the backend." : null,
    controlProfile.days ? "RANGE maps to the backend time horizon." : null,
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
    <section style={compact ? compactStatusBox : statusBox} data-testid="function-status-panel">
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
    <section style={newsList}>
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
          <article key={`${title}-${idx}`} style={newsItem}>
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
            {summary ? <p style={newsSummary}>{summary}</p> : null}
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

function MetricRibbon({ metrics }: { metrics: MetricCard[] }) {
  return (
    <section style={metricRibbon}>
      {metrics.slice(0, 12).map((metric) => (
        <div key={metric.label} style={metricRibbonItem}>
          <span style={metaLabel}>{humanizeKey(metric.label)}</span>
          <strong style={metricRibbonValue}>{formatValue(metric.value)}</strong>
        </div>
      ))}
    </section>
  );
}

function SeriesChart({ series }: { series: ChartSeries }) {
  const width = 1000;
  const height = 280;
  const padX = 40;
  const padY = 26;
  const values = series.points.map((point) => point.y);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const coords = series.points.map((point, idx) => {
    const x =
      padX +
      (series.points.length === 1
        ? 0
        : (idx / (series.points.length - 1)) * (width - padX * 2));
    const y = padY + ((max - point.y) / span) * (height - padY * 2);
    return { x, y };
  });
  const linePath = coords
    .map((point, idx) => `${idx === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(" ");
  const areaPath = `${linePath} L ${coords.at(-1)?.x.toFixed(2) ?? padX} ${height - padY} L ${padX} ${height - padY} Z`;
  const first = series.points[0]?.y ?? 0;
  const last = series.points.at(-1)?.y ?? 0;
  const delta = last - first;
  const stroke = delta >= 0 ? "var(--positive)" : "var(--negative)";
  const fillId = `chart-fill-${series.yKey.replace(/[^a-z0-9_-]/gi, "-")}`;
  return (
    <section style={chartPanel}>
      <div style={chartHeader}>
        <div>
          <div style={metaLabel}>Chart</div>
          <strong style={{ color: "var(--text-primary)" }}>{series.title}</strong>
        </div>
        <div style={chartStats}>
          <Metric label="last" value={formatValue(last)} />
          <Metric label="min" value={formatValue(min)} />
          <Metric label="max" value={formatValue(max)} />
          <Metric label="delta" value={formatValue(delta)} />
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={chartSvg}>
        <defs>
          <linearGradient id={fillId} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.22" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        <line x1={padX} x2={width - padX} y1={padY} y2={padY} stroke="rgba(255,255,255,0.08)" />
        <line
          x1={padX}
          x2={width - padX}
          y1={height - padY}
          y2={height - padY}
          stroke="rgba(255,255,255,0.08)"
        />
        <path d={areaPath} fill={`url(#${fillId})`} />
        <path d={linePath} fill="none" stroke={stroke} strokeWidth="3" vectorEffect="non-scaling-stroke" />
        {coords.length > 0 ? (
          <circle
            cx={coords.at(-1)?.x}
            cy={coords.at(-1)?.y}
            r="4"
            fill={stroke}
            stroke="var(--bg-elev-1)"
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />
        ) : null}
      </svg>
      <div style={chartAxis}>
        <span>{series.points[0]?.xLabel ?? "-"}</span>
        <span>{series.xKey ? `${series.xKey} / ${series.yKey}` : series.yKey}</span>
        <span>{series.points.at(-1)?.xLabel ?? "-"}</span>
      </div>
    </section>
  );
}

function SourceStrip({ result }: { result: FunctionCallResult<unknown> }) {
  const providerErrors = asStringArray(result.metadata?.provider_errors);
  return (
    <section style={sourceStrip} data-testid="function-source">
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

interface ChartSeries {
  title: string;
  rows: RecordRow[];
  xKey: string | null;
  yKey: string;
  points: Array<{ xLabel: string; y: number }>;
}

interface MetricCard {
  label: string;
  value: unknown;
}

interface PayloadStatus {
  state: "live" | "degraded" | "unavailable" | "empty";
  label: string;
  title: string;
  reasons: string[];
  actions: string[];
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
  if (status && reason) return `${status}: ${reason}`;
  return reason || status;
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
  limit: boolean;
  days: boolean;
}

const LIMIT_PARAM_CODES = new Set([
  "AIM",
  "EXEC",
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
  "BTFW",
  "BTUNE",
  "FXH",
  "GC3D",
  "PORT_OPT",
  "RPAR",
]);

const WEEKS_PARAM_CODES = new Set(["DPF"]);
const HORIZON_PARAM_CODES = new Set(["TAUC"]);

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
  return {
    limitParam,
    rangeParam,
    limit: Boolean(limitParam),
    days: Boolean(rangeParam),
  };
}

function buildControlParams(
  profile: ControlProfile,
  limit: RowLimit,
  range: StubRangeId,
): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  if (profile.limitParam) params[profile.limitParam] = limit;
  if (profile.rangeParam) {
    const days = STUB_RANGES.find((r) => r.id === range)?.days ?? 365;
    params[profile.rangeParam] =
      profile.rangeParam === "weeks" ? Math.max(4, Math.round(days / 7)) : days;
  }
  return params;
}

function defaultRuntimeParams(code: string): Record<string, unknown> {
  switch (code.toUpperCase()) {
    case "NALRT":
      return { live: true, health: true, threshold: 70, news_timeout: 6 };
    case "BETA":
      return { benchmark: "^GSPC", live: true, yfinance_timeout: 4 };
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

function extractChartSeries(data: unknown, fallbackRows: RecordRow[]): ChartSeries | null {
  const candidates = collectChartCandidates(data);
  if (fallbackRows.length > 1) candidates.push({ title: "rows", rows: fallbackRows });

  const ranked = candidates
    .map((candidate) => {
      const series = rowsToChartSeries(candidate.rows, candidate.title);
      if (!series) return null;
      const priority = CHART_KEYS.indexOf(candidate.title);
      const score =
        (priority >= 0 ? 100 - priority : 20) +
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
  const numericKeys = fields.filter((field) =>
    rows.some((row) => toFiniteNumber(row[field]) !== null),
  );
  const yKey =
    VALUE_KEYS.find((key) => numericKeys.includes(key)) ??
    numericKeys.find((key) => key !== xKey) ??
    null;
  if (!yKey) return null;
  const points = rows
    .map((row, idx) => {
      const y = toFiniteNumber(row[yKey]);
      if (y === null) return null;
      const xRaw = xKey ? row[xKey] : idx + 1;
      return { xLabel: formatAxisLabel(xRaw, idx), y };
    })
    .filter((point): point is { xLabel: string; y: number } => Boolean(point));
  if (points.length < 2) return null;
  return {
    title: `${humanizeKey(title)} · ${humanizeKey(yKey)}`,
    rows,
    xKey,
    yKey,
    points,
  };
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
  display: "grid",
  gap: 10,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  padding: 12,
  background: "rgba(0,0,0,0.16)",
  minWidth: 0,
};

const chartHeader: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 16,
  alignItems: "start",
  minWidth: 0,
};

const chartStats: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(84px, 1fr))",
  gap: 6,
  minWidth: 280,
  width: "min(460px, 100%)",
};

const chartSvg: CSSProperties = {
  width: "100%",
  height: 260,
  display: "block",
  overflow: "visible",
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
