/**
 * CRVF — Yield Curve.
 *
 * Sovereign yield curve ordered by maturity. Header: tenor count + data-mode
 * pill + refresh. Body: inline-SVG maturity curve (tenor years → yield) +
 * headline cards (2s10s slope, long-short slope, 10Y reference) + tenor
 * table with spread-vs-reference in bps.
 *
 * Data honesty: when the live FRED curve is not used, the backend returns its
 * labelled computed-model curve and the pane shows a MODEL FIXTURE pill plus
 * an inline notice with the backend's reason. A non-US country returns an
 * explicit unavailable state, never the US levels under another label.
 * The tenor chips send the `tenors` filter; with none picked the full curve
 * comes back. The country select sends `country` for non-US choices, and the
 * Live FRED switch sends `live_curve=false` to request the labelled model curve.
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
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface CRVFRow {
  country?: string;
  tenor?: string;
  tenor_years?: number;
  yield?: number;
  as_of?: string;
}

interface CRVFData {
  status?: string;
  reason?: string;
  rows?: CRVFRow[];
  curve?: CRVFRow[];
  summary?: {
    country?: string;
    tenors?: number;
    source_mode?: string;
    latest_10y?: number;
  };
  methodology?: string;
  field_dictionary?: Record<string, unknown>;
}

const CHART_W = 620;
const CHART_H = 190;
const PAD = { top: 12, right: 14, bottom: 26, left: 38 };

// Mirrors the CRVF manifest `tenors` options (backend crvf_seed.py).
const TENOR_OPTIONS = ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"];
// Mirrors the CRVF manifest `country` options (backend crvf_seed.py). Only US has a
// curve; other countries return the backend's explicit unavailable state.
const COUNTRY_OPTIONS = ["US", "DE", "JP", "GB", "FR", "IT", "ES", "AU", "CA", "TR"];

export function CRVFPane({ code, symbol }: FunctionPaneProps) {
  const effectiveSymbol =
    symbol || defaultSymbolForFunction(code, ["EQUITY", "BOND"]);
  const [tenorPick, setTenorPick] = useState<string[]>([]);
  const [country, setCountry] = useState("US");
  const [live, setLive] = useState(true);
  // Defaults send no params: the backend serves the US live curve. Only the
  // non-default choices are sent.
  const requestParams = useMemo(() => {
    const params: Record<string, unknown> = {};
    if (country !== "US") params.country = country;
    if (!live) params.live_curve = false;
    if (tenorPick.length) params.tenors = tenorPick;
    return Object.keys(params).length ? params : undefined;
  }, [country, live, tenorPick]);
  const toggleTenor = (tenor: string) => {
    setTenorPick((prev) => {
      const next = new Set(prev);
      if (next.has(tenor)) next.delete(tenor);
      else next.add(tenor);
      return TENOR_OPTIONS.filter((t) => next.has(t));
    });
  };
  const { state, data, error, refetch } = useFunction<CRVFData>({
    code,
    symbol: effectiveSymbol,
    params: requestParams,
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows: CRVFRow[] = useMemo(() => {
    const raw = payload?.curve && payload.curve.length ? payload.curve : payload?.rows ?? [];
    return [...raw]
      .filter((r) => typeof r.tenor_years === "number" && typeof r.yield === "number")
      .sort((a, b) => (a.tenor_years ?? 0) - (b.tenor_years ?? 0));
  }, [payload]);

  const summary = payload?.summary;
  const sourceMode = summary?.source_mode ?? "computed_model";
  const isUnavailable = payload?.status === "provider_unavailable";
  const isModelFixture = sourceMode !== "fred";
  // The backend reason for the fallback (a FRED failure, or reference mode
  // requested). Never a guessed cause such as a missing key.
  const fixtureCause = data?.warnings?.[0] ?? "reference curve requested";

  const ref = useMemo(() => deriveReference(rows, summary?.latest_10y), [rows, summary?.latest_10y]);
  const stats = useMemo(() => deriveCurveStats(rows), [rows]);

  const COLS: DataGridColumn<CRVFRow>[] = useMemo(
    () => [
      {
        key: "tenor",
        header: "Tenor",
        width: 96,
        render: (r) => <span style={monoStrongStyle}>{r.tenor ?? "—"}</span>,
      },
      {
        key: "tenor_years",
        header: "Maturity",
        numeric: true,
        width: 104,
        render: (r) => (
          <span style={monoMutedStyle}>
            {r.tenor_years != null ? `${fmtYears(r.tenor_years)}y` : "—"}
          </span>
        ),
      },
      {
        key: "yield",
        header: "Yield",
        numeric: true,
        width: 110,
        render: (r) => (
          <span style={monoPrimaryStyle}>{fmtPct(r.yield)}</span>
        ),
      },
      {
        key: "spread",
        header: `Spread vs ${ref.tenor ?? "ref"}`,
        numeric: true,
        width: 150,
        render: (r) => {
          const bps =
            typeof r.yield === "number" && ref.yield != null
              ? (r.yield - ref.yield) * 100
              : null;
          return (
            <span style={{ ...monoStrongStyle, color: bpsColor(bps) }}>
              {fmtSignedBps(bps)}
            </span>
          );
        },
      },
      {
        key: "as_of",
        header: "As of",
        width: 116,
        render: (r) => (
          <span style={monoMutedStyle}>{String(r.as_of ?? "—").slice(0, 10)}</span>
        ),
      },
    ],
    [ref],
  );

  const body =
    state === "loading" || state === "idle" ? (
      <div className="u-grid-gap-8">
        <Skeleton height={CHART_H} />
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
    ) : payload?.status === "provider_unavailable" ? (
      <Empty
        title={`Curve unavailable — ${summary?.country ?? "country"}`}
        body={payload.reason ?? "The backend has no curve for this country."}
        icon="!"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : payload?.status === "empty" ? (
      <Empty
        title="No curve points for this selection"
        body={payload.reason ?? "The tenor filter matches no curve point."}
        icon="∅"
        action={
          <button type="button" onClick={() => setTenorPick([])} className="btn">
            Clear tenor filter
          </button>
        }
      />
    ) : rows.length === 0 ? (
      <Empty
        title="No curve returned"
        body="The backend returned no tenor points — retry or check the curve provider."
        icon="∅"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : (
      <div className="u-grid-gap-14">
        {isModelFixture ? (
          <div role="note" style={noticeStyle}>
            <strong>Computed-model curve.</strong> The live FRED curve was not
            used ({fixtureCause}), so the backend served its labelled reference
            fixture — these are static levels, NOT live market yields.
          </div>
        ) : null}
        <section style={kpiGridStyle} aria-label="CRVF curve stats">
          <StatCard
            label="2s10s slope"
            value={fmtSignedBps(stats.slope2s10s)}
            caption={stats.slope2s10s != null && stats.slope2s10s < 0 ? "INVERTED" : "UPWARD"}
            tone={stats.slope2s10s != null && stats.slope2s10s < 0 ? "negative" : "neutral"}
          />
          <StatCard
            label="Long-short"
            value={fmtSignedBps(stats.slopeLongShort)}
            caption="30Y − 1M"
            tone="neutral"
          />
          <StatCard
            label={`${ref.tenor ?? "REF"} reference`}
            value={fmtPct(ref.yield)}
            caption="SPREAD BASE FOR TABLE"
            tone="neutral"
          />
          <StatCard
            label="Front yield"
            value={fmtPct(stats.frontYield)}
            caption={`TENOR ${stats.frontTenor ?? "—"}`}
            tone="neutral"
          />
        </section>
        <figure style={figureStyle} aria-label="CRVF maturity curve chart">
          <CurveChart rows={rows} />
          <figcaption style={captionStyle}>
            <span style={legendItemStyle}>
              <span aria-hidden="true" style={swatchStyle} /> yield by maturity
            </span>
            <span>x-axis: maturity in years (sqrt-scaled for readability)</span>
          </figcaption>
        </figure>
        <DataGrid
          columns={COLS}
          rows={rows}
          rowKey={(r, i) => `${r.tenor ?? "t"}-${i}`}
          density="compact"
          ariaLabel="CRVF tenor table"
        />
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Yield Curve — ${summary?.country ?? "US"}`}
          subtitle={`${effectiveSymbol || "—"} · ${rows.length} tenors`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} tenors
              </Pill>
              <Pill
                tone={isUnavailable ? "warn" : isModelFixture ? "warn" : "positive"}
                variant="soft"
                withDot={!isModelFixture && !isUnavailable}
              >
                {isUnavailable
                  ? "unavailable"
                  : isModelFixture
                    ? "model fixture"
                    : "FRED live"}
              </Pill>
              <LoadStatePill state={state} status={sourceMode} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh yield curve"
              />
            </FunctionControlGroup>
          }
        />
        <div role="group" aria-label="Curve controls" style={tenorBarStyle}>
          <label style={tenorChipStyle}>
            Country{" "}
            <select
              aria-label="Country"
              value={country}
              onChange={(e) => setCountry(e.target.value)}
              style={selectStyle}
            >
              {COUNTRY_OPTIONS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            aria-pressed={live}
            onClick={() => setLive((v) => !v)}
            style={live ? tenorChipOnStyle : tenorChipStyle}
            title="On: FRED live US curve. Off: the labelled computed-model curve (not live)."
          >
            Live FRED
          </button>
        </div>
        <div role="group" aria-label="Tenor filter" style={tenorBarStyle}>
          {TENOR_OPTIONS.map((t) => {
            const on = tenorPick.includes(t);
            return (
              <button
                key={t}
                type="button"
                aria-pressed={on}
                onClick={() => toggleTenor(t)}
                style={on ? tenorChipOnStyle : tenorChipStyle}
              >
                {t}
              </button>
            );
          })}
          {tenorPick.length ? (
            <button
              type="button"
              onClick={() => setTenorPick([])}
              style={tenorChipStyle}
            >
              All
            </button>
          ) : null}
        </div>
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection label="mode" value={sourceMode} />
          <StatusDivider />
          <StatusSection label="tenors" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection
            label="country"
            value={summary?.country ?? "US"}
            tone="accent"
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── chart ─────────────────────────────────────────────────────────── */

