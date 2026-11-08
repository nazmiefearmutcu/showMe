/**
 * MEET — Meeting Briefings: world-events tracker.
 *
 * One list for everything market-moving in the world: every country's
 * scheduled calendar (rate decisions, CPI, GDP — from the Awareness economic
 * calendar and holidays) plus country-tagged world headlines (geopolitics,
 * sanctions, trade-tariff news from Awareness). Upcoming events run ascending
 * with a live adaptive countdown
 * (days → hours → minutes → seconds), past events run descending; a
 * country sidebar shows every country's local state and next event; a
 * spot-alert engine fires toasts on configured lead times for rate
 * decisions / wars (persisted at `showme.meet.alerts`).
 *
 * Honesty: every row shows its source; empty windows say so; the pane
 * never invents events.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
} from "react";
import {
  DataGrid,
  type DataGridColumn,
  DeltaChip,
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
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { ProviderHealthStrip } from "./awareness/ProviderHealthStrip";
import type { AwarenessMeta } from "./awareness/types";
import { useLiveQuote } from "@/lib/market-data";
import { toast } from "@/lib/toast";
import { formatPrice } from "@/lib/format";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption, usePersistentString } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";
import {
  MEET_ALERT_HISTORY_CAP,
  dueAlert,
  flagOf,
  formatAge,
  formatCountdown,
  formatPrint,
  groupCalendarByDay,
  groupRows,
  impactTone,
  isPastRow,
  isSpotFor,
  leadLabel,
  loadMeetAlerts,
  parsePrintNumber,
  polarityOf,
  saveMeetAlerts,
  secondsUntil,
  surpriseOf,
  type MeetAlertConfig,
  type MeetAlertEntry,
  type MeetAlertHistoryItem,
  type MeetCountryEntry,
  type MeetData,
  type MeetRow,
} from "./meet/helpers";

const KIND_OPTIONS = [
  { value: "all", label: "All" },
  { value: "economic", label: "Calendar" },
  { value: "world", label: "World" },
] as const;
type KindFilter = (typeof KIND_OPTIONS)[number]["value"];

/* Mode tabs (spec §3): all = mixed list, calendar = MQL5-parity table,
   wire = world list + asset chips. Mode wins over kind (backend rule). */
const MODE_OPTIONS = [
  { value: "all", label: "All" },
  { value: "calendar", label: "Calendar" },
  { value: "wire", label: "Wire" },
] as const;
type ModeFilter = (typeof MODE_OPTIONS)[number]["value"];
const MODE_VALUES = MODE_OPTIONS.map((m) => m.value);

const DATA_FILTER_OPTIONS = ["all", "spot", "pinned", "major_only", "with_forecast", "with_actual", "surprise_only"] as const;
type DataFilter = (typeof DATA_FILTER_OPTIONS)[number];

/* major_only is a STRICT majors-only cut (backend Task B ruling): every low
   row drops — even a tagged one — and medium rows survive only when grounded
   (a country or an asset/topic tag). Labelled honestly wherever it renders. */
const MAJOR_ONLY_TITLE =
  "Majors-only cut: drops every low-impact row (even tagged); medium needs a country or asset/topic tag. Default all unchanged; spot/pinned rows survive.";

const IMPACT_OPTIONS = ["high", "medium", "low", "holiday"] as const;
type ImpactFilter = (typeof IMPACT_OPTIONS)[number];

const AHEAD_DAYS = [7, 30, 90, 180] as const;
const BACK_DAYS = [1, 7, 30] as const;

const LIMIT_OPTIONS = [100, 250, 400, 1000] as const;

/* Faz 5 realtime delta cursor (backend contract): hash/new_rows/removed_ids
   ride on the payload; helpers.ts MeetData is untouched on purpose. */
type MeetDeltaData = MeetData & {
  hash?: string;
  new_rows?: MeetRow[];
  removed_ids?: string[];
  since_echo?: string;
};

