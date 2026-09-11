/**
 * TAUC — Treasury Auction Calendar.
 *
 * Upcoming (or recent) US Treasury auctions from the TAUC backend function
 * (live TreasuryDirect rows when the adapter is available; an honest,
 * source-labelled calendar model otherwise). Header: upcoming/recent window
 * segmented control + horizon segmented control (persisted) + status pill +
 * refresh. Body: KPI ribbon (auctions, total offering, next auction, source)
 * + security-type filter chips (client-side, derived from the fetched rows)
 * + a date-sorted auction table with a totals strip.
 *
 * Honesty: when the payload's source_mode is NOT "treasurydirect" the pane
 * renders a prominent "NOT live TreasuryDirect" note instead of passing the
 * model rows off as the real calendar.
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
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface TAUCRow {
  auction_date?: string;
  issue_date?: string;
  security_type?: string;
  security_term?: string;
  term?: string;
  offering_amount?: number | string;
  cusip?: string;
  reopening?: string;
  high_yield?: string | number;
  high_discount_rate?: string | number;
  high_investment_rate?: string | number;
  bid_to_cover?: string | number;
}

interface TAUCByType {
  security_type?: string;
  count?: number;
  total_offering?: number;
}

interface TAUCData {
  rows?: TAUCRow[];
  n?: number;
  by_type?: TAUCByType[];
  horizon_days?: number;
  status?: string;
  reason?: string;
  summary?: {
    action?: string;
    horizon_days?: number;
    auctions?: number;
    source_mode?: string;
    security_filter?: string;
  };
}

const HORIZON_OPTIONS = [
  { value: 7, label: "7d" },
  { value: 14, label: "14d" },
  { value: 30, label: "30d" },
] as const;
const HORIZON_IDS = HORIZON_OPTIONS.map((o) => o.value);

const ACTION_OPTIONS = [
  { value: "upcoming", label: "Upcoming" },
  { value: "recent", label: "Recent" },
] as const;

type AuctionAction = (typeof ACTION_OPTIONS)[number]["value"];

export function TAUCPane({ code }: FunctionPaneProps) {
  const [horizon, setHorizon] = usePersistentOption<number>(
    "showme.tauc.horizon",
    HORIZON_IDS,
    30,
  );
  const [action, setAction] = useState<AuctionAction>("upcoming");
  const [typeFilter, setTypeFilter] = useState<string | null>(null);

  // TAUC is a macro function — the backend ignores the instrument, so no
  // symbol is required and the pane works without one.
  const { state, data, error, refetch } = useFunction<TAUCData>({
    code,
    params: { action, horizon_days: horizon },
  });

  const payload = data?.data;
  const status = payload?.status ?? "—";
  const sourceMode = payload?.summary?.source_mode ?? "";
  const isLive = state === "ok" && sourceMode === "treasurydirect";

  const allRows: TAUCRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const sortedRows = useMemo(
    () => [...allRows].sort((a, b) => dateKey(a) - dateKey(b)),
    [allRows],
  );
  const typeAgg = useMemo(() => aggregateByType(allRows), [allRows]);
  const rows = useMemo(
    () =>
      typeFilter
        ? sortedRows.filter((r) => String(r.security_type ?? "") === typeFilter)
        : sortedRows,
    [sortedRows, typeFilter],
  );
  const totalOffering = useMemo(
    () => rows.reduce((acc, r) => acc + toNum(r.offering_amount), 0),
    [rows],
  );

  const actionTag = action === "recent" ? "Recent" : "Upcoming";
  const nextRow = rows[0];
  const nextDate = nextRow ? String(nextRow.auction_date ?? "").slice(0, 10) : "—";

  const COLS: DataGridColumn<TAUCRow>[] = useMemo(
    () => [
      {
        key: "auction_date",
        header: "Auction date",
        width: 116,
        render: (r) => (
          <span style={monoPrimaryStyle}>
            {String(r.auction_date ?? "—").slice(0, 10)}
          </span>
        ),
      },
      {
        key: "security",
        header: "Security",
        width: 200,
        render: (r) => (
          <span
            style={monoPrimaryStyle}
            title={r.reopening === "Yes" ? "Reopening" : undefined}
          >
            {String(r.security_type ?? "—")} ·{" "}
            {String(r.term || r.security_term || "—")}
            {r.reopening === "Yes" ? (
              <span style={monoMutedStyle}> ↻</span>
            ) : null}
          </span>
        ),
      },
      {
        key: "cusip",
        header: "CUSIP",
        width: 112,
        render: (r) => (
          <span style={monoMutedStyle}>{String(r.cusip ?? "—")}</span>
        ),
      },
      {
        key: "offering_amount",
        header: "Offering",
        numeric: true,
        width: 128,
        render: (r) => (
          <span style={monoStrongStyle}>{fmtUsd(r.offering_amount)}</span>
        ),
      },
      {
        key: "status",
        header: "Status",
        width: 116,
        render: (r) => {
          const s = auctionStatus(r);
          return (
            <Pill tone={s.tone} variant="soft" withDot={false}>
              {s.label}
            </Pill>
          );
        },
      },
    ],
    [],
  );

  const body =
    state === "loading" || state === "idle" ? (
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
    ) : allRows.length === 0 ? (
      <Empty
        title="No auctions returned"
        body={
          payload?.reason ??
          `No ${action} Treasury auctions in the ${horizon}-day window.`
        }
        icon="⌦"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : rows.length === 0 ? (
      <Empty
        title={`No ${typeFilter ?? ""} auctions in the ${horizon}d window`}
        body="The selected security type has no auctions in this horizon."
        icon="⌦"
        action={
          <button onClick={() => setTypeFilter(null)} className="btn">
            Show all types
          </button>
        }
      />
    ) : (
      <div className="u-grid-gap-14">
        <section style={kpiGridStyle} aria-label="TAUC KPI ribbon">
          <StatCard
            label="Auctions"
            value={String(rows.length)}
            caption={`${actionTag.toUpperCase()} · ${horizon}D`}
            tone="neutral"
          />
          <StatCard
            label="Total offering"
            value={fmtUsd(totalOffering)}
            caption={`${typeAgg.length} TYPES`}
            tone="neutral"
          />
          <StatCard
            label={action === "recent" ? "Oldest in window" : "Next auction"}
            value={nextDate}
            caption={
              nextRow
                ? `${String(nextRow.security_type ?? "")} ${String(
                    nextRow.term || nextRow.security_term || "",
                  )}`.trim()
                : "—"
            }
            tone="neutral"
          />
          <StatCard
            label="Source"
            value={sourceMode || "—"}
            caption={isLive ? "LIVE TREASURYDIRECT" : "MODEL — NOT LIVE"}
            tone={isLive ? "positive" : "neutral"}
          />
        </section>
        {!isLive ? (
          <div role="note" style={noteStyle}>
            NOT live TreasuryDirect data — rows come from the{" "}
            {sourceMode || "model"} calendar model and may not match the real
            auction schedule.
          </div>
        ) : null}
        <div
          role="group"
          aria-label="Security type filter"
          style={chipRowStyle}
        >
          <span style={chipLabelStyle}>TYPE</span>
          <button
            type="button"
            aria-pressed={typeFilter === null}
            onClick={() => setTypeFilter(null)}
            style={chipStyle(typeFilter === null)}
          >
            All {allRows.length}
          </button>
          {typeAgg.map((t) => (
            <button
              key={t.type}
              type="button"
              aria-pressed={typeFilter === t.type}
              onClick={() => setTypeFilter(t.type)}
              title={`${t.type}: ${t.count} auctions · ${fmtUsd(t.total)} offering`}
              style={chipStyle(typeFilter === t.type)}
            >
              {t.type} {t.count}
            </button>
          ))}
        </div>
        <DataGrid
          columns={COLS}
          rows={rows}
          rowKey={(r, i) => `${r.cusip ?? ""}-${r.auction_date ?? ""}-${i}`}
          density="compact"
          ariaLabel="Treasury auction calendar"
        />
        <div role="status" aria-label="TAUC totals" style={totalsStyle}>
          Total {rows.length} auction{rows.length === 1 ? "" : "s"} ·{" "}
          {fmtUsd(totalOffering)} offering · {horizon}d {actionTag.toLowerCase()}{" "}
          window · source {sourceMode || "—"}
        </div>
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Treasury Auction Calendar"
          subtitle={`${actionTag} · ${horizon}d horizon · ${rows.length} auctions`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : "model"}
              </Pill>
              <SegmentedControl
                label="WINDOW"
                value={action}
                options={ACTION_OPTIONS}
                onChange={setAction}
              />
              <SegmentedControl
                label="HORIZON"
                value={horizon}
                options={HORIZON_OPTIONS}
                onChange={setHorizon}
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh auction calendar"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="rows" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="horizon" value={`${horizon}d`} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── helpers ───────────────────────────────────────────────────────── */

