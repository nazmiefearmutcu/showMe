/**
 * EVTS — corporate events calendar (Awareness-backed).
 *
 * Rows come from awareness `/calendar/corporate` (earnings, dividends, splits,
 * IPOs, filings) for one symbol. Upcoming events list first (soonest first),
 * then recent events (newest first). Type chips filter client-side.
 *
 * Honesty: no events are invented. An unreachable awareness service renders
 * AwarenessUnavailable; an empty window says so.
 */
import { useMemo, useState, type CSSProperties } from "react";
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
import { defaultSymbolForFunction } from "@/lib/symbols";
import { formatMissing } from "@/lib/format";
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";
import { AwarenessUnavailable } from "./awareness/AwarenessUnavailable";
import { ProviderHealthStrip } from "./awareness/ProviderHealthStrip";
import type { AwarenessMeta } from "./awareness/types";
import type { ProvenanceSource } from "./awareness/ProvenanceButton";

export interface EvtsRow {
  date?: string | null;
  datetime_utc?: string | null;
  type?: string | null;
  event?: string | null;
  symbol?: string | null;
  company?: string | null;
  time_of_day?: string | null;
  status?: string | null;
  details?: Record<string, unknown> | null;
  sources?: ProvenanceSource[] | null;
}

interface EvtsPayload {
  status?: string;
  reason?: string | null;
  symbol?: string;
  rows?: EvtsRow[];
  upcoming?: EvtsRow[];
  recent?: EvtsRow[];
  meta?: AwarenessMeta;
  next_actions?: string[];
}

const TYPE_FILTERS = ["all", "earnings", "dividend", "split", "ipo", "filing"] as const;
type TypeFilter = (typeof TYPE_FILTERS)[number];

interface DisplayRow extends EvtsRow {
  group: "upcoming" | "recent";
}

