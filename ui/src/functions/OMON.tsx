/**
 * OMON — Option Monitor (single-name listed option chain).
 *
 * One screen, one job: the chain IS the product.
 *
 *  Header   : symbol · expiry · poll — expiry/side segmented controls, CSV,
 *             load-state pill, refresh. Exactly one status indicator.
 *  KPI      : spot, ATM IV, call/put open-interest share (4 cards max).
 *  Primary  : the option chain DataGrid — sortable, keyboard navigable
 *             (roving cells + Ctrl/Cmd+C copy) and CSV-exportable.
 *  Secondary: one compact IV-smile panel fed by the backend's real
 *             `series[]` (call_iv/put_iv per strike). `cards[]` duplicates
 *             `summary` and is deliberately not rendered.
 *  Footer   : provenance once (provider · mode · status · rows · elapsed).
 *
 * Data honesty: provider_unavailable payloads render the PaneState empty
 * branch carrying the backend reason + Retry; backend warnings surface as
 * ONE inline notice (never a second pill/banner duplicate).
 */
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
  FlashValue,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  PaneState,
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
import { SymbolBar } from "@/shell/SymbolBar";
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
  // null/undefined/"" must stay missing — Number("") === 0 would turn an
  // empty wire cell into a confident 0.00 (FIX R1-F8).
  if (v == null || v === "") return null;
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

interface OmonSeriesPoint {
  strike?: number;
  call_iv?: number | null;
  put_iv?: number | null;
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
  series?: OmonSeriesPoint[];
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

  const status = payload?.status;
  const isLive = state === "ok" && status === "ok";
  const metaMode = data?.metadata?.data_mode;
  const dataMode =
    (typeof metaMode === "string" && metaMode) || (isLive ? "live chain" : status || state);
  const shown = view.rows.length;
  const total = allRows.length;
  // FIX R2-#6: `provider_unavailable` was stated three times (header pill +
  // footer MODE + footer STATUS). The footer `status` slot is now the single
  // copy; the header pill and the footer `mode` duplicate are suppressed in
  // that state (the PaneState hero carries the reason + Retry).
  const providerDown = status === "provider_unavailable";
  const statusText = status ?? state;

  // IV-smile series (real backend field). Keep strikes that carry at least
  // one finite side so the panel never renders a dead axis.
  const smile = useMemo(() => {
    const points = (payload?.series ?? [])
      .filter((p) => p && typeof p.strike === "number" && Number.isFinite(p.strike))
      .map((p) => ({
        strike: p.strike as number,
        call: numOrNull(p.call_iv),
        put: numOrNull(p.put_iv),
      }))
      .sort((a, b) => a.strike - b.strike);
    const usable = points.length > 1 && points.some((p) => p.call != null || p.put != null);
    return { points, usable };
  }, [payload?.series]);

