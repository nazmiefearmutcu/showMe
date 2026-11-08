/**
 * ECO — economic calendar, day-grouped timeline (Awareness-backed).
 *
 * Data: awareness `/calendar/economic` + `/calendar/holidays` via the ECO function.
 * The invented reference schedule is gone; every row is a sourced event. Each
 * day lists its holidays first, then the events in local or UTC order.
 *
 * Honesty rules: unknown values render "—", surprise shows only for released
 * prints, colour follows surprise direction (not good/bad), and an unreachable
 * awareness service renders AwarenessUnavailable with no rows.
 */
import { useMemo, type ReactNode } from "react";
import {
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Skeleton,
  StatusDivider,
  StatusSection,
  Tabs,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { formatMissing } from "@/lib/format";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption, usePersistentString } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";
import { AwarenessUnavailable } from "./awareness/AwarenessUnavailable";
import { ProviderHealthStrip } from "./awareness/ProviderHealthStrip";
import type { AwarenessMeta, AwarenessProvider } from "./awareness/types";
import { ImportanceDots } from "./awareness/ImportanceDots";
import { SurpriseCell, type SurpriseDirection } from "./awareness/SurpriseCell";
import { ProvenanceButton, type ProvenanceSource } from "./awareness/ProvenanceButton";

interface EconRow {
  id?: string;
  date?: string | null;
  all_day?: boolean;
  country?: string | null;
  currency?: string | null;
  event?: string | null;
  category?: string | null;
  importance?: number | null;
  actual?: string | null;
  forecast?: string | null;
  previous?: string | null;
  revised?: string | null;
  actual_value?: number | null;
  forecast_value?: number | null;
  previous_value?: number | null;
  unit?: string | null;
  surprise?: number | null;
  surprise_direction?: SurpriseDirection | null;
  status?: string | null;
  description?: string | null;
  sources?: ProvenanceSource[] | null;
  is_central_bank?: boolean;
}

/** Awareness ProviderRef: live holiday rows carry this object as `source`. */
interface ProviderRef {
  provider?: string | null;
  url?: string | null;
  fetched_at?: string | null;
  basis?: string | null;
}

interface HolidayRow {
  date?: string | null;
  country?: string | null;
  exchange?: string | null;
  name?: string | null;
  kind?: string | null;
  early_close_time?: string | null;
  /** Provider name (string) from the function layer; a ProviderRef object is accepted too. */
  source?: string | ProviderRef | null;
}

/** Provider name for a holiday's source, never the object itself (a React child crash). */
function holidayProviderLabel(
  source: string | ProviderRef | null | undefined,
): string | null {
  if (typeof source === "string") return source.trim() || null;
  if (source && typeof source === "object" && typeof source.provider === "string") {
    return source.provider.trim() || null;
  }
  return null;
}

interface EcoPayload {
  status?: string;
  reason?: string | null;
  rows?: EconRow[];
  holidays?: HolidayRow[];
  meta?: AwarenessMeta;
  next_actions?: string[];
}

const RANGES = [
  { id: "today", label: "Today", from: "today", days: 1 },
  { id: "week", label: "This week", from: "monday", days: 7 },
  { id: "next7", label: "Next 7d", from: "today", days: 7 },
  { id: "next14", label: "Next 14d", from: "today", days: 14 },
] as const;
type RangeId = (typeof RANGES)[number]["id"];
const RANGE_IDS = RANGES.map((r) => r.id);

const IMPORTANCE = [
  { value: "all", label: "All" },
  { value: "med", label: "Med+" },
  { value: "high", label: "High" },
] as const;
type ImportanceId = (typeof IMPORTANCE)[number]["value"];
const IMPORTANCE_IDS = IMPORTANCE.map((o) => o.value);
const IMPORTANCE_LEVEL: Record<ImportanceId, number> = { all: 1, med: 2, high: 3 };

const COUNTRY_CODES = ["US", "EU", "GB", "DE", "JP", "CN", "TR"] as const;