function CurveChart({ rows }: { rows: CRVFRow[] }) {
  const points = useMemo(() => {
    const yields = rows.map((r) => r.yield ?? 0);
    const minY = Math.min(...yields);
    const maxY = Math.max(...yields);
    const spanY = maxY - minY || 1;
    const maxX = Math.sqrt(Math.max(...rows.map((r) => r.tenor_years ?? 0), 0.0001));
    const innerW = CHART_W - PAD.left - PAD.right;
    const innerH = CHART_H - PAD.top - PAD.bottom;
    const x = (ty: number) =>
      PAD.left + (Math.sqrt(Math.max(ty, 0.0001)) / maxX) * innerW;
    const y = (yld: number) =>
      PAD.top + (1 - (yld - minY) / spanY) * innerH;
    return {
      line: rows
        .map((r) => `${x(r.tenor_years ?? 0).toFixed(1)},${y(r.yield ?? 0).toFixed(1)}`)
        .join(" "),
      dots: rows.map((r) => ({
        tenor: r.tenor ?? "?",
        yld: r.yield ?? 0,
        cx: x(r.tenor_years ?? 0),
        cy: y(r.yield ?? 0),
      })),
      grid: [0, 0.5, 1].map((f) => ({
        y: PAD.top + f * innerH,
        yld: maxY - f * spanY,
      })),
      xLabels: rows
        .filter((_, i) => i === 0 || i === rows.length - 1 || i === Math.floor(rows.length / 2))
        .map((r) => ({
          label: r.tenor ?? "",
          cx: x(r.tenor_years ?? 0),
        })),
    };
  }, [rows]);

  return (
    <svg
      viewBox={`0 0 ${CHART_W} ${CHART_H}`}
      role="img"
      aria-label={`Maturity curve with ${rows.length} tenor points`}
      style={svgStyle}
    >
      {points.grid.map((g, i) => (
        <g key={i}>
          <line
            x1={PAD.left}
            x2={CHART_W - PAD.right}
            y1={g.y}
            y2={g.y}
            stroke="var(--grid-color, var(--text-mute))"
            strokeWidth={1}
          />
          <text x={4} y={g.y + 3} style={axisTextStyle}>
            {g.yld.toFixed(2)}
          </text>
        </g>
      ))}
      <polyline
        points={points.line}
        fill="none"
        stroke="var(--accent)"
        strokeWidth={1.6}
      />
      {points.dots.map((d) => (
        <circle key={d.tenor} cx={d.cx} cy={d.cy} r={3.2} fill="var(--accent)">
          <title>{`${d.tenor}: ${d.yld.toFixed(3)}%`}</title>
        </circle>
      ))}
      {points.xLabels.map((l) => (
        <text
          key={l.label}
          x={l.cx}
          y={CHART_H - 8}
          textAnchor="middle"
          style={axisTextStyle}
        >
          {l.label}
        </text>
      ))}
    </svg>
  );
}

