/**
 * CRPR — Credit Rating (model-implied).
 *
 * Bloomberg `CRPR<GO>` / `RATD<GO>` analogue. The sidecar derives a
 * long-term issuer rating bucket from financial fundamentals (leverage,
 * coverage, scale, profitability) and — where available — surfaces the
 * three major agency rows (S&P / Moody's / Fitch). The implied figure is
 * an in-house model output, NOT an official agency rating, so the pane
 * carries an honest "model-implied-from-financials" pill and never lets
 * the user mistake it for a live ratings feed.
 *
 * Visualization: a vertical AAA→D rating ladder with the issuer's marker
 * pinned at its implied bucket, a compact agency table, and KPI cards for
 * implied rating, debt/EBITDA, and interest coverage.
 */
import { useMemo, type CSSProperties } from "react";
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
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface CrprCard {
  label?: string;
  value?: string | number | null;
  caption?: string | null;
  hint?: string | null;
  tone?: string | null;
}

interface CrprAgencyRow {
  agency?: string;
  name?: string;
  rating?: string | null;
  outlook?: string | null;
  action?: string | null;
  date?: string | null;
}

interface CrprLadderRow {
  grade: string;
  label?: string | null;
  marker?: boolean | null;
  tone?: "ig" | "junk" | string | null;
}

interface CrprMetricRow {
  label?: string;
  value?: string | number | null;
  hint?: string | null;
}

interface CrprPayload {
  symbol?: string | null;
  as_of?: string | null;
  summary?: string | null;
  status?: string | null;
  reason?: string | null;
  implied_rating?: string | null;
  rating_bucket?: string | null;
  outlook?: string | null;
  cards?: CrprCard[] | null;
  rows?: CrprAgencyRow[] | null;
  agencies?: CrprAgencyRow[] | null;
  ladder?: CrprLadderRow[] | null;
  scale?: string[] | null;
  metrics?: CrprMetricRow[] | null;
  source_mode?: string | null;
  methodology?: string | null;
  warnings?: string[] | null;
}

/* Canonical S&P-style long-term rating scale, best (top) → worst (bottom). */
const DEFAULT_SCALE = [
  "AAA",
  "AA+",
  "AA",
  "AA-",
  "A+",
  "A",
  "A-",
  "BBB+",
  "BBB",
  "BBB-",
  "BB+",
  "BB",
  "BB-",
  "B+",
  "B",
  "B-",
  "CCC+",
  "CCC",
  "CCC-",
  "CC",
  "C",
  "D",
];

/* Investment grade = BBB- and above. */
const IG_FLOOR_INDEX = DEFAULT_SCALE.indexOf("BBB-");

const REFRESH_MS = 60_000;

const SCALE_MODES = ["compact", "full"] as const;
type ScaleMode = (typeof SCALE_MODES)[number];

