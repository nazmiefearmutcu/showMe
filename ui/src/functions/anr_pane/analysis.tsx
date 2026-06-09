import {
  Card,
  CardBody,
  CardHeader,
  DataGrid,
  Pill,
  type DataGridColumn,
} from "@/design-system";
import type { VeryfinderOverlay } from "@/lib/veryfinder";
import type {
  ANRData,
  AnalystRow,
  BucketRow,
  SignalRow,
  SourceDetail,
  TargetRow,
  VeryfinderRunState,
} from "./_types";
import {
  formatConsensusDate,
  formatInt,
  formatMoney,
  formatPct,
  formatScore,
  formatSources,
  providerLabel,
  sourceLabel,
} from "./formatters";
import {
  analysisFlowStyle,
  analysisListRowStyle,
  analysisListStyle,
  analysisScoreLabelStyle,
  analysisScoreStyle,
  analysisStepIndexStyle,
  analysisStepStyle,
  analysisTextStyle,
  analysisTitleRowStyle,
  analysisTitleStyle,
  analysisWarningListStyle,
  twoColumnAnalysisGridStyle,
} from "./styles";
import { DistributionBars, ConsensusScoreMeter } from "./cards";
import { StatGrid, Methodology } from "./tables";
import { VeryfinderAnalysisCard } from "./veryfinder";

export function ANRAnalysisScreen({
  data,
  symbol,
  crypto,
  analystRows,
  functionSources,
  warnings,
  elapsedMs,
  veryfinderEnabled,
  veryfinder,
  veryfinderState,
  veryfinderError,
  veryfinderMinTweets,
  veryfinderMinTweetsInput,
  veryfinderRecommendedTweets,
  veryfinderSource,
  veryfinderStartedAt,
  veryfinderUpdatedAt,
  veryfinderLiveRefreshCount,
  onVeryfinderMinTweetsInputChange,
  onVeryfinderTweetSearch,
}: {
  data: ANRData;
  symbol: string;
  crypto: boolean;
  analystRows: AnalystRow[];
  functionSources: string[];
  warnings: string[];
  elapsedMs?: number;
  veryfinderEnabled: boolean;
  veryfinder: VeryfinderOverlay | null;
  veryfinderState: VeryfinderRunState;
  veryfinderError: string | null;
  veryfinderMinTweets: number;
  veryfinderMinTweetsInput: string;
  veryfinderRecommendedTweets: number;
  veryfinderSource: string;
  veryfinderStartedAt: string | null;
  veryfinderUpdatedAt: string | null;
  veryfinderLiveRefreshCount: number;
  onVeryfinderMinTweetsInputChange: (value: string) => void;
  onVeryfinderTweetSearch: () => void;
}) {
  const summary = data.summary ?? {};
  const signalRows = data.signal_rows ?? [];
  const count = crypto ? summary.signal_count ?? signalRows.length : summary.analyst_count ?? analystRows.length;
  const dataMode = crypto ? "market-data proxy" : analystRows.length ? "broker-level + consensus" : "aggregate consensus";
  return (
    <div data-testid="anr-analysis-screen" className="u-grid-gap-12">
      <Card variant="elev-2" style={{ borderColor: "color-mix(in srgb, var(--accent) 32%, transparent)" }}>
        <CardHeader
          trailing={
            <div className="u-flex u-gap-6 u-flex-wrap u-justify-end">
              <Pill tone={crypto ? "accent" : "positive"} variant="soft">{dataMode}</Pill>
              {summary.not_analyst_target ? <Pill tone="warn" variant="soft">target caveat</Pill> : null}
            </div>
          }
        >
          Analysis Detail
        </CardHeader>
        <CardBody>
          <div className="u-grid-gap-12">
            <div style={analysisTitleRowStyle}>
              <div>
                <div style={analysisTitleStyle}>{symbol} ANR analysis</div>
                <p style={analysisTextStyle}>
                  {crypto
                    ? "Crypto ANR is a market-data consensus proxy. It combines live price/volume signals, freshness checks, reference bands, and the optional Veryfinder social overlay."
                    : "Equity ANR combines recommendation consensus, broker action rows, live target-price provenance, stale-rating filtering, and the optional Veryfinder social overlay."}
                </p>
              </div>
              <div style={analysisScoreStyle}>
                <span style={analysisScoreLabelStyle}>consensus</span>
                <ConsensusScoreMeter score={summary.consensus_score} />
              </div>
            </div>
            <StatGrid
              items={[
                ["Label", summary.label ?? "—"],
                [crypto ? "Signals analyzed" : "Ratings analyzed", formatInt(count)],
                ["Positive", formatPct(summary.positive_pct)],
                ["Neutral", formatPct(summary.neutral_pct)],
                ["Negative", formatPct(summary.negative_pct)],
                ["Last updated", formatConsensusDate(summary.last_updated)],
                ["Elapsed", elapsedMs == null ? "—" : `${elapsedMs.toFixed(0)} ms`],
                ["Asset class", summary.asset_class ?? (crypto ? "CRYPTO" : "EQUITY")],
              ]}
            />
          </div>
        </CardBody>
      </Card>

      <AnalysisFlowCard crypto={crypto} veryfinderEnabled={veryfinderEnabled} />

      <div style={twoColumnAnalysisGridStyle}>
        <AnalysisSourceAuditCard
          sources={data.source_details ?? []}
          functionSources={functionSources}
          warnings={warnings}
          detailStatus={data.analyst_detail_status ?? summary.analyst_detail_status}
          detailReason={data.analyst_detail_reason}
        />
        <AnalysisRulesCard data={data} crypto={crypto} />
      </div>

      {crypto ? (
        <AnalysisSignalAuditCard rows={signalRows} />
      ) : (
        <AnalysisAnalystCoverageCard rows={analystRows} detailReason={data.analyst_detail_reason} />
      )}

      <div style={twoColumnAnalysisGridStyle}>
        <AnalysisBucketAuditCard rows={data.bucket_rows ?? []} />
        <AnalysisTargetAuditCard data={data} />
      </div>

      <VeryfinderAnalysisCard
        enabled={veryfinderEnabled}
        overlay={veryfinder}
        state={veryfinderState}
        error={veryfinderError}
        minTweets={veryfinderMinTweets}
        minTweetsInput={veryfinderMinTweetsInput}
        recommendedTweets={veryfinderRecommendedTweets}
        source={veryfinderSource}
        startedAt={veryfinderStartedAt}
        updatedAt={veryfinderUpdatedAt}
        liveRefreshCount={veryfinderLiveRefreshCount}
        onMinTweetsInputChange={onVeryfinderMinTweetsInputChange}
        onTweetSearch={onVeryfinderTweetSearch}
      />

      <Methodology data={data} />
    </div>
  );
}