/* ── stats helpers ─────────────────────────────────────────────────── */

function yieldAt(rows: CRVFRow[], tenor: string): number | null {
  const row = rows.find((r) => r.tenor === tenor);
  return typeof row?.yield === "number" ? row.yield : null;
}

interface CurveStats {
  slope2s10s: number | null;
  slopeLongShort: number | null;
  frontYield: number | null;
  frontTenor: string | null;
}

function deriveCurveStats(rows: CRVFRow[]): CurveStats {
  const y2 = yieldAt(rows, "2Y");
  const y10 = yieldAt(rows, "10Y");
  const y30 = yieldAt(rows, "30Y");
  const y1m = yieldAt(rows, "1M");
  const first = rows[0];
  return {
    slope2s10s: y2 != null && y10 != null ? (y10 - y2) * 100 : null,
    slopeLongShort: y1m != null && y30 != null ? (y30 - y1m) * 100 : null,
    frontYield: typeof first?.yield === "number" ? first.yield : null,
    frontTenor: first?.tenor ?? null,
  };
}

function deriveReference(
  rows: CRVFRow[],
  latest10y: number | undefined,
): { tenor: string | null; yield: number | null } {
  const row10 = rows.find((r) => r.tenor === "10Y");
  if (row10 && typeof row10.yield === "number") {
    return { tenor: "10Y", yield: row10.yield };
  }
  if (typeof latest10y === "number" && Number.isFinite(latest10y)) {
    return { tenor: "10Y", yield: latest10y };
  }
  const last = rows[rows.length - 1];
  if (last && typeof last.yield === "number") {
    return { tenor: last.tenor ?? null, yield: last.yield };
  }
  return { tenor: null, yield: null };
}

