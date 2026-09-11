/**
 * DARK — Dark Pool Volume (FINRA ATS off-exchange volume by venue/MPID).
 *
 * Keyless FINRA OTC Transparency weekly ATS aggregates per venue, joined
 * with yfinance weekly totals for a real dark-pool %. Header: weeks
 * segmented control (persisted `showme.dark.weeks`) + status pill +
 * refresh. Body: off-exchange headline cards, weekly ATS-volume
 * sparkline (design-system `Sparkline`) and the venue table with
 * share-of-ATS tint bars.
 *
 * Data honesty: FINRA data may be missing or stale — a
 * provider_unavailable payload with rows still renders them, but under a
 * prominent stale/unavailable banner carrying the backend reason, and a
 * fully empty payload renders `next_actions` instead of any numbers.
 * dark_pool_pct is only shown when the weekly total volume actually
 * joined; otherwise an explicit "—" (never a guess).
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
  Sparkline,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import {
  buildGridCsv,
  downloadGridCsv,
  gridCsvFilename,
  type GridCsvColumn,
} from "@/design-system/grid-csv";
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

/* ── payload types (probed from /api/fn/DARK) ──────────────────────── */

interface DarkVenueRow {
  venue?: string;
  ats_share_volume?: number;
  ats_trade_count?: number;
  share_of_ats_pct?: number | null;
  dark_pool_pct?: number | null;
  weekStartDate?: string | null;
  source_mode?: string;
}

interface DarkWeekRow {
  weekStartDate?: string;
  ats_share_volume?: number;
  ats_trade_count?: number;
  n_venues?: number;
  total_weekly_volume?: number | null;
  dark_pool_pct?: number | null;
  source_mode?: string;
}

interface DarkCards {
  latest_dark_pool_pct?: number | null;
  latest_ats_volume?: number | null;
  venue_count?: number;
  data_mode?: string;
  as_of?: string | null;
}

interface DarkData {
  status?: string;
  reason?: string | null;
  symbol?: string;
  n_rows?: number;
  total_shares_off_exchange?: number;
  top_venue_share_pct?: number | null;
  rows?: DarkVenueRow[];
  venues?: DarkVenueRow[];
  by_venue?: DarkVenueRow[];
  by_week?: DarkWeekRow[];
  history?: DarkWeekRow[];
  cards?: DarkCards;
  summary?: { latest_week?: string | null; latest_dark_pool_pct?: number | null; venue_count?: number };
  next_actions?: string[];
  methodology?: string;
}

const WEEKS_OPTIONS = [
  { value: 4, label: "4w" },
  { value: 8, label: "8w" },
  { value: 12, label: "12w" },
  { value: 26, label: "26w" },
] as const;
const WEEKS_IDS = WEEKS_OPTIONS.map((o) => o.value);

/* ── pane ──────────────────────────────────────────────────────────── */

