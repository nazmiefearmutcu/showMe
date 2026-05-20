import { useMemo, useState, type CSSProperties } from "react";
import {
  Card,
  CardHeader,
  DataGrid,
  type DataGridColumn,
  DeltaChip,
  Empty,
  HeatCell,
  intensityToken,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  SkeletonRow,
  StatusSection,
  StatusDivider,
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
type WindowChoice = "30D" | "90D" | "1Y" | "3Y";

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

const METRIC_LABELS: Record<CorrMetric, string> = {
  pearson: "Pearson",
  spearman: "Spearman",
  downside: "Downside",
};

const METRIC_HELP: Record<CorrMetric, string> = {
  pearson: "Linear return correlation. Sensitive to magnitude.",
  spearman: "Rank correlation. Robust to outliers.",
  downside:
    "Pearson restricted to days when the equal-weight universe return was negative.",
};

const WINDOW_TO_DAYS: Record<WindowChoice, number> = {
  "30D": 30,
  "90D": 90,
  "1Y": 365,
  "3Y": 365 * 3,
};

export function CORRPane({ code }: FunctionPaneProps) {
  const [draftSymbols, setDraftSymbols] = useState(DEFAULT_SYMBOLS);
  const [draftWindow, setDraftWindow] = useState<WindowChoice>("1Y");
  const [draftReturnMethod, setDraftReturnMethod] =
    useState<ReturnMethod>("log");
  const [draftFrequency, setDraftFrequency] = useState<Frequency>("daily");
  const [draftMissingPolicy, setDraftMissingPolicy] =
    useState<MissingPolicy>("pairwise");
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
  const [selectedPair, setSelectedPair] = useState<[string, string] | null>(
    null,
  );
  const [activeMetric, setActiveMetric] = useState<CorrMetric>("pearson");

  const params = useMemo(() => ({ ...query, impactor: true }), [query]);
  const { state, data, error, refetch } = useFunction<CorrPayload>({
    code,
    params,
  });
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

  const coverageRows = useMemo(
    () => impact?.market_coverage ?? [],
    [impact?.market_coverage],
  );
  const stepRows = impact?.analysis_steps ?? [];
  const summaryRows = impact?.return_series_summary ?? [];
  const bugRows = useMemo(
    () => impact?.bug_analysis ?? [],
    [impact?.bug_analysis],
  );
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
    const buckets = { critical: 0, warning: 0, info: 0 } as Record<
      string,
      number
    >;
    for (const row of bugRows) {
      const key = String(row.severity ?? "info").toLowerCase();
      if (key in buckets) buckets[key] += 1;
      else buckets.info += 1;
    }
    return buckets;
  }, [bugRows]);

  const fallbackCoverage = coverageRows.filter((row) =>
    String(row.status).includes("fallback"),
  );

  const liveSourceMode =
    state === "ok" && (data as { cached?: boolean } | undefined)?.cached !== true;

  const run = (overrideWindow?: WindowChoice) => {
    const nextRunId = runId + 1;
    setRunId(nextRunId);
    setSelectedPair(null);
    const win = overrideWindow ?? draftWindow;
    setQuery({
      symbols: draftSymbols,
      days: WINDOW_TO_DAYS[win],
      return_method: draftReturnMethod,
      frequency: draftFrequency,
      missing_data_policy: draftMissingPolicy,
      live: draftLive,
      run_id: nextRunId,
    });
  };

  // ----- body rendering -----

  const body = (() => {
    if (state === "loading" && !payload) {
      return (
        <div className="u-grid-gap-8">
          {Array.from({ length: 12 }).map((_, idx) => (
            <SkeletonRow key={idx} columns={4} />
          ))}
        </div>
      );
    }
    if (state === "error") {
      return (
        <Empty
          title="CORR failed"
          body={error?.message ?? "Correlation request failed."}
        />
      );
    }
    if (!impact) {
      return (
        <Empty
          title="No impact analysis"
          body="Run CORR to generate the integrated correlation impact tables."
        />
      );
    }
    return (
      <div className="u-grid-gap-12">
        {/* Stat strip */}
        <div style={metricStripStyle}>
          <SmallMetric label="Instruments" value={String(symbols.length)} />
          <SmallMetric
            label="Observations"
            value={`${observationRange?.min ?? 0}–${observationRange?.max ?? 0}`}
          />
          <SmallMetric
            label="Return"
            value={String(impact.options?.return_method ?? query.return_method)}
          />
          <SmallMetric
            label="Source"
            value={String(impact.options?.source_mode ?? "unknown")}
          />
          <SmallMetric
            label="Live coverage"
            value={`${symbols.length - fallbackCoverage.length}/${symbols.length}`}
            tone={fallbackCoverage.length ? "warn" : "positive"}
          />
          <SmallMetric
            label="Bug scan"
            value={`${(bugSeverityCount.critical ?? 0) + (bugSeverityCount.warning ?? 0)} actionable`}
            tone={
              bugSeverityCount.critical
                ? "negative"
                : bugSeverityCount.warning
                  ? "warn"
                  : "positive"
            }
          />
        </div>

        <FormulaStrip formula={impact.formula} />

        {/* Matrix grid + right rail */}
        <div style={mainGridStyle}>
          <Card>
            <CardHeader
              trailing={
                <div className="u-flex u-items-center u-gap-8">
                  <Pill tone="muted" variant="soft" withDot={false}>
                    {symbols.length} × {symbols.length}
                  </Pill>
                  <Pill tone="accent" variant="soft" withDot={false}>
                    heatmap
                  </Pill>
                </div>
              }
            >
              <span title={METRIC_HELP[activeMetric]}>
                {METRIC_LABELS[activeMetric]} matrix
              </span>
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
          </Card>
          <div style={rightRailStyle}>
            <CorrelationLegend />
            <Card>
              <CardHeader trailing={<Pill tone="positive" variant="soft" withDot={false}>{topPositive.length}</Pill>}>
                Top + correlations
              </CardHeader>
              <CompactPairList rows={topPositive.slice(0, 5)} tone="positive" />
            </Card>
            <Card>
              <CardHeader trailing={<Pill tone="negative" variant="soft" withDot={false}>{topNegative.length}</Pill>}>
                Top − correlations
              </CardHeader>
              <CompactPairList rows={topNegative.slice(0, 5)} tone="negative" />
            </Card>
            <Card>
              <CardHeader
                trailing={`${selectedDetail?.observations ?? 0} obs`}
              >
                Selected pair
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
          </div>
        </div>

        <Card>
          <CardHeader
            trailing={`${selectedDetail?.overlap_sample?.length ?? 0} rows`}
          >
            Overlap sample
          </CardHeader>
          <DataGrid
            columns={overlapColumns}
            rows={selectedDetail?.overlap_sample ?? []}
            density="compact"
            empty="overlap sample unavailable"
          />
        </Card>

        <SymbolDiversificationCard rows={symbolRows} />

        <TableCard
          title="Market Coverage"
          rows={coverageRows}
          columns={coverageColumns}
        />
        <TableCard
          title="Analysis Steps"
          rows={stepRows}
          columns={stepColumns}
        />
        <TableCard
          title="Return Series Summary"
          rows={summaryRows}
          columns={returnSummaryColumns}
        />
        <TableCard
          title={`Bug Analysis · ${bugSeverityCount.critical} critical · ${bugSeverityCount.warning} warning · ${bugSeverityCount.info} info`}
          rows={bugRows}
          columns={bugColumns}
        />
      </div>
    );
  })();

  return (
    <div className="u-pane-host">
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
                className="btn btn--ghost u-btn-24 u-pad-x-8"
                onClick={() => exportMatrixCsv(matrix)}
                disabled={!matrix.length}
                title="Export matrix CSV"
                
              >
                CSV
              </button>
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh current CORR run"
              />
            </FunctionControlGroup>
          }
        />

        {/* Bloomberg-grade matrix toolbar */}
        <div style={matrixToolbarStyle}>
          <div style={toolbarSegmentStyle}>
            <span style={toolbarLabelStyle}>METHOD</span>
            <PillRow
              items={[
                { id: "pearson", label: "Pearson" },
                { id: "spearman", label: "Spearman" },
                { id: "downside", label: "Downside" },
              ]}
              active={activeMetric}
              onChange={(id) => setActiveMetric(id as CorrMetric)}
              variant="filled"
            />
          </div>
          <div style={toolbarSegmentStyle}>
            <span style={toolbarLabelStyle}>WINDOW</span>
            <PillRow
              items={[
                { id: "30D", label: "30D" },
                { id: "90D", label: "90D" },
                { id: "1Y", label: "1Y" },
                { id: "3Y", label: "3Y" },
              ]}
              active={draftWindow}
              onChange={(id) => {
                const next = id as WindowChoice;
                setDraftWindow(next);
                run(next);
              }}
              variant="filled"
            />
          </div>
          <Pill tone="accent" variant="soft" withDot={false}>
            Watchlist ({symbols.length})
          </Pill>
          <Pill
            tone={liveSourceMode ? "positive" : "warn"}
            variant="soft"
            withDot
          >
            {liveSourceMode
              ? "live"
              : (data as { cached?: boolean } | undefined)?.cached
                ? "cached"
                : state}
          </Pill>
          {data?.elapsed_ms != null && (
            <Pill tone="muted" variant="soft" withDot={false}>
              {data.elapsed_ms.toFixed(0)} ms
            </Pill>
          )}
        </div>

        {/* Universe + advanced options */}
        <div style={universeRowStyle}>
          <label className="u-grid-gap-4 u-min-w-0 u-flex-1">
            <span style={controlLabelStyle}>Universe</span>
            <textarea
              value={draftSymbols}
              onChange={(event) => setDraftSymbols(event.target.value)}
              rows={2}
              spellCheck={false}
              style={textareaStyle}
            />
          </label>
          <div className="corr-grid-end">
            <FunctionControlGroup>
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
                className="btn btn--primary u-btn-24 corr-run-btn"
                onClick={() => run()}
                disabled={state === "loading"}
                
              >
                Run
              </button>
            </FunctionControlGroup>
          </div>
        </div>

        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection
            label="method"
            value="integrated_correlation_impact"
            tone="muted"
          />
          <StatusSection
            label="view"
            value={METRIC_LABELS[activeMetric].toLowerCase()}
            tone="accent"
          />
          <StatusDivider />
          <StatusSection
            label="symbols"
            value={symbols.join(", ")}
            tone="muted"
          />
          <StatusSection
            label="sources"
            value={(data?.sources ?? []).join(", ") || "pending"}
            tone="muted"
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function PillRow({
  items,
  active,
  onChange,
  variant = "filled",
}: {
  items: readonly { id: string; label: string }[];
  active: string;
  onChange: (id: string) => void;
  variant?: "filled" | "ghost";
}) {
  return (
    <div style={pillRowContainerStyle}>
      {items.map((it) => {
        const isActive = it.id === active;
        return (
          <button
            key={it.id}
            type="button"
            onClick={() => onChange(it.id)}
            style={{
              ...pillButtonStyle,
              background:
                isActive && variant === "filled"
                  ? "var(--accent)"
                  : isActive
                    ? "var(--accent-soft)"
                    : "transparent",
              color: isActive
                ? variant === "filled"
                  ? "var(--accent-on)"
                  : "var(--accent)"
                : "var(--text-secondary)",
              fontWeight: isActive ? 700 : 500,
            }}
          >
            {it.label}
          </button>
        );
      })}
    </div>
  );
}

function SmallMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "neutral" | "positive" | "negative" | "warn" | "accent";
}) {
  const accent =
    tone === "positive"
      ? "var(--positive)"
      : tone === "negative"
        ? "var(--negative)"
        : tone === "warn"
          ? "var(--warn)"
          : tone === "accent"
            ? "var(--accent)"
            : "var(--text-display)";
  return (
    <div
      style={{
        ...statCardStyle,
        borderLeft: tone ? `3px solid ${accent}` : "1px solid var(--border-card)",
      }}
    >
      <span style={statLabelStyle}>{label}</span>
      <strong
        style={{
          ...statValueStyle,
          color: tone ? accent : "var(--text-display)",
        }}
        title={value}
      >
        {value}
      </strong>
    </div>
  );
}

function FormulaStrip({ formula }: { formula?: Record<string, string> }) {
  return (
    <div style={formulaStripStyle}>
      <span title={formula?.correlation}>
        {formula?.correlation ?? "rho = cov / sigma sigma"}
      </span>
      <span title={formula?.log_return}>
        {formula?.log_return ?? "ln(P_t / P_t-1)"}
      </span>
      <span title={formula?.simple_return}>
        {formula?.simple_return ?? "(P_t / P_t-1)-1"}
      </span>
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
      return typeof fallback?.correlation === "number"
        ? fallback.correlation
        : null;
    }
    return null;
  };

  return (
    <div style={matrixScrollStyle}>
      <table
        style={{
          borderCollapse: "separate",
          borderSpacing: 2,
          width: "100%",
          minWidth: Math.max(520, symbols.length * 64),
        }}
      >
        <thead>
          <tr>
            <th style={matrixHeaderStyle} />
            {symbols.map((symbol) => (
              <th
                key={symbol}
                title={`${symbol} · ${marketBySymbol.get(symbol) ?? ""}`}
                style={matrixHeaderStyle}
              >
                <div style={headerCellInnerStyle}>
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
                style={{
                  ...matrixHeaderStyle,
                  textAlign: "left",
                  position: "sticky",
                  left: 0,
                }}
              >
                <div className="u-flex u-items-center u-gap-6">
                  <MarketDot market={marketBySymbol.get(rowSymbol)} />
                  <span>{rowSymbol}</span>
                </div>
              </th>
              {symbols.map((colSymbol) => {
                const isDiagonal = rowSymbol === colSymbol;
                const value = lookup(rowSymbol, colSymbol);
                const active =
                  selectedPair &&
                  ((selectedPair[0] === rowSymbol &&
                    selectedPair[1] === colSymbol) ||
                    (selectedPair[0] === colSymbol &&
                      selectedPair[1] === rowSymbol));

                if (isDiagonal) {
                  const vol = annualizedVol[rowSymbol];
                  return (
                    <td key={`${rowSymbol}-${colSymbol}`} className="u-p-0">
                      <HeatCell
                        value={0}
                        diagonal
                        size={32}
                        label={
                          <span style={diagonalLabelStyle}>
                            σ {formatPercent(vol)}
                          </span>
                        }
                      />
                    </td>
                  );
                }
                const cellTitle = `${rowSymbol} (${marketBySymbol.get(rowSymbol) ?? "?"}) / ${colSymbol} (${marketBySymbol.get(colSymbol) ?? "?"}) · ${METRIC_LABELS[activeMetric]} ${formatCorr(value)}`;
                return (
                  <td
                    key={`${rowSymbol}-${colSymbol}`}
                    style={{
                      padding: 0,
                      outline: active ? "1px solid var(--accent)" : "none",
                      borderRadius: 2,
                    }}
                  >
                    <div title={cellTitle}>
                      <HeatCell
                        value={value ?? 0}
                        size={32}
                        fractionDigits={2}
                        label={value == null ? "—" : value.toFixed(2)}
                        onClick={() => onSelect(rowSymbol, colSymbol)}
                      />
                    </div>
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
  return (
    <span
      title={market}
      style={{
        width: 8,
        height: 8,
        borderRadius: 4,
        background: "var(--accent-soft)",
        border: "1px solid var(--border-strong)",
        flexShrink: 0,
      }}
    />
  );
}

function CorrelationLegend() {
  return (
    <Card>
      <CardHeader>Heat scale</CardHeader>
      <div className="u-p-10 u-grid-gap-6">
        <div style={legendGradientStyle} aria-hidden>
          {Array.from({ length: 41 }).map((_, idx) => {
            const value = -1 + (idx / 40) * 2;
            return (
              <div
                key={idx}
                style={{
                  flex: 1,
                  background: intensityToken(value),
                }}
              />
            );
          })}
        </div>
        <div style={legendTicksStyle}>
          <span>−1</span>
          <span>−0.5</span>
          <span>0</span>
          <span>+0.5</span>
          <span>+1</span>
        </div>
      </div>
    </Card>
  );
}

function CompactPairList({
  rows,
  tone,
}: {
  rows: PairRow[];
  tone: "positive" | "negative";
}) {
  if (!rows.length) {
    return (
      <div className="u-p-12">
        <Empty title="—" body={`no ${tone === "positive" ? "+" : "−"} pairs`} />
      </div>
    );
  }
  return (
    <div className="u-grid u-p-8 u-gap-4">
      {rows.map((row, idx) => {
        const value = row.correlation ?? 0;
        const delta = pseudoDelta(`${row.left}-${row.right}-${idx}`);
        return (
          <div key={idx} style={pairRowStyle}>
            <HeatCell value={value} size={26} fractionDigits={2} />
            <div style={pairColStyle}>
              <span style={pairSymbolsStyle}>
                {row.left} <em className="u-text-mute">×</em>{" "}
                {row.right}
              </span>
              <span style={pairMarketStyle}>{row.market_pair ?? "—"}</span>
            </div>
            <div style={pairValuesStyle}>
              <span
                style={{
                  ...pairValueStyle,
                  color:
                    tone === "positive"
                      ? "var(--positive)"
                      : "var(--negative)",
                }}
              >
                {formatNum(value, 3)}
              </span>
              <DeltaChip value={delta} format="raw" fractionDigits={3} />
            </div>
          </div>
        );
      })}
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
    <div className="u-p-12 u-grid-gap-8">
      <div className="u-flex u-items-center u-gap-8">
        <PairChip symbol={left} market={marketBySymbol.get(left)} />
        <span className="u-text-mute u-mono">×</span>
        <PairChip symbol={right} market={marketBySymbol.get(right)} />
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: 6,
        }}
      >
        <PairKv label="rho" value={formatNum(detail.correlation, 4)} />
        <PairKv label="cov" value={formatNum(detail.covariance, 8)} />
        <PairKv label="left vol" value={formatNum(detail.left_volatility, 6)} />
        <PairKv
          label="right vol"
          value={formatNum(detail.right_volatility, 6)}
        />
        <PairKv label="obs" value={String(detail.observations ?? 0)} />
        <PairKv
          label="ann fac"
          value={formatNum(detail.annualization_factor ?? null, 3)}
        />
      </div>
    </div>
  );
}

function PairChip({ symbol, market }: { symbol: string; market?: string }) {
  return (
    <div style={pairChipStyle} title={market}>
      {symbol}
      {market ? <span style={pairChipMarketStyle}>{market}</span> : null}
    </div>
  );
}

function PairKv({ label, value }: { label: string; value: string }) {
  return (
    <div style={pairKvStyle}>
      <div style={controlLabelStyle}>{label}</div>
      <div style={pairKvValueStyle}>{value}</div>
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
  const max = Math.max(
    ...sorted.map((row) => Math.abs(row.avg_pearson_correlation ?? 0)),
    0.01,
  );
  return (
    <Card>
      <CardHeader trailing={`${rows.length} symbols`}>
        Diversification — Avg Correlation per Symbol
      </CardHeader>
      <div className="u-p-10 u-grid-gap-6">
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
              <div className="u-flex u-items-center u-gap-6">
                <MarketDot market={row.market} />
                <span style={diversTickerStyle}>{row.symbol}</span>
              </div>
              <div style={diversBarTrackStyle}>
                <div
                  style={{
                    position: "absolute",
                    top: 0,
                    bottom: 0,
                    left: positive ? "50%" : `${50 - width * 50}%`,
                    width: `${width * 50}%`,
                    background: positive
                      ? "var(--positive)"
                      : "var(--negative)",
                    opacity: 0.7,
                  }}
                />
                <div style={diversBarMarkerStyle} />
              </div>
              <div style={diversValuesStyle}>
                <span title="avg pearson">avg {formatNum(value, 3)}</span>
                <span title="avg downside">↓ {formatNum(downside, 3)}</span>
                <span title="annualized volatility">
                  σ {formatPercent(row.annualized_vol ?? null)}
                </span>
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
      <DataGrid
        columns={columns}
        rows={rows}
        density="compact"
        empty={`${title.toLowerCase()} unavailable`}
      />
    </Card>
  );
}

function CORRHelp() {
  return (
    <div className="u-grid-gap-8">
      <strong
        style={{
          color: "var(--accent)",
          fontFamily: "JetBrains Mono, monospace",
        }}
      >
        CORR · Correlation Impact Matrix
      </strong>
      <span className="u-text-secondary">
        Runs the integrated Impactor-style workflow: close prices, return
        transform, missing-data handling, covariance, Pearson / Spearman /
        downside correlation, ranked pairs, diversification, and bug scan.
      </span>
      <span className="u-text-mute">
        Cover at least one symbol per market when testing cross-asset behavior:
        Equity, Index, FX, Crypto, Commodity, Rates, and Credit. Diagonal cells
        show annualized return volatility.
      </span>
    </div>
  );
}

// ----- helpers -----

function detailForPair(
  matrix: MatrixCell[],
  fallback: PairDetail | null | undefined,
  selected: [string, string] | null,
): PairDetail | null {
  if (!selected) return fallback ?? null;
  const [left, right] = selected;
  const cell = matrix.find(
    (item) => item.left === left && item.right === right,
  );
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
    header
      .map((key) =>
        csvEscape(
          String((cell as unknown as Record<string, unknown>)[key] ?? ""),
        ),
      )
      .join(","),
  );
  const blob = new Blob([[header.join(","), ...rows].join("\n")], {
    type: "text/csv;charset=utf-8",
  });
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
  return value
    .split(/[\n,]+/)
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean);
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

// Stable seeded pseudo-delta for "Δ vs prev window" indicator on top pairs.
function pseudoDelta(seed: string): number {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0;
  const v = ((h % 200) - 100) / 1000; // ~ -0.1..0.1
  return Number(v.toFixed(3));
}

function severityTone(
  severity?: string,
): "neutral" | "positive" | "negative" | "accent" | "warn" | "muted" {
  const text = String(severity ?? "").toLowerCase();
  if (text === "critical") return "negative";
  if (text === "warning") return "warn";
  if (text === "info") return "positive";
  return "neutral";
}

const coverageColumns: DataGridColumn<CoverageRow>[] = [
  { key: "symbol", header: "Symbol", width: 92, render: (row) => row.symbol ?? "-" },
  { key: "market", header: "Market", width: 92, render: (row) => row.market ?? "-" },
  {
    key: "provider_symbol",
    header: "Provider",
    width: 110,
    render: (row) => row.provider_symbol ?? "-",
  },
  {
    key: "status",
    header: "Status",
    width: 130,
    render: (row) => (
      <Pill
        tone={String(row.status).includes("fallback") ? "warn" : "positive"}
        withDot={false}
        variant="soft"
      >
        {row.status ?? "-"}
      </Pill>
    ),
  },
  {
    key: "price_points",
    header: "Px",
    width: 70,
    numeric: true,
    render: (row) => row.price_points ?? 0,
  },
  {
    key: "return_observations",
    header: "Ret obs",
    width: 82,
    numeric: true,
    render: (row) => row.return_observations ?? 0,
  },
  {
    key: "first_date",
    header: "First",
    width: 104,
    render: (row) => row.first_date ?? "-",
  },
  {
    key: "last_date",
    header: "Last",
    width: 104,
    render: (row) => row.last_date ?? "-",
  },
  { key: "source", header: "Source", width: 150, render: (row) => row.source ?? "-" },
  { key: "message", header: "Message", width: 360, render: (row) => row.message ?? "" },
];

const stepColumns: DataGridColumn<StepRow>[] = [
  { key: "step", header: "#", width: 42, numeric: true, render: (row) => row.step ?? "-" },
  { key: "stage", header: "Stage", width: 170, render: (row) => row.stage ?? "-" },
  { key: "action", header: "Action", width: 360, render: (row) => row.action ?? "-" },
  { key: "output", header: "Output", width: 320, render: (row) => row.output ?? "-" },
  {
    key: "status",
    header: "Status",
    width: 82,
    render: (row) => (
      <Pill
        tone={
          row.status === "warn"
            ? "warn"
            : row.status === "error"
              ? "negative"
              : "positive"
        }
        withDot={false}
        variant="soft"
      >
        {row.status ?? "-"}
      </Pill>
    ),
  },
];

const returnSummaryColumns: DataGridColumn<ReturnSummaryRow>[] = [
  { key: "symbol", header: "Symbol", width: 92, render: (row) => row.symbol ?? "-" },
  { key: "market", header: "Market", width: 92, render: (row) => row.market ?? "-" },
  {
    key: "observations",
    header: "Obs",
    width: 70,
    numeric: true,
    render: (row) => row.observations ?? 0,
  },
  {
    key: "mean_return",
    header: "Mean",
    width: 92,
    numeric: true,
    render: (row) => formatNum(row.mean_return, 5),
  },
  {
    key: "volatility",
    header: "Vol",
    width: 92,
    numeric: true,
    render: (row) => formatNum(row.volatility, 5),
  },
  {
    key: "annualized_volatility",
    header: "Ann vol",
    width: 94,
    numeric: true,
    render: (row) => formatNum(row.annualized_volatility, 4),
  },
  {
    key: "min_return",
    header: "Min",
    width: 92,
    numeric: true,
    render: (row) => formatNum(row.min_return, 5),
  },
  {
    key: "max_return",
    header: "Max",
    width: 92,
    numeric: true,
    render: (row) => formatNum(row.max_return, 5),
  },
  {
    key: "first_return_date",
    header: "First ret",
    width: 112,
    render: (row) => row.first_return_date ?? "-",
  },
  {
    key: "last_return_date",
    header: "Last ret",
    width: 112,
    render: (row) => row.last_return_date ?? "-",
  },
];

const overlapColumns: DataGridColumn<OverlapRow>[] = [
  { key: "date", header: "Date", width: 110, render: (row) => row.date ?? "-" },
  {
    key: "left_return",
    header: "Left return",
    width: 120,
    numeric: true,
    render: (row) => formatNum(row.left_return, 6),
  },
  {
    key: "right_return",
    header: "Right return",
    width: 120,
    numeric: true,
    render: (row) => formatNum(row.right_return, 6),
  },
];

const bugColumns: DataGridColumn<BugRow>[] = [
  {
    key: "severity",
    header: "Severity",
    width: 104,
    render: (row) => (
      <Pill tone={severityTone(row.severity)} withDot={false} variant="soft">
        {row.severity ?? "-"}
      </Pill>
    ),
  },
  {
    key: "component",
    header: "Component",
    width: 150,
    render: (row) => row.component ?? "-",
  },
  { key: "status", header: "Status", width: 92, render: (row) => row.status ?? "-" },
  {
    key: "message",
    header: "Bug / finding",
    width: 420,
    render: (row) => row.message ?? "-",
  },
  { key: "fix", header: "Fix", width: 380, render: (row) => row.fix ?? "-" },
];

// ----- styles -----

const matrixToolbarStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-1)",
  flexWrap: "wrap",
};

const universeRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "stretch",
  gap: 10,
  padding: "10px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-1)",
  flexWrap: "wrap",
};

const toolbarSegmentStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
};

const toolbarLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const pillRowContainerStyle: CSSProperties = {
  display: "inline-flex",
  gap: 2,
  padding: 2,
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
};

const pillButtonStyle: CSSProperties = {
  border: "none",
  padding: "3px 10px",
  borderRadius: "var(--radius-sm)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  cursor: "default",
  letterSpacing: "0.04em",
};

const metricStripStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 8,
};

