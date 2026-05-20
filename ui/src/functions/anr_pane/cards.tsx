import { useMemo } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  DataGrid,
  Pill,
  Skeleton,
  type DataGridColumn,
} from "@/design-system";
import type { VeryfinderOverlay } from "@/lib/veryfinder";
import type {
  ANRData,
  ANRSummary,
  StaleRule,
  TargetRow,
  VeryfinderRunState,
} from "./_types";
import {
  distributionLabel,
  formatInt,
  formatMoney,
  formatPct,
  formatScore,
  formatSignedInt,
  isCryptoSummary,
  providerLabel,
  sourceLabel,
  veryfinderTone,
} from "./formatters";
import {
  analysisMutedStyle,
  distributionBlockStyle,
  distributionRowStyle,
  distributionTitleStyle,
  distributionTrackStyle,
} from "./styles";
import { StatGrid } from "./tables";

export function ConsensusCard({ summary, symbol }: { summary: ANRSummary; symbol: string }) {
  const label = summary.label ?? "No consensus";
  const crypto = isCryptoSummary(summary);
  const count = crypto ? summary.signal_count ?? summary.analyst_count : summary.analyst_count;
  const countLabel = summary.count_label ?? (crypto ? "signals" : "analysts");
  const tone = label.toLowerCase().includes("buy")
    ? "positive"
    : label.toLowerCase().includes("sell")
      ? "negative"
      : "neutral";
  return (
    <Card variant="elev-2" style={{ borderColor: "color-mix(in srgb, var(--accent) 36%, transparent)" }}>
      <CardHeader
        trailing={
          <div className="u-flex u-gap-6 u-flex-wrap u-justify-end">
            <Pill tone={tone} variant="soft">{label}</Pill>
            {summary.not_analyst_target ? <Pill tone="warn" variant="soft">not analyst target</Pill> : null}
          </div>
        }
      >
        Consensus
      </CardHeader>
      <CardBody>
        <div className="u-grid-gap-10">
          <div className="anr-consensus-head">
            <div>
              <div className="anr-consensus-title">
                {summary.title ?? `${symbol} ${crypto ? "Crypto Market Consensus" : "Analyst Consensus"}`}
              </div>
              <div className="anr-consensus-meta">
                {formatInt(count)} {countLabel} · last updated {summary.last_updated ?? "—"}
              </div>
            </div>
            <div className="anr-consensus-score">
              <div className="anr-consensus-score-label">Consensus</div>
              <div className="anr-consensus-score-val">
                {formatScore(summary.consensus_score)} / 5
              </div>
            </div>
          </div>
          <StatGrid
            items={[
              ["Positive", `${formatPct(summary.positive_pct)}`],
              ["Neutral", `${formatPct(summary.neutral_pct)}`],
              ["Negative", `${formatPct(summary.negative_pct)}`],
              ["Source", providerLabel(summary.consensus_source)],
              ["Included", formatInt(summary.included_count)],
              [crypto ? "Freshness excluded" : "Stale excluded", formatInt(summary.excluded_stale_count)],
              [crypto ? "Market data" : "Oldest included", crypto ? summary.last_updated ?? "—" : summary.oldest_included_rating_date ?? "—"],
            ]}
          />
        </div>
      </CardBody>
    </Card>
  );
}

export function VeryfinderConsensusCard({
  overlay,
  state,
  error,
}: {
  overlay: VeryfinderOverlay | null;
  state: VeryfinderRunState;
  error: string | null;
}) {
  const tone = veryfinderTone(overlay?.tone);
  const loading = state === "loading" && !overlay;
  const refreshing = state === "refreshing" || (state === "loading" && !!overlay);
  const errored = state === "error";
  const label = loading
    ? "loading"
    : refreshing
      ? "refreshing"
      : overlay?.label ?? (error ? "unavailable" : "waiting");
  return (
    <Card variant="elev-2" style={{ borderColor: "color-mix(in srgb, var(--warn) 38%, transparent)" }}>
      <CardHeader
        trailing={
          <div className="u-flex u-gap-6 u-flex-wrap u-justify-end">
            <Pill tone={tone} variant="soft">{label}</Pill>
            {errored && overlay ? <Pill tone="warn" variant="soft">refresh failed</Pill> : null}
            {overlay?.fixture_mode ? <Pill tone="warn" variant="soft">fixture</Pill> : null}
            {overlay?.fallback_mode ? <Pill tone="warn" variant="soft">{providerLabel(overlay.fallback_mode)}</Pill> : null}
            {overlay?.quality ? <Pill tone={overlay.quality === "ok" ? "positive" : "warn"} variant="soft">{overlay.quality}</Pill> : null}
            {overlay ? <Pill tone={refreshing ? "warn" : "positive"} variant="soft" withDot={!refreshing}>live rolling</Pill> : null}
          </div>
        }
      >
        Veryfinder Social Overlay
      </CardHeader>
      <CardBody>
        {loading ? (
          <div className="u-grid-gap-8">
            <Skeleton height={24} />
            <Skeleton height={58} />
          </div>
        ) : overlay ? (
          <div className="u-grid-gap-10">
            <StatGrid
              items={[
                ["Dominant view", overlay.dominant_view?.display ?? "—"],
                ["Confidence", formatPct(Number(overlay.dominant_view?.score ?? 0) * 100)],
                ["Social score", formatSignedInt(overlay.social_score)],
                ["Unique accounts", formatInt(overlay.unique_accounts)],
                ["Source", providerLabel(overlay.source)],
                ["Engine", overlay.engine ?? "—"],
                ["Mood", distributionLabel(overlay.top_mood)],
                ["Action", distributionLabel(overlay.top_action)],
              ]}
            />
            <p className="anr-card-meaning">
              {overlay.meaning ?? "Veryfinder is a social overlay, not analyst consensus."}
            </p>
            <p title={overlay.query} className="anr-card-query">
              Query: {overlay.query ?? "—"}
            </p>
          </div>
        ) : errored && error ? (
          <p className="anr-card-text">{error}</p>
        ) : (
          <p className="anr-card-text">
            Enable Veryfinder to compare ANR consensus against unique-account social reaction.
          </p>
        )}
      </CardBody>
    </Card>
  );
}