export function DARKPane({ code, symbol }: FunctionPaneProps) {
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const [weeks, setWeeks] = usePersistentOption<number>(
    "showme.dark.weeks",
    WEEKS_IDS,
    8,
  );
  const { state, data, error, refetch } = useFunction<DarkData>({
    code,
    symbol: effectiveSymbol,
    params: { weeks },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const warnings: string[] = data?.warnings ?? [];
  const venues: DarkVenueRow[] = useMemo(
    () =>
      (payload?.venues && payload.venues.length
        ? payload.venues
        : payload?.by_venue ?? payload?.rows ?? []),
    [payload],
  );
  const byWeek: DarkWeekRow[] = useMemo(() => payload?.by_week ?? [], [payload]);
  // by_week arrives newest-first; the sparkline is chronological.
  const weekVolumes = useMemo(
    () =>
      [...byWeek]
        .reverse()
        .map((w) => (typeof w.ats_share_volume === "number" && Number.isFinite(w.ats_share_volume) ? w.ats_share_volume : null))
        .filter((v): v is number => v != null),
    [byWeek],
  );
  const status = payload?.status ?? "—";
  const isLive = state === "ok" && status === "ok";
  const degraded = !isLive && venues.length > 0; // stale / partial — still renderable
  const totalOffExchange = num(payload?.total_shares_off_exchange);
  const latestWeek =
    payload?.cards?.as_of ?? payload?.summary?.latest_week ?? byWeek[0]?.weekStartDate ?? null;

  const columns = useMemo<DataGridColumn<DarkVenueRow>[]>(
    () => [
      {
        key: "venue",
        header: "Venue / MPID",
        width: 150,
        sortable: true,
        render: (v) => <span style={monoStrongStyle}>{v.venue ?? "—"}</span>,
      },
      {
        key: "ats_share_volume",
        header: "ATS volume",
        numeric: true,
        width: 130,
        sortable: true,
        render: (v) => <span style={monoMutedStyle}>{fmtCompact(v.ats_share_volume)}</span>,
      },
      {
        key: "ats_trade_count",
        header: "Trades",
        numeric: true,
        width: 110,
        sortable: true,
        render: (v) => <span style={monoMutedStyle}>{fmtCompact(v.ats_trade_count)}</span>,
      },
      {
        key: "share_of_ats_pct",
        header: "Share of ATS",
        numeric: true,
        width: 150,
        sortable: true,
        render: (v) => (
          <span style={shareCellStyle}>
            <span
              aria-hidden
              style={{ ...tintBarStyle, ...tintFor(v.share_of_ats_pct) }}
            />
            {fmtPct(v.share_of_ats_pct)}
          </span>
        ),
      },
      {
        key: "dark_pool_pct",
        header: "Dark % of total",
        numeric: true,
        width: 140,
        sortable: true,
        render: (v) => <span style={monoMutedStyle}>{fmtPct(v.dark_pool_pct)}</span>,
      },
    ],
    [],
  );

  const csvColumns = useMemo<GridCsvColumn<DarkVenueRow>[]>(
    () => [
      { key: "venue", header: "Venue / MPID", value: (v) => v.venue ?? "" },
      { key: "ats_share_volume", header: "ATS volume", value: (v) => v.ats_share_volume ?? "" },
      { key: "ats_trade_count", header: "Trades", value: (v) => v.ats_trade_count ?? "" },
      { key: "share_of_ats_pct", header: "Share of ATS (%)", value: (v) => v.share_of_ats_pct ?? "" },
      { key: "dark_pool_pct", header: "Dark % of total", value: (v) => v.dark_pool_pct ?? "" },
    ],
    [],
  );

  const exportCsv = () => {
    const csv = buildGridCsv(csvColumns, venues);
    downloadGridCsv(gridCsvFilename(`dark-${effectiveSymbol || "venues"}`), csv);
  };

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="DARK needs an equity / ETF ticker." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8" aria-busy="true">
      <Skeleton height={56} />
      <Skeleton height={64} />
      <Skeleton height={20} width="75%" />
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
  ) : venues.length === 0 ? (
    <Empty
      title="FINRA ATS data unavailable"
      body={
        payload?.reason ??
        "No off-exchange ATS rows returned — this symbol may not be ATS-reported or FINRA is unreachable."
      }
      icon="∅"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {degraded && (
        <div role="status" style={bannerStyle} aria-label="Data quality warning">
          <strong>{status === "provider_unavailable" ? "PROVIDER DATA STALE — " : ""}</strong>
          {[payload?.reason, ...warnings].filter(Boolean).join(" · ") ||
            "FINRA data could not be fully verified."}
        </div>
      )}

      <section style={kpiGridStyle} aria-label="DARK KPI ribbon">
        <StatCard
          label="Off-exchange shares"
          value={fmtCompact(totalOffExchange)}
          caption={`${byWeek.length || weeks}W WINDOW${latestWeek ? ` · AS OF ${latestWeek}` : ""}`}
          tone="neutral"
          trend={trendOf(weekVolumes)}
        />
        <StatCard
          label="Top venue share"
          value={fmtPct(payload?.top_venue_share_pct)}
          caption="OF AGGREGATE ATS VOLUME"
          tone="neutral"
        />
        <StatCard
          label="Venues (latest week)"
          value={String(payload?.cards?.venue_count ?? venues.length)}
          caption={latestWeek ? `WEEK ${latestWeek}` : "—"}
          tone="neutral"
        />
        <StatCard
          label="Dark % of total"
          value={fmtPct(payload?.cards?.latest_dark_pool_pct)}
          caption={payload?.cards?.latest_dark_pool_pct == null ? "NO WEEKLY TOTAL JOINED" : "ATS / TOTAL VOLUME"}
          tone="neutral"
        />
      </section>

      <section style={sparkCardStyle} aria-label="Weekly ATS volume history">
        <div style={sparkHeadStyle}>
          <span className="u-text-mute" style={noteTextStyle}>
            WEEKLY ATS VOLUME · {weekVolumes.length} WKS
          </span>
          <span style={monoStrongStyle}>{fmtCompact(weekVolumes[weekVolumes.length - 1])}</span>
        </div>
        <Sparkline
          values={weekVolumes}
          width={560}
          height={64}
          tone="accent"
          ariaLabel={`Weekly ATS share volume, ${weekVolumes.length} weeks, latest ${fmtCompact(weekVolumes[weekVolumes.length - 1])}`}
        />
      </section>

      <section style={tableWrapStyle} aria-label="Off-exchange volume by venue">
        <DataGrid
          columns={columns}
          rows={venues}
          rowKey={(v, i) => `${v.venue ?? "venue"}-${i}`}
          density="compact"
          ariaLabel="Venue ranking"
          defaultSortKey="ats_share_volume"
          defaultSortDir="descending"
          keyboardNavigable
        />
        <div className="u-text-mute" style={noteTextStyle}>
          dark % of total shown only when the yfinance weekly total volume
          joined for that week · source {venues[0]?.source_mode ?? "—"}
        </div>
      </section>
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Dark Pool Volume — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${venues.length} venue${venues.length === 1 ? "" : "s"} · ${latestWeek ? `week ${latestWeek}` : "no week reported"}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : status}
              </Pill>
              <SegmentedControl
                label="WEEKS"
                value={weeks}
                options={WEEKS_OPTIONS}
                onChange={setWeeks}
                title="Weeks window"
              />
              <button
                type="button"
                className="btn"
                onClick={exportCsv}
                disabled={venues.length === 0}
                title="Download CSV"
                aria-label={`Download ${venues.length} venues as CSV`}
              >
                CSV
              </button>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh FINRA ATS volume"
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
          <StatusSection label="rows" value={payload?.n_rows ?? venues.length} tone="accent" />
          <StatusDivider />
          <StatusSection label="mode" value={payload?.cards?.data_mode ?? "—"} />
          <StatusDivider />
          <StatusSection label="elapsed" value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`} />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── helpers ───────────────────────────────────────────────────────── */

function num(v: unknown): number | null {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function trendOf(values: number[]): number[] {
  return values.slice(-22);
}

function fmtCompact(v: unknown): string {
  const n = num(v);
  if (n == null) return "—";
  const a = Math.abs(n);
  if (a >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function fmtPct(v: unknown): string {
  const n = num(v);
  if (n == null) return "—";
  return `${n.toFixed(2)}%`;
}

/** Share-of-ATS tint: accent mixed toward transparent, capped for legibility. */
function tintFor(pct: unknown): CSSProperties {
  const n = num(pct);
  const mix = n == null ? 0 : Math.max(0, Math.min(45, Math.round(n * 0.6)));
  return { background: `color-mix(in srgb, var(--accent) ${mix}%, transparent)` };
}

/* ── styles (design tokens only) ───────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
  gap: 10,
};

const bannerStyle: CSSProperties = {
  padding: "6px 10px",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--border-subtle)",
  background: "var(--scrim-low)",
  color: "var(--text-primary)",
  fontSize: "var(--font-size-sm)",
};

const sparkCardStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
  padding: "10px 12px",
  border: "1px solid var(--border)",
  borderRadius: 8,
  background: "var(--bg-raised, transparent)",
};

const sparkHeadStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "baseline",
  gap: 12,
};

const tableWrapStyle: CSSProperties = { minWidth: 0 };

const shareCellStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  justifyContent: "flex-end",
  width: "100%",
};

const tintBarStyle: CSSProperties = {
  display: "inline-block",
  width: 42,
  height: 6,
  borderRadius: 3,
};

const noteTextStyle: CSSProperties = {
  fontSize: "var(--font-size-2xs)",
  fontFamily: "JetBrains Mono, monospace",
  letterSpacing: "0.05em",
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
};