interface TypeAgg {
  type: string;
  count: number;
  total: number;
}

function aggregateByType(rows: TAUCRow[]): TypeAgg[] {
  const map = new Map<string, TypeAgg>();
  for (const r of rows) {
    const type = String(r.security_type || "Unknown");
    const slot = map.get(type) ?? { type, count: 0, total: 0 };
    slot.count += 1;
    slot.total += toNum(r.offering_amount);
    map.set(type, slot);
  }
  return [...map.values()].sort((a, b) => b.total - a.total);
}

interface StatusInfo {
  label: string;
  tone: "positive" | "warn" | "muted";
}

function auctionStatus(r: TAUCRow): StatusInfo {
  const hasResults = [
    r.high_yield,
    r.high_discount_rate,
    r.high_investment_rate,
    r.bid_to_cover,
  ].some((v) => v != null && String(v).trim() !== "");
  if (hasResults) return { label: "results out", tone: "positive" };
  const d = String(r.auction_date ?? "").slice(0, 10);
  const today = new Date().toISOString().slice(0, 10);
  if (d && d < today) return { label: "closed", tone: "warn" };
  return { label: "scheduled", tone: "muted" };
}

function dateKey(r: TAUCRow): number {
  const t = Date.parse(String(r.auction_date ?? ""));
  return Number.isFinite(t) ? t : 0;
}

