import { useMemo, useState } from "react";
import {
  Card,
  CardHeader,
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  SkeletonRow,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

type ReturnMethod = "log" | "simple";
type Frequency = "daily" | "weekly" | "monthly";
type MissingPolicy = "pairwise" | "intersection" | "forward_fill";
type CorrMetric = "pearson" | "spearman" | "downside";

interface CorrPayload {
  symbols?: string[];
  samples?: number;
  summary?: Record<string, unknown>;
  pearson?: NestedMatrix;
  spearman?: NestedMatrix;
  downside?: NestedMatrix;
  annualized_vol?: Record<string, number | null>;
  rows?: SymbolRow[];
  impactor?: ImpactPayload;
}

type NestedMatrix = Record<string, Record<string, number | null>>;

interface SymbolRow {
  symbol?: string;
  market?: string;
  annualized_vol?: number | null;
  avg_pearson_correlation?: number | null;
  avg_downside_correlation?: number | null;
  return_observations?: number;
}

interface ImpactPayload {
  label?: string;
  formula?: Record<string, string>;
  options?: Record<string, unknown>;
  provider_contract?: Record<string, unknown>;
  observation_range?: { min?: number; max?: number };
  market_coverage?: CoverageRow[];
  analysis_steps?: StepRow[];
  return_series_summary?: ReturnSummaryRow[];
  matrix?: MatrixCell[];
  heatmap_rows?: Record<string, unknown>[];
  top_positive_pairs?: PairRow[];
  top_negative_pairs?: PairRow[];
  selected_pair?: PairDetail | null;
  bug_analysis?: BugRow[];
  csv_columns?: string[];
}

interface CoverageRow {
  symbol?: string;
  name?: string;
  market?: string;
  provider_symbol?: string;
  source?: string;
  status?: string;
  price_points?: number;
  return_observations?: number;
  first_date?: string | null;
  last_date?: string | null;
  message?: string;
}

interface StepRow {
  step?: number;
  stage?: string;
  action?: string;
  output?: string;
  status?: string;
}

interface ReturnSummaryRow {
  symbol?: string;
  market?: string;
  observations?: number;
  mean_return?: number | null;
  volatility?: number | null;
  annualized_volatility?: number | null;
  min_return?: number | null;
  max_return?: number | null;
  first_return_date?: string | null;
  last_return_date?: string | null;
}

interface MatrixCell {
  y?: string;
  x?: string;
  left?: string;
  right?: string;
  market_y?: string;
  market_x?: string;
  correlation?: number | null;
  covariance?: number | null;
  observations?: number;
}

interface PairRow {
  left?: string;
  right?: string;
  market_pair?: string;
  correlation?: number | null;
  covariance?: number | null;
  observations?: number;
}

interface PairDetail extends PairRow {
  left_volatility?: number | null;
  right_volatility?: number | null;
  annualization_factor?: number;
  overlap_sample?: OverlapRow[];
}

interface OverlapRow {
  date?: string;
  left_return?: number | null;
  right_return?: number | null;
}

interface BugRow {
  function?: string;
  component?: string;
  severity?: string;
  status?: string;
  message?: string;
  fix?: string;
}

const DEFAULT_SYMBOLS = "AAPL, SPX, EURUSD, BTCUSDT, GC=F, US10Y, CDXIG";

const MARKET_TONES: Record<string, string> = {
  Equity: "rgba(43,201,255,0.18)",
  Index: "rgba(126,87,255,0.18)",
  FX: "rgba(255,200,0,0.18)",
  Crypto: "rgba(255,122,0,0.20)",
  Commodity: "rgba(255,165,0,0.18)",
  Rates: "rgba(80,200,160,0.18)",
  Credit: "rgba(220,68,72,0.18)",
};

const METRIC_LABELS: Record<CorrMetric, string> = {
  pearson: "Pearson",
  spearman: "Spearman",
  downside: "Downside",
};

const METRIC_HELP: Record<CorrMetric, string> = {
  pearson: "Linear return correlation. Sensitive to magnitude.",
  spearman: "Rank correlation. Robust to outliers.",
  downside: "Pearson restricted to days when the equal-weight universe return was negative.",
};

export function CORRPane({ code }: FunctionPaneProps) {
  const [draftSymbols, setDraftSymbols] = useState(DEFAULT_SYMBOLS);
  const [draftDays, setDraftDays] = useState(365);
  const [draftReturnMethod, setDraftReturnMethod] = useState<ReturnMethod>("log");
  const [draftFrequency, setDraftFrequency] = useState<Frequency>("daily");
  const [draftMissingPolicy, setDraftMissingPolicy] = useState<MissingPolicy>("pairwise");
  const [draftLive, setDraftLive] = useState(true);
  const [runId, setRunId] = useState(1);
  const [query, setQuery] = useState({
    symbols: DEFAULT_SYMBOLS,
    days: 365,
    return_method: "log" as ReturnMethod,
    frequency: "daily" as Frequency,
    missing_data_policy: "pairwise" as MissingPolicy,
    live: true,
    run_id: 1,
  });
  const [selectedPair, setSelectedPair] = useState<[string, string] | null>(null);
  const [activeMetric, setActiveMetric] = useState<CorrMetric>("pearson");

  const params = useMemo(() => ({ ...query, impactor: true }), [query]);
  const { state, data, error, refetch } = useFunction<CorrPayload>({ code, params });
  const payload = data?.data;
  const impact = payload?.impactor;
  const symbols = payload?.symbols ?? parseSymbols(query.symbols);
  const matrix = useMemo(() => impact?.matrix ?? [], [impact?.matrix]);
  const annualizedVol = payload?.annualized_vol ?? {};
  const symbolRows = payload?.rows ?? [];

  const matrixDicts: Record<CorrMetric, NestedMatrix> = useMemo(
    () => ({
      pearson: payload?.pearson ?? {},
      spearman: payload?.spearman ?? {},
      downside: payload?.downside ?? {},
    }),
    [payload?.pearson, payload?.spearman, payload?.downside],
  );

  const selectedDetail = useMemo(
    () => detailForPair(matrix, impact?.selected_pair, selectedPair),
    [matrix, impact?.selected_pair, selectedPair],
  );

  const coverageRows = impact?.market_coverage ?? [];
  const stepRows = impact?.analysis_steps ?? [];
  const summaryRows = impact?.return_series_summary ?? [];
  const bugRows = impact?.bug_analysis ?? [];
  const topPositive = impact?.top_positive_pairs ?? [];
  const topNegative = impact?.top_negative_pairs ?? [];
  const observationRange = impact?.observation_range;

  const marketBySymbol = useMemo(() => {
    const map = new Map<string, string>();
    for (const cell of matrix) {
      if (cell.left) map.set(cell.left, cell.market_y ?? "");
      if (cell.right) map.set(cell.right, cell.market_x ?? "");
    }
    for (const row of coverageRows) {
      if (row.symbol && row.market) map.set(row.symbol, row.market);
    }
    return map;
  }, [matrix, coverageRows]);

  const bugSeverityCount = useMemo(() => {
    const buckets = { critical: 0, warning: 0, info: 0 } as Record<string, number>;
    for (const row of bugRows) {
      const key = String(row.severity ?? "info").toLowerCase();
      if (key in buckets) buckets[key] += 1;
      else buckets.info += 1;
    }
    return buckets;
  }, [bugRows]);

  const bestPositive = topPositive[0];
  const bestNegative = topNegative[0];
  const fallbackCoverage = coverageRows.filter((row) => String(row.status).includes("fallback"));

  const run = () => {
    const nextRunId = runId + 1;
    setRunId(nextRunId);
    setSelectedPair(null);
    setQuery({
      symbols: draftSymbols,
      days: clampDays(draftDays),
      return_method: draftReturnMethod,
      frequency: draftFrequency,
      missing_data_policy: draftMissingPolicy,
      live: draftLive,
      run_id: nextRunId,
    });
  };

  const body = (() => {
    if (state === "loading" && !payload) {
      return (
        <div style={{ display: "grid", gap: 8 }}>
          {Array.from({ length: 12 }).map((_, idx) => (
            <SkeletonRow key={idx} columns={4} />
          ))}
        </div>
      );
    }
    if (state === "error") {
      return <Empty title="CORR failed" body={error?.message ?? "Correlation request failed."} />;
    }
    if (!impact) {
      return <Empty title="No impact analysis" body="Run CORR to generate the integrated correlation impact tables." />;
    }
    return (
      <div style={{ display: "grid", gap: 12 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(160px, 1fr))", gap: 8 }}>
          <MetricCard label="Instruments" value={String(symbols.length)} />
          <MetricCard label="Observations" value={`${observationRange?.min ?? 0}–${observationRange?.max ?? 0}`} />
          <MetricCard label="Return" value={String(impact.options?.return_method ?? query.return_method)} />
          <MetricCard label="Source mode" value={String(impact.options?.source_mode ?? "unknown")} />
        </div>

        <SummaryStrip
          bestPositive={bestPositive}
          bestNegative={bestNegative}
          fallbackCount={fallbackCoverage.length}
          totalSymbols={symbols.length}
          bugCounts={bugSeverityCount}
        />

        <FormulaStrip formula={impact.formula} />

        <div style={{ display: "grid", gridTemplateColumns: "minmax(380px, 1.15fr) minmax(320px, 0.85fr)", gap: 12 }}>
          <Card>
            <CardHeader
              trailing={
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <SegmentedControl
                    label="VIEW"
                    value={activeMetric}
                    options={[
                      { value: "pearson", label: METRIC_LABELS.pearson },
                      { value: "spearman", label: METRIC_LABELS.spearman },
                      { value: "downside", label: METRIC_LABELS.downside },
                    ]}
                    onChange={(value) => setActiveMetric(value as CorrMetric)}
                    title={`${METRIC_LABELS[activeMetric]}: ${METRIC_HELP[activeMetric]}`}
                  />
                  <Pill tone="accent" withDot={false}>
                    heatmap
                  </Pill>
                </div>
              }
            >
              <span title={METRIC_HELP[activeMetric]}>{METRIC_LABELS[activeMetric]} Matrix</span>
            </CardHeader>
            <MatrixHeatmap
              symbols={symbols}
              matrixDict={matrixDicts[activeMetric]}
              fallbackCells={matrix}
              activeMetric={activeMetric}
              annualizedVol={annualizedVol}
              marketBySymbol={marketBySymbol}
              selectedPair={selectedPair}
              onSelect={(left, right) => setSelectedPair([left, right])}
            />
            <CorrelationLegend />
          </Card>
          <div style={{ display: "grid", gap: 12, alignContent: "start" }}>
            <Card>
              <CardHeader trailing={`${selectedDetail?.observations ?? 0} obs`}>
                Selected Pair Detail
              </CardHeader>
              {selectedDetail ? (
                <PairDetailCard
                  detail={selectedDetail}
                  marketBySymbol={marketBySymbol}
                />
              ) : (
                <Empty title="No pair" body="Select a matrix cell." />
              )}
            </Card>
            <Card>
              <CardHeader trailing={`${selectedDetail?.overlap_sample?.length ?? 0} rows`}>
                Overlap Sample
              </CardHeader>
              <DataGrid
                columns={overlapColumns}
                rows={selectedDetail?.overlap_sample ?? []}
                density="compact"
                empty="overlap sample unavailable"
              />
            </Card>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <TableCard title="Top Positive Pairs" rows={topPositive} columns={pairColumns} />
          <TableCard title="Top Negative Pairs" rows={topNegative} columns={pairColumns} />
        </div>

        <SymbolDiversificationCard rows={symbolRows} />

        <TableCard title="Market Coverage" rows={coverageRows} columns={coverageColumns} />
        <TableCard title="Analysis Steps" rows={stepRows} columns={stepColumns} />
        <TableCard title="Return Series Summary" rows={summaryRows} columns={returnSummaryColumns} />
        <TableCard
          title={`Bug Analysis · ${bugSeverityCount.critical} critical · ${bugSeverityCount.warning} warning · ${bugSeverityCount.info} info`}
          rows={bugRows}
          columns={bugColumns}
        />
      </div>
    );
  })();

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="Correlation impact matrix"
          subtitle={`${symbols.length} symbols · ${query.frequency} · ${query.return_method} returns · ${query.missing_data_policy}`}
          help={<CORRHelp />}
          trailing={
            <FunctionControlGroup>
              <LoadStatePill state={state} />
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => exportMatrixCsv(matrix)}
                disabled={!matrix.length}
                title="Export matrix CSV"
                style={{ height: 24, padding: "0 8px" }}
              >
                CSV
              </button>
              <RefreshButton loading={state === "loading"} onClick={refetch} title="Refresh current CORR run" />
            </FunctionControlGroup>
          }
        />
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(260px, 1fr) auto",
            gap: 10,
            padding: "10px 14px",
            borderBottom: "1px solid var(--border-subtle)",
            background: "var(--bg-elev-2)",
          }}
        >
          <label style={{ display: "grid", gap: 4, minWidth: 0 }}>
            <span style={controlLabel}>Universe</span>
            <textarea
              value={draftSymbols}
              onChange={(event) => setDraftSymbols(event.target.value)}
              rows={2}
              spellCheck={false}
              style={{
                resize: "vertical",
                minHeight: 38,
                maxHeight: 92,
                minWidth: 0,
                background: "var(--bg-elev-1)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-md)",
                color: "var(--text-primary)",
                padding: "7px 9px",
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 12,
                outline: "none",
              }}
            />
          </label>
          <div style={{ display: "grid", alignContent: "end", justifyItems: "end", gap: 8 }}>
            <FunctionControlGroup>
              <label style={{ display: "grid", gap: 3 }}>
                <span style={controlLabel}>Days</span>
                <input
                  type="number"
                  min={30}
                  max={2520}
                  value={draftDays}
                  onChange={(event) => setDraftDays(Number(event.target.value))}
                  style={numberInputStyle}
                />
              </label>
              <SegmentedControl
                label="SRC"
                value={draftLive ? "live" : "ref"}
                options={[
                  { value: "live", label: "Live" },
                  { value: "ref", label: "Ref" },
                ]}
                onChange={(value) => setDraftLive(value === "live")}
              />
              <SegmentedControl
                label="RET"
                value={draftReturnMethod}
                options={[
                  { value: "log", label: "Log" },
                  { value: "simple", label: "Simple" },
                ]}
                onChange={setDraftReturnMethod}
              />
            </FunctionControlGroup>
            <FunctionControlGroup>
              <SegmentedControl
                label="FREQ"
                value={draftFrequency}
                options={[
                  { value: "daily", label: "D" },
                  { value: "weekly", label: "W" },
                  { value: "monthly", label: "M" },
                ]}
                onChange={setDraftFrequency}
              />
              <SegmentedControl
                label="MISS"
                value={draftMissingPolicy}
                options={[
                  { value: "pairwise", label: "Pair" },
                  { value: "intersection", label: "Inter" },
                  { value: "forward_fill", label: "Ffill" },
                ]}
                onChange={setDraftMissingPolicy}
              />
              <button
                type="button"
                className="btn btn--primary"
                onClick={run}
                disabled={state === "loading"}
                style={{ height: 24, minWidth: 58, padding: "0 10px" }}
              >
                Run
              </button>
            </FunctionControlGroup>
          </div>
        </div>
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <span>method · integrated_correlation_impact</span>
          <span>view · {METRIC_LABELS[activeMetric].toLowerCase()}</span>
          <span>symbols · {symbols.join(", ")}</span>
          <span>sources · {(data?.sources ?? []).join(", ") || "pending"}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        minWidth: 0,
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-md)",
        padding: "9px 10px",
        background: "var(--bg-elev-2)",
      }}
    >
      <div style={{ ...controlLabel, marginBottom: 4 }}>{label}</div>
      <div
        title={value}
        style={{
          minWidth: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          color: "var(--text-primary)",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 14,
          fontWeight: 700,
        }}
      >
        {value}
      </div>
    </div>
  );
}