function AnalysisFlowCard({ crypto, veryfinderEnabled }: { crypto: boolean; veryfinderEnabled: boolean }) {
  const steps = crypto
    ? [
        ["Input", "symbol + asset class"],
        ["Market signals", "trend, momentum, volatility, liquidity"],
        ["Freshness", "market-data recency filter"],
        ["Score", "weighted 1-5 consensus proxy"],
        ["Overlay", veryfinderEnabled ? "Veryfinder social view" : "Veryfinder off"],
      ]
    : [
        ["Input", "symbol + recommendation feed"],
        ["Rows", "rating, previous rating, action, target"],
        ["Freshness", "1Y stale-rating exclusion"],
        ["Score", "buy/hold/sell consensus map"],
        ["Overlay", veryfinderEnabled ? "Veryfinder social view" : "Veryfinder off"],
      ];
  return (
    <Card>
      <CardHeader>Analysis Path</CardHeader>
      <CardBody>
        <div style={analysisFlowStyle}>
          {steps.map(([label, value], index) => (
            <div key={label} style={analysisStepStyle}>
              <span style={analysisStepIndexStyle}>{index + 1}</span>
              <strong>{label}</strong>
              <span>{value}</span>
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  );
}

function AnalysisSourceAuditCard({
  sources,
  functionSources,
  warnings,
  detailStatus,
  detailReason,
}: {
  sources: SourceDetail[];
  functionSources: string[];
  warnings: string[];
  detailStatus?: string;
  detailReason?: string;
}) {
  return (
    <Card>
      <CardHeader trailing={<Pill tone={warnings.length ? "warn" : "positive"} variant="soft">{warnings.length ? "warnings" : "clean"}</Pill>}>
        Source Audit
      </CardHeader>
      <CardBody>
        <div className="u-grid-gap-10">
          <StatGrid
            items={[
              ["Runtime sources", formatSources(functionSources)],
              ["Source rows", formatInt(sources.length)],
              ["Detail status", providerLabel(detailStatus)],
              ["Warnings", formatInt(warnings.length)],
            ]}
          />
          {sources.length ? (
            <div style={analysisListStyle}>
              {sources.map((source, index) => (
                <div key={`${source.name ?? "source"}-${index}`} style={analysisListRowStyle}>
                  <strong>{providerLabel(source.name)}</strong>
                  <span>{providerLabel(source.status)} · {source.asOf ?? "as-of —"} · {source.fields ?? "fields —"}</span>
                </div>
              ))}
            </div>
          ) : null}
          {detailReason ? <p style={analysisTextStyle}>{detailReason}</p> : null}
          {warnings.length ? (
            <div style={analysisWarningListStyle}>
              {warnings.slice(0, 6).map((warning) => (
                <span key={warning}>{warning}</span>
              ))}
            </div>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}

function AnalysisRulesCard({ data, crypto }: { data: ANRData; crypto: boolean }) {
  const stale = data.stale_rule;
  const source = data.target_price_source;
  return (
    <Card>
      <CardHeader trailing={<Pill tone={crypto ? "accent" : "muted"} variant="soft">{crypto ? "crypto" : "equity"}</Pill>}>
        Rules & Caveats
      </CardHeader>
      <CardBody>
        <div className="u-grid-gap-10">
          <StatGrid
            items={[
              ["Freshness rule", stale?.rule_type === "market_data_freshness" ? "market data" : "1Y stale rule"],
              ["Included", formatInt(stale?.included_count)],
              ["Excluded", formatInt(stale?.excluded_stale_count)],
              ["Undated rows", formatInt(stale?.undated_provider_rows)],
              ["Target source", source?.label ?? "—"],
              ["Target caveat", source?.not_analyst_target ? "not analyst target" : "live target"],
            ]}
          />
          <p style={analysisTextStyle}>{stale?.rule ?? "No stale/freshness rule text supplied."}</p>
          {source?.not_analyst_target ? (
            <p style={analysisTextStyle}>
              Price references in this run are explicitly labelled as non-analyst targets so they are not confused with broker target prices.
            </p>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}

function AnalysisSignalAuditCard({ rows }: { rows: SignalRow[] }) {
  const cols: DataGridColumn<SignalRow>[] = [
    { key: "signal", header: "Signal", width: "1fr", render: (r) => r.signal ?? "—" },
    { key: "value", header: "Value", width: 110, render: (r) => r.value ?? "—" },
    { key: "score", header: "Score", width: 80, numeric: true, render: (r) => formatScore(r.score) },
    { key: "weight", header: "Weight", width: 80, numeric: true, render: (r) => formatPct(Number(r.weight ?? 0) * 100) },
    { key: "weighted_score", header: "Weighted", width: 90, numeric: true, render: (r) => formatScore(r.weighted_score) },
    { key: "explanation", header: "Meaning", width: "1.4fr", render: (r) => r.explanation ?? "—" },
  ];
  return (
    <Card>
      <CardHeader trailing={<Pill tone={rows.length ? "positive" : "warn"} variant="soft">{rows.length} signals</Pill>}>
        Signal Weight Audit
      </CardHeader>
      <CardBody>
        <DataGrid columns={cols} rows={rows} density="compact" empty="signal rows unavailable" />
      </CardBody>
    </Card>
  );
}

function AnalysisAnalystCoverageCard({ rows, detailReason }: { rows: AnalystRow[]; detailReason?: string }) {
  const brokerCount = new Set(rows.map((row) => row.broker).filter(Boolean)).size;
  const targetCount = rows.filter((row) => row.target_price != null && row.target_price !== "").length;
  const actionCount = rows.filter((row) => row.action).length;
  const cols: DataGridColumn<AnalystRow>[] = [
    { key: "broker", header: "Broker", width: 150, render: (r) => r.broker ?? "—" },
    { key: "rating", header: "Rating", width: 110, render: (r) => r.rating ?? "—" },
    { key: "previous_rating", header: "Previous", width: 110, render: (r) => r.previous_rating ?? "—" },
    { key: "action", header: "Action", width: 120, render: (r) => r.action ?? "—" },
    { key: "target_price", header: "Target", width: 100, numeric: true, render: (r) => formatMoney(r.target_price) },
    { key: "date", header: "Date", width: 110, render: (r) => r.date ?? "—" },
  ];
  return (
    <Card>
      <CardHeader trailing={<Pill tone={rows.length ? "positive" : "warn"} variant="soft">{rows.length} rows</Pill>}>
        Analyst Coverage Audit
      </CardHeader>
      <CardBody>
        <div className="u-grid-gap-10">
          <StatGrid
            items={[
              ["Brokers", formatInt(brokerCount)],
              ["Rows", formatInt(rows.length)],
              ["Rows with target", formatInt(targetCount)],
              ["Rows with action", formatInt(actionCount)],
            ]}
          />
          <DataGrid columns={cols} rows={rows.slice(0, 12)} density="compact" empty="analyst rows unavailable" />
          {detailReason ? <p style={analysisTextStyle}>{detailReason}</p> : null}
        </div>
      </CardBody>
    </Card>
  );
}

function AnalysisBucketAuditCard({ rows }: { rows: BucketRow[] }) {
  const cols: DataGridColumn<BucketRow>[] = [
    { key: "bucket", header: "Bucket", width: "1fr", render: (r) => r.bucket ?? "—" },
    { key: "count", header: "Count", width: 90, numeric: true, render: (r) => formatInt(r.count) },
    { key: "pct_of_consensus", header: "%", width: 80, numeric: true, render: (r) => formatPct(r.pct_of_consensus) },
    { key: "sentiment_score", header: "Score", width: 80, numeric: true, render: (r) => formatInt(r.sentiment_score) },
  ];
  return (
    <Card>
      <CardHeader>Consensus Distribution</CardHeader>
      <CardBody>
        <div className="u-grid-gap-10">
          <DistributionBars
            distribution={Object.fromEntries(
              rows.map((row) => [row.bucket ?? "unknown", Number(row.pct_of_consensus ?? 0) / 100]),
            )}
          />
          <DataGrid columns={cols} rows={rows} density="compact" empty="bucket rows unavailable" />
        </div>
      </CardBody>
    </Card>
  );
}

function AnalysisTargetAuditCard({ data }: { data: ANRData }) {
  const rows = data.target_rows ?? [];
  const cols: DataGridColumn<TargetRow>[] = [
    { key: "metric", header: "Metric", width: "1fr", render: (r) => r.metric ?? "—" },
    { key: "price", header: "Price", width: 110, numeric: true, render: (r) => formatMoney(r.price) },
    { key: "source_mode", header: "Source", width: 180, render: (r) => sourceLabel(r.source_mode) },
  ];
  return (
    <Card>
      <CardHeader
        trailing={<Pill tone={data.target_price_source?.not_analyst_target ? "warn" : "positive"} variant="soft">{data.target_price_source?.label ?? "target source"}</Pill>}
      >
        Target Price Provenance
      </CardHeader>
      <CardBody>
        <div className="u-grid-gap-10">
          <StatGrid
            items={[
              ["Spot", formatMoney(data.spot)],
              ["Mode", sourceLabel(data.target_price_source?.mode)],
              ["Rows", formatInt(rows.length)],
              ["Caveat", data.target_price_source?.not_analyst_target ? "not analyst target" : "analyst target"],
            ]}
          />
          <DataGrid columns={cols} rows={rows} density="compact" empty="target rows unavailable" />
        </div>
      </CardBody>
    </Card>
  );
}