export function CRPRPane({ code, symbol }: FunctionPaneProps) {
  const [scaleMode, setScaleMode] = usePersistentOption<ScaleMode>(
    "showme.crpr-scale",
    SCALE_MODES as unknown as ScaleMode[],
    "compact",
  );
  // Bundle D / PERF-04. Visibility-aware poll.
  const tick = useVisibilityTick(REFRESH_MS);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    symbol,
    params: { tick },
  });

  const payload = useMemo<CrprPayload>(
    () =>
      data?.data && typeof data.data === "object" && !Array.isArray(data.data)
        ? (data.data as CrprPayload)
        : {},
    [data?.data],
  );

  const impliedRating = useMemo(
    () => normGrade(payload.implied_rating ?? payload.rating_bucket),
    [payload.implied_rating, payload.rating_bucket],
  );

  const cards = useMemo<CrprCard[]>(
    () => (Array.isArray(payload.cards) ? payload.cards : []),
    [payload.cards],
  );

  const agencyRows = useMemo<CrprAgencyRow[]>(
    () =>
      Array.isArray(payload.rows)
        ? payload.rows
        : Array.isArray(payload.agencies)
          ? payload.agencies
          : [],
    [payload.rows, payload.agencies],
  );

  const metrics = useMemo<CrprMetricRow[]>(
    () => (Array.isArray(payload.metrics) ? payload.metrics : []),
    [payload.metrics],
  );

  const warnings = useMemo<string[]>(
    () =>
      Array.isArray(payload.warnings)
        ? payload.warnings
        : Array.isArray(data?.warnings)
          ? (data.warnings as string[])
          : [],
    [payload.warnings, data?.warnings],
  );

  /* Build the rating ladder: prefer an explicit ladder/scale from the
     backend, otherwise synthesize the canonical scale and mark the
     implied bucket. */
  const ladder = useMemo<CrprLadderRow[]>(() => {
    if (Array.isArray(payload.ladder) && payload.ladder.length) {
      return payload.ladder.map((r) => ({ ...r, grade: normGrade(r.grade) }));
    }
    const scale =
      Array.isArray(payload.scale) && payload.scale.length
        ? payload.scale.map(normGrade)
        : DEFAULT_SCALE;
    const floor = IG_FLOOR_INDEX < 0 ? 9 : IG_FLOOR_INDEX;
    return scale.map((grade, idx) => ({
      grade,
      marker: grade === impliedRating,
      tone: idx <= floor ? "ig" : "junk",
    }));
  }, [payload.ladder, payload.scale, impliedRating]);

  /* When compact, show a window around the marker so the ladder stays tight. */
  const visibleLadder = useMemo<CrprLadderRow[]>(() => {
    if (scaleMode === "full" || !ladder.length) return ladder;
    const markerIdx = ladder.findIndex(
      (r) => r.marker || r.grade === impliedRating,
    );
    if (markerIdx < 0) return ladder.slice(0, 11);
    const start = Math.max(0, markerIdx - 4);
    const end = Math.min(ladder.length, markerIdx + 5);
    return ladder.slice(start, end);
  }, [ladder, scaleMode, impliedRating]);

  const agencyColumns = useMemo<DataGridColumn<CrprAgencyRow>[]>(
    () => [
      {
        key: "agency",
        header: "Agency",
        width: 110,
        render: (r) => (
          <span style={agencyNameStyle}>{r.agency ?? r.name ?? "—"}</span>
        ),
      },
      {
        key: "rating",
        header: "Rating",
        numeric: true,
        width: 96,
        render: (r) => {
          const g = normGrade(r.rating);
          const idx = g ? DEFAULT_SCALE.indexOf(g) : -1;
          const ig = idx >= 0 ? idx <= IG_FLOOR_INDEX : null;
          return (
            <span
              style={{
                ...ratingCellStyle,
                color:
                  ig === null
                    ? "var(--text-display)"
                    : ig
                      ? "var(--positive)"
                      : "var(--negative)",
              }}
            >
              {r.rating ?? "—"}
            </span>
          );
        },
      },
      {
        key: "outlook",
        header: "Outlook",
        width: 100,
        render: (r) => (
          <span className="u-text-secondary">{r.outlook ?? "—"}</span>
        ),
      },
      {
        key: "action",
        header: "Last action",
        render: (r) => (
          <span className="u-text-secondary">
            {r.action ?? r.date ?? "—"}
          </span>
        ),
      },
    ],
    [],
  );

  const metricColumns = useMemo<DataGridColumn<CrprMetricRow>[]>(
    () => [
      {
        key: "label",
        header: "Metric",
        render: (r) => <span className="u-text-secondary">{r.label ?? "—"}</span>,
      },
      {
        key: "value",
        header: "Value",
        numeric: true,
        width: 140,
        render: (r) => <span style={metricValueStyle}>{fmtCell(r.value)}</span>,
      },
    ],
    [],
  );

  const src = classifySource(payload.source_mode, payload.status);
  const sources =
    data?.sources?.join(", ") ||
    String(payload.source_mode ?? "showMe credit model");
  const hasContent =
    cards.length > 0 ||
    agencyRows.length > 0 ||
    ladder.length > 0 ||
    !!impliedRating;

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Credit rating"
          subtitle={`${payload.symbol ?? symbol ?? "—"} · ${
            impliedRating || "n/a"
          } implied · poll ${REFRESH_MS / 1000}s`}
          trailing={
            <FunctionControlGroup>
              {impliedRating ? (
                <Pill tone="accent" variant="soft" withDot={false}>
                  {impliedRating}
                </Pill>
              ) : null}
              <span
                title={`source_mode: ${payload.source_mode ?? "model-implied"}`}
                style={{ display: "inline-flex" }}
              >
                <Pill tone={src.tone} variant="soft">
                  {src.label}
                </Pill>
              </span>
              <button
                type="button"
                onClick={() =>
                  setScaleMode(scaleMode === "full" ? "compact" : "full")
                }
                style={scaleToggleStyle}
                title="Toggle full AAA→D scale"
              >
                {scaleMode === "full" ? "compact scale" : "full scale"}
              </button>
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <div className="u-grid-gap-14">
              <Skeleton height={72} />
              <Skeleton height={300} />
            </div>
          ) : state === "error" ? (
            <Empty
              title="Credit rating unavailable"
              body={error?.message ?? "—"}
              icon="!"
            />
          ) : !hasContent ? (
            <Empty
              title="No rating data"
              body="The credit model returned no implied bucket for this issuer."
            />
          ) : (
            <div className="u-grid-gap-14">
              {src.tone !== "positive" ? (
                <section style={noticeStyle}>
                  <strong className="u-text-warn">
                    Model-implied rating — not an agency rating
                  </strong>
                  <span className="u-text-secondary">
                    {payload.reason ||
                      "The implied bucket is derived in-house from issuer financials (leverage, coverage, scale, profitability). It is a labelled model output, not an official S&P / Moody's / Fitch rating."}
                  </span>
                </section>
              ) : null}

              {payload.summary ? (
                <p style={summaryStyle}>{payload.summary}</p>
              ) : null}

              {/* KPI ribbon: implied rating, debt/EBITDA, interest coverage, … */}
              <section style={kpiGridStyle} aria-label="CRPR KPI ribbon">
                {cards.length ? (
                  cards.slice(0, 4).map((card, i) => (
                    <StatCard
                      key={`${card.label ?? "card"}-${i}`}
                      label={card.label ?? `Metric ${i + 1}`}
                      value={fmtCell(card.value)}
                      caption={card.caption ?? card.hint ?? undefined}
                      tone={cardTone(card.tone)}
                    />
                  ))
                ) : (
                  <StatCard
                    label="Implied rating"
                    value={impliedRating || "—"}
                    caption={payload.outlook ?? "long-term issuer"}
                    tone="neutral"
                  />
                )}
              </section>

              <StatusDivider />

              <div style={twoColLayout}>
                {/* Vertical AAA → D ladder with the issuer marker */}
                <aside style={ladderCard} aria-label="Rating ladder">
                  <div style={ladderHeaderStyle}>
                    <span style={metaLabel}>Rating ladder</span>
                    {impliedRating ? (
                      <Pill tone="accent" variant="soft" withDot={false}>
                        {impliedRating}
                      </Pill>
                    ) : null}
                  </div>
                  <div style={ladderWrapStyle}>
                    {visibleLadder.map((r) => {
                      const marked = !!r.marker || r.grade === impliedRating;
                      const isIG = r.tone === "ig";
                      return (
                        <div
                          key={r.grade}
                          style={{
                            ...ladderRowStyle,
                            background: marked
                              ? "color-mix(in srgb, var(--accent) 22%, transparent)"
                              : "transparent",
                            border: marked
                              ? "1px solid var(--accent)"
                              : "1px solid transparent",
                            color: marked
                              ? "var(--accent)"
                              : isIG
                                ? "var(--text-display)"
                                : "var(--text-secondary)",
                            fontWeight: marked ? 700 : 500,
                          }}
                          title={
                            marked
                              ? `Implied bucket: ${r.grade}`
                              : isIG
                                ? "Investment grade"
                                : "Speculative grade"
                          }
                        >
                          <span
                            aria-hidden
                            style={{
                              ...ladderDotStyle,
                              background: isIG
                                ? "var(--positive)"
                                : "var(--negative)",
                              opacity: marked ? 1 : 0.45,
                            }}
                          />
                          <span style={{ flex: 1 }}>{r.grade}</span>
                          {marked ? (
                            <span style={ladderMarkerStyle}>◀ ISSUER</span>
                          ) : r.label ? (
                            <span className="u-text-mute" style={{ fontSize: 10 }}>
                              {r.label}
                            </span>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                  <div style={legendStyle}>
                    <span style={{ color: "var(--positive)" }}>● Investment</span>
                    <span style={{ color: "var(--negative)" }}>● Speculative</span>
                  </div>
                </aside>

                {/* Agency rows + optional credit metrics */}
                <div className="u-grid-gap-14">
                  <div>
                    <div style={metaLabel}>Agency ratings</div>
                    {agencyRows.length ? (
                      <DataGrid
                        columns={agencyColumns}
                        rows={agencyRows}
                        rowKey={(r, i) => `${r.agency ?? r.name ?? "ag"}-${i}`}
                        density="compact"
                      />
                    ) : (
                      <Empty
                        title="No agency ratings"
                        body="S&P / Moody's / Fitch rows not available for this issuer."
                      />
                    )}
                  </div>

                  {metrics.length ? (
                    <div>
                      <div style={metaLabel}>Credit metrics</div>
                      <DataGrid
                        columns={metricColumns}
                        rows={metrics}
                        rowKey={(r, i) => `${r.label ?? "m"}-${i}`}
                        density="compact"
                      />
                    </div>
                  ) : null}
                </div>
              </div>

              {warnings.length ? (
                <section style={warningBox}>
                  <strong className="u-text-warn">Provider warnings</strong>
                  <ul style={warningList}>
                    {warnings.slice(0, 3).map((w, i) => (
                      <li key={i} className="u-text-secondary">
                        {String(w)}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {payload.methodology ? (
                <section style={methodPanel}>
                  <div style={metaLabel}>Methodology</div>
                  <p style={methodText}>{payload.methodology}</p>
                </section>
              ) : null}
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection label="model" value={src.label} tone="accent" />
          <StatusDivider />
          <StatusSection label="provider" value={sources} />
          <StatusDivider />
          <StatusSection label="poll" value={`${REFRESH_MS / 1000}s`} />
          <StatusDivider />
          <StatusSection label="agencies" value={agencyRows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          {payload.as_of ? (
            <>
              <StatusDivider />
              <StatusSection label="as of" value={payload.as_of} />
            </>
          ) : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

/** Normalize a rating string to compare against the scale (strip ws, upper). */
function normGrade(g?: string | null): string {
  return (g ?? "").trim().toUpperCase();
}

function fmtCell(v: string | number | null | undefined): string {
  if (v == null) return "—";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "—";
    return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  const s = String(v).trim();
  return s.length ? s : "—";
}

/* StatCard's tone union is only neutral|positive|negative. */
function cardTone(
  tone?: string | null,
): "positive" | "negative" | "neutral" {
  switch ((tone ?? "").toLowerCase()) {
    case "positive":
    case "up":
    case "ig":
    case "investment":
      return "positive";
    case "negative":
    case "down":
    case "junk":
    case "speculative":
      return "negative";
    default:
      return "neutral";
  }
}

/** Is this source mode honestly "live", or modeled / reference? */
function classifySource(
  mode?: string | null,
  status?: string | null,
): { label: string; tone: "positive" | "warn" | "muted" } {
  const m = (mode ?? "").toLowerCase();
  const s = (status ?? "").toLowerCase();
  if (s && s !== "ok") return { label: s.toUpperCase(), tone: "warn" };
  if (m === "live" || m === "realtime" || m === "agency") {
    return { label: "AGENCY LIVE", tone: "positive" };
  }
  if (m === "reference" || m === "ref" || m === "static" || m === "snapshot") {
    return { label: "REFERENCE", tone: "muted" };
  }
  if (m === "degraded" || m === "stale") {
    return { label: "DEGRADED", tone: "warn" };
  }
  return { label: "MODEL-IMPLIED", tone: "warn" };
}

const scaleToggleStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  letterSpacing: "0.02em",
  padding: "2px 8px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border-subtle)",
  background: "transparent",
  color: "var(--text-secondary)",
  cursor: "pointer",
};

const summaryStyle: CSSProperties = {
  margin: 0,
  color: "var(--text-secondary)",
  fontSize: 13,
  lineHeight: 1.5,
};

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 10,
};

const twoColLayout: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(190px, 0.7fr) minmax(0, 1.6fr)",
  gap: 14,
  alignItems: "start",
};

const ladderCard: CSSProperties = {
  display: "grid",
  gap: 8,
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-2)",
  padding: 12,
};

const ladderHeaderStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const ladderWrapStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
};

const ladderRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  padding: "3px 8px",
  borderRadius: "var(--radius-sm)",
  fontSize: 12,
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
};

const ladderDotStyle: CSSProperties = {
  width: 6,
  height: 6,
  borderRadius: "50%",
  flexShrink: 0,
};

const ladderMarkerStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.05em",
  fontWeight: 700,
};

const legendStyle: CSSProperties = {
  display: "flex",
  gap: 12,
  fontSize: 10,
  letterSpacing: "0.04em",
  color: "var(--text-mute)",
};

const agencyNameStyle: CSSProperties = {
  color: "var(--text-display)",
  fontWeight: 600,
};

const ratingCellStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontWeight: 700,
};

const metricValueStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-display)",
};

const noticeStyle: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  background: "var(--warn-soft)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
  fontSize: 12,
};

const warningBox: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 30%, transparent)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
  display: "grid",
  gap: 4,
};

const warningList: CSSProperties = {
  margin: 0,
  paddingLeft: 18,
  fontSize: "var(--font-size-xs)",
};

const methodPanel: CSSProperties = {
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  padding: 12,
  background: "var(--surface-2)",
};

const metaLabel: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  marginBottom: 6,
};

const methodText: CSSProperties = {
  margin: 0,
  color: "var(--text-secondary)",
  lineHeight: 1.5,
  fontSize: 12,
};
