/**
 * TRDH — trading-hours board (Awareness-backed exchange calendars).
 *
 * Sessions come from awareness `/calendar/sessions` and closures from
 * `/calendar/holidays`. The pane sends an explicit MIC list (XNYS, XLON, ...),
 * persisted under `showme.trdh.exchanges`. Venues that awareness does not
 * calendar (crypto venues) are not offered.
 *
 * Countdowns are computed from the payload's next_open_utc / next_close_utc
 * against the wall clock. A venue open with no next close is shown as
 * "continuous" rather than given an invented close time.
 */
import { useEffect, useMemo, useState, type CSSProperties } from "react";
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
import { formatMissing } from "@/lib/format";
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";
import { AwarenessUnavailable } from "./awareness/AwarenessUnavailable";
import type { AwarenessMeta } from "./awareness/types";

// Countdowns fall as wall-clock advances, so the board re-fetches every
// minute (visibility-paused). The tick stays OUT of the fetch params.
const REFRESH_MS = 60_000;

export interface TrdhSession {
  date?: string | null;
  open_local?: string | null;
  close_local?: string | null;
  break_start_local?: string | null;
  break_end_local?: string | null;
  early_close?: boolean;
  open_utc?: string | null;
  close_utc?: string | null;
}

export interface TrdhClosure {
  date?: string | null;
  name?: string | null;
  kind?: string | null;
}

export interface TrdhExchange {
  mic: string;
  name?: string | null;
  timezone?: string | null;
  today?: TrdhSession | null;
  is_open_now: boolean;
  next_open_utc?: string | null;
  next_close_utc?: string | null;
  sessions?: TrdhSession[];
  closures?: TrdhClosure[];
}

interface TrdhPayload {
  status?: string;
  reason?: string | null;
  exchanges?: TrdhExchange[];
  meta?: AwarenessMeta;
}

/** Venues awareness calendars today. Stored values are MIC codes. */
const EXCHANGE_OPTIONS = [
  { mic: "XNYS", label: "NYSE" },
  { mic: "XNAS", label: "NASDAQ" },
  { mic: "XLON", label: "LSE" },
  { mic: "XETR", label: "XETRA" },
  { mic: "XPAR", label: "EURONEXT" },
  { mic: "XTKS", label: "TSE" },
  { mic: "XHKG", label: "HKEX" },
  { mic: "XASX", label: "ASX" },
  { mic: "XIST", label: "BIST" },
  { mic: "XSHG", label: "SSE" },
] as const;
const ALL_MICS: string[] = EXCHANGE_OPTIONS.map((o) => o.mic);

const EXCHANGES_STORAGE_KEY = "showme.trdh.exchanges";

function readPersistedSelection(): string[] {
  if (typeof localStorage === "undefined") return [...ALL_MICS];
  const raw = localStorage.getItem(EXCHANGES_STORAGE_KEY);
  if (raw == null) return [...ALL_MICS];
  const picked = raw
    .split(",")
    .map((part) => part.trim().toUpperCase())
    .filter((part) => ALL_MICS.includes(part));
  return picked.length ? picked : [...ALL_MICS];
}

