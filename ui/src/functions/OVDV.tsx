/**
 * OVDV — FX Option Volatility Surface.
 *
 * One screen, one job: the surf. The tenor×delta implied-vol matrix is the
 * primary visual and is drawn with the design-system `HeatCell` (no local
 * heat implementation). The ATM term structure reads the backend's REAL
 * `series[].atm_vol_pct`; the 25Δ RR / BF cards read the real card fields.
 *
 *  Header : pair segmented control + CSV + load-state pill + refresh.
 *  KPI    : ATM (1M anchor), 25Δ RR, 25Δ BF, term slope — 4 cards, no
 *           duplicate trend sparks (the term panel is the one term view).
 *  Primary: roving-focus tenor×delta IV grid (arrow keys + Home/End move the
 *           active cell, compact readout line below, accent outline marks
 *           the selection; colour comes from the heat scale only).
 *  Term   : one compact Sparkline panel fed by `series[].atm_vol_pct`.
 *  Notice : ONE panel max — the reference-model context and provider
 *           warnings share it (no stacked amber boxes).
 *  Footer : provenance once (provider · mode · vol src · cells · elapsed).
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import {
  HeatCell,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  PaneState,
  Sparkline,
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
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface SurfaceRow {
  tenor?: string;
  delta?: string;
  vol?: number;
  vol_decimal?: number;
  tenor_years?: number;
  source_mode?: string;
}

interface TermPoint {
  tenor?: string;
  tenor_years?: number;
  /** Backend ATM-term field name (percent). Real realized-vol anchor. */
  atm_vol_pct?: number;
  /** Legacy alias kept for older payloads. */
  vol?: number;
}

interface OVDVCard {
  key?: string;
  label?: string;
  value?: number | string | null;
}

interface OVDVPayload {
  pair?: string;
  as_of?: string;
  status?: string;
  reason?: string;
  surface?: SurfaceRow[];
  rows?: SurfaceRow[];
  series?: TermPoint[];
  cards?: OVDVCard[] | Record<string, unknown>;
  vol_source?: string;
  data_mode?: string;
  source_mode?: string;
  tenors?: string[];
  delta_buckets?: string[];
  methodology?: string;
  warnings?: string[];
  atm_vol_pct?: number;
  risk_reversal_25d_pct?: number;
  butterfly_25d_pct?: number;
}

const PAIRS = [
  { id: "EURUSD", label: "EUR/USD" },
  { id: "USDJPY", label: "USD/JPY" },
  { id: "GBPUSD", label: "GBP/USD" },
  { id: "AUDUSD", label: "AUD/USD" },
  { id: "USDCHF", label: "USD/CHF" },
] as const;
type PairId = (typeof PAIRS)[number]["id"];
const PAIR_IDS = PAIRS.map((p) => p.id);

// Canonical delta order across the smile (puts -> ATM -> calls).
const DELTA_ORDER = ["10P", "25P", "ATM", "25C", "10C"];
const REFRESH_MS = 60_000;