  const sideValue = (r: OmonRow, key: string): number | null => {
    return numOrNull(
      (r as unknown as Record<string, unknown>)[`${side}_${key}`],
    );
  };
  const cellText = useCallback(
    (r: OmonRow, key: string): string => {
      switch (key) {
        case "strike":
          return fmtNum(r.strike);
        case "bid":
          return fmtNum(sideValue(r, "bid"));
        case "ask":
          return fmtNum(sideValue(r, "ask"));
        case "oi":
          return fmtInt(sideValue(r, "oi"));
        case "volume":
          return fmtInt(sideValue(r, "volume"));
        case "iv":
          return fmtIv(sideValue(r, "iv"));
        case "delta":
          return fmtNum(sideValue(r, "delta"), 3);
        default:
          return "";
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sideValue closes over `side`
    [side],
  );

  // Sortable + copyable chain columns. `sortValue` drives the built-in
  // sorter; `getCellText` makes Ctrl/Cmd+C copy the side-aware value (the
  // grid's raw-row fallback would copy undefined for side columns).
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
        sortValue: (r) => sideValue(r, "bid"),
        render: (r) => fmtNum(sideValue(r, "bid")),
      },
      {
        key: "ask",
        header: "Ask",
        numeric: true,
        sortable: true,
        width: 80,
        sortValue: (r) => sideValue(r, "ask"),
        render: (r) => fmtNum(sideValue(r, "ask")),
      },
      {
        key: "oi",
        header: "OI",
        numeric: true,
        sortable: true,
        width: 90,
        sortValue: (r) => sideValue(r, "oi"),
        render: (r) => fmtInt(sideValue(r, "oi")),
      },
      {
        key: "volume",
        header: "Vol",
        numeric: true,
        sortable: true,
        width: 80,
        sortValue: (r) => sideValue(r, "volume"),
        render: (r) => fmtInt(sideValue(r, "volume")),
      },
      {
        key: "iv",
        header: "IV",
        numeric: true,
        sortable: true,
        width: 78,
        sortValue: (r) => sideValue(r, "iv"),
        render: (r) => fmtIv(sideValue(r, "iv")),
      },
      {
        key: "delta",
        header: "Delta",
        numeric: true,
        sortable: true,
        width: 84,
        sortValue: (r) => sideValue(r, "delta"),
        render: (r) => fmtNum(sideValue(r, "delta"), 3),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sideValue closes over `side`
    [side, view.atmStrike],
  );

  const csvColumns = useMemo<GridCsvColumn<OmonRow>[]>(
    () => [
      { key: "strike", header: "Strike", value: (r) => r.strike ?? "" },
      { key: "bid", header: "Bid", value: (r) => sideValue(r, "bid") },
      { key: "ask", header: "Ask", value: (r) => sideValue(r, "ask") },
      { key: "oi", header: "OI", value: (r) => sideValue(r, "oi") },
      { key: "volume", header: "Volume", value: (r) => sideValue(r, "volume") },
      { key: "iv", header: "IV", value: (r) => sideValue(r, "iv") },
      { key: "delta", header: "Delta", value: (r) => sideValue(r, "delta") },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sideValue closes over `side`
    [side],
  );

  const exportCsv = () => {
    const csv = buildGridCsv(csvColumns, view.rows);
    downloadGridCsv(
      gridCsvFilename(`omon-${effectiveSymbol || "chain"}-${payload?.expiry ?? "expiry"}`),
      csv,
    );
  };

  const callOi = numOrNull(payload?.summary?.total_call_oi);
  const putOi = numOrNull(payload?.summary?.total_put_oi);
  const oiTotal = (callOi ?? 0) + (putOi ?? 0);
  const oiCaption = (v: number | null, sideName: Side): string =>
    v != null && oiTotal > 0
      ? `${((v / oiTotal) * 100).toFixed(1)}% of chain OI`
      : `${sideName} open interest`;

  const isEmpty = total === 0;
  const showPill = !(providerDown && isEmpty);
  const showFooterMode = dataMode !== statusText;
  const emptyTitle = !effectiveSymbol
    ? "Pick a symbol"
    : status === "provider_unavailable"
      ? "Option chain unavailable"
      : "No option strikes returned";
  const emptyReason = payload?.reason ?? warnings[0] ?? null;
  const emptyBody = !effectiveSymbol
    ? "OMON needs an equity / ETF underlier."
    : emptyReason
      ? (
          <span style={reasonClampStyle} title={emptyReason}>
            {emptyReason}
          </span>
        )
      : "Provider returned no strikes for this underlier / expiry.";

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Option Monitor — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · expiry ${payload?.expiry ?? "—"} · poll ${REFRESH_MS / 1000}s`}
          trailing={
            <FunctionControlGroup>
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
                disabled={isEmpty}
                title="Option side"
              />
              <button
                type="button"
                className="btn btn--ghost"
                onClick={exportCsv}
                disabled={view.rows.length === 0}
                title="Download CSV"
                aria-label={`Download ${view.rows.length} strikes as CSV`}
              >
                CSV
              </button>
              {showPill && <LoadStatePill state={state} status={status} />}
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh option chain"
              />
            </FunctionControlGroup>
          }
        />
        <SymbolBar code={code} symbol={effectiveSymbol} />
        <PaneBody>
          <PaneState
            state={state}
            error={error}
            empty={isEmpty}
            emptyTitle={emptyTitle}
            emptyBody={emptyBody}
            emptyIcon={status === "provider_unavailable" ? "!" : "∅"}
            onRetry={refetch}
            retryLabel="Retry"
            className="u-grid-gap-14"
          >
            {warnings.length > 0 && (
              <div role="status" aria-label="Data quality notice" style={noticeStyle}>
                {warnings.join(" · ")}
              </div>
            )}
            <section style={kpiGridStyle} aria-label="OMON KPI ribbon">
              <StatCard
                label="Spot"
                value={
                  <FlashValue value={numOrNull(payload?.summary?.spot ?? spot)}>
                    {fmtNum(payload?.summary?.spot ?? spot)}
                  </FlashValue>
                }
                caption={`expiry ${payload?.expiry ?? "—"}`}
                tone="neutral"
              />
              <StatCard
                label="ATM IV"
                value={fmtIv(payload?.summary?.atm_iv)}
                caption={view.atmStrike != null ? `atm strike ${fmtNum(view.atmStrike)}` : "—"}
                tone="neutral"
              />
              <StatCard
                label="Call OI"
                value={fmtCompact(callOi)}
                caption={oiCaption(callOi, "call")}
                tone="positive"
              />
              <StatCard
                label="Put OI"
                value={fmtCompact(putOi)}
                caption={oiCaption(putOi, "put")}
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
                getCellText={(r, col) => cellText(r, col.key)}
              />
              <div style={noteStyle} aria-label="Chain coverage note">
                Showing {shown} of {total} strikes
                {view.capped ? ` (±${MAX_STRIKES_PER_SIDE} around spot)` : ""} ·{" "}
                {side === "call" ? "calls" : "puts"} view
              </div>
            </div>
            {smile.usable && (
              <section
                aria-label="IV smile by strike"
                data-testid="omon-iv-smile"
                style={smileWrapStyle}
              >
                <div style={sectionHeadStyle}>
                  <span style={sectionLabelStyle}>IV smile · call vs put</span>
                  <span style={sectionLabelStyle}>
                    strikes {fmtNum(smile.points[0].strike)}–
                    {fmtNum(smile.points[smile.points.length - 1].strike)}
                  </span>
                </div>
                <IvSmileChart points={smile.points} />
                <div style={legendStyle} aria-hidden>
                  <span style={legendItemStyle}>
                    <span style={{ ...legendSwatchStyle, background: "var(--positive)" }} />
                    Call IV
                  </span>
                  <span style={legendItemStyle}>
                    <span style={{ ...legendSwatchStyle, background: "var(--negative)" }} />
                    Put IV
                  </span>
                </div>
              </section>
            )}
          </PaneState>
        </PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={data?.sources?.join(", ") || "yfinance"} />
          {showFooterMode && (
            <>
              <StatusDivider />
              <StatusSection label="mode" value={dataMode} tone={isLive ? "positive" : "warn"} />
            </>
          )}
          <StatusDivider />
          <StatusSection label="status" value={statusText} />
          <StatusDivider />
          <StatusSection label="rows" value={total} />
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

/* ── IV smile chart (real series[] only — no synthetic fallback) ─────── */

interface SmilePoint {
  strike: number;
  call: number | null;
  put: number | null;
}

function IvSmileChart({ points }: { points: SmilePoint[] }) {
  const geo = useMemo(() => {
    const finite = points
      .flatMap((p) => [p.call, p.put])
      .filter((v): v is number => v != null && Number.isFinite(v));
    if (finite.length < 2) return null;
    const W = 560;
    const H = 116;
    const ML = 44;
    const MR = 10;
    const MT = 8;
    const MB = 18;
    const minX = points[0].strike;
    const maxX = points[points.length - 1].strike;
    const padX = (maxX - minX) * 0.02 || 1;
    const minY = Math.min(...finite);
    const maxY = Math.max(...finite);
    const padY = (maxY - minY) * 0.12 || Math.max(0.01, maxY * 0.1);
    const y0 = Math.max(0, minY - padY);
    const y1 = maxY + padY;
    const sx = (x: number) =>
      ML + ((x - (minX - padX)) / (maxX + padX - (minX - padX))) * (W - ML - MR);
    const sy = (v: number) => MT + (1 - (v - y0) / (y1 - y0)) * (H - MT - MB);
    const segment = (key: "call" | "put"): string[] => {
      const segs: string[] = [];
      let current: string[] = [];
      for (const p of points) {
        const v = p[key];
        if (v == null || !Number.isFinite(v)) {
          if (current.length > 1) segs.push(current.join(" "));
          current = [];
          continue;
        }
        current.push(
          `${current.length ? "L" : "M"}${sx(p.strike).toFixed(1)},${sy(v).toFixed(1)}`,
        );
      }
      if (current.length > 1) segs.push(current.join(" "));
      return segs;
    };
    return {
      W,
      H,
      ML,
      MB,
      y0,
      y1,
      minX,
      maxX,
      call: segment("call"),
      put: segment("put"),
    };
  }, [points]);

  if (!geo) return null;
  return (
    <svg
      width={geo.W}
      height={geo.H}
      viewBox={`0 0 ${geo.W} ${geo.H}`}
      role="img"
      aria-label="Implied volatility smile by strike, call and put"
      className="u-block"
    >
      <text x={geo.ML - 6} y={12} textAnchor="end" fontSize={9} fill="var(--text-mute)">
        {fmtIv(geo.y1)}
      </text>
      <text
        x={geo.ML - 6}
        y={geo.H - geo.MB}
        textAnchor="end"
        fontSize={9}
        fill="var(--text-mute)"
      >
        {fmtIv(geo.y0)}
      </text>
      <text x={geo.ML} y={geo.H - 4} fontSize={9} fill="var(--text-mute)">
        {fmtNum(geo.minX)}
      </text>
      <text
        x={geo.W - 10}
        y={geo.H - 4}
        textAnchor="end"
        fontSize={9}
        fill="var(--text-mute)"
      >
        {fmtNum(geo.maxX)}
      </text>
      {geo.call.map((d, i) => (
        <path
          key={`call-${i}`}
          d={d}
          fill="none"
          stroke="var(--positive)"
          strokeWidth={1.5}
          data-series="call"
        />
      ))}
      {geo.put.map((d, i) => (
        <path
          key={`put-${i}`}
          d={d}
          fill="none"
          stroke="var(--negative)"
          strokeWidth={1.5}
          data-series="put"
        />
      ))}
    </svg>
  );
}

/* ── styles (design tokens only) ───────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
  gap: 10,
};

const tableWrapStyle: CSSProperties = { minWidth: 0 };

const noteStyle: CSSProperties = {
  marginTop: 6,
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
};

const noticeStyle: CSSProperties = {
  padding: "6px 10px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  background: "var(--warn-soft)",
  color: "var(--text-primary)",
  fontSize: "var(--font-size-sm)",
};

/** Two-line clamp for the long provider diagnostic — full text via `title`. */
const reasonClampStyle: CSSProperties = {
  display: "-webkit-box",
  WebkitLineClamp: 2,
  WebkitBoxOrient: "vertical",
  overflow: "hidden",
  wordBreak: "break-word",
};

const smileWrapStyle: CSSProperties = {
  minWidth: 0,
  display: "grid",
  gap: 4,
};

const sectionHeadStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const sectionLabelStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-2xs)",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const legendStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
};

const legendItemStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
};

const legendSwatchStyle: CSSProperties = {
  width: 10,
  height: 2,
  borderRadius: 1,
  flex: "0 0 auto",
};

function monoStyle(strong: boolean): CSSProperties {
  return {
    color: strong ? "var(--accent)" : "var(--text-primary)",
    fontWeight: strong ? 700 : 500,
  };
}

/* ── formatting helpers ────────────────────────────────────────────── */

function fmtNum(v: unknown, digits = 2): string {
  if (v == null || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return formatNumber(n, digits);
}

function fmtInt(v: unknown): string {
  if (v == null || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return Math.round(n).toLocaleString("en-US");
}

function fmtCompact(v: unknown): string {
  if (v == null || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  const a = Math.abs(n);
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return Math.round(n).toLocaleString("en-US");
}

function fmtIv(v: unknown): string {
  if (v == null || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  // yfinance IV is a decimal fraction (0.31 → 31.2%).
  return `${(n * 100).toFixed(1)}%`;
}