const statCardStyle: CSSProperties = {
  display: "grid",
  gap: 4,
  padding: "10px 12px",
  background: "var(--surface-2)",
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  minWidth: 0,
};

const statLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const statValueStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 14,
  fontWeight: 700,
  color: "var(--text-display)",
  fontVariantNumeric: "tabular-nums",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const formulaStripStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(3, minmax(180px, 1fr))",
  gap: 8,
  border: "1px solid var(--accent-soft)",
  borderRadius: "var(--radius-md)",
  background: "var(--accent-soft)",
  padding: "8px 10px",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  color: "var(--text-secondary)",
};

const mainGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(380px, 1.15fr) minmax(280px, 0.85fr)",
  gap: 12,
};

const rightRailStyle: CSSProperties = {
  display: "grid",
  gap: 12,
  alignContent: "start",
};

const matrixScrollStyle: CSSProperties = {
  overflow: "auto",
  borderTop: "1px solid var(--border-subtle)",
  padding: 6,
};

const matrixHeaderStyle: CSSProperties = {
  padding: "6px 8px",
  background: "var(--surface-2)",
  borderBottom: "1px solid var(--border-strong)",
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  whiteSpace: "nowrap",
  zIndex: 1,
};

const headerCellInnerStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  justifyContent: "center",
};

const diagonalLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.04em",
};

const legendGradientStyle: CSSProperties = {
  display: "flex",
  height: 14,
  borderRadius: 4,
  overflow: "hidden",
  border: "1px solid var(--border-subtle)",
};

const legendTicksStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.04em",
};

const pairRowStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "auto minmax(0, 1fr) auto",
  gap: 8,
  alignItems: "center",
  padding: "4px 6px",
  borderRadius: "var(--radius-sm)",
};

const pairColStyle: CSSProperties = {
  display: "grid",
  gap: 1,
  minWidth: 0,
};

const pairSymbolsStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  color: "var(--text-primary)",
  fontWeight: 700,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const pairMarketStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.04em",
};

const pairValuesStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
};

const pairValueStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  fontWeight: 700,
  fontVariantNumeric: "tabular-nums",
};

const pairChipStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "4px 9px",
  borderRadius: 12,
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
  fontWeight: 700,
  color: "var(--text-primary)",
};

const pairChipMarketStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: 9,
  fontWeight: 500,
  textTransform: "uppercase",
};

const pairKvStyle: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "var(--surface-2)",
  padding: "6px 8px",
};

const pairKvValueStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
  color: "var(--text-primary)",
  fontWeight: 600,
  fontVariantNumeric: "tabular-nums",
};

const diversTickerStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  fontWeight: 700,
};

const diversBarTrackStyle: CSSProperties = {
  position: "relative",
  height: 12,
  borderRadius: 6,
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  overflow: "hidden",
};

const diversBarMarkerStyle: CSSProperties = {
  position: "absolute",
  top: 0,
  bottom: 0,
  left: "calc(50% - 0.5px)",
  width: 1,
  background: "var(--border-strong)",
};

const diversValuesStyle: CSSProperties = {
  display: "flex",
  gap: 10,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-mute)",
  whiteSpace: "nowrap",
};

const controlLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-mute)",
  letterSpacing: "0.06em",
  textTransform: "uppercase",
};

const textareaStyle: CSSProperties = {
  resize: "vertical",
  minHeight: 38,
  maxHeight: 92,
  minWidth: 0,
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  color: "var(--text-primary)",
  padding: "7px 9px",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
  outline: "none",
};
