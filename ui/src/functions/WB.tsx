/**
 * WB — World Bonds (sovereign yield grid).
 *
 * Bloomberg `WB<GO>` analogue: sovereign 10Y yields by country with a
 * developed/emerging tab split, heatmap intensity per yield, a 30 s poll,
 * and a methodology footer. Binds to `/api/fn/WB` so the live FRED path
 * and the sovereign_yield_model fallback both reach the UI.
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
  Tabs,
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

interface WBRow {
  country?: string;
  tenor?: string;
  yield?: number;
  as_of?: string;
  source_mode?: string;
}

interface WBPayload {
  rows?: WBRow[];
  summary?: { countries?: number; tenor?: string; source_mode?: string };
  methodology?: string;
  field_dictionary?: Record<string, string>;
}

// Bucket countries the engine ships today (`_SOVEREIGN_FRED_IDS` /
// `_world_bond_template`) into the developed-market and emerging-market
// split that the WB tab strip surfaces. Anything unrecognised is grouped
// under "other" so the tab still renders if the catalog grows later.
const DEVELOPED = new Set(["US", "DE", "JP", "GB", "FR", "IT", "ES", "AU", "CA"]);
const EMERGING = new Set(["TR", "BR", "MX", "ZA", "IN", "CN", "RU", "ID"]);

const REGIONS = [
  { id: "all", label: "All" },
  { id: "dm", label: "Developed" },
  { id: "em", label: "Emerging" },
] as const;
type RegionId = (typeof REGIONS)[number]["id"];
const REGION_IDS = REGIONS.map((r) => r.id);

const REFRESH_MS = 30_000;

export function WBPane({ code }: FunctionPaneProps) {
  const [region, setRegion] = usePersistentOption<RegionId>(
    "showme.wb-region",
    REGION_IDS,
    "all",
  );
  const [live, setLive] = usePersistentOption<"on" | "off">(
    "showme.wb-live",
    ["on", "off"],
    "off",
  );
  // Bundle D / PERF-04. Visibility-aware poll.
  const tick = useVisibilityTick(REFRESH_MS);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: { live_bonds: live === "on", live: live === "on", tick },
  });

  const payload = useMemo<WBPayload>(
    () =>
      data?.data && typeof data.data === "object" && !Array.isArray(data.data)
        ? (data.data as WBPayload)
        : {},
    [data?.data],
  );

  const allRows = useMemo<WBRow[]>(() => {
    const rows = Array.isArray(payload.rows) ? payload.rows : [];
    return rows.filter((r) => r && typeof r.yield === "number" && Number.isFinite(r.yield));
  }, [payload.rows]);

  const rows = useMemo<WBRow[]>(() => {
    if (region === "all") return allRows;
    const set = region === "dm" ? DEVELOPED : EMERGING;
    return allRows.filter((r) => set.has((r.country ?? "").toUpperCase()));
  }, [allRows, region]);

  const stats = useMemo(() => deriveStats(allRows), [allRows]);
  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 16), [tick]);
  const sourceMode = payload.summary?.source_mode ?? rows[0]?.source_mode ?? "—";
  const isLiveSource = sourceMode === "fred";
  const noticeText =
    sourceMode === "sovereign_yield_model"
      ? "Rows are the labelled sovereign_yield_model template. Set `live` to on for live FRED yields."
      : null;

  const minYield = stats.min;
  const maxYield = stats.max;
  const range = Math.max(0.0001, maxYield - minYield);

  const cols = useMemo<DataGridColumn<WBRow>[]>(
    () => [
      {
        key: "country",
        header: "Country",
        width: 96,
        render: (r) => (
          <span style={countryCell}>
            <span aria-hidden style={countryDot} />
            {(r.country ?? "—").toUpperCase()}
          </span>
        ),
      },
      {
        key: "tenor",
        header: "Tenor",
        width: 80,
        render: (r) => (
          <Pill tone="muted" variant="soft" withDot={false}>
            {r.tenor ?? "10Y"}
          </Pill>
        ),
      },
      {
        key: "yield",
        header: "Yield",
        numeric: true,
        width: 110,
        render: (r) =>
          r.yield == null ? "—" : (
            <span style={numCell}>{r.yield.toFixed(2)}%</span>
          ),
      },
      {
        key: "heat",
        header: "Rank",
        width: 140,
        render: (r) => {
          if (r.yield == null) return "—";
          const pct = ((r.yield - minYield) / range) * 100;
          const tone = r.yield >= stats.avg ? "var(--negative)" : "var(--positive)";
          const intensity = 0.2 + (Math.abs(r.yield - stats.avg) / range) * 0.7;
          return (
            <span style={heatTrackWrap}>
              <span style={heatTrack} aria-hidden>
                <span
                  style={{
                    ...heatFill,
                    left: `${Math.max(0, Math.min(100, pct))}%`,
                    background: `color-mix(in srgb, ${tone} ${(intensity * 100).toFixed(0)}%, transparent)`,
                    boxShadow: `0 0 6px ${tone}`,
                  }}
                />
              </span>
            </span>
          );
        },
      },
      {
        key: "spread",
        header: "Δ vs US",
        numeric: true,
        width: 100,
        render: (r) => {
          if (r.yield == null) return "—";
          const us = allRows.find((row) => (row.country ?? "").toUpperCase() === "US");
          if (!us?.yield) return "—";
          const bp = (r.yield - us.yield) * 100;
          if (!Number.isFinite(bp)) return "—";
          const tone = bp >= 0 ? "var(--negative)" : "var(--positive)";
          return (
            <span style={{ ...numCell, color: tone, fontWeight: 600 }}>
              {bp >= 0 ? "+" : ""}
              {bp.toFixed(0)} bp
            </span>
          );
        },
      },
      {
        key: "source",
        header: "Source",
        width: 132,
        render: (r) =>
          r.source_mode === "fred" ? (
            <Pill tone="positive" variant="soft">live FRED</Pill>
          ) : (
            <Pill tone="warn" variant="soft">template</Pill>
          ),
      },
      {
        key: "as_of",
        header: "As of",
        width: 110,
        render: (r) => <span className="u-text-secondary u-mono">{r.as_of ?? "—"}</span>,
      },
    ],
    [allRows, minYield, range, stats.avg],
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="World sovereign bonds"
          subtitle={`${rows.length} of ${allRows.length} countries · poll ${REFRESH_MS / 1000}s · ${sourceMode}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>{rows.length} ctry</Pill>
              <Pill tone="accent" variant="soft" withDot={false}>{utcStamp} UTC</Pill>
              <Pill
                tone={isLiveSource ? "positive" : "warn"}
                variant="soft"
              >
                {isLiveSource ? "live" : "stub"}
              </Pill>
              <button
                type="button"
                onClick={() => setLive(live === "on" ? "off" : "on")}
                style={liveToggleStyle}
                aria-pressed={live === "on"}
              >
                live {live}
              </button>
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <div style={tabBarStyle}>
          <Tabs
            variant="segmented"
            items={REGIONS.map((r) => ({ id: r.id, label: r.label }))}
            active={region}
            onChange={(id) => setRegion(id as RegionId)}
          />
        </div>
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <Skeleton height={300} />
          ) : state === "error" ? (
            <Empty title="Function error" body={error?.message ?? "—"} icon="!" />
          ) : rows.length === 0 ? (
            <Empty title="No yields" body={`No WB rows for ${region}.`} />
          ) : (
            <div className="u-grid-gap-14">
              {noticeText ? (
                <div style={noticeStyle}>
                  <strong className="u-text-warn">Template rows</strong>
                  <span className="u-text-secondary">{noticeText}</span>
                </div>
              ) : null}
              <section style={kpiGrid} aria-label="WB KPI ribbon">
                <StatCard
                  label="Avg yield"
                  value={`${stats.avg.toFixed(2)}%`}
                  caption={`AS OF ${utcStamp} UTC · ${stats.count} ctry`}
                  tone={stats.avg >= 4 ? "negative" : "positive"}
                />
                <StatCard
                  label="Spread"
                  value={`${(maxYield - minYield).toFixed(2)} pp`}
                  caption={`${stats.minCountry} → ${stats.maxCountry}`}
                  tone="neutral"
                />
                <StatCard
                  label="Lowest"
                  value={`${minYield.toFixed(2)}%`}
                  caption={stats.minCountry || "—"}
                  tone="positive"
                />
                <StatCard
                  label="Highest"
                  value={`${maxYield.toFixed(2)}%`}
                  caption={stats.maxCountry || "—"}
                  tone="negative"
                />
              </section>
              <DataGrid
                columns={cols}
                rows={rows}
                rowKey={(r, i) => `${r.country ?? "row"}-${i}`}
                density="compact"
              />
              {payload.methodology ? (
                <div style={methodologyBox}>
                  <strong className="u-text-secondary">Methodology</strong>
                  <span>{payload.methodology}</span>
                </div>
              ) : null}
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={data?.sources?.join(", ") || sourceMode} />
          <StatusDivider />
          <StatusSection label="poll" value={`${REFRESH_MS / 1000}s`} />
          <StatusDivider />
          <StatusSection label="rows" value={rows.length} />
          <StatusDivider />
          <StatusSection label="elapsed" value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`} />
          <StatusDivider />
          <StatusSection label="mode" value={live} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

interface WBStats {
  count: number;
  avg: number;
  min: number;
  max: number;
  minCountry: string;
  maxCountry: string;
}

function deriveStats(rows: WBRow[]): WBStats {
  if (!rows.length) {
    return { count: 0, avg: 0, min: 0, max: 0, minCountry: "", maxCountry: "" };
  }
  let acc = 0;
  let min = Infinity;
  let max = -Infinity;
  let minCountry = "";
  let maxCountry = "";
  for (const r of rows) {
    if (r.yield == null) continue;
    acc += r.yield;
    if (r.yield < min) {
      min = r.yield;
      minCountry = (r.country ?? "").toUpperCase();
    }
    if (r.yield > max) {
      max = r.yield;
      maxCountry = (r.country ?? "").toUpperCase();
    }
  }
  return {
    count: rows.length,
    avg: acc / rows.length,
    min: Number.isFinite(min) ? min : 0,
    max: Number.isFinite(max) ? max : 0,
    minCountry,
    maxCountry,
  };
}

const tabBarStyle: CSSProperties = {
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const numCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
};

const countryCell: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  fontFamily: "JetBrains Mono, monospace",
  fontWeight: 600,
  letterSpacing: "0.04em",
  color: "var(--text-display)",
};

const countryDot: CSSProperties = {
  width: 6,
  height: 6,
  borderRadius: 3,
  background: "var(--accent)",
  boxShadow: "0 0 6px var(--accent)",
};

const heatTrackWrap: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  width: "100%",
};

const heatTrack: CSSProperties = {
  position: "relative",
  flex: "1 1 auto",
  height: 6,
  background: "var(--surface-3)",
  borderRadius: 999,
};

const heatFill: CSSProperties = {
  position: "absolute",
  top: -2,
  width: 10,
  height: 10,
  borderRadius: 5,
  transform: "translateX(-50%)",
};

const kpiGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: 10,
};

const noticeStyle: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  background: "var(--warn-soft)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
};

const methodologyBox: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "10px 12px",
  display: "grid",
  gap: 6,
};

const liveToggleStyle: CSSProperties = {
  background: "var(--surface-3)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-pill)",
  color: "var(--text-secondary)",
  cursor: "pointer",
  font: "inherit",
  padding: "2px 10px",
  fontSize: "var(--font-size-xs)",
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.04em",
};