function toNum(v: unknown): number {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
}

function fmtUsd(v: unknown): string {
  const n = toNum(v);
  const a = Math.abs(n);
  if (a >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

/* ── styles (tokens only) ──────────────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const noteStyle: CSSProperties = {
  border: "1px solid var(--grid-color)",
  borderLeft: "3px solid var(--accent)",
  padding: "8px 10px",
  fontSize: "var(--font-size-md)",
  color: "var(--text-mute)",
};

const chipRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: 6,
};

const chipLabelStyle: CSSProperties = {
  fontSize: "var(--font-size-2xs)",
  letterSpacing: 1,
  color: "var(--text-mute)",
};

function chipStyle(active: boolean): CSSProperties {
  return {
    fontSize: "var(--font-size-sm)",
    fontFamily: "JetBrains Mono, monospace",
    fontVariantNumeric: "tabular-nums",
    padding: "2px 8px",
    borderRadius: 999,
    border: `1px solid ${active ? "var(--accent)" : "var(--grid-color)"}`,
    background: "transparent",
    color: active ? "var(--text-primary)" : "var(--text-mute)",
    cursor: "pointer",
  };
}

const totalsStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 10,
  borderTop: "1px solid var(--grid-color)",
  paddingTop: 8,
  fontSize: "var(--font-size-md)",
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
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
