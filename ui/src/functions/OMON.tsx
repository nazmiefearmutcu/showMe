/**
 * OMON — Option Monitor (single-name listed option chain).
 *
 * Header: expiry segmented control (first 4 listed expiries, persisted) +
 * CALLS/PUTS side toggle + status pill + refresh. Body: KPI ribbon (spot,
 * ATM IV, call/put OI) + a compact chain table — strike, bid/ask, OI, volume,
 * IV and Black-Scholes delta for the selected side. Rows are tinted with the
 * side's soft token (calls positive / puts negative) and the ATM strike is
 * highlighted. Only ±10 strikes around spot are rendered, with an honest
 * "showing N of M" note.
 *
 * Data honesty: provider_unavailable / empty payloads render an explicit
 * empty state, and backend warnings surface as a degraded pill + footer row.
 */
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  FlashValue,
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
import {
  buildGridCsv,
  downloadGridCsv,
  gridCsvFilename,
  type GridCsvColumn,
} from "@/design-system/grid-csv";
import { formatNumber } from "@/lib/format";
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { defaultSymbolForFunction } from "@/lib/symbols";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

const EXPIRY_KEY = "showme.omon.expiry";
const MAX_STRIKES_PER_SIDE = 10; // ±10 strikes around spot
const MAX_EXPIRY_SEGMENTS = 4;

/** Live adoption: visibility-paused 30s poll (campaign 2026-09-11). */
const REFRESH_MS = 30_000;

