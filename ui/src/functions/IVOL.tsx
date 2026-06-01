/**
 * IVOL — Implied Vol Surface.
 *
 * Bloomberg `OVDV`/`SKEW` analogue: the option chain's implied-vol surface
 * across expiry × moneyness for one underlying. The sidecar emits a labelled
 * *reference* surface (no live options provider wired) with a
 * "live options provider not configured" warning — the pane surfaces that
 * warning + a REFERENCE source pill so the heatmap is never mistaken for a
 * live OPRA/CBOE feed.
 *
 * Payload (data?.data), verified against
 * engine/functions/derivative/_funcs.py::IVOLFunction + _stubs.py templates:
 *   spot            number ($)
 *   as_of           iso8601
 *   surface[]       { expiry, dte?, strike, moneyness?, iv(decimal),
 *                     option_type?, type? }
 *   rows[]          { expiry, dte?, atm_iv?, rr_25d?, bf_25d?, put_skew?, ... }
 *   series[]        { t: expiryLabel, v: atm_iv(decimal) }   (ATM term structure)
 *   cards[]         { label, value, unit? }                  (KPIs)
 *   summary         { atm_iv_front?, atm_iv_back?, skew?, term_slope?,
 *                     x_labels?, y_labels?, contracts?, expiries?, source_mode? }
 *   source_mode, methodology, name, symbol, warnings[]
 * NOTE: surface[].iv and skew-row scalars are DECIMALS (×100 for display).
 *       Moneyness may be absent on raw chain rows → derived from strike/spot.
 *       The pane defensively normalises whichever shape the handler returns.
 */
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
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
  Sparkline,
  StatCard,
  StatusDivider,
  StatusSection,
  Tabs,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

const EXPIRY_STORAGE_KEY = "showme.ivol-expiry";

interface RawSurfaceCell {
  expiry?: string;
  dte?: number;
  moneyness?: number;
  strike?: number;
  iv?: number; // decimal (e.g. 0.32)
  option_type?: string;
  type?: string;
}

interface RawSkewRow {
  expiry?: string;
  dte?: number;
  atm_iv?: number; // decimal
  rr_25d?: number; // decimal
  bf_25d?: number; // decimal
  put_skew?: number; // decimal
}

interface IvolSeriesPoint {
  t?: string;
  v?: number; // decimal
}

interface IvolCard {
  label?: string;
  value?: number | string | null;
  unit?: string;
}

interface IvolSummary {
  atm_iv_front?: number;
  atm_iv_back?: number;
  skew?: number;
  term_slope?: number;
  x_labels?: string[];
  y_labels?: string[];
  contracts?: number;
  expiries?: number;
  source_mode?: string;
}

interface IvolPayload {
  symbol?: string;
  name?: string;
  spot?: number;
  as_of?: string;
  surface?: RawSurfaceCell[];
  rows?: RawSkewRow[];
  series?: IvolSeriesPoint[];
  cards?: IvolCard[];
  summary?: IvolSummary;
  source_mode?: string;
  methodology?: string;
  warnings?: string[];
}

// Normalised grid model assembled from whichever surface shape the backend
// returns. `mny` is a bucketed moneyness ratio (K/S) used as the column key.
interface GridCell {
  iv: number; // decimal
  strike?: number;
  optionType?: string;
}
interface GridRow {
  expiry: string;
  dte?: number;
  cells: Map<string, GridCell>; // mny-bucket → cell
}

const REFRESH_MS = 60_000;

const mnyKey = (m: number): string => m.toFixed(2);
const isAtmBucket = (m: number): boolean => Math.abs(m - 1) < 0.026;

/** decimal → "32.00%" */
const pct = (decimal: number | undefined, digits = 2): string =>
  typeof decimal === "number" && Number.isFinite(decimal)
    ? `${(decimal * 100).toFixed(digits)}%`
    : "—";

/** decimal → "+32.00%" (×100, signed) — matches the heatmap's scaling */
const signedPct = (decimal: number | undefined, digits = 2): string =>
  typeof decimal === "number" && Number.isFinite(decimal)
    ? `${decimal > 0 ? "+" : ""}${(decimal * 100).toFixed(digits)}%`
    : "—";