const TZ_OPTIONS = [
  { value: "local", label: "Local" },
  { value: "utc", label: "UTC" },
] as const;
type TzMode = (typeof TZ_OPTIONS)[number]["value"];
const TZ_IDS = TZ_OPTIONS.map((o) => o.value);

const DAY_MS = 86_400_000;

export function ECOPane({ code }: FunctionPaneProps) {
  const [range, setRange] = usePersistentOption<RangeId>(
    "showme.eco-range",
    RANGE_IDS,
    "week",
  );
  const [importance, setImportance] = usePersistentOption<ImportanceId>(
    "showme.eco-importance",
    IMPORTANCE_IDS,
    "all",
  );
  const [countriesCsv, setCountriesCsv] = usePersistentString("showme.eco-countries", "US");
  const [tz, setTz] = usePersistentOption<TzMode>("showme.eco-tz", TZ_IDS, "local");

  const selectedCountries = useMemo(
    () =>
      countriesCsv
        .split(",")
        .map((c) => c.trim())
        .filter((c) => c.length > 0),
    [countriesCsv],
  );
  const rangeDef = RANGES.find((r) => r.id === range) ?? RANGES[1];
  const countryParam = selectedCountries.length ? selectedCountries.join(",") : "all";
  const params = useMemo(
    () => ({
      from: fromDateFor(rangeDef.from),
      days: rangeDef.days,
      country: countryParam,
      importance: IMPORTANCE_LEVEL[importance],
    }),
    [rangeDef, countryParam, importance],
  );

  const { state, data, error, refetch } = useFunction<EcoPayload>({ code, params });
  const payload: EcoPayload = data?.data ?? {};
  const status = payload.status ?? "—";
  const unavailable = status === "provider_unavailable";
  const meta: AwarenessMeta = payload.meta ?? {};
  const rows = useMemo(() => payload.rows ?? [], [payload.rows]);
  const holidays = useMemo(() => payload.holidays ?? [], [payload.holidays]);

  // Countdown and "now" re-read every second while the tab is visible.
  const tick = useVisibilityTick(1000);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- tick re-reads the wall clock each visible second
  const now = useMemo(() => Date.now(), [tick]);

  const timed = useMemo(() => {
    const out: { row: EconRow; t: number }[] = [];
    for (const row of rows) {
      const t = parseMs(row.date);
      if (t != null) out.push({ row, t });
    }
    return out.sort((a, b) => a.t - b.t);
  }, [rows]);

  const nextHigh = useMemo(() => {
    const hit = timed.find(
      (x) => x.row.importance === 3 && x.row.status === "scheduled" && x.t >= now,
    );
    return hit ? hit.row : null;
  }, [timed, now]);

  const todayKey = dayKeyOf(now, tz);
  const groups = useMemo(() => buildGroups(timed, holidays, tz), [timed, holidays, tz]);
  const kpis = useMemo(
    () => deriveKpis(timed, now, todayKey, tz),
    [timed, now, todayKey, tz],
  );
  const ecoProviders = (meta.providers ?? []).filter((p) => p.provider.startsWith("econ."));

  const toggleCountry = (code: string) => {
    const set = new Set(selectedCountries);
    if (set.has(code)) set.delete(code);
    else set.add(code);
    setCountriesCsv(COUNTRY_CODES.filter((c) => set.has(c)).join(","));
  };

  const body = (() => {
    if (state === "loading" || state === "idle") {
      return (
        <div className="u-grid-gap-8">
          <Skeleton height={56} />
          <Skeleton height={20} />
          <Skeleton height={20} />
          <Skeleton height={20} width="80%" />
        </div>
      );
    }
    if (state === "error") {
      return (
        <div role="status">
          <Empty
            title="Function error"
            body={error?.message ?? formatMissing}
            icon="!"
            action={
              <button type="button" onClick={refetch} className="btn">
                Retry
              </button>
            }
          />
        </div>
      );
    }
    if (unavailable) {
      return (
        <AwarenessUnavailable
          reason={payload.reason ?? null}
          onRetry={refetch}
          subject="economic calendar"
        />
      );
    }
    if (timed.length === 0 && holidays.length === 0) {
      return (
        <div className="aw-cal__empty">
          <Empty
            title="No events in this window"
            body={`Countries ${countryParam} · importance ${IMPORTANCE.find((o) => o.value === importance)?.label} · ${rangeDef.label}. No sample events are substituted.`}
          />
          <div className="aw-cal__relaxers" role="group" aria-label="Widen the filters">
            {importance !== "all" ? (
              <button type="button" className="aw-btn" onClick={() => setImportance("all")}>
                Include all importance
              </button>
            ) : null}
            {range !== "next14" ? (
              <button type="button" className="aw-btn" onClick={() => setRange("next14")}>
                Widen to 14 days
              </button>
            ) : null}
            {selectedCountries.length ? (
              <button type="button" className="aw-btn" onClick={() => setCountriesCsv("")}>
                All countries
              </button>
            ) : null}
          </div>
        </div>
      );
    }
    return (
      <div className="aw-cal">
        <section className="aw-cal__kpis" aria-label="ECO summary">
          <div className="aw-kpi">
            <span className="aw-kpi__label">Next high-impact release</span>
            {nextHigh ? (
              <>
                <span className="aw-kpi__value">{nextHigh.event ?? formatMissing}</span>
                <span className="aw-kpi__caption">
                  {formatWhen(parseMs(nextHigh.date), tz)} ·{" "}
                  <span className="aw-countdown" aria-live="off">
                    {formatCountdown(parseMs(nextHigh.date) ?? now, now)}
                  </span>
                </span>
              </>
            ) : (
              <span className="aw-kpi__caption">None scheduled in this window</span>
            )}
          </div>
          <div className="aw-kpi">
            <span className="aw-kpi__label">Released today</span>
            <span className="aw-kpi__value">{kpis.releasedToday}</span>
            <span className="aw-kpi__caption">
              {kpis.above} above · {kpis.below} below · {kpis.inline} inline
            </span>
          </div>
          <div className="aw-kpi">
            <span className="aw-kpi__label">Scheduled next 7 days</span>
            <span className="aw-kpi__value">{kpis.scheduled7d}</span>
            <span className="aw-kpi__caption">{kpis.high7d} high importance</span>
          </div>
          <div className="aw-kpi">
            <span className="aw-kpi__label">Providers</span>
            {ecoProviders.length === 0 ? (
              <span className="aw-kpi__caption">No provider health reported</span>
            ) : (
              <ul className="aw-kpi__providers">
                {ecoProviders.map((p) => (
                  <ProviderLine key={p.provider} provider={p} nowMs={now} />
                ))}
              </ul>
            )}
          </div>
        </section>
        <div className="aw-cal__grid" role="table" aria-label="Economic calendar by day">
          <div className="aw-cal__head" role="row">
            <span role="columnheader">Time</span>
            <span role="columnheader">Ctry</span>
            <span role="columnheader">Imp</span>
            <span role="columnheader">Event</span>
            <span role="columnheader" className="aw-num">
              Actual
            </span>
            <span role="columnheader" className="aw-num">
              Forecast
            </span>
            <span role="columnheader" className="aw-num">
              Previous
            </span>
            <span role="columnheader">Surprise</span>
            <span role="columnheader">Src</span>
          </div>
          {groups.map((group) => (
            <section
              key={group.key}
              className="aw-cal__day"
              role="rowgroup"
              aria-label={dayLabel(group.key, todayKey)}
            >
              <header className="aw-cal__dayhead" role="presentation">
                <span className="aw-cal__daytitle">{dayLabel(group.key, todayKey)}</span>
                <span className="aw-cal__daymeta">
                  {group.rows.length} events,{" "}
                  {group.rows.filter((r) => r.importance === 3).length} high
                </span>
              </header>
              {group.holidays.map((h, i) => (
                <div key={`h-${group.key}-${i}`} className="aw-cal__holiday" role="row">
                  <span className="aw-cal__holiday-text" role="cell">
                    <span aria-hidden="true">📅 </span>
                    {holidayText(h)}
                    {holidayProviderLabel(h.source) ? (
                      <span className="aw-cal__holiday-src">
                        {" "}
                        · {holidayProviderLabel(h.source)}
                      </span>
                    ) : null}
                  </span>
                </div>
              ))}
              {group.rows.map((row, i) => (
                <EventRow
                  key={row.id ?? `${group.key}-${i}`}
                  row={row}
                  tz={tz}
                  now={now}
                  isNextHigh={nextHigh != null && nextHigh === row}
                />
              ))}
            </section>
          ))}
        </div>
        <p className="aw-cal__legend">
          Surprise = actual minus forecast in the same unit. ▲ above, ▼ below, = inline with
          consensus. Colour shows direction only, not good or bad. Local = {localZoneName()}
          {tz === "utc" ? " (showing UTC)" : ""}.
        </p>
      </div>
    );
  })();

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Economic calendar"
          subtitle={`${countryParam} · ${rangeDef.label} · ${timed.length} events`}
          trailing={
            <FunctionControlGroup>
              <SegmentedControl
                label="IMP"
                title="Importance filter"
                value={importance}
                options={IMPORTANCE}
                onChange={setImportance}
              />
              <SegmentedControl
                label="TZ"
                title="Time zone"
                value={tz}
                options={TZ_OPTIONS}
                onChange={setTz}
              />
              <Tabs
                variant="segmented"
                ariaLabel="Date range"
                items={RANGES.map((r) => ({ id: r.id, label: r.label }))}
                active={range}
                onChange={(id) => setRange(id as RangeId)}
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh the economic calendar"
              />
            </FunctionControlGroup>
          }
        />
        <div className="aw-cal__toolbar" role="toolbar" aria-label="Country filter">
          <span className="aw-cal__label">COUNTRY</span>
          {COUNTRY_CODES.map((c) => {
            const active = selectedCountries.includes(c);
            return (
              <button
                key={c}
                type="button"
                aria-pressed={active}
                className={`aw-chip${active ? " aw-chip--on" : ""}`}
                onClick={() => toggleCountry(c)}
              >
                {c}
              </button>
            );
          })}
        </div>
        <ProviderHealthStrip
          providers={meta.providers}
          feedHealth={meta.feed_health}
          generatedAt={meta.generated_at}
          nowMs={now}
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="sources" value={data?.sources?.join(", ") || "awareness"} />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="events" value={timed.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="range" value={rangeDef.label} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function ProviderLine({ provider, nowMs }: { provider: AwarenessProvider; nowMs: number }) {
  const ok = provider.status === "ok";
  const ago = provider.last_ok_at ? minutesBetween(provider.last_ok_at, nowMs) : null;
  const text =
    provider.status === "ok"
      ? `ok${ago !== null ? `, ${ago}m ago` : ""}`
      : provider.status === "never"
        ? "never fetched"
        : provider.status;
  return (
    <li className="aw-kpi__provider">
      <span
        className={`aw-dot ${ok ? "aw-dot--ok" : provider.status === "down" ? "aw-dot--down" : "aw-dot--warn"}`}
        aria-hidden="true"
      />
      <span className="aw-kpi__pname">{provider.provider}</span>
      <span className="aw-kpi__pstate">{text}</span>
    </li>
  );
}

interface EventRowProps {
  row: EconRow;
  tz: TzMode;
  now: number;
  isNextHigh: boolean;
}

function EventRow({ row, tz, now, isNextHigh }: EventRowProps): ReactNode {
  const t = parseMs(row.date);
  const released = row.status === "released" || row.status === "revised";
  const direction = row.surprise_direction ?? null;
  const actualTone =
    direction === "above"
      ? "aw-eco__actual--above"
      : direction === "below"
        ? "aw-eco__actual--below"
        : "";
  const classes = ["aw-cal__row"];
  if (row.is_central_bank) classes.push("aw-cal__row--cb");
  if (isNextHigh) classes.push("aw-cal__row--next");
  const title = row.event ?? "—";
  const eventTone =
    row.importance === 3 || row.is_central_bank ? "aw-cal__title--strong" : "";
  const timeText = row.all_day ? "All day" : t != null ? formatClock(t, tz) : formatMissing;
  return (
    <div className={classes.join(" ")} role="row" data-testid="eco-row">
      <span className="aw-cal__time" role="cell">
        <span>{timeText}</span>
        {t != null && !row.all_day ? (
          <span className="aw-cal__utc">{formatClock(t, "utc")}Z</span>
        ) : null}
      </span>
      <span className="aw-cal__ctry" role="cell">
        <span className="aw-cal__cc">{row.country ?? "—"}</span>
        {row.currency ? <span className="aw-cal__ccy">{row.currency}</span> : null}
      </span>
      <span role="cell">
        <ImportanceDots importance={row.importance} />
      </span>
      <span className="aw-cal__event" role="cell">
        <span className="aw-cal__eventline">
          {row.is_central_bank ? <span className="aw-cb-badge">CB</span> : null}
          <span className={eventTone || "aw-cal__title"}>{title}</span>
        </span>
        <span className="aw-cal__meta">
          {row.category ? <span>{row.category.replace(/_/g, " ")}</span> : null}
          <span className={`aw-cal__status${isNextHigh ? " aw-cal__status--warn" : ""}`}>
            {statusLabel(row, t, now, isNextHigh)}
          </span>
        </span>
      </span>
      <span className={`aw-num aw-eco__actual ${actualTone}`} role="cell">
        {displayValue(row.actual, row.actual_value, row.unit)}
      </span>
      <span className="aw-num aw-eco__forecast" role="cell">
        {displayValue(row.forecast, row.forecast_value, row.unit)}
      </span>
      <span className="aw-num aw-eco__previous" role="cell">
        {row.revised
          ? `${displayValue(row.previous, row.previous_value, row.unit)} → ${row.revised}`
          : displayValue(row.previous, row.previous_value, row.unit)}
      </span>
      <span role="cell">
        <SurpriseCell
          surprise={row.surprise}
          unit={row.unit}
          direction={direction}
          released={released}
        />
      </span>
      <span role="cell">
        <ProvenanceButton sources={row.sources} subject={title} />
      </span>
    </div>
  );
}

function statusLabel(
  row: EconRow,
  t: number | null,
  now: number,
  isNextHigh: boolean,
): string {
  if (row.status === "released" || row.status === "revised") return "released";
  if (row.status === "cancelled") return "cancelled";
  if (t != null && t > now && t - now <= DAY_MS) {
    if (isNextHigh) return `next high · in ${formatShortCountdown(t - now)}`;
    return `in ${formatShortCountdown(t - now)}`;
  }
  return row.status ?? "scheduled";
}

function displayValue(
  text: string | null | undefined,
  value: number | null | undefined,
  unit: string | null | undefined,
): string {
  if (text != null && String(text).trim() !== "") return String(text);
  if (typeof value === "number" && Number.isFinite(value)) {
    return `${value.toLocaleString("en-US", { maximumFractionDigits: 4 })}${unit ?? ""}`;
  }
  return formatMissing;
}

function holidayText(h: HolidayRow): string {
  const name = h.name ?? "holiday";
  const country = h.country ?? "";
  if (h.kind === "market_closed") return `${h.exchange ?? country} closed: ${name}.`;
  if (h.kind === "early_close") {
    const at = h.early_close_time ? ` at ${h.early_close_time}` : "";
    return `${h.exchange ?? country} early close${at}: ${name}.`;
  }
  return `${country} public holiday: ${name}.`;
}

function parseMs(raw: string | null | undefined): number | null {
  if (!raw) return null;
  const t = new Date(String(raw)).getTime();
  return Number.isNaN(t) ? null : t;
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

function dayKeyOf(ms: number, tz: TzMode): string {
  if (tz === "utc") return new Date(ms).toISOString().slice(0, 10);
  const d = new Date(ms);
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function fromDateFor(anchor: "today" | "monday"): string {
  const now = Date.now();
  if (anchor === "today") return new Date(now).toISOString().slice(0, 10);
  const d = new Date(now);
  const dow = (d.getUTCDay() + 6) % 7;
  return new Date(now - dow * DAY_MS).toISOString().slice(0, 10);
}

function formatClock(ms: number, tz: TzMode): string {
  const d = new Date(ms);
  if (tz === "utc") return `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}`;
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

function formatWhen(ms: number | null, tz: TzMode): string {
  if (ms == null) return formatMissing;
  return `${dayLabelFromKey(dayKeyOf(ms, tz))} ${formatClock(ms, tz)}${tz === "utc" ? " UTC" : ""}`;
}

/** "Tue 10 Nov" for a calendar-date key; UTC noon keeps the date stable in every zone. */
function dayLabelFromKey(key: string): string {
  const d = new Date(`${key}T12:00:00Z`);
  return d.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

function dayLabel(key: string, todayKey: string): string {
  const base = dayLabelFromKey(key);
  return key === todayKey ? `Today, ${base}` : base;
}

function formatCountdown(targetMs: number, nowMs: number): string {
  const diff = targetMs - nowMs;
  if (diff <= 0) return "now";
  const totalSec = Math.floor(diff / 1000);
  const days = Math.floor(totalSec / 86_400);
  const hh = pad2(Math.floor((totalSec % 86_400) / 3600));
  const mm = pad2(Math.floor((totalSec % 3600) / 60));
  const ss = pad2(totalSec % 60);
  return days > 0 ? `in ${days}d ${hh}:${mm}:${ss}` : `in ${hh}:${mm}:${ss}`;
}

function formatShortCountdown(diffMs: number): string {
  const totalMin = Math.max(0, Math.floor(diffMs / 60_000));
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return `${h}h ${m}m`;
}

function minutesBetween(iso: string, nowMs: number): number | null {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.round((nowMs - t) / 60_000));
}

function localZoneName(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "local";
  } catch {
    return "local";
  }
}

interface DayGroup {
  key: string;
  rows: EconRow[];
  holidays: HolidayRow[];
}

function buildGroups(
  timed: { row: EconRow; t: number }[],
  holidays: HolidayRow[],
  tz: TzMode,
): DayGroup[] {
  const map = new Map<string, DayGroup>();
  const get = (key: string) => {
    let group = map.get(key);
    if (!group) {
      group = { key, rows: [], holidays: [] };
      map.set(key, group);
    }
    return group;
  };
  for (const { row, t } of timed) get(dayKeyOf(t, tz)).rows.push(row);
  for (const h of holidays) {
    const key = String(h.date ?? "").slice(0, 10);
    if (/^\d{4}-\d{2}-\d{2}$/.test(key)) get(key).holidays.push(h);
  }
  return [...map.values()].sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
}

interface Kpis {
  releasedToday: number;
  above: number;
  below: number;
  inline: number;
  scheduled7d: number;
  high7d: number;
}

function deriveKpis(
  timed: { row: EconRow; t: number }[],
  now: number,
  todayKey: string,
  tz: TzMode,
): Kpis {
  const out: Kpis = {
    releasedToday: 0,
    above: 0,
    below: 0,
    inline: 0,
    scheduled7d: 0,
    high7d: 0,
  };
  for (const { row, t } of timed) {
    const released = row.status === "released" || row.status === "revised";
    if (released && dayKeyOf(t, tz) === todayKey) {
      out.releasedToday += 1;
      if (row.surprise_direction === "above") out.above += 1;
      else if (row.surprise_direction === "below") out.below += 1;
      else if (row.surprise_direction === "inline") out.inline += 1;
    }
    if (row.status === "scheduled" && t >= now && t - now <= 7 * DAY_MS) {
      out.scheduled7d += 1;
      if (row.importance === 3) out.high7d += 1;
    }
  }
  return out;
}
