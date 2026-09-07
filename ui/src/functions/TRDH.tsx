/**
 * TRDH — Trading Hours board.
 *
 * Backend defect note: the DEFAULT board (no `exchanges` param) returns only
 * BINANCE even though the registry holds ~50 venues, so this pane ALWAYS
 * sends an explicit `exchanges` list and offers the user a multi-select chip
 * row (the ten registry venues from the impl's own default list) persisted
 * under `showme.trdh.exchanges`. Body: open-now summary, a per-exchange
 * session table (local hours, timezone, OPEN/CLOSED tone, countdown to the
 * next state change) sorted open-first / soonest-change, and a server
 * now-UTC stamp.
 *
 * Honesty: countdowns come only from the payload's seconds_until_open /
 * seconds_until_close; a 24h venue with no next close renders "continuous".
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
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface TRDHRow {
  exchange?: string;
  name?: string;
  country?: string;
  currency?: string;
  open_local?: string;
  close_local?: string;
  timezone?: string;
  is_open_now?: boolean;
  next_open_utc?: string | null;
  next_close_utc?: string | null;
  seconds_until_open?: number | null;
  seconds_until_close?: number | null;
  hours_until_open?: number | null;
  hours_until_close?: number | null;
  value?: number | null;
}

interface TRDHData {
  rows?: TRDHRow[];
  surface?: Array<Record<string, unknown>>;
  cards?: Array<{ label?: string; value?: unknown }>;
  source_mode?: string;
}

// The ten venues from the backend's own default list (impl constants).
const EXCHANGE_OPTIONS = [
  "NYSE",
  "NASDAQ",
  "LSE",
  "FWB",
  "TYO",
  "HKEX",
  "ASX",
  "BIST",
  "BINANCE",
  "DERIBIT",
] as const;

const EXCHANGES_STORAGE_KEY = "showme.trdh.exchanges";

function readPersistedSelection(): string[] {
  if (typeof localStorage === "undefined") return [...EXCHANGE_OPTIONS];
  const raw = localStorage.getItem(EXCHANGES_STORAGE_KEY);
  if (raw == null) return [...EXCHANGE_OPTIONS];
  const picked = raw
    .split(",")
    .map((part) => part.trim().toUpperCase())
    .filter((part): part is (typeof EXCHANGE_OPTIONS)[number] =>
      (EXCHANGE_OPTIONS as readonly string[]).includes(part),
    );
  return picked.length ? picked : [...EXCHANGE_OPTIONS];
}

export function TRDHPane({ code }: FunctionPaneProps) {
  const [selected, setSelected] = useState<string[]>(readPersistedSelection);

  const { state, data, error, refetch } = useFunction<TRDHData>({
    code,
    // DEFECT WORKAROUND: the backend's default board returns only BINANCE,
    // so the explicit exchanges list is always sent.
    params: { exchanges: selected.join(",") },
    enabled: selected.length > 0,
  });

  function toggleExchange(exchange: string) {
    const next = selected.includes(exchange)
      ? selected.filter((item) => item !== exchange)
      : EXCHANGE_OPTIONS.filter(
          (option) => option === exchange || selected.includes(option),
        );
    setSelected(next);
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(EXCHANGES_STORAGE_KEY, next.join(","));
    }
  }

  const payload = data?.data;
  const rows = useMemo(() => {
    const raw = payload?.rows ?? [];
    return [...raw].sort((a, b) => {
      const openDelta = (b.is_open_now ? 1 : 0) - (a.is_open_now ? 1 : 0);
      if (openDelta !== 0) return openDelta;
      return (a.value ?? Number.MAX_SAFE_INTEGER) - (b.value ?? Number.MAX_SAFE_INTEGER);
    });
  }, [payload]);
  const openNow = rows.filter((r) => r.is_open_now).length;
  const nowUtc = typeof data?.metadata?.now_utc === "string" ? data.metadata.now_utc : null;
  const isLive = state === "ok" && rows.length > 0;

  const COLS: DataGridColumn<TRDHRow>[] = useMemo(
    () => [
      {
        key: "exchange",
        header: "Exchange",
        width: 210,
        render: (r) => (
          <span>
            <span style={monoStrongStyle}>{r.exchange ?? "—"}</span>
            <span style={venueSubStyle}>
              {r.name ?? ""}
              {r.country ? ` · ${r.country}` : ""}
            </span>
          </span>
        ),
      },
      {
        key: "session",
        header: "Local session",
        width: 190,
        render: (r) => (
          <span style={monoMutedStyle}>
            {r.open_local || "—"}–{r.close_local || "—"}{" "}
            {r.timezone ? `(${r.timezone})` : ""}
          </span>
        ),
      },
      {
        key: "state",
        header: "State",
        width: 110,
        render: (r) => (
          <Pill
            tone={r.is_open_now ? "positive" : "muted"}
            variant="soft"
            withDot
          >
            {r.is_open_now ? "open" : "closed"}
          </Pill>
        ),
      },
      {
        key: "countdown",
        header: "Next change",
        width: 230,
        render: (r) => {
          if (r.is_open_now) {
            if (r.seconds_until_close == null) {
              return <span style={monoMutedStyle}>continuous (24h)</span>;
            }
            return (
              <span style={monoPrimaryStyle}>
                closes in {fmtDuration(r.seconds_until_close)}
                {r.next_close_utc
                  ? ` · ${r.next_close_utc.slice(11, 16)} UTC`
                  : ""}
              </span>
            );
          }
          if (r.seconds_until_open == null) {
            return <span style={monoMutedStyle}>—</span>;
          }
          return (
            <span style={monoPrimaryStyle}>
              opens in {fmtDuration(r.seconds_until_open)}
              {r.next_open_utc ? ` · ${r.next_open_utc.slice(11, 16)} UTC` : ""}
            </span>
          );
        },
      },
    ],
    [],
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
      body={error?.message ?? "—"}
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : rows.length === 0 ? (
    <Empty
      title="No sessions returned"
      body="The calendar registry returned no rows for the selected exchanges."
      icon="◷"
      action={
        <button onClick={refetch} className="btn">
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
          value={payload?.source_mode ?? "registry"}
          caption="EXCHANGE CALENDARS"
          tone="neutral"
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(r, i) => `${r.exchange ?? ""}-${i}`}
        density="compact"
        ariaLabel="Trading hours board"
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Trading Hours"
          subtitle={`${selected.length} venue${selected.length === 1 ? "" : "s"} · explicit exchange list (default board defect bypassed)`}
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
          <div
            role="group"
            aria-label="Exchange selection"
            style={chipRowStyle}
          >
            <span style={chipLabelStyle}>EXCHANGES</span>
            {EXCHANGE_OPTIONS.map((option) => {
              const active = selected.includes(option);
              return (
                <button
                  key={option}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleExchange(option)}
                  title={`${active ? "Remove" : "Add"} ${option} ${active ? "from" : "to"} the board`}
                  style={chipStyle(active)}
                >
                  {option}
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
            value={nowUtc ? nowUtc.slice(11, 19) + " UTC" : "—"}
          />
          <StatusDivider />
          <StatusSection label="sources" value={data?.sources?.join(", ") || "—"} />
        </PaneFooter>
      </Pane>
    </div>
  );
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
  fontSize: 10,
  letterSpacing: 1,
  color: "var(--text-mute)",
};

function chipStyle(active: boolean): CSSProperties {
  return {
    fontSize: 11,
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
  fontSize: 10,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
};