const numFmt = (v: number | undefined | null, digits = 0): string =>
  typeof v === "number" && Number.isFinite(v)
    ? v.toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })
    : "—";

/** IV (decimal) → heat background. Cool accent for low vol, hot negative for high. */
function heatColor(iv: number, lo: number, hi: number): string {
  const span = hi - lo || 1;
  const t = Math.min(1, Math.max(0, (iv - lo) / span));
  if (t < 0.5) {
    const a = Math.round((0.12 + t * 0.5) * 100);
    return `color-mix(in srgb, var(--accent) ${a}%, transparent)`;
  }
  const a = Math.round((0.18 + (t - 0.5) * 0.9) * 100);
  return `color-mix(in srgb, var(--negative) ${a}%, transparent)`;
}

export function IVOLPane({ code, symbol }: FunctionPaneProps) {
  // Bundle D / PERF-04. Visibility-aware poll.
  const tick = useVisibilityTick(REFRESH_MS);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    symbol,
    params: { underlying: symbol, tick },
  });

  const payload = useMemo<IvolPayload>(
    () =>
      data?.data && typeof data.data === "object" && !Array.isArray(data.data)
        ? (data.data as IvolPayload)
        : {},
    [data?.data],
  );

  const spot = typeof payload.spot === "number" ? payload.spot : undefined;
  const surfaceRaw = useMemo<RawSurfaceCell[]>(
    () => (Array.isArray(payload.surface) ? payload.surface : []),
    [payload.surface],
  );
  const skewRows = useMemo<RawSkewRow[]>(
    () => (Array.isArray(payload.rows) ? payload.rows : []),
    [payload.rows],
  );
  const series = useMemo<IvolSeriesPoint[]>(
    () => (Array.isArray(payload.series) ? payload.series : []),
    [payload.series],
  );
  const cards = Array.isArray(payload.cards) ? payload.cards : [];
  const summary = payload.summary ?? {};

  // ---- Normalise the surface into an expiry×moneyness grid. -------------
  // Some handler paths return rich {moneyness} cells; the offline reference
  // template returns plain {expiry, strike, iv}. Bucket moneyness to a small
  // strike ladder around spot so the heatmap columns line up cleanly.
  const grid = useMemo<GridRow[]>(() => {
    if (!surfaceRaw.length) return [];
    const byExpiry = new Map<string, GridRow>();
    const order: string[] = [];
    for (const c of surfaceRaw) {
      const expiry = String(c.expiry ?? "");
      if (!expiry || typeof c.iv !== "number" || !Number.isFinite(c.iv)) {
        continue;
      }
      let m = typeof c.moneyness === "number" ? c.moneyness : undefined;
      if (m == null && typeof c.strike === "number" && spot && spot > 0) {
        m = c.strike / spot;
      }
      if (m == null || !Number.isFinite(m)) continue;
      // Bucket to 5% moneyness steps so calls+puts at the same strike merge.
      const bucket = Math.round(m / 0.05) * 0.05;
      const key = mnyKey(bucket);
      let row = byExpiry.get(expiry);
      if (!row) {
        row = { expiry, dte: c.dte, cells: new Map() };
        byExpiry.set(expiry, row);
        order.push(expiry);
      }
      // Prefer the cell closest to the bucket center; otherwise average IVs so
      // a call/put pair at one strike reads as one smooth surface point.
      const existing = row.cells.get(key);
      if (existing) {
        existing.iv = (existing.iv + c.iv) / 2;
      } else {
        row.cells.set(key, {
          iv: c.iv,
          strike: c.strike,
          optionType: c.option_type ?? c.type,
        });
      }
    }
    return order.map((e) => byExpiry.get(e)!);
  }, [surfaceRaw, spot]);

  // Ordered moneyness columns present anywhere in the grid.
  const moneyCols = useMemo<number[]>(() => {
    const set = new Set<string>();
    for (const r of grid) for (const k of r.cells.keys()) set.add(k);
    return [...set].map(Number).sort((a, b) => a - b);
  }, [grid]);

  // Expiry tenor labels for tabs / rows. Prefer the grid order; fall back to
  // the skew rows or the ATM term series so the selector still works when the
  // surface array is sparse.
  const expiries = useMemo<string[]>(() => {
    if (grid.length) return grid.map((r) => r.expiry);
    if (skewRows.length) {
      return skewRows.map((r) => String(r.expiry ?? "")).filter(Boolean);
    }
    return series.map((p) => String(p.t ?? "")).filter(Boolean);
  }, [grid, skewRows, series]);

  // Heat scale bounds across all real IV cells.
  const ivBounds = useMemo(() => {
    let lo = Infinity;
    let hi = -Infinity;
    for (const r of grid) {
      for (const c of r.cells.values()) {
        if (c.iv < lo) lo = c.iv;
        if (c.iv > hi) hi = c.iv;
      }
    }
    if (!Number.isFinite(lo)) lo = 0;
    if (!Number.isFinite(hi)) hi = 1;
    return { lo, hi };
  }, [grid]);

  // ATM term-structure series: prefer the backend series, else read the ATM
  // bucket out of each grid row.
  const termSeries = useMemo<number[]>(() => {
    if (series.length) {
      return series.map((p) => (typeof p.v === "number" ? p.v * 100 : 0));
    }
    return grid
      .map((r) => {
        for (const [k, c] of r.cells) {
          if (isAtmBucket(Number(k))) return c.iv * 100;
        }
        return null;
      })
      .filter((v): v is number => v != null);
  }, [series, grid]);

  // Persisted expiry selection, validated against the live expiry set.
  // Read the stored expiry lazily; the placeholder "—" is never honoured so a
  // cold-start render (before data arrives) can't lock the selection to it.
  const [activeExpiry, setActiveExpiry] = useState<string>(() => {
    if (typeof localStorage === "undefined") return "";
    const raw = localStorage.getItem(EXPIRY_STORAGE_KEY);
    return raw && raw !== "—" ? raw : "";
  });

  // Once real expiries exist, snap the selection onto a valid one if the stored
  // key isn't among them (covers first data arrival + symbol/expiry changes).
  useEffect(() => {
    if (expiries.length && !expiries.includes(activeExpiry)) {
      setActiveExpiry(expiries[0]);
    }
  }, [expiries, activeExpiry]);

  // Persist only real expiries — never the "—" placeholder — so a saved
  // selection survives cold starts instead of being clobbered.
  const selectExpiry = useCallback((next: string) => {
    setActiveExpiry(next);
    if (typeof localStorage !== "undefined" && next && next !== "—") {
      localStorage.setItem(EXPIRY_STORAGE_KEY, next);
    }
  }, []);

  const effectiveExpiry = expiries.includes(activeExpiry)
    ? activeExpiry
    : (expiries[0] ?? "");

  const sourceMode =
    payload.source_mode ?? summary.source_mode ?? "reference";
  const isReference = sourceMode !== "live";
  const warningsList = Array.isArray(payload.warnings)
    ? payload.warnings
    : Array.isArray(data?.warnings)
      ? (data?.warnings as string[])
      : [];
  const sources =
    data?.sources?.join(", ") || sourceMode || "showMe option-chain reference";
  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 16), [tick]);

  const cardTone = (
    label: string,
    value: number,
  ): "neutral" | "positive" | "negative" => {
    const l = label.toLowerCase();
    if (l.includes("skew")) return value > 0 ? "negative" : "positive";
    if (l.includes("slope")) return value >= 0 ? "positive" : "negative";
    return "neutral";
  };

  const tableCols = useMemo<DataGridColumn<RawSkewRow>[]>(
    () => [
      {
        key: "expiry",
        header: "Expiry",
        width: 92,
        render: (r) => <span style={expiryCell}>{r.expiry ?? "—"}</span>,
      },
      {
        key: "dte",
        header: "DTE",
        numeric: true,
        width: 70,
        render: (r) => <span style={mutedNum}>{numFmt(r.dte)}</span>,
      },
      {
        key: "atm_iv",
        header: "ATM IV",
        numeric: true,
        width: 94,
        render: (r) => <span style={primaryNum}>{pct(r.atm_iv)}</span>,
      },
      {
        key: "rr_25d",
        header: "25Δ RR",
        numeric: true,
        width: 96,
        render: (r) =>
          typeof r.rr_25d === "number" ? (
            <DeltaChip value={r.rr_25d * 100} format="raw" fractionDigits={2} />
          ) : (
            "—"
          ),
      },
      {
        key: "bf_25d",
        header: "25Δ BF",
        numeric: true,
        width: 92,
        render: (r) => <span style={mutedNum}>{pct(r.bf_25d)}</span>,
      },
      {
        key: "put_skew",
        header: "Put Skew",
        numeric: true,
        width: 96,
        render: (r) => <span style={mutedNum}>{pct(r.put_skew)}</span>,
      },
    ],
    [],
  );

  const hasData =
    grid.length > 0 || skewRows.length > 0 || series.length > 0;

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Implied vol surface"
          subtitle={`${payload.symbol ?? symbol ?? "—"} · spot ${spot != null ? numFmt(spot, 2) : "—"} · ${expiries.length} exp · poll ${REFRESH_MS / 1000}s`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {moneyCols.length}×{expiries.length}
              </Pill>
              <Pill tone="accent" variant="soft" withDot={false}>
                {utcStamp} UTC
              </Pill>
              <Pill tone={isReference ? "warn" : "positive"} variant="soft">
                {isReference ? "reference" : "live"}
              </Pill>
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <Skeleton height={320} />
          ) : state === "error" ? (
            <Empty
              title="Function error"
              body={error?.message ?? "Request failed"}
              icon="!"
            />
          ) : !hasData ? (
            <Empty
              title="No surface data"
              body={`No implied-vol points for ${payload.symbol ?? symbol ?? "this underlying"}.`}
            />
          ) : (
            <div className="u-grid-gap-14">
              {isReference ? (
                <div style={noticeStyle}>
                  <strong className="u-text-warn">
                    Labelled reference surface
                  </strong>
                  <span className="u-text-secondary">
                    {warningsList[0] ??
                      "No live options provider configured. IV is a deterministic per-symbol reference (skew/smile modeled), not a live OPRA/CBOE chain."}
                  </span>
                </div>
              ) : null}

              {/* KPI ribbon — prefer backend cards, fall back to summary. */}
              <section style={kpiGrid} aria-label="IVOL KPI ribbon">
                {cards.length ? (
                  cards.slice(0, 3).map((c, i) => {
                    const v = typeof c.value === "number" ? c.value : NaN;
                    return (
                      <StatCard
                        key={i}
                        label={c.label ?? `Card ${i + 1}`}
                        value={
                          Number.isFinite(v)
                            ? `${v.toFixed(2)}${c.unit ?? "%"}`
                            : String(c.value ?? "—")
                        }
                        caption={`AS OF ${utcStamp} UTC`}
                        tone={cardTone(c.label ?? "", v)}
                        trend={termSeries}
                      />
                    );
                  })
                ) : (
                  <>
                    <StatCard
                      label="ATM IV (front)"
                      value={pct(summary.atm_iv_front)}
                      caption={`AS OF ${utcStamp} UTC`}
                      tone="neutral"
                      trend={termSeries}
                    />
                    <StatCard
                      label="Skew (90-110)"
                      value={pct(summary.skew)}
                      tone={(summary.skew ?? 0) > 0 ? "negative" : "positive"}
                    />
                    <StatCard
                      label="Term slope"
                      value={signedPct(summary.term_slope)}
                      tone={
                        (summary.term_slope ?? 0) >= 0
                          ? "positive"
                          : "negative"
                      }
                    />
                  </>
                )}
              </section>

              {/* ATM term-structure sparkline. */}
              {termSeries.length > 1 ? (
                <section style={termBlock}>
                  <div style={termHead}>
                    <span style={sectionLabel}>ATM term structure</span>
                    <span style={termRange}>
                      {pct(summary.atm_iv_front)} →{" "}
                      {pct(summary.atm_iv_back)}
                    </span>
                  </div>
                  <Sparkline
                    values={termSeries}
                    width={520}
                    height={46}
                    tone="accent"
                    ariaLabel="ATM implied vol term structure"
                  />
                </section>
              ) : null}

              {/* Expiry tab selector (cross-highlights the surface row). */}
              {expiries.length > 0 ? (
                <div style={tabBarStyle}>
                  <Tabs
                    variant="segmented"
                    items={expiries.map((e) => ({ id: e, label: e }))}
                    active={effectiveExpiry}
                    onChange={selectExpiry}
                  />
                </div>
              ) : null}

              {/* Vol surface heatmap: expiry rows × moneyness columns. */}
              {grid.length > 0 && moneyCols.length > 0 ? (
                <section>
                  <div style={sectionLabelRow}>
                    <span style={sectionLabel}>
                      Vol surface · IV by moneyness (K/S)
                    </span>
                    <span className="u-text-mute" style={tinyMeta}>
                      {pct(ivBounds.lo, 1)} – {pct(ivBounds.hi, 1)}
                    </span>
                  </div>
                  <div style={surfaceWrap}>
                    <table style={surfaceTable}>
                      <thead>
                        <tr>
                          <th style={cornerTh}>Exp \ K</th>
                          {moneyCols.map((m) => (
                            <th
                              key={m}
                              style={{
                                ...colTh,
                                ...(isAtmBucket(m) ? colThAtm : null),
                              }}
                            >
                              {`${Math.round(m * 100)}%`}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {grid.map((row) => {
                          const isActive = row.expiry === effectiveExpiry;
                          return (
                            <tr key={row.expiry}>
                              <th
                                style={{
                                  ...rowTh,
                                  ...(isActive ? rowThActive : null),
                                }}
                                onClick={() => selectExpiry(row.expiry)}
                                title={`Select ${row.expiry}`}
                              >
                                {row.expiry}
                              </th>
                              {moneyCols.map((m) => {
                                const cell = row.cells.get(mnyKey(m));
                                const atm = isAtmBucket(m);
                                if (!cell) {
                                  return (
                                    <td key={m} style={emptyCell}>
                                      —
                                    </td>
                                  );
                                }
                                return (
                                  <td
                                    key={m}
                                    style={{
                                      ...heatCellStyle,
                                      background: heatColor(
                                        cell.iv,
                                        ivBounds.lo,
                                        ivBounds.hi,
                                      ),
                                      ...(atm ? heatCellAtm : null),
                                      ...(isActive ? heatCellActiveRow : null),
                                      fontWeight: isActive ? 600 : 400,
                                    }}
                                    title={`${row.expiry} @ ${Math.round(m * 100)}% (${cell.optionType ?? "—"}): ${(cell.iv * 100).toFixed(2)}% IV · K ${numFmt(cell.strike, 2)}`}
                                  >
                                    {(cell.iv * 100).toFixed(1)}
                                  </td>
                                );
                              })}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <div style={legendRow}>
                    <span className="u-text-mute">Low IV</span>
                    <span
                      style={swatch(
                        heatColor(ivBounds.lo, ivBounds.lo, ivBounds.hi),
                      )}
                    />
                    <span
                      style={swatch(
                        heatColor(
                          (ivBounds.lo + ivBounds.hi) / 2,
                          ivBounds.lo,
                          ivBounds.hi,
                        ),
                      )}
                    />
                    <span
                      style={swatch(
                        heatColor(ivBounds.hi, ivBounds.lo, ivBounds.hi),
                      )}
                    />
                    <span className="u-text-mute">High IV</span>
                  </div>
                </section>
              ) : null}

              {/* Per-expiry skew detail (real rows). */}
              {skewRows.length > 0 ? (
                <section>
                  <div style={sectionLabelRow}>
                    <span style={sectionLabel}>Skew detail by expiry</span>
                  </div>
                  <DataGrid
                    columns={tableCols}
                    rows={skewRows}
                    rowKey={(r, i) => `${r.expiry ?? "row"}-${i}`}
                    density="compact"
                    ariaLabel="Implied vol skew detail by expiry"
                  />
                </section>
              ) : null}

              {payload.methodology ? (
                <section style={methodPanel}>
                  <div style={metaLabel}>Methodology</div>
                  <p style={methodText}>{payload.methodology}</p>
                </section>
              ) : null}
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={sources} />
          <StatusDivider />
          <StatusSection label="poll" value={`${REFRESH_MS / 1000}s`} />
          <StatusDivider />
          <StatusSection label="cells" value={surfaceRaw.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection
            label="mode"
            value={sourceMode}
            tone={isReference ? "warn" : "positive"}
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

const tabBarStyle: CSSProperties = {
  padding: "6px 0",
};

const kpiGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
  gap: 10,
};

const noticeStyle: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  background: "var(--warn-soft)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
  fontSize: 12,
};

const sectionLabel: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  color: "var(--text-mute)",
};

const sectionLabelRow: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  justifyContent: "space-between",
  marginBottom: 6,
};

const tinyMeta: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: 10,
};

const termBlock: CSSProperties = {
  display: "grid",
  gap: 4,
};

const termHead: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  justifyContent: "space-between",
};

const termRange: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: 10,
  color: "var(--text-secondary)",
};

const surfaceWrap: CSSProperties = {
  overflowX: "auto",
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-2)",
};

const surfaceTable: CSSProperties = {
  borderCollapse: "separate",
  borderSpacing: 0,
  width: "100%",
  fontSize: 10,
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
};

const cornerTh: CSSProperties = {
  position: "sticky",
  left: 0,
  zIndex: 2,
  background: "var(--surface-2)",
  color: "var(--text-mute)",
  textAlign: "left",
  padding: "4px 8px",
  fontWeight: 600,
  fontSize: 9,
  letterSpacing: "0.04em",
};

const colTh: CSSProperties = {
  padding: "4px 5px",
  color: "var(--text-secondary)",
  fontWeight: 600,
  textAlign: "center",
  fontSize: 9,
  whiteSpace: "nowrap",
};

const colThAtm: CSSProperties = {
  color: "var(--accent)",
};

const rowTh: CSSProperties = {
  position: "sticky",
  left: 0,
  zIndex: 1,
  background: "var(--surface-2)",
  color: "var(--text-secondary)",
  textAlign: "left",
  padding: "3px 8px",
  fontWeight: 600,
  whiteSpace: "nowrap",
  cursor: "pointer",
};

const rowThActive: CSSProperties = {
  color: "var(--accent)",
};

const heatCellStyle: CSSProperties = {
  textAlign: "center",
  padding: "3px 5px",
  color: "var(--text-display)",
  borderTop: "1px solid var(--grid-color)",
  minWidth: 42,
};

const heatCellAtm: CSSProperties = {
  boxShadow: "inset 0 0 0 1px var(--accent)",
};

const heatCellActiveRow: CSSProperties = {
  borderTop: "1px solid var(--accent)",
};

const emptyCell: CSSProperties = {
  textAlign: "center",
  padding: "3px 5px",
  color: "var(--text-mute)",
  borderTop: "1px solid var(--grid-color)",
};

const legendRow: CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "center",
  fontSize: 9,
  marginTop: 6,
};

const swatch = (bg: string): CSSProperties => ({
  width: 24,
  height: 9,
  borderRadius: 2,
  background: bg,
  border: "1px solid var(--grid-color)",
});

const expiryCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-display)",
  fontWeight: 600,
};

const primaryNum: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-display)",
};

const mutedNum: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
};

const methodPanel: CSSProperties = {
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  padding: 12,
  background: "var(--surface-2)",
};

const metaLabel: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  marginBottom: 6,
};

const methodText: CSSProperties = {
  margin: 0,
  color: "var(--text-secondary)",
  lineHeight: 1.5,
  fontSize: 12,
};

export default IVOLPane;