function numOrNull(v: unknown): number | null {
  if (v == null) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

interface OmonRow {
  strike?: number;
  moneyness?: number | null;
  call_bid?: number | null;
  call_ask?: number | null;
  call_oi?: number | null;
  call_volume?: number | null;
  call_iv?: number | null;
  call_delta?: number | null;
  put_bid?: number | null;
  put_ask?: number | null;
  put_oi?: number | null;
  put_volume?: number | null;
  put_iv?: number | null;
  put_delta?: number | null;
}

interface OmonSummary {
  underlier?: string;
  expiry?: string;
  spot?: number | null;
  atm_iv?: number | null;
  total_call_oi?: number | null;
  total_put_oi?: number | null;
  strike_count?: number;
}

interface OmonData {
  status?: string;
  reason?: string;
  underlier?: string;
  expiry?: string;
  expiries?: string[];
  spot?: number | null;
  rows?: OmonRow[];
  summary?: OmonSummary;
  methodology?: string;
}

type Side = "call" | "put";

const SIDE_OPTIONS = [
  { value: "call" as const, label: "CALLS" },
  { value: "put" as const, label: "PUTS" },
];

/**
 * Persisted expiry preference. `usePersistentOption` validates the stored
 * value against the options captured at mount, but the expiry list only
 * exists after the first successful load — so this thin wrapper keeps the
 * same localStorage key contract while re-validating against the *loaded*
 * expiries on every render.
 */
function useExpiryPreference() {
  const [pref, setPref] = useState<string>(() => {
    try {
      return localStorage.getItem(EXPIRY_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const setPrefPersist = useCallback((value: string) => {
    setPref(value);
    try {
      localStorage.setItem(EXPIRY_KEY, value);
    } catch {
      /* storage unavailable — session-only preference */
    }
  }, []);
  return [pref, setPrefPersist] as const;
}

export function OMONPane({ code, symbol }: FunctionPaneProps) {
  const effectiveSymbol =
    symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF", "DERIVATIVE"]);

  const [side, setSide] = useState<Side>("call");
  const [expiryPref, setExpiryPref] = useExpiryPreference();

  // Single query. The expiry param is sent only when the user has picked one
  // (the backend itself falls back to the nearest listed expiry for unknown
  // values); with no preference the backend default (nearest) is used and the
  // payload reports which expiry actually served the rows.
  const { state, data, error, refetch } = useFunction<OmonData>({
    code,
    symbol: effectiveSymbol,
    params: expiryPref ? { expiry: expiryPref } : {},
    enabled: !!effectiveSymbol,
  });

  // Live adoption (campaign 2026-09-11): visibility-paused 30s refetch for
  // the spot quote; the tick must stay out of `params` (UA-HIGH-16) or every
  // poll would change the fetch key and re-flash the skeleton.
  const tick = useVisibilityTick(REFRESH_MS);
  useEffect(() => {
    if (tick === 0) return; // initial mount is useFunction's own load
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tick is the trigger
  }, [tick]);

  const payload = data?.data;
  const warnings: string[] = data?.warnings ?? [];
  const allRows: OmonRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const spot = typeof payload?.spot === "number" ? payload.spot : null;
  const expirySlice = useMemo(
    () => (payload?.expiries ?? []).slice(0, MAX_EXPIRY_SEGMENTS),
    [payload?.expiries],
  );
  // Control value: the persisted pick when it is listed, else the expiry the
  // backend actually served.
  const selectedExpiry =
    expiryPref && expirySlice.includes(expiryPref)
      ? expiryPref
      : payload?.expiry ?? "";

  // ATM index + ±N strike window around spot.
  const view = useMemo(() => {
    if (!allRows.length) {
      return { rows: [] as OmonRow[], atmStrike: null as number | null, capped: false };
    }
    let atmIdx = 0;
    if (spot != null) {
      let best = Math.abs((allRows[0].strike ?? 0) - spot);
      for (let i = 1; i < allRows.length; i++) {
        const d = Math.abs((allRows[i].strike ?? 0) - spot);
        if (d < best) {
          best = d;
          atmIdx = i;
        }
      }
    }
    const lo = Math.max(0, atmIdx - MAX_STRIKES_PER_SIDE);
    const hi = Math.min(allRows.length, atmIdx + MAX_STRIKES_PER_SIDE + 1);
    return {
      rows: allRows.slice(lo, hi),
      atmStrike: allRows[atmIdx]?.strike ?? null,
      capped: allRows.length > hi - lo,
    };
  }, [allRows, spot]);

  const isLive = state === "ok" && payload?.status === "ok";
  const shown = view.rows.length;
  const total = allRows.length;

  // Audit A4 OMON M: the primary chain surface now uses the shared DataGrid —
  // sortable headers (built-in tri-state sorter), keyboard cell navigation +
  // clipboard copy, and a CSV export of the visible window.
  const cols = useMemo<DataGridColumn<OmonRow>[]>(
    () => [
      {
        key: "strike",
        header: "Strike",
        numeric: true,
        sortable: true,
        width: 90,
        sortValue: (r) => r.strike ?? null,
        render: (r) => {
          const isAtm = r.strike != null && r.strike === view.atmStrike;
          return (
            <span
              style={monoStyle(isAtm)}
              data-testid={isAtm ? "omon-atm-strike" : undefined}
              data-atm={isAtm ? "true" : undefined}
            >
              {fmtNum(r.strike)}
            </span>
          );
        },
      },
      {
        key: "bid",
        header: "Bid",
        numeric: true,
        sortable: true,
        width: 80,
        sortValue: (r) => numOrNull(side === "call" ? r.call_bid : r.put_bid),
        render: (r) => fmtNum(side === "call" ? r.call_bid : r.put_bid),
      },
      {
        key: "ask",
        header: "Ask",
        numeric: true,
        sortable: true,
        width: 80,
        sortValue: (r) => numOrNull(side === "call" ? r.call_ask : r.put_ask),
        render: (r) => fmtNum(side === "call" ? r.call_ask : r.put_ask),
      },
      {
        key: "oi",
        header: "OI",
        numeric: true,
        sortable: true,
        width: 90,
        sortValue: (r) => numOrNull(side === "call" ? r.call_oi : r.put_oi),
        render: (r) => fmtInt(side === "call" ? r.call_oi : r.put_oi),
      },
      {
        key: "volume",
        header: "Vol",
        numeric: true,
        sortable: true,
        width: 80,
        sortValue: (r) => numOrNull(side === "call" ? r.call_volume : r.put_volume),
        render: (r) => fmtInt(side === "call" ? r.call_volume : r.put_volume),
      },
      {
        key: "iv",
        header: "IV",
        numeric: true,
        sortable: true,
        width: 78,
        sortValue: (r) => numOrNull(side === "call" ? r.call_iv : r.put_iv),
        render: (r) => fmtIv(side === "call" ? r.call_iv : r.put_iv),
      },
      {
        key: "delta",
        header: "Delta",
        numeric: true,
        sortable: true,
        width: 84,
        sortValue: (r) => numOrNull(side === "call" ? r.call_delta : r.put_delta),
        render: (r) => fmtNum(side === "call" ? r.call_delta : r.put_delta, 3),
      },
    ],
    [side, view.atmStrike],
  );

  const csvColumns = useMemo<GridCsvColumn<OmonRow>[]>(
    () => [
      { key: "strike", header: "Strike", value: (r) => r.strike ?? "" },
      { key: "bid", header: "Bid", value: (r) => (side === "call" ? r.call_bid : r.put_bid) },
      { key: "ask", header: "Ask", value: (r) => (side === "call" ? r.call_ask : r.put_ask) },
      { key: "oi", header: "OI", value: (r) => (side === "call" ? r.call_oi : r.put_oi) },
      {
        key: "volume",
        header: "Volume",
        value: (r) => (side === "call" ? r.call_volume : r.put_volume),
      },
      { key: "iv", header: "IV", value: (r) => (side === "call" ? r.call_iv : r.put_iv) },
      { key: "delta", header: "Delta", value: (r) => (side === "call" ? r.call_delta : r.put_delta) },
    ],
    [side],
  );

  const exportCsv = () => {
    const csv = buildGridCsv(csvColumns, view.rows);
    downloadGridCsv(
      gridCsvFilename(`omon-${effectiveSymbol || "chain"}-${payload?.expiry ?? "expiry"}`),
      csv,
    );
  };

  const warningBanner =
    warnings.length > 0 ? (
      <div role="status" style={warningStyle} aria-label="Data quality warning">
        {warnings.join(" · ")}
      </div>
    ) : null;

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="OMON needs an equity / ETF underlier." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
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
  ) : total === 0 ? (
    <div className="u-grid-gap-14">
      {warningBanner}
      <Empty
        title={
          payload?.status === "provider_unavailable"
            ? "Option chain unavailable"
            : "No option strikes returned"
        }
        body={
          payload?.reason ??
          "Provider returned no strikes for this underlier / expiry."
        }
        icon="∅"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    </div>
  ) : (
    <div className="u-grid-gap-14">
      {warningBanner}
      <section style={kpiGridStyle} aria-label="OMON KPI ribbon">
        <StatCard
          label="Spot"
          value={
            <FlashValue value={numOrNull(payload?.summary?.spot ?? spot)}>
              {fmtNum(payload?.summary?.spot ?? spot)}
            </FlashValue>
          }
          caption={`EXPIRY ${payload?.expiry ?? "—"}`}
          tone="neutral"
        />
        <StatCard
          label="ATM IV"
          value={fmtIv(payload?.summary?.atm_iv)}
          caption={view.atmStrike != null ? `ATM ${fmtNum(view.atmStrike)}` : "—"}
          tone="neutral"
        />
        <StatCard
          label="Call OI"
          value={fmtCompact(payload?.summary?.total_call_oi)}
          caption="TOTAL CHAIN"
          tone="positive"
        />
        <StatCard
          label="Put OI"
          value={fmtCompact(payload?.summary?.total_put_oi)}
          caption="TOTAL CHAIN"
          tone="negative"
        />
      </section>
      <div style={tableWrapStyle}>
        <DataGrid
          columns={cols}
          rows={view.rows}
          rowKey={(r, i) => `${r.strike ?? "strike"}-${i}`}
          density="compact"
          ariaLabel={`OMON ${side === "call" ? "call" : "put"} chain`}
          defaultSortKey="strike"
          defaultSortDir="ascending"
          keyboardNavigable
        />
        <div style={chainFooterStyle}>
          <div style={noteStyle} aria-label="Chain coverage note">
            Showing {shown} of {total} strikes
            {view.capped ? ` (±${MAX_STRIKES_PER_SIDE} around spot)` : ""} ·{" "}
            {side === "call" ? "calls" : "puts"} view
          </div>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={exportCsv}
            disabled={view.rows.length === 0}
            title="Download the visible strike window as CSV"
            aria-label={`Download ${view.rows.length} strikes as CSV`}
          >
            CSV
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Option Monitor — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${payload?.expiry ?? "—"} · spot ${fmtNum(payload?.summary?.spot ?? spot)}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {shown}/{total} st
              </Pill>
              {warnings.length > 0 && (
                <Pill tone="warn" variant="soft">
                  degraded
                </Pill>
              )}
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live chain" : payload?.status || state}
              </Pill>
              {expirySlice.length > 0 && (
                <SegmentedControl
                  label="EXPIRY"
                  value={selectedExpiry}
                  options={expirySlice}
                  onChange={setExpiryPref}
                  title="Expiry"
                />
              )}
              <SegmentedControl
                label="SIDE"
                value={side}
                options={SIDE_OPTIONS}
                onChange={setSide}
                title="Option side"
              />
              <LoadStatePill state={state} status={payload?.status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh option chain"
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
          <StatusSection label="status" value={payload?.status ?? state} />
          <StatusDivider />
          <StatusSection
            label="expiry"
            value={payload?.expiry ?? "—"}
            tone="accent"
          />
          <StatusDivider />
          <StatusSection label="shown" value={`${shown} of ${total}`} />
          {warnings.length > 0 && (
            <>
              <StatusDivider />
              <StatusSection label="warnings" value={warnings.length} tone="warn" />
            </>
          )}
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── styles (design tokens only) ───────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 10,
};

const tableWrapStyle: CSSProperties = { minWidth: 0 };

const chainFooterStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const noteStyle: CSSProperties = {
  marginTop: 6,
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
};

const warningStyle: CSSProperties = {
  padding: "6px 10px",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--border-subtle)",
  background: "var(--scrim-low)",
  color: "var(--text-primary)",
  fontSize: "var(--font-size-sm)",
};

function monoStyle(strong: boolean): CSSProperties {
  return {
    color: strong ? "var(--accent)" : "var(--text-primary)",
    fontWeight: strong ? 700 : 500,
  };
}

/* ── formatting helpers ────────────────────────────────────────────── */

function fmtNum(v: unknown, digits = 2): string {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return formatNumber(n, digits);
}

function fmtInt(v: unknown): string {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return Math.round(n).toLocaleString("en-US");
}

function fmtCompact(v: unknown): string {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  const a = Math.abs(n);
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return Math.round(n).toLocaleString("en-US");
}

function fmtIv(v: unknown): string {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  // yfinance IV is a decimal fraction (0.31 → 31.2%).
  return `${(n * 100).toFixed(1)}%`;
}