export function MEETPane({ code }: FunctionPaneProps) {
  const [kind, setKind] = usePersistentOption<KindFilter>(
    "showme.meet.kind",
    KIND_OPTIONS.map((k) => k.value),
    "all",
  );
  const [mode, setMode] = usePersistentOption<ModeFilter>(
    "showme.meet.mode",
    MODE_VALUES,
    "all",
  );
  const [dataFilter, setDataFilter] = usePersistentOption<DataFilter>(
    "showme.meet.data-filter",
    DATA_FILTER_OPTIONS,
    "all",
  );
  const [tags, setTags] = usePersistentString("showme.meet.tags", "");
  const [tagsDraft, setTagsDraft] = useState(tags);
  const [daysAhead, setDaysAhead] = usePersistentOption<number>(
    "showme.meet.days-ahead",
    AHEAD_DAYS,
    90,
  );
  const [daysBack, setDaysBack] = usePersistentOption<number>(
    "showme.meet.days-back",
    BACK_DAYS,
    7,
  );
  const [limit, setLimit] = usePersistentOption<number>(
    "showme.meet.limit",
    LIMIT_OPTIONS,
    400,
  );
  const [impacts, setImpacts] = useState<ImpactFilter[]>(() => readImpactFilter());
  const [queryDraft, setQueryDraft] = useState("");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const [alertConfig, setAlertConfig] = useState<MeetAlertConfig>(() => loadMeetAlerts());
  const firedRef = useRef<Set<string>>(new Set(alertConfig.history.map((h) => h.key)));

  const countriesParam = alertConfig.spotCountries.join(",");
  const impactParam = impacts.join(",");
  const [deltaParams, setDeltaParams] = useState<{ since?: string; known_ids?: string }>(
    {},
  );
  const { state, data, error, refetch } = useFunction<MeetDeltaData>({
    code,
    params: {
      countries: countriesParam,
      kind,
      mode,
      tags,
      data_filter: dataFilter,
      impact: impactParam,
      days_ahead: daysAhead,
      days_back: daysBack,
      query,
      limit,
      // Followed symbols ride along so the backend can surface matched world
      // headlines as their own section (owner: BTC followed, no events shown).
      symbols: alertConfig.symbols.join(","),
      // Faz 5 realtime delta cursor (empty on first load — the backend then
      // answers backward-compat with empty new_rows/removed_ids).
      ...deltaParams,
    },
  });
  const livePayload = data?.data;
  const livePayloadRef = useRef<MeetDeltaData | undefined>(livePayload);
  livePayloadRef.current = livePayload;

  /* Faz 5 realtime delta — 30 sn visibility-aware poll. The cursor
     (since/known_ids) rides in params, while every complete response replaces
     the displayed snapshot because mutable row fields and side sections may
     change even when the backend row-ID hash does not. */
  const [shown, setShown] = useState<MeetDeltaData | null>(null);
  const lastAsOfRef = useRef<string>("");
  const lastIdsRef = useRef<string[]>([]);
  const baselineKeyRef = useRef<string>("");
  const pendingBaselinePayloadRef = useRef<MeetDeltaData | null>(null);
  const rebaselineFilterRef = useRef<string>("");
  // Poll-pattern guard: the tick effect reads through a ref — `refetch`
  // itself never enters a dependency array.
  const refetchRef = useRef(refetch);
  useEffect(() => {
    refetchRef.current = refetch;
  }, [refetch]);
  const pollTick = useVisibilityTick(30_000);
  const filterKey = JSON.stringify({
    countries: countriesParam,
    kind,
    mode,
    tags,
    dataFilter,
    impact: impactParam,
    daysAhead,
    daysBack,
    query,
    limit,
    symbols: alertConfig.symbols.join(","),
  });
  // A filter change starts a new baseline: drop the cursor so the next poll
  // re-baselines instead of diffing across two different windows.
  useEffect(() => {
    if (baselineKeyRef.current && baselineKeyRef.current !== filterKey) {
      pendingBaselinePayloadRef.current = livePayloadRef.current ?? null;
      rebaselineFilterRef.current = filterKey;
    }
    setDeltaParams({});
  }, [filterKey]);
  useEffect(() => {
    if (pollTick === 0) return; // initial mount handled by useFunction's own load
    const ids = lastIdsRef.current;
    if (ids.length > 0) {
      const asOf = lastAsOfRef.current;
      setDeltaParams({
        ...(asOf ? { since: asOf } : {}),
        known_ids: ids.slice(-1000).join(","),
      });
    }
    refetchRef.current();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tick is the trigger
  }, [pollTick]);
  // Tab return (market-data.ts pattern): exactly one refresh so the first
  // visible frame is not a full cadence stale.
  useEffect(() => {
    if (typeof document === "undefined") return;
    const onVisible = () => {
      if (document.visibilityState === "visible") refetchRef.current();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);
  useEffect(() => {
    const next = livePayload;
    if (!next || typeof next !== "object") return;
    const awaitingRebaseline = rebaselineFilterRef.current === filterKey;
    if (awaitingRebaseline && pendingBaselinePayloadRef.current === next) {
      return; // still the previous filter's payload; wait for the new baseline
    }
    const sameBaseline = baselineKeyRef.current === filterKey && !awaitingRebaseline;
    baselineKeyRef.current = filterKey;
    pendingBaselinePayloadRef.current = null;
    if (typeof next.as_of === "string") lastAsOfRef.current = next.as_of;
    lastIdsRef.current = (next.rows ?? []).map((row) => row.id);
    setShown(next);
    if (!sameBaseline) {
      if (awaitingRebaseline) {
        rebaselineFilterRef.current = "";
        // The response is a fresh baseline, not an arrival. Prime only the
        // currently crossed keys so later, smaller leads can still fire.
        for (const row of next.rows ?? []) {
          const hit = dueAlert(row, alertConfig, Date.now(), firedRef.current);
          if (hit) firedRef.current.add(hit.key);
        }
        for (const row of next.new_rows ?? []) {
          firedRef.current.add(`delta:${row.id}`);
        }
      }
      return; // initial/new filter window — adopt silently, no delta toast
    }
    if (!alertConfig.enabled || !Array.isArray(next.new_rows)) return;
    const arrivals: MeetAlertHistoryItem[] = [];
    for (const fresh of next.new_rows) {
      const key = `delta:${fresh.id}`;
      if (firedRef.current.has(key)) continue;
      if (!isSpotFor(fresh, alertConfig)) continue;
      firedRef.current.add(key);
      arrivals.push({
        key,
        id: fresh.id,
        title: fresh.title,
        when_utc: fresh.when_utc ?? "",
        lead: null,
        fired_at: new Date().toISOString(),
      });
      toast.warn(
        `MEET spot · ${fresh.title}`,
        [
          utcLabel(fresh.when_utc),
          fresh.pairs?.length ? fresh.pairs.slice(0, 4).join(", ") : null,
        ]
          .filter(Boolean)
          .join(" · "),
      );
    }
    if (arrivals.length > 0) {
      setAlertConfig((cfg) => ({
        ...cfg,
        history: [...arrivals, ...cfg.history].slice(0, MEET_ALERT_HISTORY_CAP),
      }));
    }
  }, [livePayload, alertConfig, filterKey]);
  const payload = shown ?? livePayload;
  const [symbolDraft, setSymbolDraft] = useState("");

  // Live clock: 1s tick drives countdowns + lead-time alerts.
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem("showme.meet.impact", impacts.join(","));
    }
  }, [impacts]);

  useEffect(() => {
    saveMeetAlerts(alertConfig);
  }, [alertConfig]);

  const catalog = useMemo(() => payload?.country_catalog ?? [], [payload]);
  const countryIndex = useMemo(() => {
    const byIso = new Map<string, MeetCountryEntry>();
    for (const entry of payload?.country_index ?? []) byIso.set(entry.iso, entry);
    return byIso;
  }, [payload]);

  const normaliseRow = useCallback(
    (row: MeetRow) => ({
      ...row,
      title: row.title ?? "—",
      countries: row.countries ?? [],
      country_names: row.country_names ?? [],
      pairs: row.pairs ?? [],
      spot: row.spot ?? false,
      pinned: row.pinned ?? false,
    }),
    [],
  );

  /* Followed-symbol events (owner 2026-09-16: BTC was followed but its
     events never appeared). The backend matches the tickers' terms against
     the world headlines and ships them as their own section, independent of
     the country filters. */
  const symbolRows = useMemo(
    () => (payload?.symbol_rows ?? []).map(normaliseRow),
    [payload, normaliseRow],
  );

  const rows = useMemo(() => {
    // Defensive normalisation: a sidecar restart can briefly serve a
    // pre-world-events MEET payload — rows then lack the world fields and
    // must degrade instead of crashing the pane.
    const all = (payload?.rows ?? []).map(normaliseRow);
    // Server already filters; this second pass keeps the UI instant on
    // country toggles while the refetch is in flight.
    const wanted = new Set(alertConfig.spotCountries.map((c) => c.toUpperCase()));
    if (wanted.size === 0) return all;
    return all.filter((row) => row.countries.some((iso) => wanted.has(iso.toUpperCase())));
  }, [payload, alertConfig.spotCountries, normaliseRow]);

  const { upcoming, past } = useMemo(() => groupRows(rows, nowMs), [rows, nowMs]);
  const selectRow = useCallback((id: string) => {
    setSelectedId((current) => (current === id ? null : id));
  }, []);
  const selected = useMemo(
    () =>
      rows.find((row) => row.id === selectedId) ??
      symbolRows.find((row) => row.id === selectedId) ??
      null,
    [rows, selectedId, symbolRows],
  );
  const status = payload?.status ?? "—";
  // Provider health from the backend's data.meta (ProviderHealthStrip): stale or degraded Awareness
  // providers stay visible next to the rows they fed.
  const awarenessMeta = (payload as { meta?: AwarenessMeta } | null | undefined)?.meta;
  const droppedNoTime = typeof payload?.dropped_no_time === "number"
    ? payload.dropped_no_time
    : 0;
  const unfilteredUpcoming = typeof payload?.unfiltered_upcoming_count === "number"
    ? payload.unfiltered_upcoming_count
    : null;
  const methodology = typeof payload?.methodology === "string" && payload.methodology
    ? payload.methodology
    : null;
  const spotCount = useMemo(
    () => upcoming.filter((row) => isSpotFor(row, alertConfig)).length,
    [upcoming, alertConfig],
  );

  // Alert engine — fires once per (row, lead) pair; history persists.
  useEffect(() => {
    if (!alertConfig.enabled) return;
    const due: (MeetAlertHistoryItem & { lead: number })[] = [];
    for (const row of upcoming) {
      const hit = dueAlert(row, alertConfig, nowMs, firedRef.current);
      if (!hit) continue;
      firedRef.current.add(hit.key);
      due.push({
        key: hit.key,
        id: row.id,
        title: row.title,
        when_utc: row.when_utc ?? "",
        lead: hit.lead,
        fired_at: new Date(nowMs).toISOString(),
      });
    }
    if (due.length === 0) return;
    for (const item of due) {
      const row = upcoming.find((r) => r.id === item.id);
      toast.warn(
        `MEET spot · ${item.title}`,
        [
          leadLabel(item.lead) + " lead",
          utcLabel(item.when_utc),
          row?.pairs?.length ? row.pairs.slice(0, 4).join(", ") : null,
        ]
          .filter(Boolean)
          .join(" · "),
      );
    }
    setAlertConfig((cfg) => ({
      ...cfg,
      history: [...due, ...cfg.history].slice(0, MEET_ALERT_HISTORY_CAP),
    }));
  }, [nowMs, upcoming, alertConfig]);

  const toggleCountry = (iso: string) => {
    const upper = iso.toUpperCase();
    setAlertConfig((cfg) => {
      const has = cfg.spotCountries.includes(upper);
      return {
        ...cfg,
        spotCountries: has
          ? cfg.spotCountries.filter((c) => c !== upper)
          : [...cfg.spotCountries, upper],
      };
    });
  };

  const toggleImpact = (value: ImpactFilter) => {
    setImpacts((current) => {
      /* Single-select semantics (owner 2026-09-16): with the old membership
         toggle the default "all selected" state kept LOW rows listed while
         the HIGH chip looked focused. A click now focuses exactly ONE band;
         clicking the focused band again restores "all". */
      const onlyThis = current.length === 1 && current[0] === value;
      if (onlyThis) return [...IMPACT_OPTIONS];
      return [value];
    });
  };

  const addSymbol = (raw: string) => {
    const symbol = raw.trim().toUpperCase();
    if (!symbol) return;
    setAlertConfig((cfg) => ({
      ...cfg,
      symbols: cfg.symbols.includes(symbol) ? cfg.symbols : [...cfg.symbols, symbol],
    }));
    setSymbolDraft("");
  };

  const removeSymbol = (symbol: string) => {
    setAlertConfig((cfg) => ({ ...cfg, symbols: cfg.symbols.filter((s) => s !== symbol) }));
  };

  const submitQuery = (event: FormEvent) => {
    event.preventDefault();
    setQuery(queryDraft.trim());
  };

  const submitTags = (event: FormEvent) => {
    event.preventDefault();
    setTags(tagsDraft.trim());
  };

  const serverNextHigh = payload?.window?.next_high_impact ?? null;
  const serverNextHighSeconds = serverNextHigh?.when_utc
    ? (Date.parse(serverNextHigh.when_utc) - nowMs) / 1000
    : null;
  const nextHighImpact =
    serverNextHigh && serverNextHighSeconds != null && serverNextHighSeconds > 0
      ? serverNextHigh
      : upcoming.find((row) => String(row.impact).toLowerCase() === "high") ?? null;
  const nextHighSeconds = nextHighImpact?.when_utc
    ? (Date.parse(nextHighImpact.when_utc) - nowMs) / 1000
    : null;

  /* Filter-honest upcoming note: `country_index` is built from UNFILTERED
     rows, so when the follow filter hides every upcoming event the rail
     still shows SOON while the list says "0 upcoming". Surface the
     filter-excluded events explicitly instead of contradicting the rail. */
  const excludedUpcoming = useMemo(() => {
    const shown = new Set<string>();
    for (const r of payload?.upcoming ?? []) if (r.id) shown.add(String(r.id));
    for (const r of payload?.past ?? []) if (r.id) shown.add(String(r.id));
    const out: {
      iso: string;
      name: string;
      title: string;
      when_utc?: string;
      seconds: number;
      impact?: string;
    }[] = [];
    const seen = new Set<string>();
    for (const entry of payload?.country_index ?? []) {
      const ne = entry.next_event;
      if (!ne) continue;
      // One clock source with the list: prefer the client countdown from
      // when_utc; the server seconds_to_event stays as a fallback for
      // unparseable timestamps.
      const ts = ne.when_utc ? Date.parse(ne.when_utc) : Number.NaN;
      const seconds = Number.isFinite(ts)
        ? (ts - nowMs) / 1000
        : (ne.seconds_to_event ?? null);
      if (seconds == null || seconds < 0) continue;
      if (ne.id && shown.has(String(ne.id))) continue;
      const eventKey = ne.id
        ? String(ne.id)
        : `${ne.when_utc ?? ""}\u0000${ne.title ?? ""}`;
      if (seen.has(eventKey)) continue;
      seen.add(eventKey);
      out.push({
        iso: entry.iso,
        name: entry.name,
        title: ne.title ?? "—",
        when_utc: ne.when_utc,
        seconds,
        impact: ne.impact,
      });
    }
    out.sort((a, b) => a.seconds - b.seconds);
    return out;
  }, [payload, nowMs]);
  const excludedHigh = useMemo(
    () => excludedUpcoming.find((e) => (e.impact ?? "").toLowerCase() === "high") ?? null,
    [excludedUpcoming],
  );
  const excludedUpcomingCount =
    unfilteredUpcoming == null
      ? excludedUpcoming.length
      : Math.max(
          0,
          unfilteredUpcoming -
            (typeof payload?.upcoming_count === "number"
              ? payload.upcoming_count
              : upcoming.length),
        );
  const excludedUpcomingSummary = excludedUpcoming[0]
    ? `: ${excludedUpcoming[0].title} (${excludedUpcoming[0].iso}, in ${formatCountdown(
        excludedUpcoming[0].seconds,
      )}).`
    : ".";
  const upcomingEmptyText =
    excludedUpcomingCount > 0
      ? `No upcoming events match the current filters — ${excludedUpcomingCount} upcoming outside your filters${excludedUpcomingSummary}`
      : "No upcoming events in the window.";
  const upcomingReleasesEmptyText =
    excludedUpcomingCount > 0
      ? `No upcoming releases match the current filters — ${excludedUpcomingCount} upcoming outside your filters${excludedUpcomingSummary}`
      : "No upcoming releases in the window.";

  // The 30 sn poll re-keys the fetch (cursor in params) so `loading` fires
  // every cycle — keep the latest complete snapshot on screen instead of
  // flashing the skeleton (or the error card on a failed poll).
  const keepStale = shown != null && (state === "loading" || state === "error");
  const body = !keepStale && (state === "loading" || state === "idle") ? (
    <div className="u-grid-gap-8">
      <Skeleton height={52} />
      <Skeleton height={20} />
      <Skeleton height={20} />
      <Skeleton height={20} width="80%" />
    </div>
  ) : !keepStale && state === "error" ? (
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
      title="No world-events provider responded"
      body={payload.reason ?? "The calendar and news providers are unreachable — no events are invented."}
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div style={stackStyle}>
      <FilterBar
        mode={mode}
        onMode={setMode}
        kind={kind}
        onKind={setKind}
        impacts={impacts}
        onToggleImpact={toggleImpact}
        daysAhead={daysAhead}
        onDaysAhead={setDaysAhead}
        daysBack={daysBack}
        onDaysBack={setDaysBack}
        limit={limit}
        onLimit={setLimit}
        queryDraft={queryDraft}
        onQueryDraft={setQueryDraft}
        onQuerySubmit={submitQuery}
        queryApplied={query}
        tagsDraft={tagsDraft}
        onTagsDraft={setTagsDraft}
        onTagsSubmit={submitTags}
        tagsApplied={tags}
        dataFilter={dataFilter}
        onDataFilter={setDataFilter}
        followedCountries={alertConfig.spotCountries}
        catalog={catalog}
        onToggleCountry={toggleCountry}
        symbols={alertConfig.symbols}
        symbolDraft={symbolDraft}
        onSymbolDraft={setSymbolDraft}
        onAddSymbol={addSymbol}
        onRemoveSymbol={removeSymbol}
      />

      {payload?.data_quality ? (
        <section aria-label="MEET data quality" style={nextImpactStyle}>
          <span style={stripLabelStyle}>DATA QUALITY</span>
          <span style={monoMuteStyle}>
            {payload.data_quality.row_count} rows · {payload.data_quality.timed_count} timed ·{" "}
            {payload.data_quality.undated_count} undated ·{" "}
            {payload.data_quality.source_traceable_count} source-traceable ·{" "}
            {payload.data_quality.url_traceable_count} URL-traceable ·{" "}
            {payload.data_quality.duplicate_rows_dropped} duplicates dropped
            {payload.data_quality.rows_capped_at_limit
              ? ` · ${payload.data_quality.rows_capped_at_limit} excluded by result limit`
              : ""}
          </span>
          {payload.data_quality.active_source_tiers.map((tier) => (
            <Pill key={tier} tone={tier.includes("fallback") ? "warn" : "neutral"} variant="soft" withDot={false}>
              {tier.replaceAll("_", " ")}
            </Pill>
          ))}
          {(payload.attributions ?? []).map((attribution) => (
            <a
              key={attribution.url}
              href={attribution.url}
              target="_blank"
              rel="noreferrer"
              style={linkStyle}
              title={attribution.text}
            >
              {attribution.name} ↗
            </a>
          ))}
        </section>
      ) : null}

      <section style={nextImpactStyle} aria-label="Next high-impact event">
        <span style={stripLabelStyle}>NEXT HIGH IMPACT</span>
        {nextHighImpact ? (
          <>
            <Pill tone="warn" variant="soft" withDot>
              {formatCountdown(nextHighSeconds)}
            </Pill>
            <span style={titleStyle}>{nextHighImpact.title}</span>
            <span style={monoMuteStyle}>
              {utcLabel(nextHighImpact.when_utc)}
              {nextHighImpact.country_names?.length
                ? ` · ${nextHighImpact.country_names.join(", ")}`
                : ""}
            </span>
          </>
        ) : excludedHigh ? (
          <>
            <Pill tone="warn" variant="soft" withDot>
              {formatCountdown(
                excludedHigh.when_utc
                  ? (Date.parse(excludedHigh.when_utc) - nowMs) / 1000
                  : excludedHigh.seconds,
              )}
            </Pill>
            <span style={titleStyle}>{excludedHigh.title}</span>
            <span style={monoMuteStyle}>
              {utcLabel(excludedHigh.when_utc)} · {excludedHigh.iso} · outside filters
            </span>
          </>
        ) : (
          <span style={monoMuteStyle}>no upcoming high-impact event in the window</span>
        )}
      </section>

      {selected ? (
        <DetailCard
          row={selected}
          nowMs={nowMs}
          onClose={() => setSelectedId(null)}
          onFilterCountry={toggleCountry}
        />
      ) : null}

      <div style={gridStyle}>
        <div style={listColumnStyle}>
          {alertConfig.symbols.length > 0 ? (
            <EventSection
              label={`YOUR SYMBOLS · ${symbolRows.length}`}
              rows={symbolRows}
              selectedId={selectedId}
              nowMs={nowMs}
              alertConfig={alertConfig}
              onSelect={selectRow}
              showWhyHere
              emptyText={`No world headline matched your followed symbols (${alertConfig.symbols.join(
                ", ",
              )}) in the window.`}
            />
          ) : null}
          {payload?.filtered_empty ? (
            <Empty
              title="No events for this filter"
              body="The providers returned events, but none match the current filters — widen the window or clear a filter."
              icon="⌕"
            />
          ) : mode === "calendar" ? (
            <>
              <CalendarSection
                label={`UPCOMING · ${upcoming.length}`}
                rows={upcoming}
                nowMs={nowMs}
                onSelect={selectRow}
                emptyText={upcomingReleasesEmptyText}
              />
              <CalendarSection
                label={`PAST · ${past.length}`}
                rows={past}
                nowMs={nowMs}
                onSelect={selectRow}
                emptyText="No past releases in the window."
              />
            </>
          ) : (
            <>
              <EventSection
                label={`UPCOMING · ${upcoming.length}`}
                rows={upcoming}
                selectedId={selectedId}
                nowMs={nowMs}
                alertConfig={alertConfig}
                onSelect={selectRow}
                showAssetTags={mode === "wire"}
                emptyText={
                kind === "world"
                  ? "World headlines are past-dated - switch KIND to Calendar for scheduled events."
                  : upcomingEmptyText
              }
              />
              {/* Full-width rule between the two windows, labelled NOW at
                 the centre (owner 2026-09-16: "çizgi çok ince içinde NOW
                 yazsın biraz daha kalın olsun") - 2px segments keep it
                 clearly visible without shouting. */}
              <div
                aria-hidden
                style={{
                  alignItems: "center",
                  display: "flex",
                  gap: 10,
                  margin: "12px 0",
                  width: "100%",
                }}
              >
                <span style={{ background: "var(--border-strong)", flex: 1, height: 2 }} />
                <span
                  style={{
                    color: "var(--text-mute)",
                    fontFamily: "JetBrains Mono, monospace",
                    fontSize: "var(--font-size-sm)",
                    letterSpacing: "0.16em",
                  }}
                >
                  NOW
                </span>
                <span style={{ background: "var(--border-strong)", flex: 1, height: 2 }} />
              </div>
              <EventSection
                label={`PAST · ${past.length}`}
                rows={past}
                selectedId={selectedId}
                nowMs={nowMs}
                alertConfig={alertConfig}
                onSelect={selectRow}
                showAssetTags={mode === "wire"}
                emptyText="No past events in the window."
              />
            </>
          )}
        </div>
        <CountrySidebar
          catalog={catalog}
          index={countryIndex}
          followed={alertConfig.spotCountries}
          nowMs={nowMs}
          asOf={payload?.as_of}
          onToggle={toggleCountry}
        />
      </div>
    </div>
  );

  return (
    <div className="u-pane-host meet-pane">
      <Pane>
        <PaneHeader
          code={code}
          title="Meeting Briefings — World Events"
          subtitle={`${upcoming.length} upcoming · ${past.length} past · ${spotCount} spot-tracked · as of ${payload?.as_of?.slice(11, 19) ?? "—"} UTC`}
          trailing={
            <FunctionControlGroup>
              <span style={alertsWrapStyle}>
                <AlertsButton
                  open={alertsOpen}
                  historyCount={alertConfig.history.length}
                  onClick={() => setAlertsOpen((v) => !v)}
                />
                {alertsOpen ? (
                  <MeetAlertsPopover
                    config={alertConfig}
                    catalog={catalog}
                    serverAlerts={payload?.alerts}
                    nowMs={nowMs}
                    asOf={payload?.as_of}
                    onChange={setAlertConfig}
                    onClose={() => setAlertsOpen(false)}
                  />
                ) : null}
              </span>
              <LoadStatePill state={state} status={status === "—" ? null : status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh world events"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <ProviderHealthStrip
          providers={awarenessMeta?.providers}
          feedHealth={awarenessMeta?.feed_health}
          generatedAt={awarenessMeta?.generated_at}
        />
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "—"}
            title={data?.sources?.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="upcoming" value={upcoming.length} />
          <StatusDivider />
          <StatusSection label="past" value={past.length} />
          <StatusDivider />
          <StatusSection
            label="alerts"
            value={alertConfig.history.length}
            tone={alertConfig.history.length > 0 ? "warn" : undefined}
          />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection
            label="follow"
            value={alertConfig.spotCountries.join(", ") || "all countries"}
            tone="accent"
          />
          {droppedNoTime > 0 ? (
            <>
              <StatusDivider />
              <StatusSection label="untimed" value={`${droppedNoTime} untimed rows hidden`} />
            </>
          ) : null}
          {unfilteredUpcoming != null ? (
            <>
              <StatusDivider />
              <StatusSection
                label="window"
                value={`showing ${upcoming.length} of ${unfilteredUpcoming} upcoming`}
              />
            </>
          ) : null}
          {methodology ? (
            <>
              <StatusDivider />
              <span
                role="img"
                aria-label="Methodology"
                title={methodology}
                style={monoMuteStyle}
              >
                ⓘ
              </span>
            </>
          ) : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── filter bar ────────────────────────────────────────────────────── */

function FilterBar({
  mode,
  onMode,
  kind,
  onKind,
  impacts,
  onToggleImpact,
  daysAhead,
  onDaysAhead,
  daysBack,
  onDaysBack,
  limit,
  onLimit,
  queryDraft,
  onQueryDraft,
  onQuerySubmit,
  queryApplied,
  tagsDraft,
  onTagsDraft,
  onTagsSubmit,
  tagsApplied,
  dataFilter,
  onDataFilter,
  followedCountries,
  catalog,
  onToggleCountry,
  symbols,
  symbolDraft,
  onSymbolDraft,
  onAddSymbol,
  onRemoveSymbol,
}: {
  mode: ModeFilter;
  onMode: (value: ModeFilter) => void;
  kind: KindFilter;
  onKind: (value: KindFilter) => void;
  impacts: ImpactFilter[];
  onToggleImpact: (value: ImpactFilter) => void;
  daysAhead: number;
  onDaysAhead: (value: number) => void;
  daysBack: number;
  onDaysBack: (value: number) => void;
  limit: number;
  onLimit: (value: number) => void;
  queryDraft: string;
  onQueryDraft: (value: string) => void;
  onQuerySubmit: (event: FormEvent) => void;
  queryApplied: string;
  tagsDraft: string;
  onTagsDraft: (value: string) => void;
  onTagsSubmit: (event: FormEvent) => void;
  tagsApplied: string;
  dataFilter: DataFilter;
  onDataFilter: (value: DataFilter) => void;
  followedCountries: string[];
  catalog: { iso: string; name: string }[];
  onToggleCountry: (iso: string) => void;
  symbols: string[];
  symbolDraft: string;
  onSymbolDraft: (value: string) => void;
  onAddSymbol: (raw: string) => void;
  onRemoveSymbol: (symbol: string) => void;
}) {
  const unfollowed = catalog.filter((c) => !followedCountries.includes(c.iso));
  return (
    <section style={filterBarStyle} aria-label="World-event filters">
      <div style={filterRowStyle}>
        <span style={stripLabelStyle}>MODE</span>
        {MODE_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            disabled={mode === option.value}
            aria-pressed={mode === option.value}
            className={`fn-segmented__opt${mode === option.value ? " fn-segmented__opt--active" : ""}`}
            onClick={() => onMode(option.value)}
          >
            {option.label}
          </button>
        ))}
        <span style={{ ...stripLabelStyle, marginLeft: 10 }}>DATA</span>
        <select
          aria-label="Data filter"
          value={dataFilter}
          style={selectStyle}
          title={`Calendar print filter. major_only is a majors-only cut: ${MAJOR_ONLY_TITLE}`}
          onChange={(event) => onDataFilter(event.target.value as DataFilter)}
        >
          {DATA_FILTER_OPTIONS.map((d) => (
            <option
              key={d}
              value={d}
              title={d === "major_only" ? MAJOR_ONLY_TITLE : undefined}
            >
              {d === "major_only" ? "major_only · majors-only cut" : d}
            </option>
          ))}
        </select>
        <form onSubmit={onTagsSubmit} style={queryFormStyle}>
          <input
            type="text"
            value={tagsDraft}
            onChange={(event) => onTagsDraft(event.target.value)}
            placeholder="tags: BTC, FOMC…"
            aria-label="Filter by asset tags"
            style={searchInputStyle}
          />
          {/* Empty submit clears the persisted filter: the button stays
              active while applied tags exist, so the filter is escapable. */}
          <button
            type="submit"
            className="btn"
            disabled={!tagsDraft.trim() && !tagsApplied.trim()}
          >
            Tag
          </button>
        </form>
      </div>
      <div style={filterRowStyle}>
        <span style={stripLabelStyle}>FOLLOW</span>
        {followedCountries.length === 0 ? (
          <span style={monoMuteStyle}>all countries — pick countries to spot-track</span>
        ) : (
          followedCountries.map((iso) => {
            const entry = catalog.find((c) => c.iso === iso);
            return (
              <button
                key={iso}
                type="button"
                className="fn-segmented__opt fn-segmented__opt--active"
                aria-pressed
                title={`Stop tracking ${entry?.name ?? iso}`}
                onClick={() => onToggleCountry(iso)}
              >
                {entry?.name ?? iso} ✕
              </button>
            );
          })
        )}
        <select
          aria-label="Add country to follow list"
          value=""
          style={selectStyle}
          onChange={(event) => {
            if (event.target.value) onToggleCountry(event.target.value);
          }}
        >
          <option value="">+ country…</option>
          {unfollowed.map((c) => (
            <option key={c.iso} value={c.iso}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      <div style={filterRowStyle}>
        <span style={stripLabelStyle}>KIND</span>
        {KIND_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            disabled={kind === option.value || mode !== "all"}
            aria-pressed={kind === option.value}
            className={`fn-segmented__opt${kind === option.value ? " fn-segmented__opt--active" : ""}`}
            onClick={() => onKind(option.value)}
            title={mode !== "all" ? "KIND applies in All mode (MODE overrides it)" : undefined}
          >
            {option.label}
          </button>
        ))}
        <span
          style={{ ...stripLabelStyle, marginLeft: 10 }}
          title="Single-focus: a click focuses exactly one impact band; clicking the focused band again restores all."
        >
          IMPACT (single-focus)
        </span>
        {IMPACT_OPTIONS.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={impacts.includes(option)}
            className={`fn-segmented__opt${impacts.includes(option) ? " fn-segmented__opt--active" : ""}`}
            title={`Toggle ${option} impact`}
            onClick={() => onToggleImpact(option)}
          >
            {option}
          </button>
        ))}
        <span style={{ ...stripLabelStyle, marginLeft: 10 }}>WINDOW</span>
        <select
          aria-label="Days ahead"
          value={String(daysAhead)}
          style={selectStyle}
          onChange={(event) => onDaysAhead(Number(event.target.value))}
        >
          {AHEAD_DAYS.map((d) => (
            <option key={d} value={d}>
              ahead {d}d
            </option>
          ))}
        </select>
        <select
          aria-label="Days back"
          value={String(daysBack)}
          style={selectStyle}
          onChange={(event) => onDaysBack(Number(event.target.value))}
        >
          {BACK_DAYS.map((d) => (
            <option key={d} value={d}>
              back {d}d
            </option>
          ))}
        </select>
        <select
          aria-label="Result limit"
          value={String(limit)}
          style={selectStyle}
          title="Rows requested per load (upcoming-first priority)"
          onChange={(event) => onLimit(Number(event.target.value))}
        >
          {LIMIT_OPTIONS.map((n) => (
            <option key={n} value={n}>
              limit {n}
            </option>
          ))}
        </select>
        <form onSubmit={onQuerySubmit} style={queryFormStyle}>
          <input
            type="text"
            value={queryDraft}
            onChange={(event) => onQueryDraft(event.target.value)}
            placeholder="search events…"
            aria-label="Search world events"
            style={searchInputStyle}
          />
          <button type="submit" className="btn" disabled={!queryDraft.trim() && !queryApplied.trim()}>
            Find
          </button>
        </form>
      </div>

      <div style={filterRowStyle}>
        <span style={stripLabelStyle}>SYMBOLS</span>
        {symbols.length === 0 ? (
          <span style={monoMuteStyle}>follow crypto / equity / pairs (e.g. BTCUSDT, USDTRY)</span>
        ) : (
          symbols.map((symbol) => (
            <FollowQuote key={symbol} symbol={symbol} onRemove={onRemoveSymbol} />
          ))
        )}
        <form
          onSubmit={(event) => {
            event.preventDefault();
            onAddSymbol(symbolDraft);
          }}
          style={queryFormStyle}
        >
          <input
            type="text"
            value={symbolDraft}
            onChange={(event) => onSymbolDraft(event.target.value)}
            placeholder="add symbol…"
            aria-label="Add symbol to follow list"
            style={searchInputStyle}
          />
          <button type="submit" className="btn" disabled={!symbolDraft.trim()}>
            Add
          </button>
        </form>
      </div>
    </section>
  );
}

function FollowQuote({ symbol, onRemove }: { symbol: string; onRemove: (symbol: string) => void }) {
  const quote = useLiveQuote(symbol);
  const change = quote.changePct;
  const tone =
    change == null ? "var(--text-mute)" : change >= 0 ? "var(--positive)" : "var(--negative)";
  return (
    <span style={followChipStyle} data-testid={`meet-follow-${symbol}`}>
      <strong style={monoStyle}>{symbol}</strong>
      <span style={monoStyle}>{quote.price == null ? "—" : formatPrice(quote.price)}</span>
      <span style={{ ...monoStyle, color: tone }}>
        {change == null ? "—" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`}
      </span>
      <button
        type="button"
        aria-label={`Stop following ${symbol}`}
        title={`Stop following ${symbol}`}
        style={chipRemoveStyle}
        onClick={() => onRemove(symbol)}
      >
        ✕
      </button>
    </span>
  );
}

/* ── list ──────────────────────────────────────────────────────────── */

function EventSection({
  label,
  rows,
  nowMs,
  alertConfig,
  onSelect,
  emptyText,
  selectedId,
  showAssetTags = false,
  showWhyHere = false,
}: {
  label: string;
  rows: MeetRow[];
  nowMs: number;
  alertConfig: MeetAlertConfig;
  onSelect: (id: string) => void;
  emptyText: string;
  selectedId?: string | null;
  showAssetTags?: boolean;
  showWhyHere?: boolean;
}) {
  return (
    <section aria-label={label} style={sectionStyle}>
      <div style={sectionHeadStyle}>
        <span style={stripLabelStyle}>{label}</span>
      </div>
      {rows.length === 0 ? (
        <div style={emptyRowStyle}>{emptyText}</div>
      ) : (
        <ul style={listStyle}>
          {rows.map((row) => (
            <EventRow
              key={row.id}
              row={row}
              nowMs={nowMs}
              spot={isSpotFor(row, alertConfig)}
              onSelect={onSelect}
              expanded={row.id === selectedId}
              showAssetTags={showAssetTags}
              whyHere={showWhyHere ? whyHereOf(row) : null}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function EventRow({
  row,
  nowMs,
  spot,
  onSelect,
  expanded = false,
  showAssetTags = false,
  whyHere = null,
}: {
  row: MeetRow;
  nowMs: number;
  spot: boolean;
  onSelect: (id: string) => void;
  expanded?: boolean;
  showAssetTags?: boolean;
  whyHere?: string | null;
}) {
  const seconds = secondsUntil(row, nowMs);
  const past = isPastRow(row, nowMs);
  const countdown = row.undated
    ? "wire"
    : past
      ? formatAge(seconds)
      : formatCountdown(seconds);
  const impact = String(row.impact || "low");
  /* High-impact rows carry a VERY transparent red wash (owner 2026-09-16:
     "kırmızı highlight ... ancak çok transparan bir kırmızı"). Fixed alpha
     on purpose so the tint reads identically across presets. */
  const highImpact = impact.toLowerCase() === "high";
  return (
    <li style={rowItemStyle}>
      <button
        type="button"
        className="btn btn--ghost"
        style={
          highImpact
            ? { ...rowButtonStyle, background: "rgba(198, 40, 40, 0.06)" }
            : rowButtonStyle
        }
        aria-label={`${row.title} — ${countdown}`}
        onClick={() => onSelect(row.id)}
      >
        <span style={countdownStyle} title="Adaptive countdown to the event">
          {countdown}
        </span>
        <span
          style={{
            ...monoMuteStyle,
            minWidth: 118,
          }}
          title={row.when_utc ?? undefined}
        >
          {row.undated ? "undated" : utcLabel(row.when_utc)}
        </span>
        <Pill tone={impactTone(impact)} variant="soft" withDot={false}>
          {impact}
        </Pill>
        <Pill tone={row.kind === "world" ? "accent" : "neutral"} variant="soft" withDot={false}>
          {row.kind === "world" ? "WORLD" : "ECON"}
        </Pill>
        <span style={rowMainStyle}>
          <span style={titleStyle}>{row.title}</span>
          <span style={metaStyle}>
            {[
              row.country_names.join(" / "),
              row.pairs.length ? row.pairs.slice(0, 6).join(", ") : "",
              row.source,
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
          {whyHere ? (
            <span style={metaStyle} aria-label={`match rationale: ${whyHere}`}>
              {whyHere}
            </span>
          ) : null}
        </span>
        {showAssetTags ? <AssetChips row={row} /> : null}
        {spot ? (
          <Pill tone="warn" variant="filled" withDot>
            SPOT
          </Pill>
        ) : row.pinned ? (
          <Pill tone="accent" variant="ghost" withDot={false}>
            PIN
          </Pill>
        ) : null}
      </button>
      {/* In-place growth on click (owner 2026-09-16): the wire summary
          appears under the row instead of only in the detail aside. */}
      {expanded ? (
        <div style={expandPanelStyle} data-testid="meet-row-summary">
          {(() => {
            const summary = row.summary ?? row.details?.summary ?? null;
            const forecast = row.details?.forecast;
            const previous = row.details?.previous;
            const hasNumbers = forecast != null || previous != null;
            const meta = [
              row.country_names?.length ? row.country_names.join(", ") : null,
              row.currencies?.length ? row.currencies.join(", ") : null,
              row.pairs?.length ? `pairs ${row.pairs.join(", ")}` : null,
              row.source || null,
            ]
              .filter(Boolean)
              .join(" · ");
            return (
              <>
                {summary ? <p style={expandSummaryStyle}>{summary}</p> : null}
                {hasNumbers ? (
                  <p style={expandSummaryStyle}>
                    {forecast != null ? `Forecast: ${String(forecast)}` : "Forecast: —"}
                    {" · "}
                    {previous != null ? `Previous: ${String(previous)}` : "Previous: —"}
                    {row.details?.unit ? ` (${row.details.unit})` : ""}
                  </p>
                ) : null}
                {meta ? <p style={expandMutedStyle}>{meta}</p> : null}
                {row.details?.url ? (
                  <a
                    href={row.details.url}
                    target="_blank"
                    rel="noreferrer"
                    style={expandLinkStyle}
                  >
                    Open source ↗
                  </a>
                ) : null}
                {/* Calendar rows carry no article text; show the payload
                    facts instead of a "no summary" dead end (owner
                    2026-09-16: "hepsinde bu hatayı veriyor"). */}
                {!summary && !hasNumbers && !meta && !row.details?.url ? (
                  <p style={expandMutedStyle}>
                    No extra details in the payload for this item.
                  </p>
                ) : null}
              </>
            );
          })()}
        </div>
      ) : null}
    </li>
  );
}

function assetTagsOf(row: MeetRow): string[] {
  const tags = row.details?.asset_tags ?? row.asset_tags ?? [];
  return Array.from(
    new Set(tags.map((tag) => String(tag).toUpperCase()).filter(Boolean)),
  );
}

/** Per-row caption explaining why a symbol-section row is here ("why here:
 *  BTC · market_wide"). Null when the backend shipped no rationale — the row
 *  then renders exactly as before (backward compatible). */
function whyHereOf(row: MeetRow): string | null {
  const matches = (row.symbol_matches ?? []).map((m) => String(m)).filter(Boolean);
  const relevance = row.symbol_relevance ? String(row.symbol_relevance) : null;
  if (matches.length === 0 && !relevance) return null;
  return `why here: ${[...matches, ...(relevance ? [relevance] : [])].join(" · ")}`;
}

/** Wire-mode asset chips (BTC/ETF/FED...) carried by the backend tagger. */
function AssetChips({ row }: { row: MeetRow }) {
  const tags = assetTagsOf(row);
  if (tags.length === 0) return null;
  return (
    <span style={chipsWrapStyle} aria-label={`asset tags: ${tags.join(", ")}`}>
      {tags.slice(0, 6).map((tag) => (
        <span key={tag} style={pairChipStyle}>
          {tag}
        </span>
      ))}
    </span>
  );
}

/* ── calendar table (MQL5 parity) ─────────────────────────────────── */

function CalendarSection({
  label,
  rows,
  nowMs,
  onSelect,
  emptyText,
}: {
  label: string;
  rows: MeetRow[];
  nowMs: number;
  onSelect: (id: string) => void;
  emptyText: string;
}) {
  const groups = useMemo(() => groupCalendarByDay(rows, nowMs), [rows, nowMs]);
  const columns: DataGridColumn<MeetRow>[] = useMemo(
    () => [
      {
        key: "time",
        header: "Time",
        width: 150,
        sortable: true,
        sortValue: (r) => {
          const ts = Date.parse(r.when_utc ?? "");
          return Number.isFinite(ts) ? ts : null;
        },
        render: (r) => {
          const seconds = secondsUntil(r, nowMs);
          const past = isPastRow(r, nowMs);
          const countdown = r.undated
            ? "wire"
            : past
              ? formatAge(seconds)
              : formatCountdown(seconds);
          return (
            <span style={calTimeStyle}>
              <span style={countdownStyle}>{countdown}</span>
              <span style={monoMuteStyle}>
                {r.undated ? "undated" : utcLabel(r.when_utc)}
              </span>
            </span>
          );
        },
      },
      {
        key: "ccy",
        header: "Ccy",
        width: 92,
        sortable: true,
        sortValue: (r) => r.currencies?.[0] ?? r.countries?.[0] ?? "",
        render: (r) => {
          const ccy = r.currencies?.[0] ?? r.countries?.[0] ?? "—";
          return (
            <span style={monoStyle}>
              {flagOf(ccy) ? `${flagOf(ccy)} ` : ""}
              {ccy}
            </span>
          );
        },
      },
      {
        key: "event",
        header: "Event",
        sortable: true,
        sortValue: (r) => r.title ?? "",
        render: (r) => <span style={titleStyle}>{r.title}</span>,
      },
      {
        key: "actual",
        header: "Actual",
        numeric: true,
        width: 118,
        sortable: true,
        sortValue: (r) => parsePrintNumber(r.details?.actual),
        render: (r) => {
          const value = r.details?.actual;
          // Pending release: honest "—" plus a pending badge, never a guess.
          if (value == null || String(value).trim() === "") {
            return (
              <span style={pendingCellStyle}>
                <span style={monoMuteStyle}>—</span>
                <Pill tone="muted" variant="soft" withDot={false}>
                  pending
                </Pill>
              </span>
            );
          }
          return (
            <span style={primaryNumStyle}>{formatPrint(value, r.details?.unit)}</span>
          );
        },
      },
      {
        key: "forecast",
        header: "Forecast",
        numeric: true,
        width: 96,
        sortable: true,
        sortValue: (r) => parsePrintNumber(r.details?.forecast),
        render: (r) => (
          <span style={mutedNumStyle}>{formatPrint(r.details?.forecast, r.details?.unit)}</span>
        ),
      },
      {
        key: "previous",
        header: "Previous",
        numeric: true,
        width: 118,
        sortable: true,
        sortValue: (r) => parsePrintNumber(r.details?.previous),
        // The backend ships the raw previous text (carries "Prev → Rev"
        // when a revision exists); no second field is invented here.
        render: (r) => (
          <span style={mutedNumStyle}>{formatPrint(r.details?.previous, r.details?.unit)}</span>
        ),
      },
      {
        key: "surprise",
        header: "Surprise",
        numeric: true,
        width: 110,
        render: (r) => {
          const surprise = surpriseOf(r.details);
          if (surprise == null || !Number.isFinite(surprise)) {
            return <span style={monoMuteStyle}>—</span>;
          }
          // Labour-market pain gauges read inversely: a higher print is
          // bad news, so the chip flips colour (ECO DeltaChip pattern).
          const up = surprise > 0 ? "up" : surprise < 0 ? "down" : "flat";
          const inverse = polarityOf(r.title) === "inverse";
          const direction =
            inverse && up !== "flat" ? (up === "up" ? "down" : "up") : up;
          return (
            <DeltaChip value={surprise} direction={direction} format="raw" fractionDigits={2} />
          );
        },
      },
      {
        key: "source",
        header: "Source",
        width: 118,
        sortable: true,
        sortValue: (r) => r.source ?? "",
        render: (r) => <span style={monoMuteStyle}>{r.source || "—"}</span>,
      },
      {
        key: "impact",
        header: "Impact",
        width: 96,
        sortable: true,
        sortValue: (r) => r.impact ?? "",
        render: (r) => (
          <Pill tone={impactTone(String(r.impact || "low"))} variant="soft" withDot={false}>
            {String(r.impact || "low")}
          </Pill>
        ),
      },
    ],
    [nowMs],
  );
  return (
    <section aria-label={label} style={sectionStyle}>
      <div style={sectionHeadStyle}>
        <span style={stripLabelStyle}>{label}</span>
      </div>
      {rows.length === 0 ? (
        <div style={emptyRowStyle}>{emptyText}</div>
      ) : (
        <div style={calGroupsStyle}>
          {groups.map((group) => (
            <div key={group.key} style={calGroupStyle}>
              <div style={sectionHeadStyle}>
                <span style={stripLabelStyle}>
                  {group.key} · {group.rows.length}
                </span>
              </div>
              <DataGrid
                columns={columns}
                rows={group.rows}
                rowKey={(r) => r.id}
                density="compact"
                ariaLabel={`${label} ${group.key}`}
                onRowClick={(r) => onSelect(r.id)}
              />
            </div>
          ))}
          <span style={tzNoteStyle}>Times UTC</span>
        </div>
      )}
    </section>
  );
}

function DetailCard({
  row,
  nowMs,
  onClose,
  onFilterCountry,
}: {
  row: MeetRow;
  nowMs: number;
  onClose: () => void;
  onFilterCountry: (iso: string) => void;
}) {
  const seconds = secondsUntil(row, nowMs);
  const past = isPastRow(row, nowMs);
  const timing = row.undated ? "undated wire" : past ? `${formatAge(seconds)}` : `in ${formatCountdown(seconds)}`;
  const details = row.details ?? {};
  const matched = details.matched_terms ?? [];
  const eventType = details.event_type ?? row.event_type ?? null;
  const providerTags = Array.isArray(details.provider_tags)
    ? details.provider_tags.map((t) => String(t)).filter(Boolean)
    : [];
  return (
    <aside role="region" aria-label="Event detail" style={detailStyle}>
      <div style={detailHeadStyle}>
        <span style={stripLabelStyle}>EVENT DETAIL</span>
        <Pill tone={impactTone(row.impact)} variant="soft" withDot={false}>
          {row.impact}
        </Pill>
        {row.spot ? (
          <Pill tone="warn" variant="filled" withDot>
            SPOT
          </Pill>
        ) : null}
        <button
          type="button"
          className="btn"
          style={{ marginLeft: "auto" }}
          onClick={onClose}
          aria-label="Close event detail"
        >
          Close
        </button>
      </div>
      <div style={titleStyle}>{row.title}</div>
      <div style={metaStyle}>
        {row.undated ? "publish time unavailable" : `${utcLabel(row.when_utc)} UTC`} · {timing} ·{" "}
        {row.kind === "world" ? "world headline" : "scheduled release"} · source {row.source}
      </div>
      <div style={detailGridStyle}>
        <div>
          <span style={stripLabelStyle}>COUNTRIES</span>
          <div style={chipsWrapStyle}>
            {row.countries.length === 0 ? (
              <span style={monoMuteStyle}>no country attribution (global)</span>
            ) : (
              row.countries.map((iso, index) => (
                <button
                  key={iso}
                  type="button"
                  className="fn-segmented__opt"
                  title={`Follow ${row.country_names[index] ?? iso}`}
                  onClick={() => onFilterCountry(iso)}
                >
                  {row.country_names[index] ?? iso} ({iso})
                </button>
              ))
            )}
          </div>
        </div>
        <div>
          <span style={stripLabelStyle}>AFFECTED</span>
          <div style={chipsWrapStyle}>
            {row.pairs.length === 0 ? (
              <span style={monoMuteStyle}>—</span>
            ) : (
              row.pairs.map((pair) => (
                <span key={pair} style={pairChipStyle}>
                  {pair}
                </span>
              ))
            )}
          </div>
        </div>
        {row.kind === "economic" ? (
          <div>
            <span style={stripLabelStyle}>PRINT</span>
            <div style={metaStyle}>
              actual {fmtDetail(details.actual)} · forecast {fmtDetail(details.forecast)} · previous{" "}
              {fmtDetail(details.previous)}
              {details.unit ? ` ${String(details.unit)}` : ""}
            </div>
          </div>
        ) : null}
        {matched.length > 0 ? (
          <div>
            <span style={stripLabelStyle}>MATCHED TERMS</span>
            <div style={metaStyle}>{matched.join(" · ")}</div>
          </div>
        ) : null}
        {eventType ? (
          <div>
            <span style={stripLabelStyle}>EVENT TYPE</span>
            <div style={metaStyle}>{String(eventType)}</div>
          </div>
        ) : null}
        {providerTags.length > 0 ? (
          <div>
            <span style={stripLabelStyle}>PROVIDER TAGS</span>
            <div style={chipsWrapStyle}>
              {providerTags.slice(0, 6).map((tag) => (
                <span key={tag} style={pairChipStyle}>
                  {tag}
                </span>
              ))}
            </div>
          </div>
        ) : null}
        {details.publisher ? (
          <div>
            <span style={stripLabelStyle}>PUBLISHER / FEED</span>
            <div style={metaStyle}>
              {String(details.publisher)}
              {details.feed_url ? ` · ${String(details.feed_url)}` : ""}
            </div>
          </div>
        ) : null}
        {details.country_basis === "title_inference" ? (
          <div>
            <span style={stripLabelStyle}>COUNTRY BASIS</span>
            <div style={metaStyle}>inferred from event title</div>
          </div>
        ) : null}
      </div>
      {details.article_url || details.provider_event_url || details.url ? (
        <a href={String(details.article_url || details.provider_event_url || details.url)} target="_blank" rel="noreferrer" style={linkStyle}>
          open source ↗
        </a>
      ) : null}
    </aside>
  );
}

/* ── country sidebar ───────────────────────────────────────────────── */

function CountrySidebar({
  catalog,
  index,
  followed,
  nowMs,
  asOf,
  onToggle,
}: {
  catalog: { iso: string; name: string }[];
  index: Map<string, MeetCountryEntry>;
  followed: string[];
  nowMs: number;
  asOf?: string;
  onToggle: (iso: string) => void;
}) {
  const [search, setSearch] = useState("");
  const entries = useMemo(() => {
    const withEvents = catalog.filter((c) => index.has(c.iso));
    const withoutEvents = catalog.filter((c) => !index.has(c.iso));
    const ordered = [...withEvents, ...withoutEvents];
    const q = search.trim().toLowerCase();
    if (!q) return ordered;
    return ordered.filter(
      (c) => c.name.toLowerCase().includes(q) || c.iso.toLowerCase().includes(q),
    );
  }, [catalog, index, search]);

  return (
    <aside aria-label="Country status" style={sidebarStyle}>
      <div style={sectionHeadStyle}>
        <span style={stripLabelStyle}>COUNTRIES · {catalog.length}</span>
      </div>
      <input
        type="text"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="filter countries…"
        aria-label="Filter countries"
        style={{ ...searchInputStyle, width: "100%" }}
      />
      <ul style={sidebarListStyle}>
        {entries.map((entry) => {
          const bucket = index.get(entry.iso);
          const active = followed.includes(entry.iso);
          const nextSeconds = snapshotSeconds(
            bucket?.next_event?.when_utc,
            bucket?.next_event?.seconds_to_event,
            nowMs,
            asOf,
          );
          const hasCurrentNext = nextSeconds != null && nextSeconds > 0;
          const stateKey = hasCurrentNext ? (bucket?.state ?? "quiet") : "quiet";
          return (
            <li key={entry.iso}>
              <button
                type="button"
                className="btn btn--ghost"
                aria-pressed={active}
                aria-label={`Follow ${entry.name}`}
                title={`Follow ${entry.name}`}
                style={{
                  ...sidebarRowStyle,
                  background: active ? "var(--bg-elev-2)" : "transparent",
                }}
                onClick={() => onToggle(entry.iso)}
              >
                <span style={isoStyle}>{entry.iso}</span>
                <span style={sidebarNameStyle}>{entry.name}</span>
                {bucket && bucket.upcoming_count > 0 && hasCurrentNext ? (
                  <span style={monoMuteStyle}>
                    {formatCountdown(nextSeconds)}
                  </span>
                ) : null}
                <Pill
                  tone={stateTone(stateKey)}
                  variant="soft"
                  withDot={stateKey === "live" || stateKey === "imminent"}
                >
                  {stateKey}
                </Pill>
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}

/* ── alerts popover ────────────────────────────────────────────────── */

function AlertsButton({
  open,
  historyCount,
  onClick,
}: {
  open: boolean;
  historyCount: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="btn"
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-label="MEET alert settings"
      title="Spot alert rules: lead times, followed countries, followed symbols"
      onClick={onClick}
    >
      {`Alerts${historyCount > 0 ? ` · ${historyCount}` : ""}`}
    </button>
  );
}

function MeetAlertsPopover({
  config,
  catalog,
  serverAlerts,
  nowMs,
  asOf,
  onChange,
  onClose,
}: {
  config: MeetAlertConfig;
  catalog: { iso: string; name: string }[];
  serverAlerts?: MeetAlertEntry[];
  nowMs?: number;
  asOf?: string;
  onChange: (next: MeetAlertConfig) => void;
  onClose: () => void;
}) {
  const LEAD_CHOICES = [1440, 60, 5];
  const unfollowed = catalog.filter((c) => !config.spotCountries.includes(c.iso));
  const activeServerAlerts = (serverAlerts ?? [])
    .map((alert) => ({
      alert,
      seconds: snapshotSeconds(
        alert.when_utc,
        alert.seconds_to_event,
        nowMs ?? Date.now(),
        asOf,
      ),
    }))
    .filter(({ seconds }) => seconds != null && seconds >= 0);
  return (
    <div
      role="dialog"
      aria-label="MEET alert settings"
      data-testid="meet-alerts-popover"
      style={popoverStyle}
      onKeyDown={(event) => {
        if (event.key === "Escape") onClose();
      }}
    >
      <div style={{ ...popoverTitleStyle, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span>MEET SPOT ALERTS</span>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={onClose}
          aria-label="Close alert settings"
          title="Close"
        >
          ✕
        </button>
      </div>
      {activeServerAlerts.length > 0 ? (
        <div style={popoverBlockStyle}>
          <span style={stripLabelStyle}>SERVER SPOT (upcoming)</span>
          <ul style={historyListStyle}>
            {activeServerAlerts.slice(0, 8).map(({ alert, seconds }) => {
              const meta = [
                (alert.country_names ?? []).join(", "),
                (alert.pairs ?? []).slice(0, 4).join(", "),
                (alert.lead_minutes ?? []).map((m) => leadLabel(m)).join(" · "),
              ]
                .filter(Boolean)
                .join(" · ");
              return (
                <li key={alert.id} style={historyItemStyle}>
                  <span style={monoMuteStyle}>{formatCountdown(seconds)}</span>
                  <span style={historyTitleStyle}>{alert.title}</span>
                  {meta ? <span style={monoMuteStyle}>{meta}</span> : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      <label style={popoverRowStyle}>
        <input
          type="checkbox"
          checked={config.enabled}
          onChange={(event) => onChange({ ...config, enabled: event.target.checked })}
        />
        enabled — toast on lead-time hits (rate decisions, wars, followed countries)
      </label>

      <div style={popoverBlockStyle}>
        <span style={stripLabelStyle}>LEAD TIMES</span>
        <div style={chipsWrapStyle}>
          {LEAD_CHOICES.map((lead) => {
            const active = config.leadMinutes.includes(lead);
            return (
              <button
                key={lead}
                type="button"
                aria-pressed={active}
                className={`fn-segmented__opt${active ? " fn-segmented__opt--active" : ""}`}
                onClick={() =>
                  onChange({
                    ...config,
                    leadMinutes: active
                      ? config.leadMinutes.filter((m) => m !== lead)
                      : [...config.leadMinutes, lead].sort((a, b) => b - a),
                  })
                }
              >
                {leadLabel(lead)}
              </button>
            );
          })}
        </div>
      </div>

      <div style={popoverBlockStyle}>
        <span style={stripLabelStyle}>SPOT-TRACKED COUNTRIES</span>
        <div style={chipsWrapStyle}>
          {config.spotCountries.length === 0 ? (
            <span style={monoMuteStyle}>none — only provider-flagged spots fire</span>
          ) : (
            config.spotCountries.map((iso) => {
              const entry = catalog.find((c) => c.iso === iso);
              return (
                <button
                  key={iso}
                  type="button"
                  className="fn-segmented__opt fn-segmented__opt--active"
                  title={`Remove ${entry?.name ?? iso}`}
                  onClick={() =>
                    onChange({
                      ...config,
                      spotCountries: config.spotCountries.filter((c) => c !== iso),
                    })
                  }
                >
                  {entry?.name ?? iso} ✕
                </button>
              );
            })
          )}
        </div>
        <select
          aria-label="Add spot-tracked country"
          value=""
          style={selectStyle}
          onChange={(event) => {
            if (event.target.value) {
              onChange({
                ...config,
                spotCountries: [...config.spotCountries, event.target.value],
              });
            }
          }}
        >
          <option value="">+ country…</option>
          {unfollowed.map((c) => (
            <option key={c.iso} value={c.iso}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      <div style={popoverBlockStyle}>
        <span style={stripLabelStyle}>ALERT HISTORY ({config.history.length})</span>
        {config.history.length === 0 ? (
          <span style={monoMuteStyle}>no alerts fired yet</span>
        ) : (
          <ul style={historyListStyle}>
            {config.history.slice(0, 8).map((item) => (
              <li key={item.key} style={historyItemStyle}>
                <span style={monoMuteStyle}>
                  {item.lead == null ? "arrival" : leadLabel(item.lead)}
                </span>
                <span style={historyTitleStyle}>{item.title}</span>
                <span style={monoMuteStyle}>{utcLabel(item.when_utc)}</span>
              </li>
            ))}
          </ul>
        )}
        {config.history.length > 0 ? (
          <button
            type="button"
            className="btn"
            onClick={() => onChange({ ...config, history: [] })}
          >
            Clear history
          </button>
        ) : null}
      </div>
    </div>
  );
}

/* ── helpers / styles ──────────────────────────────────────────────── */

function snapshotSeconds(
  whenUtc: string | undefined,
  snapshotSecondsToEvent: number | undefined,
  nowMs: number,
  asOf: string | undefined,
): number | null {
  const eventMs = whenUtc ? Date.parse(whenUtc) : Number.NaN;
  if (Number.isFinite(eventMs)) return (eventMs - nowMs) / 1000;
  const asOfMs = asOf ? Date.parse(asOf) : Number.NaN;
  if (typeof snapshotSecondsToEvent !== "number" || !Number.isFinite(snapshotSecondsToEvent)) {
    return null;
  }
  return Number.isFinite(asOfMs)
    ? snapshotSecondsToEvent - (nowMs - asOfMs) / 1000
    : snapshotSecondsToEvent;
}

function utcLabel(iso: string | undefined | null): string {
  if (!iso) return "—";
  const ts = Date.parse(iso);
  if (!Number.isFinite(ts)) return String(iso).slice(0, 16);
  return new Date(ts).toISOString().replace("T", " ").slice(0, 16);
}

function fmtDetail(value: unknown): string {
  if (value == null || value === "") return "—";
  return String(value);
}

function stateTone(state: string): "warn" | "accent" | "positive" | "muted" | "neutral" {
  switch (state) {
    case "live":
      return "warn";
    case "imminent":
      return "warn";
    case "soon":
      return "accent";
    case "scheduled":
      return "positive";
    default:
      return "muted";
  }
}

function readImpactFilter(): ImpactFilter[] {
  // No stored selection means "all bands" — return the full list (not [])
  // so the chips render active. Backend-equivalent either way (empty and
  // full both disable impact filtering), but [] looked deselected.
  const all = [...IMPACT_OPTIONS];
  if (typeof localStorage === "undefined") return all;
  const raw = localStorage.getItem("showme.meet.impact") ?? "";
  const parsed = raw
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter((value): value is ImpactFilter =>
      (IMPACT_OPTIONS as readonly string[]).includes(value),
    );
  return parsed.length > 0 ? parsed : all;
}

const stackStyle: CSSProperties = { display: "grid", gap: 12 };
const gridStyle: CSSProperties = {
  display: "flex",
  gap: 12,
  alignItems: "flex-start",
  flexWrap: "wrap",
};
const listColumnStyle: CSSProperties = { flex: "1 1 520px", minWidth: 0, display: "grid", gap: 14 };
const sidebarStyle: CSSProperties = {
  flex: "0 1 280px",
  minWidth: 240,
  display: "grid",
  gap: 6,
  border: "1px solid var(--border-subtle)",
  borderRadius: 8,
  padding: 8,
  maxHeight: 720,
};
const sidebarListStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "grid",
  gap: 2,
  overflowY: "auto",
  maxHeight: 620,
};
const sidebarRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  width: "100%",
  textAlign: "left",
  padding: "4px 6px",
  borderRadius: 5,
};
const isoStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--accent)",
  minWidth: 26,
};
const sidebarNameStyle: CSSProperties = {
  flex: 1,
  fontSize: "var(--font-size-sm)",
  color: "var(--text-primary)",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};
const filterBarStyle: CSSProperties = {
  display: "grid",
  gap: 6,
  border: "1px solid var(--border-subtle)",
  borderRadius: 8,
  padding: "8px 10px",
};
const filterRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
};
const selectStyle: CSSProperties = {
  padding: "3px 6px",
  fontSize: "var(--font-size-sm)",
};
const queryFormStyle: CSSProperties = { display: "flex", gap: 4, alignItems: "center" };
const searchInputStyle: CSSProperties = { width: 170 };
const nextImpactStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  flexWrap: "wrap",
  padding: "7px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: 7,
  background: "var(--bg-elev-2)",
};
const sectionStyle: CSSProperties = { display: "grid", gap: 6 };
const sectionHeadStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 8 };
const listStyle: CSSProperties = { listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 4 };
const rowItemStyle: CSSProperties = { minWidth: 0 };
const rowButtonStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  width: "100%",
  textAlign: "left",
  padding: "6px 8px",
  border: "1px solid var(--border-subtle)",
  borderRadius: 6,
};
const rowMainStyle: CSSProperties = { minWidth: 0, flex: 1, display: "grid", gap: 1 };
/* Expanded wire summary under a selected row (owner: "haberlere basınca
   haber büyüsün haber özeti gelsin"). */
const expandPanelStyle: CSSProperties = {
  background: "var(--bg-elev-2, var(--surface-1))",
  border: "1px solid var(--border-subtle)",
  borderRadius: 6,
  display: "grid",
  gap: 6,
  marginTop: 4,
  padding: "8px 10px",
};
const expandSummaryStyle: CSSProperties = {
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-sm)",
  lineHeight: 1.5,
  margin: 0,
  whiteSpace: "pre-wrap",
};
const expandLinkStyle: CSSProperties = {
  color: "var(--accent)",
  fontSize: "var(--font-size-sm)",
};
const expandMutedStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs, 10px)",
  margin: 0,
};
const countdownStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
  color: "var(--accent)",
  minWidth: 74,
};
/* Calendar-table (MQL5 parity) cells — mono tabular numerals like ECO. */
const calTimeStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "baseline",
  gap: 8,
  fontVariantNumeric: "tabular-nums",
};
const calGroupsStyle: CSSProperties = { display: "grid", gap: 10 };
const calGroupStyle: CSSProperties = { display: "grid", gap: 4 };
const pendingCellStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
};
const mutedNumStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
};
const primaryNumStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-display)",
  fontWeight: 600,
};
const tzNoteStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: "var(--font-size-2xs)",
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  fontFamily: "JetBrains Mono, monospace",
};
const titleStyle: CSSProperties = {
  fontSize: "var(--font-size-md)",
  color: "var(--text-primary)",
  overflowWrap: "anywhere",
};
const metaStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
};
const monoMuteStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
};
const monoStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
};
const stripLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  letterSpacing: "0.06em",
  color: "var(--text-mute)",
};
const emptyRowStyle: CSSProperties = {
  fontSize: "var(--font-size-sm)",
  color: "var(--text-mute)",
  padding: "6px 2px",
};
const detailStyle: CSSProperties = {
  display: "grid",
  gap: 6,
  border: "1px solid var(--border-strong)",
  borderRadius: 8,
  padding: "8px 10px",
  background: "var(--bg-elev-1)",
};
const detailHeadStyle: CSSProperties = { display: "flex", alignItems: "center", gap: 8 };
const detailGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
  gap: 8,
};
const chipsWrapStyle: CSSProperties = {
  display: "flex",
  gap: 4,
  flexWrap: "wrap",
  alignItems: "center",
};
const pairChipStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  border: "1px solid var(--border-subtle)",
  borderRadius: 4,
  padding: "1px 5px",
  color: "var(--text-primary)",
};
const followChipStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  border: "1px solid var(--border-subtle)",
  borderRadius: 5,
  padding: "2px 6px",
};
const chipRemoveStyle: CSSProperties = {
  background: "none",
  border: "none",
  color: "var(--text-mute)",
  cursor: "pointer",
  padding: 0,
  fontSize: "var(--font-size-2xs)",
};
const popoverStyle: CSSProperties = {
  position: "absolute",
  top: "calc(100% + 6px)",
  right: 0,
  zIndex: 60,
  width: 360,
  maxHeight: 520,
  overflowY: "auto",
  display: "grid",
  gap: 10,
  padding: 12,
  border: "1px solid var(--border-strong)",
  borderRadius: 8,
  background: "var(--bg-elev-2)",
  boxShadow: "0 12px 32px rgba(0,0,0,0.35)",
};
const popoverTitleStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
  letterSpacing: "0.08em",
  color: "var(--text-primary)",
};
const popoverRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  fontSize: "var(--font-size-sm)",
  color: "var(--text-primary)",
};
const popoverBlockStyle: CSSProperties = { display: "grid", gap: 6 };
const historyListStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "grid",
  gap: 3,
};
const historyItemStyle: CSSProperties = {
  display: "flex",
  gap: 6,
  alignItems: "baseline",
  borderBottom: "1px solid var(--border-subtle)",
  paddingBottom: 2,
};
const historyTitleStyle: CSSProperties = {
  flex: 1,
  fontSize: "var(--font-size-sm)",
  color: "var(--text-primary)",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};
const linkStyle: CSSProperties = {
  color: "var(--accent)",
  textDecoration: "none",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
};
const alertsWrapStyle: CSSProperties = { position: "relative", display: "inline-flex" };
