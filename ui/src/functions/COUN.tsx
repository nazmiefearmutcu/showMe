/**
 * COUN — Country Guide.
 *
 * Combines a curated country reference profile with the LIVE policy-rate
 * row (BTMM/BIS) and FRED-sourced indicators when `live: true`. Header:
 * persisted country segmented control (`showme.coun.country`) + status
 * pills + refresh. Body: deduped indicator cards, and the full metrics
 * table with per-row value, unit, as-of date, and source-mode stamps.
 *
 * Known backend defect: when live data flows in, the `cards` payload lists
 * the Policy rate TWICE (live value prepended + stale reference value from
 * the profile). The pane dedupes cards by label keeping the FIRST
 * occurrence — the live-prepended one — and drops the stale duplicate.
 * Rows are already deduped server-side; their source_mode stamps make the
 * live-vs-reference split visible per metric.
 */
import { useMemo, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
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
import {
  buildGridCsv,
  downloadGridCsv,
  gridCsvFilename,
  type GridCsvColumn,
} from "@/design-system/grid-csv";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface COUNRow {
  key?: string;
  section?: string;
  metric?: string;
  value?: number | string | null;
  unit?: string;
  as_of?: string | null;
  series_id?: string;
  source_mode?: string;
  // True when the latest provider observation is older than its series limit.
  // The value keeps its as-of date but is not live.
  stale?: boolean;
  reason?: string;
  note?: string;
}

interface COUNCard {
  label?: string;
  value?: unknown;
}

interface COUNData {
  country?: string;
  rows?: COUNRow[];
  cards?: COUNCard[];
  source_mode?: string;
  country_known?: boolean;
  // Explicit no-profile state for an uncurated country on the live path.
  profile_state?: { status?: string; reason?: string };
}

const COUNTRY_OPTIONS = [
  { value: "US", label: "US" },
  { value: "EU", label: "EU" },
  { value: "GB", label: "GB" },
  { value: "TR", label: "TR" },
] as const;
const COUNTRY_IDS = COUNTRY_OPTIONS.map((o) => o.value);

function isReferenceMode(mode?: string): boolean {
  const normalized = (mode ?? "").toLowerCase();
  return normalized.includes("reference") || normalized.includes("baseline");
}

// `provider_unavailable`: the backend found no live observation for this
// metric. It is neither live nor reference, and carries no value.
function isUnavailableMode(mode?: string): boolean {
  return (mode ?? "").toLowerCase().includes("unavailable");
}

export function COUNPane({ code }: FunctionPaneProps) {
  const [country, setCountry] = usePersistentOption<string>(
    "showme.coun.country",
    COUNTRY_IDS,
    "US",
  );

  const { state, data, error, refetch } = useFunction<COUNData>({
    code,
    params: { country, live: true, timeout: 8 },
  });

  const payload = data?.data;
  const rows = useMemo(() => payload?.rows ?? [], [payload]);
  // Backend warnings (provider failures, missing curated profile, ignored
  // metric names) plus the explicit profile_state reason, shown outside the
  // body so they stay visible even when no rows come back.
  const notices = useMemo(() => {
    const out: string[] = [...(data?.warnings ?? [])];
    const profileReason = payload?.profile_state?.reason;
    if (profileReason && !out.includes(profileReason)) out.push(profileReason);
    return out;
  }, [data, payload]);

  // DEFECT WORKAROUND: the payload's cards duplicate the Policy rate (live
  // value prepended first, stale reference value later). Dedupe by label,
  // first occurrence wins (= the live-prepended card).
  const cards = useMemo(() => {
    const seen = new Set<string>();
    const out: COUNCard[] = [];
    for (const card of payload?.cards ?? []) {
      const label = String(card.label ?? "").trim();
      if (!label || seen.has(label.toLowerCase())) continue;
      seen.add(label.toLowerCase());
      out.push(card);
    }
    return out;
  }, [payload]);

  // Live means a fresh row with a value from a real provider; reference-profile,
  // unavailable and stale rows never make the pane live.
  const isLive =
    state === "ok" &&
    rows.some(
      (r) =>
        r.value != null &&
        !isReferenceMode(r.source_mode) &&
        !isUnavailableMode(r.source_mode) &&
        !r.stale,
    );
  const hasUnavailable = rows.some((r) => isUnavailableMode(r.source_mode));
  const hasStale = rows.some((r) => r.stale === true);
  const hasReferenceRows = rows.some((r) => isReferenceMode(r.source_mode));

  // CSV export of the country metrics table — RAW payload values (a numeric
  // value stays numeric; string values pass through unchanged).
  const csvColumns = useMemo<GridCsvColumn<COUNRow>[]>(
    () => [
      { key: "section", header: "Section", value: (r) => r.section ?? "" },
      { key: "metric", header: "Metric", value: (r) => r.metric ?? "" },
      { key: "value", header: "Value", value: (r) => r.value ?? "" },
      { key: "unit", header: "Unit", value: (r) => r.unit ?? "" },
      { key: "as_of", header: "As of", value: (r) => r.as_of ?? "" },
      {
        key: "series_id",
        header: "Series ID",
        value: (r) => r.series_id ?? "",
      },
      {
        key: "source_mode",
        header: "Source",
        value: (r) => r.source_mode ?? "",
      },
    ],
    [],
  );

  const exportCsv = () => {
    const csv = buildGridCsv(csvColumns, rows);
    downloadGridCsv(gridCsvFilename(`coun-${country}`), csv);
  };

  const COLS: DataGridColumn<COUNRow>[] = useMemo(
    () => [
      {
        key: "metric",
        header: "Metric",
        width: 210,
        sortable: true,
        sortValue: (r) => r.metric ?? "",
        render: (r) => (
          <span>
            <span style={monoStrongStyle}>{r.metric || "—"}</span>
            <span style={sectionSubStyle}>{r.section ?? ""}</span>
            {r.note ? <span style={sectionSubStyle}>{r.note}</span> : null}
            {r.reason ? <span style={reasonStyle}>{r.reason}</span> : null}
          </span>
        ),
      },
      {
        key: "value",
        header: "Value",
        numeric: true,
        width: 150,
        sortable: true,
        sortValue: (r) => {
          if (r.value == null) return null;
          if (typeof r.value === "number") return r.value;
          const n = Number(r.value);
          return Number.isFinite(n) ? n : String(r.value);
        },
        render: (r) => (
          <span style={monoPrimaryStyle}>
            {fmtValue(r.value)}
            {r.unit ? ` ${r.unit}` : ""}
          </span>
        ),
      },
      {
        key: "as_of",
        header: "As of",
        width: 110,
        sortable: true,
        sortValue: (r) => r.as_of ?? "",
        render: (r) => (
          <span style={monoMutedStyle}>
            {r.as_of ? String(r.as_of).slice(0, 10) : "—"}
          </span>
        ),
      },
      {
        key: "source_mode",
        header: "Source",
        width: 210,
        sortable: true,
        sortValue: (r) => r.source_mode ?? "",
        render: (r) =>
          r.source_mode ? (
            <Pill
              tone={
                isUnavailableMode(r.source_mode) || r.stale
                  ? "warn"
                  : isReferenceMode(r.source_mode)
                    ? "muted"
                    : "accent"
              }
              variant="soft"
              withDot={false}
            >
              {r.source_mode}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
    ],
    [],
  );

  const body = (
    <PaneState
      state={state}
      error={error}
      empty={rows.length === 0}
      emptyTitle="No country metrics returned"
      emptyBody={`No profile or live macro rows came back for ${country}.`}
      emptyIcon="⚑"
      onRetry={refetch}
    >
      <div className="u-grid-gap-14">
        <section style={kpiGridStyle} aria-label="COUN indicator cards">
          {cards.slice(0, 5).map((card) => (
            <StatCard
              key={String(card.label)}
              label={String(card.label ?? "—")}
              value={fmtValue(card.value)}
              caption={cardCaption(card, rows)}
              tone="neutral"
            />
          ))}
        </section>
        <DataGrid
          columns={COLS}
          rows={rows}
          rowKey={(r, i) => `${r.section ?? ""}-${r.metric ?? ""}-${i}`}
          density="compact"
          ariaLabel="Country guide metrics"
          defaultSortKey="metric"
          defaultSortDir="none"
        />
      </div>
    </PaneState>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Country Guide"
          subtitle={`${country} · economy, prices, labor, fiscal · live macro with reference fallback`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive
                  ? hasReferenceRows
                    ? "live+ref"
                    : "live"
                  : hasStale
                    ? "stale"
                    : hasUnavailable
                      ? "unavailable"
                      : "reference"}
              </Pill>
              <SegmentedControl
                label="COUNTRY"
                value={country}
                options={COUNTRY_OPTIONS}
                onChange={setCountry}
              />
              <button
                type="button"
                className="btn"
                onClick={exportCsv}
                disabled={rows.length === 0}
                title="Download CSV"
                aria-label={`Download ${rows.length} country metrics as CSV`}
              >
                CSV
              </button>
              <LoadStatePill state={state} status={rows.length ? "ok" : null} />
              <RefreshButton loading={state === "loading"} onClick={refetch} title="Refresh country guide" />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          {notices.length > 0 ? (
            <div role="note" aria-label="COUN warnings" style={noticeStyle}>
              {notices.map((notice, i) => (
                <span key={i} style={noticeLineStyle}>
                  {notice}
                </span>
              ))}
            </div>
          ) : null}
          {body}
        </PaneBody>
        <PaneFooter>
          <StatusSection label="country" value={country} tone="accent" />
          <StatusDivider />
          <StatusSection label="metrics" value={rows.length} />
          <StatusDivider />
          <StatusSection label="mode" value={payload?.source_mode ?? "—"} />
          <StatusDivider />
          <StatusSection label="elapsed" value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`} />
          <StatusDivider />
          <StatusSection label="sources" value={data?.sources?.join(", ") || "—"} />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function cardCaption(card: COUNCard, rows: COUNRow[]): string {
  const label = String(card.label ?? "").toLowerCase();
  // The currency code is a fact, not a statistic: it has no provider row.
  if (label === "currency") return "CURRENCY CODE";
  const match = rows.find(
    (r) => (r.metric ?? "").toLowerCase() === label || label.includes(String(r.metric ?? "\u0000").toLowerCase()),
  );
  if (!match) return "NO LIVE ROW";
  if (isUnavailableMode(match.source_mode)) return "UNAVAILABLE";
  if (match.stale) return `STALE · ${String(match.as_of ?? "").slice(0, 10)}`;
  if (match.as_of) {
    return `${isReferenceMode(match.source_mode) ? "REF" : "LIVE"} · ${String(match.as_of).slice(0, 10)}`;
  }
  return isReferenceMode(match.source_mode) ? "REFERENCE PROFILE" : "LIVE";
}

function fmtValue(v: unknown): string {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return String(v);
  return n.toLocaleString("en-US", { maximumFractionDigits: 3 });
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 10,
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

const reasonStyle: CSSProperties = {
  display: "block",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  whiteSpace: "normal",
};

const noticeStyle: CSSProperties = {
  display: "grid",
  gap: 4,
  margin: "0 0 10px",
  padding: "8px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-2xs)",
};

const noticeLineStyle: CSSProperties = {
  display: "block",
};

const sectionSubStyle: CSSProperties = {
  display: "block",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
};
