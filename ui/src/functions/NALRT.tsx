/**
 * NALRT — Critical News Alerts.
 *
 * Threshold-gated alert stream over the backend's live RSS scan ranked by
 * market-impact score. Header: threshold + freshness-window controls (both
 * persisted under `showme.nalrt.*`) + alert count + refresh. Body: impact
 * KPI ribbon, an RSS feed_health strip (per-feed ok/failed pills), and the
 * alert list with severity pills and per-alert impact scores. Empty states
 * are honest: "no alerts above threshold" is distinct from "no headlines
 * returned" (provider outage), and neither fabricates rows.
 */
import { useMemo, type CSSProperties } from "react";
import {
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
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

interface NALRTAlert {
  title?: string;
  source?: string;
  url?: string;
  link?: string;
  age_minutes?: number;
  importance_score?: number;
  relevance_score?: number;
  severity?: string;
  alert?: boolean;
  matched_terms?: string[];
}

interface NALRTHealth {
  feeds?: number;
  ok?: number;
  failed?: number;
  ok_rate?: number;
  median_latency_ms?: number | null;
  items?: number;
}

interface NALRTFeedHealth {
  feed?: string;
  url?: string;
  ok?: boolean;
  latency_ms?: number;
  items?: number;
  error?: string;
  status_code?: number;
}

interface NALRTData {
  status?: string;
  alerts?: NALRTAlert[];
  top?: NALRTAlert[];
  health?: NALRTHealth;
  feed_health?: NALRTFeedHealth[];
  threshold?: number;
  freshness_max_hours?: number;
  query?: string;
  symbol?: string;
  alert_count?: number;
  top_importance_score?: number;
  methodology?: string;
}

const THRESHOLD_OPTIONS = [
  { value: 50, label: "50" },
  { value: 60, label: "60" },
  { value: 70, label: "70" },
  { value: 85, label: "85" },
] as const;
const THRESHOLD_IDS = THRESHOLD_OPTIONS.map((o) => o.value);

const AGE_OPTIONS = [
  { value: 6, label: "6h" },
  { value: 12, label: "12h" },
  { value: 24, label: "24h" },
  { value: 48, label: "48h" },
] as const;
const AGE_IDS = AGE_OPTIONS.map((o) => o.value);

const MAX_FEED_PILLS = 10;

export function NALRTPane({ code, symbol }: FunctionPaneProps) {
  const [threshold, setThreshold] = usePersistentOption<number>(
    "showme.nalrt.threshold",
    THRESHOLD_IDS,
    70,
  );
  const [age, setAge] = usePersistentOption<number>(
    "showme.nalrt.age",
    AGE_IDS,
    24,
  );

  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF", "INDEX", "CRYPTO"]);
  const { state, data, error, refetch } = useFunction<NALRTData>({
    code,
    symbol: effectiveSymbol,
    params: { threshold, max_alert_age_hours: age },
  });

  const payload = data?.data;
  const alerts = useMemo(() => payload?.alerts ?? [], [payload]);
  const topRanked = useMemo(() => payload?.top ?? [], [payload]);
  const health = payload?.health;
  const feedHealth = useMemo(() => payload?.feed_health ?? [], [payload]);
  const status = payload?.status ?? "—";

  const severityTone = (severity?: string): "negative" | "warn" | "accent" | "muted" => {
    switch ((severity ?? "").toLowerCase()) {
      case "critical": return "negative";
      case "high": return "warn";
      case "medium": return "accent";
      default: return "muted";
    }
  };

  const visibleFeeds = feedHealth.slice(0, MAX_FEED_PILLS);
  const hiddenFeeds = feedHealth.length - visibleFeeds.length;

  const body = state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={56} />
      <Skeleton height={20} />
      <Skeleton height={20} />
      <Skeleton height={20} width="80%" />
    </div>
  ) : state === "error" ? (
    <Empty
      title="Function error"
      body={error?.message ?? "—"}
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="NALRT impact summary">
        <StatCard
          label="Critical alerts"
          value={String(payload?.alert_count ?? alerts.length)}
          caption={`SCORE ≥ ${payload?.threshold ?? threshold} · ≤ ${payload?.freshness_max_hours ?? age}H OLD`}
          tone={(payload?.alert_count ?? alerts.length) > 0 ? "negative" : "neutral"}
        />
        <StatCard
          label="Top impact"
          value={fmtScore(payload?.top_importance_score)}
          caption="HIGHEST RANKED SCORE IN SCAN"
          tone="neutral"
        />
        <StatCard
          label="Feeds ok"
          value={`${health?.ok ?? 0}/${health?.feeds ?? 0}`}
          caption={`OK RATE ${fmtRate(health?.ok_rate)} · MEDIAN ${fmtMs(health?.median_latency_ms)}`}
          tone={(health?.failed ?? 0) > 0 ? "negative" : "positive"}
        />
        <StatCard
          label="Items scanned"
          value={String(health?.items ?? 0)}
          caption={`QUERY ${payload?.query ?? effectiveSymbol ?? "—"}`}
          tone="neutral"
        />
      </section>

      <section aria-label="Feed health" style={feedStripStyle}>
        <span style={feedStripLabelStyle}>feed health</span>
        {visibleFeeds.length === 0 ? (
          <span style={feedStripLabelStyle}>no feed probes returned</span>
        ) : (
          visibleFeeds.map((feed) => (
            <Pill
              key={feed.feed ?? feed.url ?? "feed"}
              tone={feed.ok ? "positive" : "negative"}
              variant="soft"
              withDot={false}
            >
              {`${(feed.feed ?? "feed").slice(0, 24)}${feed.ok ? ` ${fmtMs(feed.latency_ms)}` : " failed"}`}
            </Pill>
          ))
        )}
        {hiddenFeeds > 0 ? (
          <Pill tone="muted" variant="soft" withDot={false}>
            +{hiddenFeeds} more
          </Pill>
        ) : null}
      </section>

      {alerts.length === 0 ? (
        topRanked.length === 0 ? (
          <Empty
            title="No headlines returned"
            body="The news scan returned no ranked headlines for this symbol/window — nothing is fabricated while feeds are unreachable."
            action={
              <button onClick={refetch} className="btn">
                Retry
              </button>
            }
          />
        ) : (
          <Empty
            title="No alerts above threshold"
            body={`No headline scored ≥ ${payload?.threshold ?? threshold} within the ${payload?.freshness_max_hours ?? age}h freshness window (top ranked score ${fmtScore(payload?.top_importance_score)}).`}
            action={
              <button onClick={refetch} className="btn">
                Re-scan
              </button>
            }
          />
        )
      ) : (
        <ul style={listStyle} aria-label="Critical news alerts">
          {alerts.map((alert, i) => (
            <li key={`${alert.url ?? alert.link ?? alert.title ?? "alert"}-${i}`} style={rowStyle}>
              <Pill tone={severityTone(alert.severity)} variant="soft">
                {alert.severity ?? "—"}
              </Pill>
              <span style={scoreStyle}>{fmtScore(alert.importance_score)}</span>
              <div style={contentStyle}>
                <AlertTitle alert={alert} />
                <div style={metaStyle}>
                  {[alert.source, fmtAge(alert.age_minutes)].filter(Boolean).join(" · ")}
                  {(alert.matched_terms ?? []).length > 0
                    ? ` · matched: ${(alert.matched_terms ?? []).slice(0, 4).join(", ")}`
                    : ""}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Critical News Alerts — ${effectiveSymbol || ""}`}
          subtitle={`${payload?.alert_count ?? 0} alerts · threshold ≥ ${payload?.threshold ?? threshold} · window ≤ ${payload?.freshness_max_hours ?? age}h`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {payload?.alert_count ?? 0} alerts
              </Pill>
              <SegmentedControl
                label="THRESHOLD"
                value={threshold}
                options={THRESHOLD_OPTIONS}
                onChange={setThreshold}
                title="Alert impact threshold"
              />
              <SegmentedControl
                label="WINDOW"
                value={age}
                options={AGE_OPTIONS}
                onChange={setAge}
                title="Alert freshness window"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Re-scan news feeds"
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
          <StatusSection label="feeds ok" value={`${health?.ok ?? 0}/${health?.feeds ?? 0}`} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="window" value={`≤ ${payload?.freshness_max_hours ?? age}h`} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/**
 * AUDIT A10 [M]: alerts carry `url`/`link`, but the row rendered the title as
 * inert text — a trader could not open the story. Follow the BRIEF/READ guard:
 * only an absolute http(s) URL is linkable (never `javascript:` / `data:` /
 * relative), and the link opens in a new tab with `rel="noopener noreferrer"`.
 */
function AlertTitle({ alert }: { alert: NALRTAlert }) {
  const raw = [alert.url, alert.link].find(
    (c): c is string => typeof c === "string" && /^https?:\/\//.test(c.trim()),
  );
  const href = raw ? raw.trim() : null;
  const title = alert.title ?? "—";
  if (!href) return <div style={titleStyle}>{title}</div>;
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      style={titleLinkStyle}
      aria-label={`${title} — open the story (new tab)`}
    >
      {title}
    </a>
  );
}

function fmtScore(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(1);
}

function fmtRate(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(0)}%`;
}

function fmtMs(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${Math.round(v)}ms`;
}

function fmtAge(minutes: number | null | undefined): string {
  if (minutes == null || !Number.isFinite(minutes)) return "—";
  if (minutes < 90) return `${Math.round(minutes)}m`;
  return `${(minutes / 60).toFixed(1)}h`;
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const feedStripStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
};

const feedStripLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  letterSpacing: "0.06em",
  color: "var(--text-mute)",
};

const listStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "grid",
  gap: 6,
};

const rowStyle: CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  gap: 10,
  padding: "7px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: 6,
};

const scoreStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: "var(--font-size-md)",
  fontWeight: 600,
  color: "var(--text-primary)",
  minWidth: 36,
  textAlign: "right",
};

const contentStyle: CSSProperties = {
  minWidth: 0,
  display: "grid",
  gap: 2,
};

const titleStyle: CSSProperties = {
  fontSize: "var(--font-size-md)",
  color: "var(--text-primary)",
  overflowWrap: "anywhere",
};

const titleLinkStyle: CSSProperties = {
  ...titleStyle,
  color: "var(--accent)",
  textDecoration: "underline",
  textUnderlineOffset: 2,
};

const metaStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
};
