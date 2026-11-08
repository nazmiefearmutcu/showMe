/**
 * ERN — earnings calendar (Awareness-backed corporate events).
 *
 * Rows come from awareness `/calendar/corporate` (type earnings) via the ERN
 * function, sorted by date then market cap. Grouped by day, then by reporting
 * time (before open, during market hours, after close, not reported).
 *
 * Derived column: "Est vs LY" = (EPS estimate − last-year EPS) / |last-year EPS|.
 * It is blank whenever either input is missing or last-year EPS is zero.
 * Market cap is in USD.
 */
import { useMemo, useState } from "react";
import {
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Skeleton,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { navigate } from "@/lib/router";
import { formatMissing } from "@/lib/format";
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

export interface ErnRow {
  date: string;
  time_of_day?: string | null;
  symbol?: string | null;
  company?: string | null;
  eps_estimate?: number | null;
  num_estimates?: number | null;
  fiscal_quarter?: string | null;
  market_cap?: number | null;
  last_year_eps?: number | null;
  last_year_report_date?: string | null;
  in_watchlist?: boolean;
  sources?: { provider: string }[] | null;
}

interface ErnPayload {
  status?: string;
  reason?: string | null;
  rows?: ErnRow[];
  by_day?: Record<string, number>;
  meta?: AwarenessMeta;
}

const WINDOW_DAYS = 7;

const MIN_CAP = [
  { value: "10b", label: "$10B+" },
  { value: "2b", label: "$2B+" },
  { value: "all", label: "All" },
] as const;
type MinCapId = (typeof MIN_CAP)[number]["value"];
const MIN_CAP_IDS = MIN_CAP.map((o) => o.value);
const MIN_CAP_USD: Record<MinCapId, number | null> = { "10b": 10e9, "2b": 2e9, all: null };

const SORTS = [
  { value: "cap", label: "Market cap" },
  { value: "time", label: "Time" },
  { value: "est", label: "Est vs LY" },
] as const;
type SortId = (typeof SORTS)[number]["value"];
const SORT_IDS = SORTS.map((o) => o.value);

const TIME_ORDER = ["bmo", "dmh", "amc", "unknown"] as const;

export function ERNPane({ code }: FunctionPaneProps) {
  const [weekOffset, setWeekOffset] = useState(0);
  const [minCap, setMinCap] = usePersistentOption<MinCapId>(
    "showme.ern.mincap",
    MIN_CAP_IDS,
    "10b",
  );
  const [sort, setSort] = usePersistentOption<SortId>("showme.ern.sort", SORT_IDS, "cap");
  const [watchOnly, setWatchOnly] = useState(false);
  const [symbolFilter, setSymbolFilter] = useState("");

  const from = useMemo(() => isoDayPlus(weekOffset * WINDOW_DAYS), [weekOffset]);
  const minCapUsd = MIN_CAP_USD[minCap];
  const params = useMemo(
    () => ({
      from,
      days: WINDOW_DAYS,
      ...(minCapUsd != null ? { min_market_cap: minCapUsd } : {}),
    }),
    [from, minCapUsd],
  );

  const { state, data, error, refetch } = useFunction<ErnPayload>({ code, params });
  const payload: ErnPayload = data?.data ?? {};
  const status = payload.status ?? "—";
  const unavailable = status === "provider_unavailable";
  const meta: AwarenessMeta = payload.meta ?? {};

  const allRows = useMemo(() => payload.rows ?? [], [payload.rows]);
  const filtered = useMemo(() => {
    const needle = symbolFilter.trim().toUpperCase();
    return allRows.filter((r) => {
      if (watchOnly && !r.in_watchlist) return false;
      if (needle && !(r.symbol ?? "").toUpperCase().includes(needle)) return false;
      return true;
    });
  }, [allRows, watchOnly, symbolFilter]);

  const groups = useMemo(() => buildDayGroups(filtered, sort), [filtered, sort]);
  const dayTabs = useMemo(() => buildDayTabs(allRows), [allRows]);
  const watchCount = allRows.filter((r) => r.in_watchlist).length;

  const body = (() => {
    if (state === "loading" || state === "idle") {
      return (
        <div className="u-grid-gap-8">
          <Skeleton height={20} />
          <Skeleton height={20} />
          <Skeleton height={20} width="80%" />
        </div>
      );
    }
    if (state === "error") {
      return (
        <Empty
          title="Function error"
          body={error?.message ?? formatMissing}
          icon="!"
          action={
            <button type="button" className="btn" onClick={refetch}>
              Retry
            </button>
          }
        />
      );
    }
    if (unavailable) {
      return (
        <AwarenessUnavailable
          reason={payload.reason ?? null}
          onRetry={refetch}
          subject="earnings calendar"
        />
      );
    }
    if (allRows.length === 0) {
      return (
        <div className="aw-cal__empty">
          <Empty
            title="No earnings reports in this week"
            body={`${weekLabel(from)} · ${minCapLabel(minCap)}. Nothing is estimated.`}
          />
          <div className="aw-cal__relaxers" role="group" aria-label="Widen the filters">
            {minCap !== "all" ? (
              <button type="button" className="aw-btn" onClick={() => setMinCap("all")}>
                Remove market cap floor
              </button>
            ) : null}
            <button
              type="button"
              className="aw-btn"
              onClick={() => setWeekOffset((w) => w + 1)}
            >
              Next week
            </button>
          </div>
        </div>
      );
    }
    if (filtered.length === 0) {
      return (
        <Empty
          title="No rows match the filters"
          body="Clear the watchlist-only toggle or the symbol filter to see the rest of the week."
        />
      );
    }
    return (
      <div className="aw-ern" role="table" aria-label="Earnings calendar">
        <div className="aw-ern__head" role="row">
          <span role="columnheader">Time</span>
          <span role="columnheader" aria-label="Watchlist">
            ★
          </span>
          <span role="columnheader">Symbol</span>
          <span role="columnheader">Company</span>
          <span role="columnheader">Fiscal Q</span>
          <span role="columnheader" className="aw-num">
            EPS est
          </span>
          <span role="columnheader" className="aw-num">
            # est
          </span>
          <span role="columnheader" className="aw-num">
            LY EPS
          </span>
          <span
            role="columnheader"
            className="aw-num"
            title="Derived: (EPS estimate − last-year EPS) / |last-year EPS|"
          >
            Est vs LY
          </span>
          <span role="columnheader" className="aw-num">
            Mkt cap
          </span>
        </div>
        {groups.map((day) => (
          <section
            key={day.date}
            id={`ern-day-${day.date}`}
            className="aw-ern__day"
            role="rowgroup"
            aria-label={dayHeading(day.date)}
          >
            {day.slots.map((slot) => (
              <div key={slot.time} className="aw-ern__slot">
                <header className="aw-ern__slothead" role="presentation">
                  <span className="aw-ern__daytitle">{dayHeading(day.date)}</span>
                  <span className="aw-ern__slotlabel">{TIME_LABEL[slot.time]}</span>
                  <span className="aw-ern__daymeta">{slot.rows.length} reports</span>
                </header>
                {slot.rows.map((r, i) => (
                  <ErnRowView key={`${r.symbol ?? ""}-${i}`} row={r} />
                ))}
              </div>
            ))}
          </section>
        ))}
        <p className="aw-cal__legend">
          BMO before open · DMH during market hours · AMC after close · n/a not reported.
          EPS estimates are Nasdaq consensus. Est vs LY is derived in the pane. Market cap
          in USD. Abbreviations: LY last year, # est number of estimates.
        </p>
      </div>
    );
  })();

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Earnings calendar"
          subtitle={`${weekLabel(from)} · ${allRows.length} reports · ${watchCount} on watchlist`}
          trailing={
            <FunctionControlGroup>
              <SegmentedControl
                label="CAP"
                title="Minimum market cap"
                value={minCap}
                options={MIN_CAP}
                onChange={setMinCap}
              />
              <SegmentedControl
                label="SORT"
                title="Sort within each day"
                value={sort}
                options={SORTS}
                onChange={setSort}
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh the earnings calendar"
              />
            </FunctionControlGroup>
          }
        />
        <div className="aw-cal__toolbar" role="toolbar" aria-label="Earnings filters">
          <button
            type="button"
            className="aw-btn"
            aria-label="Previous week"
            onClick={() => setWeekOffset((w) => w - 1)}
          >
            ‹
          </button>
          <span className="aw-ern__week" aria-live="polite">
            {weekLabel(from)}
          </span>
          <button
            type="button"
            className="aw-btn"
            aria-label="Next week"
            onClick={() => setWeekOffset((w) => w + 1)}
          >
            ›
          </button>
          <button
            type="button"
            className={`aw-chip${watchOnly ? " aw-chip--on" : ""}`}
            aria-pressed={watchOnly}
            onClick={() => setWatchOnly((v) => !v)}
          >
            Watchlist only
          </button>
          <label className="aw-ern__symbol">
            <span className="aw-cal__label">SYMBOL</span>
            <input
              type="search"
              value={symbolFilter}
              onChange={(e) => setSymbolFilter(e.target.value)}
              placeholder="Filter symbol"
              aria-label="Filter by symbol"
              className="aw-ern__input"
            />
          </label>
        </div>
        {dayTabs.length > 0 ? (
          <div className="aw-ern__tabs" role="tablist" aria-label="Report days">
            {dayTabs.map((tab) => (
              <button
                key={tab.date}
                type="button"
                role="tab"
                aria-selected={false}
                className="aw-ern__tab"
                onClick={() => {
                  document
                    .getElementById(`ern-day-${tab.date}`)
                    ?.scrollIntoView?.({ block: "start" });
                }}
              >
                <span className="aw-ern__tabday">{shortDay(tab.date)}</span>
                <span className="aw-ern__tabcount">
                  {tab.count} reports{tab.watch > 0 ? `, ${tab.watch} on watchlist` : ""}
                </span>
              </button>
            ))}
          </div>
        ) : null}
        <ProviderHealthStrip
          providers={meta.providers}
          feedHealth={meta.feed_health}
          generatedAt={meta.generated_at}
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="sources" value={data?.sources?.join(", ") || "awareness"} />
          <StatusDivider />
          <StatusSection label="rows" value={filtered.length} />
          <StatusDivider />
          <StatusSection
            label="updated"
            value={meta.generated_at ? `${meta.generated_at.slice(11, 16)} UTC` : "—"}
          />
          <StatusDivider />
          <StatusSection label="sort" value={sort} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function ErnRowView({ row }: { row: ErnRow }) {
  const est = estVsLastYear(row.eps_estimate, row.last_year_eps);
  const symbol = row.symbol ?? "";
  return (
    <div className="aw-ern__row" role="row">
      <span role="cell">
        <TimeBadge time={row.time_of_day} />
      </span>
      <span role="cell">
        {row.in_watchlist ? (
          <span role="img" aria-label="On watchlist" className="aw-ern__star">
            ★
          </span>
        ) : null}
      </span>
      <span role="cell">
        <button
          type="button"
          className={
            row.in_watchlist ? "aw-ern__sym aw-ern__sym--watch" : "aw-ern__sym aw-link"
          }
          onClick={() => {
            if (symbol) navigate(`/symbol/${symbol}/DES`);
          }}
          aria-label={`Open ${symbol} description`}
        >
          {symbol || formatMissing}
        </button>
      </span>
      <span className="aw-ern__company" role="cell">
        {row.company ?? formatMissing}
      </span>
      <span className="aw-ern__fq" role="cell">
        {row.fiscal_quarter ?? formatMissing}
      </span>
      <span className="aw-num" role="cell">
        {fmtEps(row.eps_estimate)}
      </span>
      <span className="aw-num aw-ern__mute" role="cell">
        {row.num_estimates ?? formatMissing}
      </span>
      <span className="aw-num aw-ern__mute" role="cell">
        {fmtEps(row.last_year_eps)}
      </span>
      <span className="aw-num" role="cell">
        {est == null ? (
          ""
        ) : (
          <span className={est >= 0 ? "aw-ern__est--pos" : "aw-ern__est--neg"}>
            {est >= 0 ? "+" : "−"}
            {Math.abs(est).toFixed(1)}%
          </span>
        )}
      </span>
      <span className="aw-num" role="cell">
        {fmtCap(row.market_cap)}
      </span>
    </div>
  );
}

function TimeBadge({ time }: { time: string | null | undefined }) {
  const key = (time ?? "unknown") as (typeof TIME_ORDER)[number];
  const short =
    key === "bmo" ? "BMO" : key === "dmh" ? "DMH" : key === "amc" ? "AMC" : "n/a";
  const title = TIME_LABEL[TIME_ORDER.includes(key) ? key : "unknown"];
  return (
    <span className="aw-ern__badge" title={title} aria-label={title}>
      {short}
    </span>
  );
}

const TIME_LABEL: Record<(typeof TIME_ORDER)[number], string> = {
  bmo: "Before open",
  dmh: "During market hours",
  amc: "After close",
  unknown: "Time not reported",
};

interface DayGroup {
  date: string;
  slots: { time: (typeof TIME_ORDER)[number]; rows: ErnRow[] }[];
}

function buildDayGroups(rows: ErnRow[], sort: SortId): DayGroup[] {
  const byDay = new Map<string, Map<string, ErnRow[]>>();
  for (const r of rows) {
    const day = String(r.date ?? "").slice(0, 10);
    const slot = TIME_ORDER.includes(
      (r.time_of_day ?? "unknown") as (typeof TIME_ORDER)[number],
    )
      ? ((r.time_of_day ?? "unknown") as string)
      : "unknown";
    if (!byDay.has(day)) byDay.set(day, new Map());
    const slots = byDay.get(day)!;
    if (!slots.has(slot)) slots.set(slot, []);
    slots.get(slot)!.push(r);
  }
  const days = [...byDay.keys()].sort();
  return days.map((date) => ({
    date,
    slots: TIME_ORDER.filter((t) => byDay.get(date)!.has(t)).map((t) => ({
      time: t,
      rows: sortRows(byDay.get(date)!.get(t)!, sort),
    })),
  }));
}

function sortRows(rows: ErnRow[], sort: SortId): ErnRow[] {
  const copy = [...rows];
  if (sort === "cap") {
    copy.sort((a, b) => (b.market_cap ?? -1) - (a.market_cap ?? -1));
  } else if (sort === "est") {
    copy.sort(
      (a, b) =>
        (estVsLastYear(b.eps_estimate, b.last_year_eps) ?? -Infinity) -
        (estVsLastYear(a.eps_estimate, a.last_year_eps) ?? -Infinity),
    );
  } else {
    copy.sort((a, b) => (a.symbol ?? "").localeCompare(b.symbol ?? ""));
  }
  return copy;
}

function buildDayTabs(rows: ErnRow[]): { date: string; count: number; watch: number }[] {
  const map = new Map<string, { date: string; count: number; watch: number }>();
  for (const r of rows) {
    const date = String(r.date ?? "").slice(0, 10);
    const cur = map.get(date) ?? { date, count: 0, watch: 0 };
    cur.count += 1;
    if (r.in_watchlist) cur.watch += 1;
    map.set(date, cur);
  }
  return [...map.values()].sort((a, b) => a.date.localeCompare(b.date));
}

/** Derived: (eps_estimate − last_year_eps) / |last_year_eps| as a percent, or null. */
export function estVsLastYear(
  eps: number | null | undefined,
  lastYear: number | null | undefined,
): number | null {
  if (
    eps == null ||
    lastYear == null ||
    !Number.isFinite(eps) ||
    !Number.isFinite(lastYear)
  )
    return null;
  if (lastYear === 0) return null;
  return ((eps - lastYear) / Math.abs(lastYear)) * 100;
}

function fmtEps(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return formatMissing;
  return v.toFixed(2);
}

export function fmtCap(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return formatMissing;
  if (Math.abs(v) >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  return `$${(v / 1e6).toFixed(0)}M`;
}

function isoDayPlus(days: number): string {
  return new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
}

function weekLabel(fromIso: string): string {
  const start = new Date(`${fromIso}T12:00:00Z`);
  const end = new Date(start.getTime() + (WINDOW_DAYS - 1) * 86_400_000);
  const fmt = (d: Date, withYear: boolean) =>
    d.toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      ...(withYear ? { year: "numeric" } : {}),
      timeZone: "UTC",
    });
  return `${fmt(start, false)} – ${fmt(end, true)}`;
}

function dayHeading(date: string): string {
  return new Date(`${date}T12:00:00Z`).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

function shortDay(date: string): string {
  return new Date(`${date}T12:00:00Z`).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function minCapLabel(id: MinCapId): string {
  return MIN_CAP.find((o) => o.value === id)?.label ?? "All";
}