/* ── formatting ────────────────────────────────────────────────────── */

function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v.toFixed(3)}%`;
}

function fmtSignedBps(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)} bps`;
}

function fmtYears(v: number): string {
  return v < 1 ? v.toFixed(2) : String(v);
}

function bpsColor(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "var(--text-mute)";
  return v >= 0 ? "var(--positive)" : "var(--negative)";
}

/* ── styles ────────────────────────────────────────────────────────── */

const tenorBarStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
  padding: "6px 10px",
};

const tenorChipStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  padding: "2px 7px",
  border: "1px solid var(--text-mute)",
  borderRadius: 4,
  background: "transparent",
  color: "var(--text-mute)",
  cursor: "pointer",
};

const tenorChipOnStyle: CSSProperties = {
  ...tenorChipStyle,
  borderColor: "var(--accent)",
  color: "var(--accent)",
};

const selectStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  background: "transparent",
  color: "var(--text-primary)",
  border: "1px solid var(--text-mute)",
  borderRadius: 4,
  padding: "1px 4px",
};

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const noticeStyle: CSSProperties = {
  border: "1px solid var(--warn, var(--text-mute))",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: "var(--font-size-md)",
  color: "var(--text-primary)",
};

const figureStyle: CSSProperties = {
  margin: 0,
};

const captionStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
  marginTop: 4,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
};

const legendItemStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
};

const swatchStyle: CSSProperties = {
  width: 10,
  height: 3,
  background: "var(--accent)",
};

const svgStyle: CSSProperties = {
  width: "100%",
  height: "auto",
  display: "block",
};

const axisTextStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  fill: "var(--text-mute)",
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

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
};