export function OVDVPane({ code }: FunctionPaneProps) {
  const [pair, setPair] = usePersistentOption<PairId>(
    "showme.ovdv-pair",
    PAIR_IDS,
    "EURUSD",
  );
  // Bundle D / PERF-04. Visibility-aware poll. The tick drives a refetch via
  // the effect below and is deliberately NOT part of the fetch params: a
  // changing param key would re-key useFunction and flash the skeleton.
  const tick = useVisibilityTick(REFRESH_MS);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: { pair },
  });
  useEffect(() => {
    if (tick === 0) return;
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tick is the trigger
  }, [tick]);

  const payload = useMemo<OVDVPayload>(
    () =>
      data?.data && typeof data.data === "object" && !Array.isArray(data.data)
        ? (data.data as OVDVPayload)
        : {},
    [data?.data],
  );

  const surface = useMemo<SurfaceRow[]>(() => {
    const raw = Array.isArray(payload.surface)
      ? payload.surface
      : Array.isArray(payload.rows)
        ? payload.rows
        : [];
    return raw.filter((r) => r && typeof r.tenor === "string");
  }, [payload.surface, payload.rows]);

  const series = useMemo<TermPoint[]>(
    () => (Array.isArray(payload.series) ? payload.series : []),
    [payload.series],
  );

  // Distinct tenor rows in chronological order; distinct delta columns.
  const tenors = useMemo<string[]>(() => {
    const seen: string[] = [];
    const fromPayload = Array.isArray(payload.tenors) ? payload.tenors : [];
    for (const t of fromPayload) if (t && !seen.includes(t)) seen.push(t);
    for (const r of surface) {
      if (r.tenor && !seen.includes(r.tenor)) seen.push(r.tenor);
    }
    return seen;
  }, [payload.tenors, surface]);

  const deltas = useMemo<string[]>(() => {
    const present = new Set<string>();
    for (const r of surface) if (r.delta) present.add(r.delta);
    const ordered = DELTA_ORDER.filter((d) => present.has(d));
    // Any non-standard buckets get appended after the canonical ones.
    for (const d of present) if (!ordered.includes(d)) ordered.push(d);
    return ordered.length ? ordered : DELTA_ORDER;
  }, [surface]);

  // Fast lookup: tenor -> delta -> vol(%).
  const cellMap = useMemo(() => {
    const m = new Map<string, Map<string, number>>();
    for (const r of surface) {
      if (!r.tenor || !r.delta || typeof r.vol !== "number") continue;
      if (!m.has(r.tenor)) m.set(r.tenor, new Map());
      m.get(r.tenor)!.set(r.delta, r.vol);
    }
    return m;
  }, [surface]);

  const volStats = useMemo(() => {
    const vals = surface
      .map((r) => r.vol)
      .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
    if (!vals.length) return { min: 0, max: 0 };
    return { min: Math.min(...vals), max: Math.max(...vals) };
  }, [surface]);

  // Cards may arrive as an array [{key,label,value}] or as a dict {key: value}.
  const cardLookup = useMemo<Record<string, number | undefined>>(() => {
    const out: Record<string, number | undefined> = {};
    const c = payload.cards;
    if (Array.isArray(c)) {
      for (const card of c) {
        if (card && typeof card.key === "string") {
          out[card.key] = toNum(card.value);
        }
      }
    } else if (c && typeof c === "object") {
      for (const [k, v] of Object.entries(c)) out[k] = toNum(v);
    }
    return out;
  }, [payload.cards]);

  const cardVal = (key: string, topLevel?: number): number | undefined =>
    cardLookup[key] ?? toNum(topLevel);

  const dataMode = payload.data_mode ?? payload.source_mode ?? "modeled";
  const volSource = payload.vol_source ?? "user_inputs";
  const isLive = volSource === "live_realized_vol";

  // FIX R1-H/R2-#1: the failure disposition comes from the ENVELOPE status
  // (`data.status`, falling back to the payload status) — never from the
  // local fetch state. A provider outage must not render a green "ok" pill
  // or drop the provider reason.
  const callStatus = data?.status ?? payload.status;
  const statusOverride =
    callStatus && callStatus !== "ok" ? callStatus : undefined;
  const providerReason = payload.reason ?? data?.reason ?? null;

  const warningsList = useMemo<string[]>(() => {
    const fromPayload = Array.isArray(payload.warnings) ? payload.warnings : [];
    const fromEnvelope = Array.isArray(data?.warnings) ? data.warnings : [];
    return [...fromPayload, ...fromEnvelope.map((w) => String(w))];
  }, [payload.warnings, data?.warnings]);

  const sources =
    data?.sources?.join(", ") || (isLive ? "yfinance" : "reference_fx_vol_model");

  // ATM term-structure points (chronological) for the term panel.
  // Preferred source: the REAL `series[].atm_vol_pct` (verified live 2026-09-12:
  // {tenor, atm_vol_pct}); the grid's ATM column is only a fallback when the
  // series is absent (same real values, just pivoted).
  const term = useMemo<{ tenor: string; vol: number }[]>(() => {
    const fromSeries = series
      .map((p) => ({
        tenor: p.tenor ?? "—",
        vol: typeof p.vol === "number" ? p.vol : p.atm_vol_pct,
      }))
      .filter(
        (p): p is { tenor: string; vol: number } =>
          typeof p.vol === "number" && Number.isFinite(p.vol),
      );
    if (fromSeries.length) return fromSeries;
    return tenors
      .map((t) => ({ tenor: t, vol: cellMap.get(t)?.get("ATM") }))
      .filter(
        (p): p is { tenor: string; vol: number } =>
          typeof p.vol === "number" && Number.isFinite(p.vol),
      );
  }, [series, tenors, cellMap]);

  const atmVals = term.map((p) => p.vol);
  const frontAtm = atmVals[0];
  const backAtm = atmVals[atmVals.length - 1];
  const termSlope =
    frontAtm != null && backAtm != null ? backAtm - frontAtm : null;
  const slopeTone: "neutral" | "positive" | "negative" =
    termSlope == null ? "neutral" : termSlope >= 0 ? "positive" : "negative";

  const rr = cardVal("risk_reversal_25d_pct", payload.risk_reversal_25d_pct);
  const bf = cardVal("butterfly_25d_pct", payload.butterfly_25d_pct);
  const atmQuote = cardVal("atm_vol_pct", payload.atm_vol_pct) ?? frontAtm;

  /* ── roving-focus surface grid ─────────────────────────────────────── */

  const atmCol = Math.max(0, deltas.indexOf("ATM"));
  const fallbackCell = useMemo(
    () => ({ r: 0, c: atmCol }),
    [atmCol],
  );
  const [activePref, setActivePref] = useState<{ r: number; c: number } | null>(null);
  const activeCell = activePref ?? fallbackCell;
  // Keep the active cell inside the current bounds after a payload swap.
  useEffect(() => {
    setActivePref((a) => {
      if (!a) return a;
      const r = Math.min(a.r, Math.max(0, tenors.length - 1));
      const c = Math.min(a.c, Math.max(0, deltas.length - 1));
      return r === a.r && c === a.c ? a : { r, c };
    });
  }, [tenors.length, deltas.length]);

  const tableRef = useRef<HTMLTableElement>(null);
  // R3-N2: a ragged surface could leave the roving tab stop on an empty cell
  // (empty cells render no HeatCell → zero tab stops). Snap the effective
  // active cell to the first present cell when the preferred one has no value.
  const effectiveActiveCell = useMemo(() => {
    const has = (r: number, c: number) => {
      const t = tenors[r];
      const d = deltas[c];
      return t != null && d != null && Number.isFinite(cellMap.get(t)?.get(d) as number);
    };
    if (has(activeCell.r, activeCell.c)) return activeCell;
    for (let r = 0; r < tenors.length; r += 1) {
      for (let c = 0; c < deltas.length; c += 1) {
        if (has(r, c)) return { r, c };
      }
    }
    return activeCell;
  }, [activeCell, tenors, deltas, cellMap]);
  // FIX R2-#2: the term sparkline must fill its panel. The kit Sparkline
  // takes a pixel width, so we measure the panel (ResizeObserver) instead of
  // hard-coding 280px (~18% of the card on a desktop viewport).
  const [termRef, termWidth] = useMeasuredWidth<HTMLDivElement>(280);
  const moveActiveCell = useCallback(
    (r: number, c: number) => {
      const next = {
        r: Math.max(0, Math.min(tenors.length - 1, r)),
        c: Math.max(0, Math.min(deltas.length - 1, c)),
      };
      setActivePref(next);
      // The kit `HeatCell` button owns the roving tab stop (FIX R1-F2); the
      // wrapper <td> is not focusable anymore.
      const el = tableRef.current?.querySelector<HTMLElement>(
        `[data-cell="${next.r}-${next.c}"] .showme-heat-cell`,
      );
      el?.focus();
    },
    [tenors.length, deltas.length],
  );

  const onCellKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLTableCellElement>, r: number, c: number) => {
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          moveActiveCell(r + 1, c);
          break;
        case "ArrowUp":
          e.preventDefault();
          moveActiveCell(r - 1, c);
          break;
        case "ArrowRight":
          e.preventDefault();
          moveActiveCell(r, c + 1);
          break;
        case "ArrowLeft":
          e.preventDefault();
          moveActiveCell(r, c - 1);
          break;
        case "Home":
          e.preventDefault();
          moveActiveCell(r, 0);
          break;
        case "End":
          e.preventDefault();
          moveActiveCell(r, deltas.length - 1);
          break;
        default:
          break;
      }
    },
    [deltas.length, moveActiveCell],
  );

  const activeVol = cellMap.get(tenors[activeCell.r] ?? "")?.get(
    deltas[activeCell.c] ?? "",
  );
  const readout =
    tenors.length && deltas.length
      ? `${tenors[activeCell.r]} × ${deltas[activeCell.c]} · ${fmtPct(activeVol)}`
      : "—";

  const heatSpan = volStats.max - volStats.min;

  const csvColumns = useMemo<GridCsvColumn<SurfaceRow>[]>(
    () => [
      { key: "tenor", header: "Tenor", value: (r) => r.tenor ?? "" },
      { key: "tenor_years", header: "TenorYears", value: (r) => r.tenor_years ?? "" },
      { key: "delta", header: "Delta", value: (r) => r.delta ?? "" },
      { key: "vol", header: "VolPct", value: (r) => r.vol ?? "" },
    ],
    [],
  );
  const exportCsv = () => {
    const csv = buildGridCsv(csvColumns, surface);
    downloadGridCsv(gridCsvFilename(`ovdv-${payload.pair ?? pair}`), csv);
  };

  const showNotice =
    (state === "ok" || state === "refreshing") &&
    surface.length > 0 &&
    (!isLive || warningsList.length > 0);

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`FX vol surface — ${payload.pair ?? pair}`}
          subtitle={`${payload.pair ?? pair} · poll ${REFRESH_MS / 1000}s`}
          trailing={
            <FunctionControlGroup>
              <SegmentedControl
                label="PAIR"
                value={pair}
                options={PAIRS.map((p) => ({ value: p.id, label: p.label }))}
                onChange={(next) => setPair(next as PairId)}
                title="Currency pair"
              />
              <button
                type="button"
                className="btn btn--ghost"
                onClick={exportCsv}
                disabled={surface.length === 0}
                title="Download CSV"
                aria-label={`Download ${surface.length} surface cells as CSV`}
              >
                CSV
              </button>
              <LoadStatePill
                state={state}
                status={statusOverride ?? payload.data_mode}
              />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <PaneState
            state={state}
            error={error}
            empty={surface.length === 0}
            emptyTitle={
              statusOverride === "provider_unavailable"
                ? "Vol surface provider unavailable"
                : "No vol surface"
            }
            emptyBody={
              providerReason ? (
                <span style={reasonClampStyle} title={providerReason}>
                  {providerReason}
                </span>
              ) : (
                `No OVDV vol surface for ${payload.pair ?? pair}.`
              )
            }
            onRetry={refetch}
            className="u-grid-gap-14"
          >
            {showNotice && (
              <div
                role="status"
                aria-label="Data quality notice"
                data-testid="ovdv-notice"
                style={noticeStyle}
              >
                {!isLive && (
                  <div>
                    <strong className="u-text-warn">Reference vol model</strong>{" "}
                    <span className="u-text-secondary">
                      ATM curve labelled <code>{dataMode}</code> — no live OTC FX
                      vol vendor configured; smile wings modelled from the 25Δ
                      RR/BF inputs. Reference, not vendor-quoted OTC vols.
                    </span>
                  </div>
                )}
                {warningsList.slice(0, 3).map((w, i) => (
                  <div key={i} className="u-text-secondary">
                    {w}
                  </div>
                ))}
              </div>
            )}

            <section style={kpiGrid} aria-label="OVDV KPI ribbon">
              <StatCard
                label="ATM vol (1M)"
                value={fmtPct(atmQuote)}
                caption="realized-vol anchor"
                tone="neutral"
              />
              <StatCard
                label="25Δ risk reversal"
                value={fmtPctSigned(rr)}
                caption="call − put · 25Δ"
                tone={(rr ?? 0) >= 0 ? "positive" : "negative"}
              />
              <StatCard
                label="25Δ butterfly"
                value={fmtPct(bf)}
                caption="wing convexity · 25Δ"
                tone="neutral"
              />
              <StatCard
                label="Term slope"
                value={
                  termSlope == null
                    ? "—"
                    : `${termSlope >= 0 ? "+" : ""}${termSlope.toFixed(2)} pp`
                }
                // R2-#5/F5: the tenor range is stated once, on the term
                // panel head — the KPI caption names the slope basis instead.
                caption="back − front"
                tone={slopeTone}
              />
            </section>

            <section aria-label="FX vol surface grid" style={surfaceSection}>
              <div style={sectionHead}>
                <span style={sectionLabel}>
                  Surface · tenor × delta (implied vol %)
                </span>
                <span style={sectionLabel}>
                  {fmtPct(volStats.min)} – {fmtPct(volStats.max)}
                </span>
              </div>
              <table
                ref={tableRef}
                role="grid"
                aria-label="OVDV vol surface grid"
                aria-rowcount={tenors.length + 1}
                aria-colcount={deltas.length + 1}
                style={tableStyle}
              >
                <thead>
                  <tr>
                    <th scope="col" style={cornerHeadStyle} aria-label="Tenor" />
                    {deltas.map((delta, c) => (
                      <th
                        key={delta}
                        scope="col"
                        aria-colindex={c + 2}
                        style={colHeadStyle}
                      >
                        {delta}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {tenors.map((tenor, r) => (
                    <tr key={tenor}>
                      <th scope="row" style={rowHeadStyle}>
                        {tenor}
                      </th>
                      {deltas.map((delta, c) => {
                        const vol = cellMap.get(tenor)?.get(delta);
                        const isActive =
                          effectiveActiveCell.r === r && effectiveActiveCell.c === c;
                        return (
                          <td
                            key={delta}
                            data-cell={`${r}-${c}`}
                            aria-colindex={c + 2}
                            onFocus={() => setActivePref({ r, c })}
                            onKeyDown={(e) => onCellKeyDown(e, r, c)}
                            style={{
                              ...cellStyle,
                              outline: isActive
                                ? "1px solid var(--accent)"
                                : "none",
                              outlineOffset: -1,
                            }}
                          >
                            {vol == null || !Number.isFinite(vol) ? (
                              <span style={emptyCellStyle}>—</span>
                            ) : (
                              <HeatCell
                                value={heatValue(vol, volStats.min, heatSpan)}
                                range={1}
                                size={32}
                                label={vol.toFixed(2)}
                                tabIndex={isActive ? 0 : -1}
                                ariaLabel={`${tenor} × ${delta} implied vol ${vol.toFixed(2)} percent`}
                                onClick={() => setActivePref({ r, c })}
                              />
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={readoutRow}>
                <span
                  data-testid="ovdv-readout"
                  aria-live="polite"
                  style={readoutStyle}
                >
                  {readout}
                </span>
              </div>
            </section>

            <section aria-label="ATM term structure" style={termSection}>
              <div style={sectionHead}>
                <span style={sectionLabel}>
                  ATM term structure · realized vol
                </span>
                <span style={sectionLabel}>
                  {term.length ? `${term[0].tenor} → ${term[term.length - 1].tenor}` : "—"}
                </span>
              </div>
              {term.length > 0 ? (
                <div
                  ref={termRef}
                  style={measureWrap}
                  data-testid="ovdv-term-measure"
                >
                  <Sparkline
                    values={atmVals}
                    width={termWidth}
                    height={48}
                    tone={slopeTone}
                    ariaLabel={`ATM vol by tenor: ${term
                      .map((p) => `${p.tenor} ${p.vol.toFixed(2)}`)
                      .join(", ")}`}
                  />
                </div>
              ) : (
                <span style={emptyCellStyle}>—</span>
              )}
            </section>
          </PaneState>
        </PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={sources} />
          <StatusDivider />
          <StatusSection
            label="mode"
            // FIX R1-H/R2-#1: on a failure envelope the footer mode reads the
            // call status (provider_unavailable) instead of claiming a mode
            // the data never reached.
            value={statusOverride ?? dataMode}
            tone={isLive && !statusOverride ? "positive" : "warn"}
          />
          <StatusDivider />
          <StatusSection label="vol src" value={volSource} />
          <StatusDivider />
          <StatusSection label="cells" value={surface.length} />
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

function toNum(v: unknown): number | undefined {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string") {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return undefined;
}

/**
 * FIX R2-#4: map the real IV into the kit's [0,1] intensity scale with a
 * visible floor. The old `vol - min` mapped the cheapest cell to exactly 0,
 * which `intensityToken` paints `transparent` — one present cell lost its
 * heat encoding. Floor at 0.2 keeps every present cell in `--heat-pos-1..5`.
 */
function heatValue(vol: number, min: number, span: number): number {
  if (!(span > 1e-9)) return 0.8;
  return 0.2 + 0.8 * ((vol - min) / span);
}

/**
 * Measure a container's rendered width so a pixel-width kit chart fills it
 * (FIX R2-#2). Falls back to the previous fixed width when layout is
 * unavailable (jsdom / hidden pane) and re-measures on resize; no deps.
 */
function useMeasuredWidth<T extends HTMLElement>(
  fallback: number,
): [(node: T | null) => void, number] {
  const [width, setWidth] = useState(fallback);
  const roRef = useRef<ResizeObserver | null>(null);
  // Callback ref: the measured node is conditionally rendered (only when the
  // series exists), so a mount-time effect would measure nothing and never
  // retry. Attach the observer the moment the node attaches.
  const setRef = useCallback((node: T | null) => {
    roRef.current?.disconnect();
    roRef.current = null;
    if (!node) return;
    const measure = () => {
      const next = Math.round(node.getBoundingClientRect().width);
      if (next > 0) setWidth(next);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(node);
    roRef.current = ro;
  }, []);
  // No teardown effect: under StrictMode's double-mount React does not
  // re-invoke callback refs, so an effect cleanup would disconnect the
  // observer permanently (R3-N1). `setRef(null)` disconnects on unmount.
  return [setRef, width];
}

function fmtPct(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v.toFixed(2)}%`;
}

function fmtPctSigned(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(3)}%`;
}

/* ── styles (design tokens only) ───────────────────────────────────── */

const kpiGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const surfaceSection: CSSProperties = {
  minWidth: 0,
  display: "grid",
  gap: 6,
};

const termSection: CSSProperties = {
  minWidth: 0,
  display: "grid",
  gap: 6,
};

const sectionHead: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const sectionLabel: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-2xs)",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const tableStyle: CSSProperties = {
  borderCollapse: "collapse",
  width: "max-content",
  fontFamily: "var(--font-mono)",
};

const colHeadStyle: CSSProperties = {
  padding: "4px 8px",
  fontSize: "var(--font-size-xs)",
  letterSpacing: "var(--tracking-label)",
  color: "var(--text-mute)",
  fontWeight: 400,
  textAlign: "center",
  borderBottom: "1px solid var(--border-strong)",
};

const cornerHeadStyle: CSSProperties = {
  ...colHeadStyle,
  textAlign: "left",
  paddingLeft: 0,
};

const rowHeadStyle: CSSProperties = {
  padding: "2px 10px 2px 0",
  fontSize: "var(--font-size-sm)",
  color: "var(--text-display)",
  fontWeight: 600,
  textAlign: "left",
  whiteSpace: "nowrap",
};

const cellStyle: CSSProperties = {
  padding: 1,
  lineHeight: 0,
};

const emptyCellStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-xs)",
};

const readoutRow: CSSProperties = {
  display: "flex",
  alignItems: "center",
  minHeight: 16,
};

const readoutStyle: CSSProperties = {
  color: "var(--text-secondary)",
  fontFamily: "var(--font-mono)",
  fontVariantNumeric: "tabular-nums",
  fontSize: "var(--font-size-2xs)",
  letterSpacing: "0.04em",
};

const noticeStyle: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  background: "var(--warn-soft)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
  fontSize: "var(--font-size-sm)",
};

/** Two-line clamp for long provider diagnostics — full text via `title`. */
const reasonClampStyle: CSSProperties = {
  display: "-webkit-box",
  WebkitLineClamp: 2,
  WebkitBoxOrient: "vertical",
  overflow: "hidden",
  wordBreak: "break-word",
};

const measureWrap: CSSProperties = {
  width: "100%",
  minWidth: 0,
};