function SummaryStrip({
  bestPositive,
  bestNegative,
  fallbackCount,
  totalSymbols,
  bugCounts,
}: {
  bestPositive?: PairRow;
  bestNegative?: PairRow;
  fallbackCount: number;
  totalSymbols: number;
  bugCounts: Record<string, number>;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, minmax(180px, 1fr))",
        gap: 8,
      }}
    >
      <SummaryTile
        label="Strongest +"
        value={bestPositive ? `${bestPositive.left} / ${bestPositive.right}` : "—"}
        helper={bestPositive ? `rho ${formatNum(bestPositive.correlation, 3)}` : "no positive pairs"}
        tone="positive"
      />
      <SummaryTile
        label="Strongest −"
        value={bestNegative ? `${bestNegative.left} / ${bestNegative.right}` : "—"}
        helper={bestNegative ? `rho ${formatNum(bestNegative.correlation, 3)}` : "no negative pairs"}
        tone="negative"
      />
      <SummaryTile
        label="Live coverage"
        value={`${totalSymbols - fallbackCount} / ${totalSymbols}`}
        helper={fallbackCount ? `${fallbackCount} fell back to reference` : "all live"}
        tone={fallbackCount ? "warn" : "positive"}
      />
      <SummaryTile
        label="Bug scan"
        value={`${(bugCounts.critical ?? 0) + (bugCounts.warning ?? 0)} actionable`}
        helper={`${bugCounts.critical ?? 0} critical · ${bugCounts.warning ?? 0} warning · ${bugCounts.info ?? 0} info`}
        tone={bugCounts.critical ? "negative" : bugCounts.warning ? "warn" : "positive"}
      />
    </div>
  );
}