export function EVTSPane({ code, symbol }: FunctionPaneProps) {
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const { state, data, error, refetch } = useFunction<EvtsPayload>({
    code,
    symbol: effectiveSymbol,
    params: {},
    enabled: !!effectiveSymbol,
  });

  const payload = useMemo<EvtsPayload>(() => data?.data ?? {}, [data]);
  const status = payload.status ?? "—";
  const unavailable = status === "provider_unavailable";
  const meta: AwarenessMeta = payload.meta ?? {};
  const todayIso = new Date().toISOString().slice(0, 10);

  const rows = useMemo<DisplayRow[]>(
    () => orderRows(payload, todayIso),
    [payload, todayIso],
  );
  const visible = useMemo(
    () => (typeFilter === "all" ? rows : rows.filter((r) => (r.type ?? "") === typeFilter)),
    [rows, typeFilter],
  );
  const upcomingCount = rows.filter((r) => r.group === "upcoming").length;
  const recentCount = rows.length - upcomingCount;

  const COLS: DataGridColumn<DisplayRow>[] = useMemo(
    () => [
      {
        key: "date",
        header: "Date",
        width: 116,
        render: (r) => <span style={monoPrimaryStyle}>{fmtDate(r.date)}</span>,
      },
      {
        key: "group",
        header: "When",
        width: 96,
        render: (r) => (
          <Pill
            tone={r.group === "upcoming" ? "warn" : "muted"}
            variant="soft"
            withDot={false}
          >
            {r.group}
          </Pill>
        ),
      },
      {
        key: "type",
        header: "Type",
        width: 96,
        render: (r) => (
          <Pill tone={typeTone(r.type)} variant="soft" withDot={false}>
            {r.type ?? "event"}
          </Pill>
        ),
      },
      {
        key: "event",
        header: "Event",
        render: (r) => <span style={titleStyle}>{r.event ?? formatMissing}</span>,
      },
      {
        key: "time",
        header: "Time",
        width: 92,
        render: (r) => <span style={monoMutedStyle}>{fmtTime(r.time_of_day)}</span>,
      },
      {
        key: "status",
        header: "Status",
        width: 96,
        render: (r) => <span style={monoMutedStyle}>{r.status ?? formatMissing}</span>,
      },
      {
        key: "details",
        header: "Details",
        render: (r) => <span style={monoMutedStyle}>{fmtDetails(r.details)}</span>,
      },
      {
        key: "source",
        header: "Source",
        width: 150,
        render: (r) => (
          <span style={monoMutedStyle}>
            {(r.sources ?? []).map((s) => s.provider).join(", ") || formatMissing}
          </span>
        ),
      },
    ],
    [],
  );

  const csvColumns = useMemo<GridCsvColumn<DisplayRow>[]>(
    () => [
      { key: "date", header: "Date", value: (r) => fmtDate(r.date) },
      { key: "group", header: "When", value: (r) => r.group },
      { key: "type", header: "Type", value: (r) => r.type ?? "" },
      { key: "event", header: "Event", value: (r) => r.event ?? "" },
      { key: "status", header: "Status", value: (r) => r.status ?? "" },
    ],
    [],
  );

  const exportCsv = () => {
    const csv = buildGridCsv(csvColumns, visible);
    downloadGridCsv(gridCsvFilename(`evts-${effectiveSymbol || "events"}`), csv);
  };

  const body = !effectiveSymbol ? (
    <div role="status">Pick a symbol: EVTS needs an equity or ETF ticker.</div>
  ) : unavailable ? (
    <AwarenessUnavailable
      reason={payload.reason ?? null}
      onRetry={refetch}
      subject="corporate events"
    />
  ) : (
    <PaneState
      state={state}
      error={error}
      empty={rows.length === 0}
      emptyTitle="No corporate events in this window"
      emptyBody={`No dated corporate events for ${effectiveSymbol} (window: 90 days back, 180 days ahead). Nothing is estimated.`}
      emptyIcon="∅"
      onRetry={refetch}
    >
      <div className="u-grid-gap-14">
        <section style={kpiGridStyle} aria-label="EVTS summary">
          <StatCard
            label="Events"
            value={String(rows.length)}
            caption="IN WINDOW"
            tone="neutral"
          />
          <StatCard
            label="Upcoming"
            value={String(upcomingCount)}
            caption="SOONEST FIRST"
            tone="neutral"
          />
          <StatCard
            label="Recent"
            value={String(recentCount)}
            caption="NEWEST FIRST"
            tone="neutral"
          />
        </section>
        <div style={chipRowStyle} role="group" aria-label="Event type filter">
          {TYPE_FILTERS.map((t) => {
            const active = typeFilter === t;
            return (
              <button
                key={t}
                type="button"
                className={`fn-segmented__opt${active ? " fn-segmented__opt--active" : ""}`}
                aria-pressed={active}
                onClick={() => setTypeFilter(t)}
                title={`Filter event type ${t}`}
              >
                {t}
              </button>
            );
          })}
        </div>
        <DataGrid
          columns={COLS}
          rows={visible}
          rowKey={(r, i) => `${r.group}-${r.date ?? ""}-${r.event ?? ""}-${i}`}
          density="compact"
          ariaLabel="EVTS corporate events"
          empty="No events match this type filter"
        />
      </div>
    </PaneState>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Corporate Events — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${rows.length} events · awareness`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {visible.length}/{rows.length} rows
              </Pill>
              <button
                type="button"
                className="btn"
                onClick={exportCsv}
                disabled={visible.length === 0}
                title="Download CSV"
                aria-label={`Download ${visible.length} events as CSV`}
              >
                CSV
              </button>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh corporate events"
              />
            </FunctionControlGroup>
          }
        />
        <ProviderHealthStrip
          providers={meta.providers}
          feedHealth={meta.feed_health}
          generatedAt={meta.generated_at}
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="sources" value={data?.sources?.join(", ") || "awareness"} />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="events" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="type" value={typeFilter} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/**
 * Upcoming rows (date >= today) first, soonest first; then recent rows,
 * newest first. Rows with no parseable date keep their backend order at the end.
 */
function orderRows(payload: EvtsPayload, todayIso: string): DisplayRow[] {
  const source: EvtsRow[] = payload.rows ?? [
    ...(payload.upcoming ?? []),
    ...(payload.recent ?? []),
  ];
  const upcoming: DisplayRow[] = [];
  const recent: DisplayRow[] = [];
  const undated: DisplayRow[] = [];
  for (const row of source) {
    const day = String(row.date ?? "").slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) {
      undated.push({ ...row, group: "recent" });
    } else if (day >= todayIso) {
      upcoming.push({ ...row, group: "upcoming" });
    } else {
      recent.push({ ...row, group: "recent" });
    }
  }
  upcoming.sort((a, b) => (a.date ?? "").localeCompare(b.date ?? ""));
  recent.sort((a, b) => (b.date ?? "").localeCompare(a.date ?? ""));
  return [...upcoming, ...recent, ...undated];
}

function typeTone(
  type: string | null | undefined,
): "accent" | "positive" | "warn" | "muted" {
  switch ((type ?? "").toLowerCase()) {
    case "earnings":
      return "accent";
    case "dividend":
      return "positive";
    case "split":
    case "ipo":
      return "warn";
    default:
      return "muted";
  }
}

function fmtDate(v: string | null | undefined): string {
  const s = String(v ?? "").trim();
  if (!s) return formatMissing;
  return s.slice(0, 10);
}

function fmtTime(v: string | null | undefined): string {
  if (!v) return formatMissing;
  if (v === "bmo") return "before open";
  if (v === "amc") return "after close";
  if (v === "dmh") return "market hours";
  return v;
}

function fmtDetails(details: Record<string, unknown> | null | undefined): string {
  if (!details) return formatMissing;
  const parts = Object.entries(details)
    .filter(([, v]) => v != null && v !== "")
    .slice(0, 3)
    .map(
      ([k, v]) =>
        `${k.replace(/_/g, " ")} ${typeof v === "number" ? v.toLocaleString("en-US", { maximumFractionDigits: 4 }) : String(v)}`,
    );
  return parts.join(" · ") || formatMissing;
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

const titleStyle: CSSProperties = {
  fontSize: "var(--font-size-md)",
  color: "var(--text-primary)",
};
