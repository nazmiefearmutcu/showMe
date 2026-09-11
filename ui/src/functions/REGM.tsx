/**
 * REGM — Market Regime.
 *
 * Renders the backend's rule-based classification EXACTLY as reported:
 * the Regime / Trend / Vol / Curve cards mirror `payload.cards` verbatim,
 * and a supporting indicator table mirrors `payload.rows` (value + unit +
 * the rule that produced it). When the backend reports UNKNOWN / null /
 * "Cannot classify — no inputs available", the card renders an explicit
 * unknown state ("not reported — not guessed") — the pane never fills a
 * gap with its own classification. A provider_unavailable payload (live
 * benchmark series unreachable) surfaces the provider error verbatim.
 *
 * The payload's history/cluster fields (`action=history`) are fetched ON
 * DEMAND behind the HISTORY toggle and rendered as a compact coloured
 * regime timeline + the k-means cluster label — never as a guessed
 * classification (the run labels are the backend's own strings).
 */
import { type CSSProperties } from "react";
import {
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
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

interface REGMCard {
  label?: string | null;
  value?: string | null;
}

interface REGMComponentRow {
  symbol?: string;
  component?: string | null;
  label?: string | null;
  value?: number | null;
  unit?: string | null;
  rule?: string | null;
  source_mode?: string | null;
}

interface REGMData {
  symbol?: string;
  status?: string;
  provider_error?: string;
  current?: {
    regime?: string | null;
    trend?: string | null;
    vol?: string | null;
    drawdown?: string | null;
    curve?: string | null;
    confidence?: number | null;
    data_state?: string | null;
  };
  data_state?: string;
  confidence?: number | null;
  rows?: REGMComponentRow[];
  cards?: REGMCard[];
  methodology?: string;
  source_mode?: string;
}

interface REGMHistoryEntry {
  date?: string | null;
  regime?: string | null;
  trend?: string | null;
  vol?: string | null;
  drawdown?: string | null;
}

interface REGMCluster {
  labels?: number[];
  centers?: number[][];
  k?: number;
}

interface REGMHistoryData {
  symbol?: string;
  status?: string;
  provider_error?: string;
  history?: REGMHistoryEntry[];
  cluster?: REGMCluster;
  current?: REGMData["current"];
  rows?: REGMComponentRow[];
  methodology?: string;
}

type DaysOption = 365 | 1095 | 1825;

const DAYS_OPTIONS: { value: DaysOption; label: string }[] = [
  { value: 365, label: "1Y" },
  { value: 1095, label: "3Y" },
  { value: 1825, label: "5Y" },
];

/** True when the backend explicitly declined to classify this component. */
function isUnknownValue(value: string | null | undefined): boolean {
  if (value == null) return true;
  const text = value.trim();
  if (text === "" || text === "—") return true;
  const lower = text.toLowerCase();
  return lower === "unknown" || lower.startsWith("cannot classify");
}

export function REGMPane({ code, symbol }: FunctionPaneProps) {
  const [days, setDays] = usePersistentOption<DaysOption>(
    "showme.regm.days",
    DAYS_OPTIONS.map((o) => o.value),
    1095,
  );
  const [historyOn, setHistoryOn] = usePersistentOption<number>(
    "showme.regm.history",
    [0, 1],
    0,
  );

  const effectiveSymbol = symbol || defaultSymbolForFunction(code);
  const { state, data, error, refetch } = useFunction<REGMData>({
    code,
    symbol: effectiveSymbol || undefined,
    params: { days },
  });
  // On-demand history (`action=history`): the backend rolls the classifier
  // through time and returns `history[]` + a k-means `cluster`. Enabled
  // only while the HISTORY toggle is on — no extra call in the default view.
  const {
    state: historyState,
    data: historyData,
    error: historyError,
    refetch: historyRefetch,
  } = useFunction<REGMHistoryData>({
    code,
    symbol: effectiveSymbol || undefined,
    params: { days, action: "history" },
    enabled: historyOn === 1,
  });

  const payload = data?.data;
  const status = payload?.status ?? data?.status ?? "—";
  const cards = Array.isArray(payload?.cards) ? payload.cards : [];
  const rows = Array.isArray(payload?.rows) ? payload.rows : [];
  const dataState = payload?.data_state ?? payload?.current?.data_state;
  const confidence = payload?.confidence ?? payload?.current?.confidence ?? null;
  const warnings = data?.warnings ?? [];

  const body =
    state === "loading" || state === "idle" ? (
      <div className="u-grid-gap-8">
        <Skeleton height={64} />
        <Skeleton height={20} />
        <Skeleton height={120} />
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
    ) : status === "provider_unavailable" ? (
      <Empty
        title="Regime unavailable"
        body={
          payload?.provider_error
            ? `${payload.provider_error} — nothing is fabricated while the benchmark provider is unreachable.`
            : "The live benchmark series is unavailable — no regime is guessed without it."
        }
        icon="!"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : (
      <div className="u-grid-gap-14">
        <section style={cardGridStyle} aria-label="REGM regime cards">
          {cards.length > 0 ? (
            cards.map((card, i) => (
              <RegimeCard
                key={`${card.label ?? "card"}-${i}`}
                label={card.label ?? "—"}
                value={card.value ?? null}
              />
            ))
          ) : (
            <span style={muteTextStyle}>
              backend returned no regime cards
            </span>
          )}
        </section>

        {(dataState && dataState !== "ok") || warnings.length > 0 ? (
          <section
            style={stateStripStyle}
            aria-label="REGM data-state notes"
          >
            {dataState && dataState !== "ok" ? (
              <Pill tone="warn" variant="soft" withDot={false}>
                data_state: {dataState}
              </Pill>
            ) : null}
            {warnings.map((w, i) => (
              <span key={i} style={muteTextStyle}>
                {w}
              </span>
            ))}
          </section>
        ) : null}

        {rows.length > 0 ? (
          <table style={tableStyle} aria-label="REGM indicator table">
            <thead>
              <tr>
                <th style={thStyle}>Component</th>
                <th style={thStyle}>Label</th>
                <th style={thStyle}>Value</th>
                <th style={thStyle}>Rule</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const unknown =
                  row.value == null || !Number.isFinite(row.value);
                return (
                  <tr key={`${row.component ?? "row"}-${i}`}>
                    <td style={tdStyle}>{row.component ?? "—"}</td>
                    <td style={tdStyle}>
                      {isUnknownValue(row.label) ? (
                        <Pill tone="warn" variant="soft" withDot={false}>
                          {row.label ?? "unknown"}
                        </Pill>
                      ) : (
                        (row.label ?? "—")
                      )}
                    </td>
                    <td style={{ ...tdStyle, fontFamily: "JetBrains Mono, monospace" }}>
                      {unknown
                        ? "—"
                        : `${(row.value as number).toFixed(2)}${row.unit ? ` ${row.unit}` : ""}`}
                    </td>
                    <td style={tdStyle}>{row.rule ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <span style={muteTextStyle}>no indicator rows returned</span>
        )}

        {historyOn === 1 ? (
          <RegimeHistoryPanel
            state={historyState}
            payload={historyData?.data}
            error={historyError}
            onRetry={historyRefetch}
          />
        ) : null}

        {payload?.methodology ? (
          <div style={methodologyStyle} aria-label="REGM methodology">
            {payload.methodology}
          </div>
        ) : null}
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Market Regime — ${payload?.symbol ?? effectiveSymbol ?? ""}`}
          subtitle={`trend · vol · drawdown · curve over ${days}d lookback`}
          trailing={
            <FunctionControlGroup>
              <SegmentedControl
                label="LOOKBACK"
                value={days}
                options={DAYS_OPTIONS}
                onChange={setDays}
                title="Benchmark history window"
              />
              <button
                type="button"
                className={`btn btn--ghost${historyOn === 1 ? " regm-history-btn--on" : ""}`}
                onClick={() => setHistoryOn(historyOn === 1 ? 0 : 1)}
                aria-pressed={historyOn === 1}
                title="Fetch the rolling regime history timeline (action=history)"
              >
                HISTORY
              </button>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Re-classify regime"
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
          <StatusSection label="data_state" value={dataState ?? "—"} />
          <StatusDivider />
          <StatusSection
            label="confidence"
            value={
              confidence != null && Number.isFinite(confidence)
                ? confidence.toFixed(2)
                : "—"
            }
          />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="last" value={`${days}d`} tone="accent" />
          {historyOn === 1 ? (
            <>
              <StatusDivider />
              <StatusSection
                label="history"
                value={
                  historyState === "ok"
                    ? `${payloadHistoryCount(historyData?.data)} pts`
                    : historyState
                }
                tone="accent"
              />
            </>
          ) : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

interface RegimeRun {
  regime: string;
  trend: string;
  start: string;
  end: string;
  count: number;
}

/** Collapse consecutive equal-regime sessions into runs for a compact strip. */
function buildRegimeRuns(history: REGMHistoryEntry[]): RegimeRun[] {
  const runs: RegimeRun[] = [];
  for (const entry of history) {
    const regime = entry.regime ?? "unclassified";
    const trend = (entry.trend ?? "UNKNOWN").toUpperCase();
    const date = String(entry.date ?? "").slice(0, 10);
    const last = runs[runs.length - 1];
    if (last && last.regime === regime) {
      last.end = date || last.end;
      last.count += 1;
    } else {
      runs.push({ regime, trend, start: date, end: date, count: 1 });
    }
  }
  return runs;
}

/** Colour by the backend's trend label — never by a client-side guess. */
function trendFill(trend: string): string {
  switch (trend) {
    case "BULL":
      return "color-mix(in srgb, var(--positive) 64%, transparent)";
    case "BEAR":
      return "color-mix(in srgb, var(--negative) 64%, transparent)";
    case "SIDEWAYS":
      return "color-mix(in srgb, var(--text-mute) 42%, transparent)";
    default:
      return "repeating-linear-gradient(45deg, var(--surface-3), var(--surface-3) 3px, transparent 3px, transparent 6px)";
  }
}

/** Population per cluster id (labels are 0-based k-means ids). */
function clusterSizes(labels: number[], k?: number): number[] {
  const size = Math.max(k ?? 0, ...labels.map((l) => l + 1), 1);
  const counts = new Array<number>(size).fill(0);
  for (const label of labels) {
    if (label >= 0 && label < size) counts[label] += 1;
  }
  return counts;
}

function payloadHistoryCount(payload?: REGMHistoryData): number {
  return Array.isArray(payload?.history) ? payload.history.length : 0;
}

/**
 * Rolling regime timeline (`action=history`) — a compact coloured strip of
 * consecutive-regime runs plus the backend's k-means cluster label. Every
 * label shown is the backend's own string; an empty history renders an
 * honest "nothing to draw" state, never a placeholder strip.
 */
function RegimeHistoryPanel({
  state,
  payload,
  error,
  onRetry,
}: {
  state: "idle" | "loading" | "ok" | "error" | "refreshing" | "timeout";
  payload?: REGMHistoryData;
  error?: Error;
  onRetry: () => void;
}) {
  if (state === "loading" || state === "idle") {
    return <Skeleton height={54} />;
  }
  if (state === "error") {
    return (
      <section style={historyFrameStyle} aria-label="REGM regime timeline">
        <span style={muteTextStyle}>
          History fetch failed: {error?.message ?? "—"}
        </span>
        <button onClick={onRetry} className="btn" style={retryInlineStyle}>
          Retry
        </button>
      </section>
    );
  }
  if (payload?.status === "provider_unavailable") {
    return (
      <section style={historyFrameStyle} aria-label="REGM regime timeline">
        <span style={muteTextStyle}>
          {payload.provider_error
            ? `History unavailable: ${payload.provider_error}`
            : "History unavailable — the benchmark provider is unreachable; no regime is guessed."}
        </span>
      </section>
    );
  }
  const history = Array.isArray(payload?.history) ? payload.history : [];
  if (history.length === 0) {
    return (
      <section style={historyFrameStyle} aria-label="REGM regime timeline">
        <span style={muteTextStyle}>
          History mode returned no classified points — nothing is drawn.
        </span>
      </section>
    );
  }
  const runs = buildRegimeRuns(history);
  const cluster = payload?.cluster;
  const sizes = cluster?.labels?.length
    ? clusterSizes(cluster.labels, cluster.k)
    : null;
  const first = runs[0];
  const last = runs[runs.length - 1];
  return (
    <section style={historyFrameStyle} aria-label="REGM regime timeline">
      <div style={chartHeaderStyle}>
        <span style={historyTitleStyle}>Regime timeline</span>
        <span style={historyHintStyle}>
          {`${history.length} sessions · ${runs.length} runs · ${first.start} → ${last.end}`}
        </span>
      </div>
      <div
        style={timelineRowStyle}
        role="img"
        aria-label={`Regime timeline from ${first.start} to ${last.end}, ${runs.length} runs`}
      >
        {runs.map((run, i) => (
          <span
            key={`${run.start}-${i}`}
            title={`${run.start}${run.end !== run.start ? ` → ${run.end}` : ""} · ${run.regime} (${run.trend}) · ${run.count} session(s)`}
            style={{
              ...timelineSegStyle,
              flexGrow: Math.max(run.count, 1),
              background: trendFill(run.trend),
            }}
          />
        ))}
      </div>
      <div style={historyLegendStyle}>
        <span style={legendItemStyle}>
          <span
            aria-hidden
            style={{ ...legendDotStyle, background: trendFill("BULL") }}
          />
          BULL
        </span>
        <span style={legendItemStyle}>
          <span
            aria-hidden
            style={{ ...legendDotStyle, background: trendFill("BEAR") }}
          />
          BEAR
        </span>
        <span style={legendItemStyle}>
          <span
            aria-hidden
            style={{ ...legendDotStyle, background: trendFill("SIDEWAYS") }}
          />
          SIDEWAYS
        </span>
        <span style={legendItemStyle}>
          <span
            aria-hidden
            style={{ ...legendDotStyle, background: trendFill("UNKNOWN") }}
          />
          UNKNOWN
        </span>
        <span style={historyHintStyle}>
          {cluster
            ? `k-means k=${cluster.k ?? "—"} · cluster sizes ${sizes ? sizes.join(" / ") : "—"}`
            : "cluster label unavailable"}
        </span>
      </div>
    </section>
  );
}

/**
 * One regime card: the value is rendered verbatim from the backend.
 * Unknown values (UNKNOWN / null / "Cannot classify …") get an explicit
 * warn state — never replaced with a guessed classification.
 */
function RegimeCard({ label, value }: { label: string; value: string | null }) {  const unknown = isUnknownValue(value);
  return (
    <div style={cardStyle} aria-label={`REGM card ${label}`}>
      <div style={cardLabelStyle}>{label}</div>
      <div
        style={{
          ...cardValueStyle,
          color: unknown ? "var(--text-mute)" : "var(--text-primary)",
        }}
      >
        {unknown ? (value && value.trim() !== "" && value !== "—" ? value : "UNKNOWN") : value}
      </div>
      {unknown ? (
        <Pill tone="warn" variant="soft" withDot={false}>
          not reported — not guessed
        </Pill>
      ) : null}
    </div>
  );
}

const cardGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
  gap: 10,
};

const cardStyle: CSSProperties = {
  display: "grid",
  gap: 4,
  padding: "10px 12px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "var(--surface-1)",
  alignItems: "start",
};

const cardLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  letterSpacing: "0.06em",
  color: "var(--text-mute)",
  textTransform: "uppercase",
};

const cardValueStyle: CSSProperties = {
  fontSize: 14,
  fontWeight: 600,
  overflowWrap: "anywhere",
};

const stateStripStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  flexWrap: "wrap",
  border: "1px dashed var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "6px 10px",
};

const tableStyle: CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: "var(--font-size-sm)",
};

const thStyle: CSSProperties = {
  textAlign: "left",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--text-mute)",
  borderBottom: "1px solid var(--border-subtle)",
  padding: "4px 8px",
};

const tdStyle: CSSProperties = {
  borderBottom: "1px solid var(--border-subtle)",
  padding: "5px 8px",
  color: "var(--text-primary)",
  overflowWrap: "anywhere",
};

const methodologyStyle: CSSProperties = {
  fontSize: "var(--font-size-2xs)",
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-mute)",
  border: "1px dashed var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "6px 10px",
};

const historyFrameStyle: CSSProperties = {
  display: "grid",
  gap: 8,
  background: "var(--surface-2)",
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  padding: 12,
};

const chartHeaderStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  flexWrap: "wrap",
};

const historyTitleStyle: CSSProperties = {
  fontSize: "var(--font-size-md)",
  fontWeight: 600,
  color: "var(--text-primary)",
  letterSpacing: "0.02em",
};

const historyHintStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  letterSpacing: "0.04em",
};

const timelineRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "stretch",
  width: "100%",
  height: 18,
  borderRadius: 4,
  overflow: "hidden",
  gap: 1,
  background: "var(--surface-3)",
};

const timelineSegStyle: CSSProperties = {
  minWidth: 2,
  height: "100%",
};

const historyLegendStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 14,
  flexWrap: "wrap",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-secondary)",
};

const legendItemStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
};

const legendDotStyle: CSSProperties = {
  width: 10,
  height: 8,
  borderRadius: 2,
  display: "inline-block",
};

const retryInlineStyle: CSSProperties = {
  justifySelf: "start",
};

const muteTextStyle: CSSProperties = {
  fontSize: "var(--font-size-sm)",
  color: "var(--text-mute)",
};
