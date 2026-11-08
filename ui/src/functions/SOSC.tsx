/**
 * SOSC — Social / News Sentiment for one ticker.
 *
 * Reads awareness news sentiment for the ticker (quality-weighted mean,
 * positive/negative share, momentum z, dispersion, per-bucket series), the
 * GDELT tone series on its native scale, the latest headlines and the social
 * rank row. The methodology line comes from the backend and states exactly
 * what is computed. Awareness down renders the honest unavailable state; quiet
 * coverage renders an empty state. Nothing is fabricated.
 */
import { useMemo, useState, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { PaneState } from "@/design-system/PaneState";
import { useFunction } from "@/lib/useFunction";
import { defaultSymbolForFunction } from "@/lib/symbols";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";
import { AwarenessUnavailable } from "./awareness/AwarenessUnavailable";
import { ProviderHealthStrip } from "./awareness/ProviderHealthStrip";
import type { AwarenessMeta } from "./awareness/types";
import { SentimentBars } from "./awareness/SentimentBars";
import { formatUtcStamp } from "./awareness/FearGreedGauge";

interface SOSCRow {
  platform?: string;
  mentions?: number | null;
  sentiment?: number | null;
  trend?: string;
}

interface SeriesBucket {
  ts: string;
  mean: number | null;
  weighted_mean?: number | null;
  count?: number;
  positive?: number;
  negative?: number;
  neutral?: number;
}

interface SOSCNews {
  count?: number;
  mean?: number | null;
  weighted_mean?: number | null;
  positive_share?: number | null;
  negative_share?: number | null;
  momentum_z?: number | null;
  dispersion?: number | null;
  latest_at?: string | null;
  publishers?: string[] | number;
  series?: SeriesBucket[];
}

interface SOSCHeadline {
  title?: string | null;
  publisher?: string | null;
  publisher_name?: string | null;
  published_at?: string | null;
  url?: string | null;
  sentiment?: number | null;
}

interface SOSCSocial {
  rank?: number | null;
  mentions?: number | null;
  mention_change_pct?: number | null;
  rank_change?: number | null;
  as_of?: string | null;
}

interface SOSCToneSample {
  ts: string;
  value: number | null;
}

interface SOSCData {
  status?: string;
  reason?: string | null;
  symbol?: string;
  news?: SOSCNews;
  headlines?: SOSCHeadline[];
  social?: SOSCSocial | null;
  gdelt_tone?: SOSCToneSample[];
  rows?: SOSCRow[];
  methodology?: string;
  next_actions?: string[];
  meta?: AwarenessMeta;
}

const WINDOW_OPTIONS = [
  { value: "1d", label: "1d" },
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
] as const;
const WINDOW_IDS = WINDOW_OPTIONS.map((o) => o.value);

export function SOSCPane({ code, symbol }: FunctionPaneProps) {
  const [windowId, setWindowId] = usePersistentOption<string>(
    "showme.sosc.window",
    WINDOW_IDS,
    "7d",
  );
  const [trendFilter, setTrendFilter] = useState("ALL");
  const effectiveSymbol =
    symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF", "CRYPTO"]);
  const { state, data, error, refetch } = useFunction<SOSCData>({
    code,
    symbol: effectiveSymbol,
    params: { window: windowId },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows = useMemo(() => payload?.rows ?? [], [payload]);
  const news = payload?.news;
  const tone = payload?.gdelt_tone ?? [];
  const status = payload?.status ?? "—";
  const isUnavailable = status === "provider_unavailable";
  const count = news?.count ?? 0;
  const latestTone = lastFinite(tone.map((t) => t.value));

  const trends = useMemo(() => {
    const set = new Set<string>();
    for (const row of rows) {
      if (row.trend) set.add(row.trend.toLowerCase());
    }
    return ["ALL", ...Array.from(set).sort()];
  }, [rows]);

  const visible = useMemo(
    () =>
      trendFilter === "ALL"
        ? rows
        : rows.filter((r) => (r.trend ?? "").toLowerCase() === trendFilter),
    [rows, trendFilter],
  );

  const weighted = news?.weighted_mean ?? null;
  const read = sentimentLabel(weighted);

  const COLS: DataGridColumn<SOSCRow>[] = useMemo(
    () => [
      {
        key: "platform",
        header: "Source",
        width: 220,
        sortable: true,
        sortValue: (r) => r.platform ?? "",
        render: (r) => <span style={monoPrimaryStyle}>{r.platform ?? "—"}</span>,
      },
      {
        key: "mentions",
        header: "Mentions",
        numeric: true,
        width: 100,
        sortable: true,
        sortValue: (r) => r.mentions ?? null,
        render: (r) => <span style={monoStrongStyle}>{fmtInt(r.mentions)}</span>,
      },
      {
        key: "sentiment",
        header: "Mean tone",
        numeric: true,
        width: 110,
        sortable: true,
        sortValue: (r) => r.sentiment ?? null,
        render: (r) => (
          <span style={{ ...monoStrongStyle, color: toneColor(r.sentiment) }}>
            {fmtSigned(r.sentiment)}
          </span>
        ),
      },
      {
        key: "trend",
        header: "Trend",
        width: 110,
        sortable: true,
        sortValue: (r) => r.trend ?? "",
        render: (r) =>
          r.trend ? (
            <Pill
              tone={
                r.trend === "bullish"
                  ? "positive"
                  : r.trend === "bearish"
                    ? "negative"
                    : "muted"
              }
              variant="soft"
              withDot={false}
            >
              {r.trend}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
    ],
    [],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="SOSC needs an equity or crypto ticker." icon="⌖" />
  ) : isUnavailable ? (
    <AwarenessUnavailable
      reason={payload?.reason ?? null}
      onRetry={refetch}
      subject={`news sentiment for ${effectiveSymbol}`}
    />
  ) : (
    <PaneState
      state={state}
      error={error}
      empty={count === 0}
      emptyTitle="No recent coverage"
      emptyBody={`No scored articles matched ${effectiveSymbol} in the last ${windowId}. Nothing is filled in while coverage is quiet.`}
      emptyIcon="∅"
      onRetry={refetch}
    >
      <div className="u-grid-gap-14">
        {payload?.meta ? (
          <ProviderHealthStrip
            providers={payload.meta.providers}
            feedHealth={payload.meta.feed_health}
            generatedAt={payload.meta.generated_at}
          />
        ) : null}
        <section style={kpiGridStyle} aria-label="SOSC sentiment summary">
          <StatCard
            label="Weighted mean"
            value={fmtSigned(weighted)}
            caption={`${windowId.toUpperCase()} · ${read.toUpperCase()}`}
            tone={sentimentTone(weighted)}
          />
          <StatCard
            label="Articles"
            value={fmtInt(news?.count)}
            caption={`POSITIVE ${pct(news?.positive_share)} · NEGATIVE ${pct(news?.negative_share)}`}
            tone="neutral"
          />
          <StatCard
            label="Momentum z"
            value={fmtSigned(news?.momentum_z)}
            caption={`DISPERSION ${fmtNum(news?.dispersion)}`}
            tone={sentimentTone(news?.momentum_z)}
          />
          <StatCard
            label="GDELT tone"
            value={fmtSigned(latestTone)}
            caption="NATIVE GDELT SCALE"
            tone={sentimentTone(latestTone)}
          />
        </section>

        <section aria-labelledby="sosc-entity-title" className="u-grid-gap-14">
          <h3 id="sosc-entity-title" style={sectionTitleStyle}>
            News sentiment by bucket
          </h3>
          {series(news).length > 0 ? (
            <SentimentBars
              series={series(news).map((s) => ({ ts: s.ts, mean: s.mean }))}
              tone={tone}
              toneLabel="GDELT tone, native scale"
              ariaLabel={`${effectiveSymbol} news sentiment buckets with GDELT tone`}
            />
          ) : (
            <p style={mutedStyle}>No scored news buckets for {effectiveSymbol}.</p>
          )}
        </section>

        <section aria-labelledby="sosc-headlines-title">
          <h3 id="sosc-headlines-title" style={sectionTitleStyle}>
            Latest headlines
          </h3>
          {(payload?.headlines ?? []).length === 0 ? (
            <p style={mutedStyle}>No headlines returned for this window.</p>
          ) : (
            <ul className="aw-headlines">
              {(payload?.headlines ?? []).slice(0, 12).map((h, i) => (
                <li key={`${h.title ?? "h"}-${i}`}>
                  <span className="aw-headlines__time">
                    {formatUtcStamp(h.published_at) || "—"}
                  </span>
                  <span>
                    {h.url ? (
                      <a href={h.url} target="_blank" rel="noreferrer" className="aw-link">
                        {h.title ?? "Untitled"}
                      </a>
                    ) : (
                      (h.title ?? "Untitled")
                    )}
                    <span style={mutedInlineStyle}>
                      {" "}
                      {h.publisher_name ?? h.publisher ?? ""}
                    </span>
                  </span>
                  <span style={{ ...monoStrongStyle, color: toneColor(h.sentiment) }}>
                    {fmtSigned(h.sentiment)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {rows.length > 0 ? (
          <>
            <div style={chipRowStyle} role="group" aria-label="Trend filter">
              {trends.map((t) => {
                const active = trendFilter === t;
                return (
                  <button
                    key={t}
                    type="button"
                    className={`fn-segmented__opt${active ? " fn-segmented__opt--active" : ""}`}
                    aria-pressed={active}
                    onClick={() => setTrendFilter(t)}
                    title={`Filter trend ${t}`}
                  >
                    {t}
                  </button>
                );
              })}
            </div>
            <DataGrid
              columns={COLS}
              rows={visible}
              rowKey={(r, i) => `${r.platform ?? "source"}-${i}`}
              density="compact"
              ariaLabel="SOSC per-source sentiment"
              defaultSortKey="mentions"
              defaultSortDir="descending"
              empty="No sources match this trend filter"
            />
          </>
        ) : null}

        {payload?.methodology ? (
          <details style={mutedStyle}>
            <summary>Methodology</summary>
            <p style={{ margin: "6px 0 0" }}>{payload.methodology}</p>
          </details>
        ) : null}
      </div>
    </PaneState>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Social Sentiment — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${count} articles · ${windowId} window`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {fmtInt(news?.count)} articles
              </Pill>
              <SegmentedControl
                label="WINDOW"
                value={windowId}
                options={WINDOW_OPTIONS}
                onChange={setWindowId}
                title="Sentiment lookback window"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Re-scan news sentiment"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="sources" value={data?.sources?.join(", ") || "—"} />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="latest" value={formatUtcStamp(news?.latest_at) || "—"} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="window" value={windowId} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function series(news: SOSCNews | undefined): SeriesBucket[] {
  return news?.series ?? [];
}

function lastFinite(values: Array<number | null | undefined>): number | null {
  for (let i = values.length - 1; i >= 0; i -= 1) {
    const v = values[i];
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }
  return null;
}

function sentimentLabel(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v > 0.05 ? "bullish" : v < -0.05 ? "bearish" : "neutral";
}

function sentimentTone(v: number | null | undefined): "positive" | "negative" | "neutral" {
  if (v == null || !Number.isFinite(v)) return "neutral";
  return v > 0.05 ? "positive" : v < -0.05 ? "negative" : "neutral";
}

function toneColor(v: number | null | undefined): string {
  const tone = sentimentTone(v);
  if (tone === "positive") return "var(--positive)";
  if (tone === "negative") return "var(--negative)";
  return "var(--text-primary)";
}

function fmtSigned(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}`;
}

function fmtNum(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(2);
}

function pct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${Math.round(v * 100)}%`;
}

function fmtInt(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return Math.round(v).toLocaleString("en-US");
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const chipRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
};

const sectionTitleStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--font-display)",
  fontSize: "var(--font-size-lg)",
  fontWeight: 600,
  color: "var(--text-display)",
};

const mutedStyle: CSSProperties = {
  fontSize: "var(--font-size-sm)",
  color: "var(--text-secondary)",
};

const mutedInlineStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: "var(--font-size-2xs)",
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const monoPrimaryStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
};