export function TargetCard({ data }: { data: ANRData }) {
  const source = data.target_price_source;
  const rows = data.target_rows ?? [];
  const crypto = isCryptoSummary(data.summary);
  const title = crypto ? source?.display_name ?? "Crypto Reference Bands" : "Price Target";
  const cols = useMemo<DataGridColumn<TargetRow>[]>(
    () => [
      { key: "metric", header: crypto ? "Reference" : "Target", width: "1fr" },
      { key: "price", header: "Price", width: 100, numeric: true, render: (r) => formatMoney(r.price) },
      {
        key: "source_mode",
        header: "Source",
        width: 180,
        render: (r) => sourceLabel(r.source_mode),
      },
    ],
    [crypto],
  );
  return (
    <Card>
      <CardHeader
        trailing={
          <div className="u-flex u-gap-6 u-flex-wrap u-justify-end">
            <Pill tone={source?.not_analyst_target ? "warn" : "positive"} variant="soft">
              {source?.label ?? "Target source —"}
            </Pill>
            {source?.not_analyst_target ? <Pill tone="warn" variant="soft">not an analyst target</Pill> : null}
          </div>
        }
      >
        {title}
      </CardHeader>
      <CardBody>
        <div className="u-grid-gap-10">
          <div className="u-text-12 u-text-secondary">
            Spot reference: {formatMoney(data.spot)}
          </div>
          <DataGrid columns={cols} rows={rows} density="compact" empty={crypto ? "reference bands unavailable" : "target fields unavailable"} />
        </div>
      </CardBody>
    </Card>
  );
}

export function StaleRuleCard({ stale }: { stale?: StaleRule }) {
  const marketFreshness = stale?.rule_type === "market_data_freshness";
  return (
    <Card>
      <CardHeader trailing={<Pill tone="accent" variant="soft">{marketFreshness ? "market data" : "1Y rule"}</Pill>}>
        {marketFreshness ? "Freshness Rule" : "Stale Data Rule"}
      </CardHeader>
      <CardBody>
        <StatGrid
          items={marketFreshness
            ? [
                ["Latest data", stale?.latest_market_data_at ?? "—"],
                ["Signals included", formatInt(stale?.included_count)],
                ["Excluded", formatInt(stale?.excluded_stale_count)],
                ["Undated rows", formatInt(stale?.undated_provider_rows)],
              ]
            : [
                ["Cutoff date", stale?.cutoff_date ?? "—"],
                ["Included", formatInt(stale?.included_count)],
                ["Stale excluded", formatInt(stale?.excluded_stale_count)],
                ["Oldest included", stale?.oldest_included_rating_date ?? "—"],
                ["Oldest stale", stale?.oldest_stale_rating_date ?? "—"],
                ["Undated rows", formatInt(stale?.undated_provider_rows)],
              ]}
        />
        <p className="anr-stale-rule">
          {stale?.rule ?? "Recommendation rows older than one year are excluded from consensus."}
        </p>
      </CardBody>
    </Card>
  );
}

export function DistributionBlock({ title, distribution }: { title: string; distribution?: Record<string, number> }) {
  return (
    <div style={distributionBlockStyle}>
      <div style={distributionTitleStyle}>{title}</div>
      <DistributionBars distribution={distribution} />
    </div>
  );
}

export function DistributionBars({ distribution }: { distribution?: Record<string, number> }) {
  const entries = Object.entries(distribution ?? {})
    .filter(([, value]) => Number.isFinite(Number(value)))
    .sort((a, b) => Number(b[1]) - Number(a[1]));
  if (!entries.length) {
    return <span style={analysisMutedStyle}>distribution unavailable</span>;
  }
  return (
    <div className="u-grid-gap-6">
      {entries.map(([label, value]) => {
        const pct = Math.max(0, Math.min(100, Number(value) * 100));
        return (
          <div key={label} className="u-grid u-gap-3">
            <div style={distributionRowStyle}>
              <span>{label.replaceAll("_", " ")}</span>
              <strong>{formatPct(pct)}</strong>
            </div>
            <div style={distributionTrackStyle}>
              <span
                className="anr-dist-fill"
                style={{ ["--u-pct" as string]: `${pct}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