export function TRDHPane({ code }: FunctionPaneProps) {
  const [selected, setSelected] = useState<string[]>(readPersistedSelection);
  const tick = useVisibilityTick(REFRESH_MS);

  const { state, data, error, refetch } = useFunction<TrdhPayload>({
    code,
    params: { exchanges: selected.join(",") },
    enabled: selected.length > 0,
  });

  // Poll-on-tick: countdowns must not freeze while the board sits open.
  // Deps are [tick] ONLY; refetch changes identity each render.
  useEffect(() => {
    if (tick === 0) return;
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tick is the trigger
  }, [tick]);

  function toggleExchange(mic: string) {
    const next = selected.includes(mic)
      ? selected.filter((item) => item !== mic)
      : ALL_MICS.filter((option) => option === mic || selected.includes(option));
    setSelected(next);
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(EXCHANGES_STORAGE_KEY, next.join(","));
    }
  }

  const payload: TrdhPayload = data?.data ?? {};
  const nowMs = Date.now();
  const unavailable = payload.status === "provider_unavailable";
  const rows = useMemo(() => {
    const raw = payload.exchanges ?? [];
    return [...raw].sort((a, b) => {
      const openDelta = (b.is_open_now ? 1 : 0) - (a.is_open_now ? 1 : 0);
      if (openDelta !== 0) return openDelta;
      return secondsUntilChange(a, nowMs) - secondsUntilChange(b, nowMs);
    });
    // nowMs changes each render; sorting on the payload identity is enough.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payload.exchanges]);
  const openNow = rows.filter((r) => r.is_open_now).length;
  const generatedAt = payload.meta?.generated_at ?? null;
  const isLive = state === "ok" && rows.length > 0 && !unavailable;

  const COLS: DataGridColumn<TrdhExchange>[] = useMemo(
    () => [
      {
        key: "exchange",
        header: "Exchange",
        width: 210,
        render: (r) => (
          <span>
            <span style={monoStrongStyle}>{r.mic}</span>
            <span style={venueSubStyle}>
              {r.name ?? ""}
              {r.timezone ? ` · ${r.timezone}` : ""}
            </span>
          </span>
        ),
      },
      {
        key: "session",
        header: "Local session today",
        width: 230,
        render: (r) => <span style={monoMutedStyle}>{fmtSession(r.today)}</span>,
      },
      {
        key: "state",
        header: "State",
        width: 110,
        sortValue: (r) => (r.is_open_now ? 0 : 1),
        render: (r) => (
          <Pill tone={r.is_open_now ? "positive" : "muted"} variant="soft" withDot>
            {r.is_open_now ? "open" : "closed"}
          </Pill>
        ),
      },
      {
        key: "countdown",
        header: "Next change",
        width: 230,
        render: (r) => <span style={monoPrimaryStyle}>{countdownText(r, nowMs)}</span>,
      },
      {
        key: "closures",
        header: "Closures in window",
        width: 200,
        render: (r) => {
          const list = r.closures ?? [];
          if (list.length === 0) return <span style={monoMutedStyle}>none</span>;
          const first = list[0];
          return (
            <span
              style={monoMutedStyle}
              title={list.map((c) => `${c.date ?? ""} ${c.name ?? ""}`).join("\n")}
            >
              {list.length} · {first.date ?? ""} {first.name ?? ""}
            </span>
          );
        },
      },
    ],
    [nowMs],
  );

  const body = !selected.length ? (
    <Empty
      title="Pick at least one exchange"
      body="Select venues from the chip row above to build the trading-hours board."
      icon="◷"
    />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={56} />
      <Skeleton height={20} />
      <Skeleton height={20} width="80%" />
    </div>
  ) : state === "error" ? (
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
  ) : unavailable ? (
    <AwarenessUnavailable
      reason={payload.reason ?? null}
      onRetry={refetch}
      subject="trading calendars"
    />
  ) : rows.length === 0 ? (
    <Empty
      title="No sessions returned"
      body="The calendar returned no rows for the selected exchanges. Nothing is estimated."
      icon="◷"
      action={
        <button type="button" onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="TRDH board summary">
        <StatCard
          label="Open now"
          value={String(openNow)}
          caption={`OF ${rows.length} SELECTED`}
          tone={openNow > 0 ? "positive" : "neutral"}
        />
        <StatCard
          label="Exchanges"
          value={String(rows.length)}
          caption={`${selected.length} ON BOARD`}
          tone="neutral"
        />
        <StatCard
          label="Calendar"
          value="awareness"
          caption="EXCHANGE CALENDARS"
          tone="neutral"
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(r) => r.mic}
        density="compact"
        ariaLabel="Trading hours board"
        defaultSortKey="state"
        defaultSortDir="ascending"
        keyboardNavigable
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Trading Hours"
          subtitle={`${selected.length} venue${selected.length === 1 ? "" : "s"} · MIC calendars from awareness`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : "no data"}
              </Pill>
              <LoadStatePill state={state} status={rows.length ? "ok" : null} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!selected.length}
                title="Refresh board"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <div role="group" aria-label="Exchange selection" style={chipRowStyle}>
            <span style={chipLabelStyle}>EXCHANGES</span>
            {EXCHANGE_OPTIONS.map((option) => {
              const active = selected.includes(option.mic);
              return (
                <button
                  key={option.mic}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleExchange(option.mic)}
                  title={`${active ? "Remove" : "Add"} ${option.label} (${option.mic}) ${active ? "from" : "to"} the board`}
                  style={chipStyle(active)}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
          {body}
        </PaneBody>
        <PaneFooter>
          <StatusSection label="selected" value={selected.join(",") || "—"} />
          <StatusDivider />
          <StatusSection label="open" value={openNow} tone="accent" />
          <StatusDivider />
          <StatusSection label="rows" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="as of"
            value={generatedAt ? `${generatedAt.slice(11, 19)} UTC` : "—"}
          />
          <StatusDivider />
          <StatusSection label="sources" value={data?.sources?.join(", ") || "awareness"} />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function secondsUntilChange(r: TrdhExchange, nowMs: number): number {
  const target = r.is_open_now ? r.next_close_utc : r.next_open_utc;
  if (!target) return Number.MAX_SAFE_INTEGER;
  const t = Date.parse(target);
  return Number.isNaN(t) ? Number.MAX_SAFE_INTEGER : (t - nowMs) / 1000;
}

function countdownText(r: TrdhExchange, nowMs: number): string {
  if (r.is_open_now) {
    if (!r.next_close_utc) return "continuous (24h)";
    return `closes in ${fmtDuration(secondsUntilChange(r, nowMs))} · ${r.next_close_utc.slice(11, 16)} UTC`;
  }
  if (!r.next_open_utc) return formatMissing;
  return `opens in ${fmtDuration(secondsUntilChange(r, nowMs))} · ${r.next_open_utc.slice(11, 16)} UTC`;
}

function fmtSession(s: TrdhSession | null | undefined): string {
  if (!s || !s.open_local || !s.close_local) return "closed today";
  const brk =
    s.break_start_local && s.break_end_local
      ? ` (break ${s.break_start_local}–${s.break_end_local})`
      : "";
  const early = s.early_close ? " · early close" : "";
  return `${s.open_local}–${s.close_local}${brk}${early}`;
}

function fmtDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  const totalMinutes = Math.round(seconds / 60);
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
  gap: 10,
};

const chipRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: 6,
  marginBottom: 10,
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

const venueSubStyle: CSSProperties = {
  display: "block",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
};