function SummaryTile({
  label,
  value,
  helper,
  tone,
}: {
  label: string;
  value: string;
  helper: string;
  tone: "positive" | "negative" | "warn" | "neutral";
}) {
  const accent: Record<string, string> = {
    positive: "var(--positive)",
    negative: "var(--negative)",
    warn: "var(--warn)",
    neutral: "var(--accent)",
  };
  return (
    <div
      style={{
        minWidth: 0,
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-md)",
        padding: "9px 10px",
        background: "var(--bg-elev-2)",
        borderLeft: `3px solid ${accent[tone]}`,
      }}
    >
      <div style={{ ...controlLabel, marginBottom: 4 }}>{label}</div>
      <div
        style={{
          minWidth: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          color: "var(--text-primary)",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 13,
          fontWeight: 700,
        }}
        title={value}
      >
        {value}
      </div>
      <div
        style={{
          marginTop: 4,
          color: "var(--text-mute)",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 10,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
        title={helper}
      >
        {helper}
      </div>
    </div>
  );
}

function FormulaStrip({ formula }: { formula?: Record<string, string> }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(3, minmax(180px, 1fr))",
        gap: 8,
        border: "1px solid rgba(43,201,255,0.22)",
        borderRadius: "var(--radius-md)",
        background: "rgba(43,201,255,0.045)",
        padding: "8px 10px",
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 11,
        color: "var(--text-secondary)",
      }}
    >
      <span title={formula?.correlation}>{formula?.correlation ?? "rho = cov / sigma sigma"}</span>
      <span title={formula?.log_return}>{formula?.log_return ?? "ln(P_t / P_t-1)"}</span>
      <span title={formula?.simple_return}>{formula?.simple_return ?? "(P_t / P_t-1)-1"}</span>
    </div>
  );
}

function MatrixHeatmap({
  symbols,
  matrixDict,
  fallbackCells,
  activeMetric,
  annualizedVol,
  marketBySymbol,
  selectedPair,
  onSelect,
}: {
  symbols: string[];
  matrixDict: NestedMatrix;
  fallbackCells: MatrixCell[];
  activeMetric: CorrMetric;
  annualizedVol: Record<string, number | null>;
  marketBySymbol: Map<string, string>;
  selectedPair: [string, string] | null;
  onSelect: (left: string, right: string) => void;
}) {
  const fallbackByPair = useMemo(() => {
    const map = new Map<string, MatrixCell>();
    fallbackCells.forEach((cell) => {
      if (cell.y && cell.x) map.set(`${cell.y}::${cell.x}`, cell);
    });
    return map;
  }, [fallbackCells]);

  const lookup = (rowSymbol: string, colSymbol: string): number | null => {
    const fromDict = (matrixDict[rowSymbol] ?? {})[colSymbol];
    if (typeof fromDict === "number") return fromDict;
    if (activeMetric === "pearson") {
      const fallback = fallbackByPair.get(`${rowSymbol}::${colSymbol}`);
      return typeof fallback?.correlation === "number" ? fallback.correlation : null;
    }
    return null;
  };

  return (
    <div style={{ overflow: "auto", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-md)" }}>
      <table style={{ borderCollapse: "collapse", width: "100%", minWidth: Math.max(520, symbols.length * 78) }}>
        <thead>
          <tr>
            <th style={matrixHeaderStyle} />
            {symbols.map((symbol) => (
              <th key={symbol} title={`${symbol} · ${marketBySymbol.get(symbol) ?? ""}`} style={matrixHeaderStyle}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, justifyContent: "center" }}>
                  <span>{symbol}</span>
                  <MarketDot market={marketBySymbol.get(symbol)} />
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {symbols.map((rowSymbol) => (
            <tr key={rowSymbol}>
              <th
                title={`${rowSymbol} · ${marketBySymbol.get(rowSymbol) ?? ""}`}
                style={{ ...matrixHeaderStyle, textAlign: "left", position: "sticky", left: 0 }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <MarketDot market={marketBySymbol.get(rowSymbol)} />
                  <span>{rowSymbol}</span>
                </div>
              </th>
              {symbols.map((colSymbol) => {
                const isDiagonal = rowSymbol === colSymbol;
                const value = lookup(rowSymbol, colSymbol);
                const active =
                  selectedPair &&
                  ((selectedPair[0] === rowSymbol && selectedPair[1] === colSymbol) ||
                    (selectedPair[0] === colSymbol && selectedPair[1] === rowSymbol));
                if (isDiagonal) {
                  const vol = annualizedVol[rowSymbol];
                  return (
                    <td key={`${rowSymbol}-${colSymbol}`} style={{ padding: 2 }}>
                      <div
                        title={`${rowSymbol} · annualized volatility`}
                        style={{
                          width: "100%",
                          height: 26,
                          border: "1px dashed rgba(255,255,255,0.18)",
                          borderRadius: "var(--radius-sm)",
                          background: MARKET_TONES[marketBySymbol.get(rowSymbol) ?? ""] ?? "rgba(255,255,255,0.03)",
                          color: "var(--text-mute)",
                          fontFamily: "JetBrains Mono, monospace",
                          fontSize: 10,
                          fontWeight: 600,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          letterSpacing: "0.04em",
                        }}
                      >
                        σ {formatPercent(vol)}
                      </div>
                    </td>
                  );
                }
                const cellTitle = `${rowSymbol} (${marketBySymbol.get(rowSymbol) ?? "?"}) / ${colSymbol} (${marketBySymbol.get(colSymbol) ?? "?"}) · ${METRIC_LABELS[activeMetric]} ${formatCorr(value)}`;
                return (
                  <td key={`${rowSymbol}-${colSymbol}`} style={{ padding: 2, borderBottom: "1px solid rgba(255,255,255,0.045)" }}>
                    <button
                      type="button"
                      onClick={() => onSelect(rowSymbol, colSymbol)}
                      title={cellTitle}
                      style={{
                        width: "100%",
                        height: 26,
                        border: active ? "1px solid var(--accent)" : "1px solid rgba(255,255,255,0.04)",
                        borderRadius: "var(--radius-sm)",
                        background: colorForCorrelation(value),
                        color: Math.abs(value ?? 0) > 0.62 ? "#fff" : "var(--text-primary)",
                        fontFamily: "JetBrains Mono, monospace",
                        fontSize: 11,
                        fontWeight: 700,
                        cursor: "default",
                      }}
                    >
                      {formatCorr(value)}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MarketDot({ market }: { market?: string }) {
  if (!market) return null;
  const tone = MARKET_TONES[market] ?? "rgba(255,255,255,0.18)";
  return (
    <span
      title={market}
      style={{
        width: 8,
        height: 8,
        borderRadius: 4,
        background: tone,
        border: "1px solid rgba(255,255,255,0.25)",
        flexShrink: 0,
      }}
    />
  );
}

function CorrelationLegend() {
  const stops = [-1, -0.6, -0.2, 0, 0.2, 0.6, 1];
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 10px", gap: 12 }}>
      <div style={{ ...controlLabel }}>scale</div>
      <div style={{ display: "flex", flex: 1, height: 12, borderRadius: 6, overflow: "hidden", border: "1px solid var(--border-subtle)" }}>
        {Array.from({ length: 41 }).map((_, idx) => {
          const value = -1 + (idx / 40) * 2;
          return (
            <div
              key={idx}
              style={{
                flex: 1,
                background: colorForCorrelation(value),
              }}
            />
          );
        })}
      </div>
      <div style={{ display: "flex", gap: 14, fontFamily: "JetBrains Mono, monospace", fontSize: 9, color: "var(--text-mute)" }}>
        {stops.map((stop) => (
          <span key={stop}>{stop > 0 ? `+${stop}` : stop}</span>
        ))}
      </div>
    </div>
  );
}

function PairDetailCard({
  detail,
  marketBySymbol,
}: {
  detail: PairDetail;
  marketBySymbol: Map<string, string>;
}) {
  const left = detail.left ?? "";
  const right = detail.right ?? "";
  return (
    <div style={{ padding: 12, display: "grid", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <PairChip symbol={left} market={marketBySymbol.get(left)} />
        <span style={{ color: "var(--text-mute)", fontFamily: "JetBrains Mono, monospace" }}>×</span>
        <PairChip symbol={right} market={marketBySymbol.get(right)} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 6 }}>
        <PairKv label="rho" value={formatNum(detail.correlation, 4)} />
        <PairKv label="cov" value={formatNum(detail.covariance, 8)} />
        <PairKv label="left vol" value={formatNum(detail.left_volatility, 6)} />
        <PairKv label="right vol" value={formatNum(detail.right_volatility, 6)} />
        <PairKv label="obs" value={String(detail.observations ?? 0)} />
        <PairKv label="ann fac" value={formatNum(detail.annualization_factor ?? null, 3)} />
      </div>
    </div>
  );
}

function PairChip({ symbol, market }: { symbol: string; market?: string }) {
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 9px",
        borderRadius: 12,
        background: market ? MARKET_TONES[market] ?? "var(--bg-elev-2)" : "var(--bg-elev-2)",
        border: "1px solid var(--border-subtle)",
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 12,
        fontWeight: 700,
        color: "var(--text-primary)",
      }}
      title={market}
    >
      {symbol}
      {market ? (
        <span style={{ color: "var(--text-mute)", fontSize: 9, fontWeight: 500, textTransform: "uppercase" }}>
          {market}
        </span>
      ) : null}
    </div>
  );
}

function PairKv({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-sm)",
        background: "var(--bg-elev-2)",
        padding: "6px 8px",
      }}
    >
      <div style={{ ...controlLabel, marginBottom: 2 }}>{label}</div>
      <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 12, color: "var(--text-primary)", fontWeight: 600 }}>
        {value}
      </div>
    </div>
  );
}

function SymbolDiversificationCard({ rows }: { rows: SymbolRow[] }) {
  if (!rows.length) return null;
  const sorted = [...rows].sort((a, b) => {
    const av = a.avg_pearson_correlation ?? -2;
    const bv = b.avg_pearson_correlation ?? -2;
    return bv - av;
  });
  const max = Math.max(...sorted.map((row) => Math.abs(row.avg_pearson_correlation ?? 0)), 0.01);
  return (
    <Card>
      <CardHeader trailing={`${rows.length} symbols`}>Diversification — Avg Correlation per Symbol</CardHeader>
      <div style={{ padding: 10, display: "grid", gap: 6 }}>
        {sorted.map((row) => {
          const value = row.avg_pearson_correlation ?? null;
          const downside = row.avg_downside_correlation ?? null;
          const width = Math.abs(value ?? 0) / max;
          const positive = (value ?? 0) >= 0;
          return (
            <div
              key={row.symbol}
              style={{
                display: "grid",
                gridTemplateColumns: "92px minmax(0, 1fr) auto",
                gap: 10,
                alignItems: "center",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <MarketDot market={row.market} />
                <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11, fontWeight: 700 }}>
                  {row.symbol}
                </span>
              </div>
              <div
                style={{
                  position: "relative",
                  height: 12,
                  borderRadius: 6,
                  background: "var(--bg-elev-2)",
                  border: "1px solid var(--border-subtle)",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    position: "absolute",
                    top: 0,
                    bottom: 0,
                    left: positive ? "50%" : `${50 - width * 50}%`,
                    width: `${width * 50}%`,
                    background: positive ? "rgba(24,168,116,0.7)" : "rgba(220,68,72,0.7)",
                  }}
                />
                <div
                  style={{
                    position: "absolute",
                    top: 0,
                    bottom: 0,
                    left: "calc(50% - 0.5px)",
                    width: 1,
                    background: "rgba(255,255,255,0.18)",
                  }}
                />
              </div>
              <div
                style={{
                  display: "flex",
                  gap: 10,
                  fontFamily: "JetBrains Mono, monospace",
                  fontSize: 10,
                  color: "var(--text-mute)",
                  whiteSpace: "nowrap",
                }}
              >
                <span title="avg pearson">avg {formatNum(value, 3)}</span>
                <span title="avg downside">↓ {formatNum(downside, 3)}</span>
                <span title="annualized volatility">σ {formatPercent(row.annualized_vol ?? null)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function TableCard<T>({
  title,
  rows,
  columns,
}: {
  title: string;
  rows: T[];
  columns: DataGridColumn<T>[];
}) {
  return (
    <Card>
      <CardHeader trailing={`${rows.length} rows`}>{title}</CardHeader>
      <DataGrid columns={columns} rows={rows} density="compact" empty={`${title.toLowerCase()} unavailable`} />
    </Card>
  );
}

function CORRHelp() {
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <strong style={{ color: "var(--accent)", fontFamily: "JetBrains Mono, monospace" }}>
        CORR · Correlation Impact Matrix
      </strong>
      <span style={{ color: "var(--text-secondary)" }}>
        Runs the integrated Impactor-style workflow: close prices, return transform, missing-data handling,
        covariance, Pearson / Spearman / downside correlation, ranked pairs, diversification, and bug scan.
      </span>
      <span style={{ color: "var(--text-mute)" }}>
        Cover at least one symbol per market when testing cross-asset behavior: Equity, Index, FX, Crypto,
        Commodity, Rates, and Credit. Diagonal cells show annualized return volatility.
      </span>
    </div>
  );
}

function detailForPair(
  matrix: MatrixCell[],
  fallback: PairDetail | null | undefined,
  selected: [string, string] | null,
): PairDetail | null {
  if (!selected) return fallback ?? null;
  const [left, right] = selected;
  const cell = matrix.find((item) => item.left === left && item.right === right);
  if (!cell) return fallback ?? null;
  return {
    left,
    right,
    market_pair: `${cell.market_y ?? "-"} / ${cell.market_x ?? "-"}`,
    correlation: cell.correlation,
    covariance: cell.covariance,
    observations: cell.observations,
    overlap_sample: fallback?.overlap_sample ?? [],
    annualization_factor: fallback?.annualization_factor,
    left_volatility: fallback?.left_volatility,
    right_volatility: fallback?.right_volatility,
  };
}

function exportMatrixCsv(matrix: MatrixCell[]) {
  if (!matrix.length) return;
  const header = ["y", "x", "correlation", "covariance", "observations"];
  const rows = matrix.map((cell) =>
    header.map((key) => csvEscape(String((cell as unknown as Record<string, unknown>)[key] ?? ""))).join(","),
  );
  const blob = new Blob([[header.join(","), ...rows].join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "showme-corr-impact-matrix.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function csvEscape(value: string) {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

function parseSymbols(value: string) {
  return value.split(/[\n,]+/).map((item) => item.trim().toUpperCase()).filter(Boolean);
}

function clampDays(value: number) {
  if (!Number.isFinite(value)) return 365;
  return Math.max(30, Math.min(2520, Math.round(value)));
}

function formatCorr(value?: number | null) {
  return value == null || Number.isNaN(value) ? "N/A" : value.toFixed(2);
}

function formatNum(value?: number | null, digits = 4) {
  return value == null || Number.isNaN(value) ? "—" : value.toFixed(digits);
}

function formatPercent(value?: number | null) {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function colorForCorrelation(value: number | null) {
  if (value == null || Number.isNaN(value)) return "rgba(255,255,255,0.035)";
  const clamped = Math.max(-1, Math.min(1, value));
  const opacity = 0.15 + Math.abs(clamped) * 0.72;
  if (clamped >= 0) return `rgba(24, 168, 116, ${opacity})`;
  return `rgba(220, 68, 72, ${opacity})`;
}

function severityTone(severity?: string): "neutral" | "positive" | "negative" | "accent" | "warn" | "muted" {
  const text = String(severity ?? "").toLowerCase();
  if (text === "critical") return "negative";
  if (text === "warning") return "warn";
  if (text === "info") return "positive";
  return "neutral";
}

const coverageColumns: DataGridColumn<CoverageRow>[] = [
  { key: "symbol", header: "Symbol", width: 92, render: (row) => row.symbol ?? "-" },
  { key: "market", header: "Market", width: 92, render: (row) => row.market ?? "-" },
  { key: "provider_symbol", header: "Provider", width: 110, render: (row) => row.provider_symbol ?? "-" },
  { key: "status", header: "Status", width: 130, render: (row) => <Pill tone={String(row.status).includes("fallback") ? "warn" : "positive"} withDot={false}>{row.status ?? "-"}</Pill> },
  { key: "price_points", header: "Px", width: 70, numeric: true, render: (row) => row.price_points ?? 0 },
  { key: "return_observations", header: "Ret obs", width: 82, numeric: true, render: (row) => row.return_observations ?? 0 },
  { key: "first_date", header: "First", width: 104, render: (row) => row.first_date ?? "-" },
  { key: "last_date", header: "Last", width: 104, render: (row) => row.last_date ?? "-" },
  { key: "source", header: "Source", width: 150, render: (row) => row.source ?? "-" },
  { key: "message", header: "Message", width: 360, render: (row) => row.message ?? "" },
];

const stepColumns: DataGridColumn<StepRow>[] = [
  { key: "step", header: "#", width: 42, numeric: true, render: (row) => row.step ?? "-" },
  { key: "stage", header: "Stage", width: 170, render: (row) => row.stage ?? "-" },
  { key: "action", header: "Action", width: 360, render: (row) => row.action ?? "-" },
  { key: "output", header: "Output", width: 320, render: (row) => row.output ?? "-" },
  { key: "status", header: "Status", width: 82, render: (row) => <Pill tone={row.status === "warn" ? "warn" : row.status === "error" ? "negative" : "positive"} withDot={false}>{row.status ?? "-"}</Pill> },
];

const returnSummaryColumns: DataGridColumn<ReturnSummaryRow>[] = [
  { key: "symbol", header: "Symbol", width: 92, render: (row) => row.symbol ?? "-" },
  { key: "market", header: "Market", width: 92, render: (row) => row.market ?? "-" },
  { key: "observations", header: "Obs", width: 70, numeric: true, render: (row) => row.observations ?? 0 },
  { key: "mean_return", header: "Mean", width: 92, numeric: true, render: (row) => formatNum(row.mean_return, 5) },
  { key: "volatility", header: "Vol", width: 92, numeric: true, render: (row) => formatNum(row.volatility, 5) },
  { key: "annualized_volatility", header: "Ann vol", width: 94, numeric: true, render: (row) => formatNum(row.annualized_volatility, 4) },
  { key: "min_return", header: "Min", width: 92, numeric: true, render: (row) => formatNum(row.min_return, 5) },
  { key: "max_return", header: "Max", width: 92, numeric: true, render: (row) => formatNum(row.max_return, 5) },
  { key: "first_return_date", header: "First ret", width: 112, render: (row) => row.first_return_date ?? "-" },
  { key: "last_return_date", header: "Last ret", width: 112, render: (row) => row.last_return_date ?? "-" },
];

const pairColumns: DataGridColumn<PairRow>[] = [
  { key: "left", header: "Left", width: 90, render: (row) => row.left ?? "-" },
  { key: "right", header: "Right", width: 90, render: (row) => row.right ?? "-" },
  { key: "market_pair", header: "Markets", width: 150, render: (row) => row.market_pair ?? "-" },
  { key: "correlation", header: "Rho", width: 86, numeric: true, render: (row) => formatNum(row.correlation, 4) },
  { key: "covariance", header: "Cov", width: 110, numeric: true, render: (row) => formatNum(row.covariance, 8) },
  { key: "observations", header: "Obs", width: 70, numeric: true, render: (row) => row.observations ?? 0 },
];

const overlapColumns: DataGridColumn<OverlapRow>[] = [
  { key: "date", header: "Date", width: 110, render: (row) => row.date ?? "-" },
  { key: "left_return", header: "Left return", width: 120, numeric: true, render: (row) => formatNum(row.left_return, 6) },
  { key: "right_return", header: "Right return", width: 120, numeric: true, render: (row) => formatNum(row.right_return, 6) },
];

const bugColumns: DataGridColumn<BugRow>[] = [
  { key: "severity", header: "Severity", width: 104, render: (row) => <Pill tone={severityTone(row.severity)} withDot={false}>{row.severity ?? "-"}</Pill> },
  { key: "component", header: "Component", width: 150, render: (row) => row.component ?? "-" },
  { key: "status", header: "Status", width: 92, render: (row) => row.status ?? "-" },
  { key: "message", header: "Bug / finding", width: 420, render: (row) => row.message ?? "-" },
  { key: "fix", header: "Fix", width: 380, render: (row) => row.fix ?? "-" },
];

const controlLabel = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-mute)",
  letterSpacing: "0.06em",
  textTransform: "uppercase" as const,
};

const numberInputStyle = {
  width: 74,
  height: 24,
  background: "var(--bg-elev-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  color: "var(--text-primary)",
  padding: "0 7px",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
};

const matrixHeaderStyle = {
  padding: "6px 8px",
  background: "var(--bg-elev-2)",
  borderBottom: "1px solid var(--border-strong)",
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: "0.06em",
  textTransform: "uppercase" as const,
  whiteSpace: "nowrap" as const,
  zIndex: 1,
};
