/**
 * IVOL — Implied Vol Surface (Options-family redesign, lane L2 · 2026-09-12).
 *
 * Wire contract (probed live — raw: options-redesign/raw/ivol-payload.json):
 *   surface[] / rows[] cells → { expiry, strike, moneyness, option_type,
 *                                vol (decimal), vol_pct (percent),
 *                                bid, ask, mid, last, volume, open_interest }
 *     ⚠ the cells carry `vol` / `vol_pct` — NEVER `iv`. The pre-redesign pane
 *       keyed on `iv`, so the heatmap was empty (`0×30` pill), the smile strip
 *       never mounted and the "Skew detail" table rendered 30 rows of em-dashes.
 *   calls_grid[] / puts_grid[] → { expiry, strike, iv (decimal), volume }
 *     (reference-template mirror of the same surface; used only when the
 *      surface/rows arrays come back empty).
 *   series[]  → { t: expiry, v: atm_iv (decimal) }   (ATM term structure)
 *   summary   → { contracts, expiries, calls, puts, source_mode,
 *                 atm_iv_front, atm_iv_back, skew, term_slope }
 *   envelope  → status ("ok" | "reference" | "provider_unavailable"),
 *               data_state (spot source), reason, sources, elapsed_ms
 *
 * P0 resolution (commission MASTER-VERDICT.md:212):
 *   - heatmap + smile read the REAL `vol` field;
 *   - the smile table derives call/put IV by strike from the real rows;
 *   - the dead "Skew detail" table (atm_iv/rr_25d/bf_25d — never emitted) is gone;
 *   - expiries are deduped (was 30 duplicate tabs → duplicate React keys);
 *   - exactly ONE mode pill + ONE reference notice; no mode echo in the footer;
 *   - KPI ≤ 4; one DataGrid (sortable + keyboard + CSV); one footer provenance row.
 *
 * Honesty: the mode pill is driven by `source_mode` (only `live_*` is live) and
 * the reference notice spells out the spot anchor from `data_state` plus the
 * provider reason — a modeled surface can never read as a live OPRA/CBOE chain.
 * Missing cells render the em-dash sentinel, never a fabricated value.
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
  DataGrid,
  type DataGridColumn,
  DeltaChip,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  PaneState,
  Pill,
  StatCard,
  StatusDivider,
  StatusSection,
  Tabs,
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
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

const EXPIRY_STORAGE_KEY = "showme.ivol-expiry";
const REFRESH_MS = 60_000;
const MONEYNESS_BUCKET = 0.05;
const ATM_TOLERANCE = 0.026;

/* ── wire types ─────────────────────────────────────────────────────── */

interface RawCell {
  expiry?: string;
  strike?: number;
  moneyness?: number;
  option_type?: string;
  type?: string;
  /** decimal IV — the REAL surface field */
  vol?: number;
  /** percent IV — the REAL surface field */
  vol_pct?: number;
  /** decimal IV — calls_grid / puts_grid only */
  iv?: number;
}

interface SeriesPoint {
  t?: string;
  v?: number;
}

interface IvolSummary {
  contracts?: number;
  expiries?: number;
  calls?: number;
  puts?: number;
  source_mode?: string;
  atm_iv_front?: number | null;
  atm_iv_back?: number | null;
  skew?: number | null;
  term_slope?: number | null;
}

interface IvolPayload {
  symbol?: string;
  spot?: number;
  status?: string;
  reason?: string;
  data_state?: string;
  source_mode?: string;
  surface?: RawCell[];
  rows?: RawCell[];
  calls_grid?: RawCell[];
  puts_grid?: RawCell[];
  series?: SeriesPoint[];
  summary?: IvolSummary;
  methodology?: string;
  warnings?: string[];
}

/* ── normalization ──────────────────────────────────────────────────── */

type OptionSide = "CALL" | "PUT";

interface VolCell {
  expiry: string;
  strike?: number;
  moneyness?: number;
  side?: OptionSide;
  vol: number; // decimal
}

function sideOf(raw: string | undefined): OptionSide | undefined {
  const s = (raw ?? "").toUpperCase();
  if (s === "CALL" || s === "C") return "CALL";
  if (s === "PUT" || s === "P") return "PUT";
  return undefined;
}

/** surface / rows cells: the real field is `vol` (fallback `vol_pct`). Never `iv`. */
function surfaceVol(c: RawCell): number | undefined {
  if (typeof c.vol === "number" && Number.isFinite(c.vol)) return c.vol;
  if (typeof c.vol_pct === "number" && Number.isFinite(c.vol_pct)) {
    return c.vol_pct / 100;
  }
  return undefined;
}

/** calls_grid / puts_grid cells: the real field there is `iv`. */
function gridVol(c: RawCell): number | undefined {
  if (typeof c.iv === "number" && Number.isFinite(c.iv)) return c.iv;
  return surfaceVol(c);
}

function collectCells(
  list: RawCell[] | undefined,
  forcedSide: OptionSide | undefined,
  read: (c: RawCell) => number | undefined,
  spot: number | undefined,
): VolCell[] {
  const out: VolCell[] = [];
  for (const c of list ?? []) {
    const expiry = String(c.expiry ?? "").trim();
    if (!expiry) continue;
    const vol = read(c);
    if (vol == null || vol < 0) continue;
    let moneyness =
      typeof c.moneyness === "number" && Number.isFinite(c.moneyness)
        ? c.moneyness
        : undefined;
    if (moneyness == null && typeof c.strike === "number" && spot != null && spot > 0) {
      moneyness = c.strike / spot;
    }
    out.push({
      expiry,
      strike:
        typeof c.strike === "number" && Number.isFinite(c.strike)
          ? c.strike
          : undefined,
      moneyness,
      side: forcedSide ?? sideOf(c.option_type ?? c.type),
      vol,
    });
  }
  return out;
}

/**
 * Normalise the surface from the real wire fields. Preference order:
 * `surface` → `rows` (identical array on both backend paths) → the template's
 * `calls_grid`/`puts_grid` mirrors (which carry `iv`).
 */
function normalizeSurface(payload: IvolPayload, spot: number | undefined): VolCell[] {
  const surface = Array.isArray(payload.surface) ? payload.surface : [];
  const rows = Array.isArray(payload.rows) ? payload.rows : [];
  const primary = collectCells(
    surface.length ? surface : rows,
    undefined,
    surfaceVol,
    spot,
  );
  if (primary.length) return primary;
  return [
    ...collectCells(payload.calls_grid, "CALL", gridVol, spot),
    ...collectCells(payload.puts_grid, "PUT", gridVol, spot),
  ];
}

/* ── presentation helpers ───────────────────────────────────────────── */

/** decimal → "32.00%" */
const pct = (decimal: number | null | undefined, digits = 2): string =>
  typeof decimal === "number" && Number.isFinite(decimal)
    ? `${(decimal * 100).toFixed(digits)}%`
    : "—";

/** decimal → "+32.00%" (signed) */
const signedPct = (decimal: number | null | undefined, digits = 2): string =>
  typeof decimal === "number" && Number.isFinite(decimal)
    ? `${decimal > 0 ? "+" : ""}${(decimal * 100).toFixed(digits)}%`
    : "—";

const numFmt = (v: number | undefined | null, digits = 0): string =>
  typeof v === "number" && Number.isFinite(v)
    ? v.toLocaleString("en-US", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })
    : "—";

const bucketOf = (moneyness: number): string =>
  (Math.round(moneyness / MONEYNESS_BUCKET) * MONEYNESS_BUCKET).toFixed(2);

const isAtmBucket = (key: string): boolean =>
  Math.abs(Number(key) - 1) < ATM_TOLERANCE;

function mean(xs: number[]): number {
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

/** Sequential heat scale on the positive token ladder (IV has no sign). */
function heatBackground(vol: number, lo: number, hi: number): string {
  const span = hi - lo;
  if (!(span > 0)) return "var(--heat-pos-3)";
  const t = (vol - lo) / span;
  const step = Math.min(5, Math.max(1, Math.ceil(t * 5)));
  return `var(--heat-pos-${step})`;
}

/* ── grid models ────────────────────────────────────────────────────── */

interface HeatAgg {
  call: number[];
  put: number[];
  other: number[];
}

interface HeatRow {
  expiry: string;
  cells: Map<string, HeatAgg>;
}

interface SmileRow {
  strike: number;
  call?: number;
  put?: number;
  spread?: number;
}

export function IVOLPane({ code, symbol }: FunctionPaneProps) {
  // Visibility-aware 60s poll (refetch trigger only — never a fetch param).
  const tick = useVisibilityTick(REFRESH_MS);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    symbol,
    params: { underlying: symbol },
  });

  useEffect(() => {
    if (tick === 0) return;
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tick is the trigger
  }, [tick]);

  const payload = useMemo<IvolPayload>(
    () =>
      data?.data && typeof data.data === "object" && !Array.isArray(data.data)
        ? (data.data as IvolPayload)
        : {},
    [data?.data],
  );

  const spot = typeof payload.spot === "number" ? payload.spot : undefined;
  const summary = payload.summary ?? {};
  const series = useMemo<SeriesPoint[]>(
    () => (Array.isArray(payload.series) ? payload.series : []),
    [payload.series],
  );

  // The REAL surface cells: `vol` on surface/rows, `iv` only for the grid mirrors.
  const surfaceCells = useMemo<VolCell[]>(
    () => normalizeSurface(payload, spot),
    [payload, spot],
  );

  // Unique expiries in wire order — dedupe is structural (Map keys), which
  // kills the old duplicate-tab React keys (30 duplicate "30d" entries).
  const expiries = useMemo<string[]>(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const c of surfaceCells) {
      if (!seen.has(c.expiry)) {
        seen.add(c.expiry);
        out.push(c.expiry);
      }
    }
    return out;
  }, [surfaceCells]);

  // Expiry × moneyness heat model (call+put at one bucket merge into the
  // cell average; the per-side split lives in the smile table below).
  const heat = useMemo(() => {
    const byExpiry = new Map<string, Map<string, HeatAgg>>();
    const order: string[] = [];
    for (const c of surfaceCells) {
      if (c.moneyness == null || !Number.isFinite(c.moneyness)) continue;
      const key = bucketOf(c.moneyness);
      let row = byExpiry.get(c.expiry);
      if (!row) {
        row = new Map();
        byExpiry.set(c.expiry, row);
        order.push(c.expiry);
      }
      const agg = row.get(key) ?? { call: [], put: [], other: [] };
      (c.side === "CALL" ? agg.call : c.side === "PUT" ? agg.put : agg.other).push(c.vol);
      row.set(key, agg);
    }
    const rows: HeatRow[] = order.map((expiry) => ({
      expiry,
      cells: byExpiry.get(expiry)!,
    }));
    const bucketSet = new Set<string>();
    for (const r of rows) for (const k of r.cells.keys()) bucketSet.add(k);
    const buckets = [...bucketSet].sort((a, b) => Number(a) - Number(b));
    let lo = Infinity;
    let hi = -Infinity;
    for (const r of rows) {
      for (const agg of r.cells.values()) {
        const v = mean([...agg.call, ...agg.put, ...agg.other]);
        lo = Math.min(lo, v);
        hi = Math.max(hi, v);
      }
    }
    if (!Number.isFinite(lo)) {
      lo = 0;
      hi = 1;
    }
    return { rows, buckets, lo, hi };
  }, [surfaceCells]);

  // Persisted expiry selection, validated against the loaded set.
  const [activeExpiry, setActiveExpiry] = useState<string>(() => {
    if (typeof localStorage === "undefined") return "";
    const raw = localStorage.getItem(EXPIRY_STORAGE_KEY);
    return raw && raw !== "—" ? raw : "";
  });
  useEffect(() => {
    if (expiries.length && !expiries.includes(activeExpiry)) {
      setActiveExpiry(expiries[0]);
    }
  }, [expiries, activeExpiry]);

  const selectExpiry = useCallback((next: string) => {
    setActiveExpiry(next);
    if (typeof localStorage !== "undefined" && next && next !== "—") {
      localStorage.setItem(EXPIRY_STORAGE_KEY, next);
    }
  }, []);

  const effectiveExpiry = expiries.includes(activeExpiry)
    ? activeExpiry
    : (expiries[0] ?? "");

  // Smile: real CALL/PUT IV by strike for the active expiry.
  const smileRows = useMemo<SmileRow[]>(() => {
    if (!effectiveExpiry) return [];
    const byStrike = new Map<number, SmileRow>();
    for (const c of surfaceCells) {
      if (c.expiry !== effectiveExpiry) continue;
      if (typeof c.strike !== "number" || !Number.isFinite(c.strike)) continue;
      if (!c.side) continue; // cannot attribute a side → not a smile point
      const row = byStrike.get(c.strike) ?? { strike: c.strike };
      if (c.side === "CALL") {
        if (row.call == null) row.call = c.vol;
      } else if (row.put == null) {
        row.put = c.vol;
      }
      byStrike.set(c.strike, row);
    }
    return [...byStrike.values()]
      .sort((a, b) => a.strike - b.strike)
      .map((r) => ({
        ...r,
        spread: r.call != null && r.put != null ? r.put - r.call : undefined,
      }));
  }, [surfaceCells, effectiveExpiry]);

  const frontLabel = String(series[0]?.t ?? expiries[0] ?? "front");
  const backLabel = String(
    series[series.length - 1]?.t ?? expiries[expiries.length - 1] ?? "back",
  );

  // ---- honesty layer -----------------------------------------------------
  const sourceMode = payload.source_mode ?? summary.source_mode ?? "reference";
  const isLive = sourceMode.startsWith("live_");
  const isSynthetic = sourceMode.startsWith("synthetic");
  const modeLabel = isLive ? "live" : isSynthetic ? "synthetic" : "reference";
  const spotState = payload.data_state;
  const anchorLabel =
    spotState === "live_quote"
      ? "the live spot"
      : spotState === "synthetic_anchor"
        ? "a synthetic spot anchor"
        : spotState === "user_override"
          ? "the user spot override"
          : "the resolved spot";
  const envelopeStatus = data?.status ?? payload.status;
  const providerReason = payload.reason ?? data?.reason;
  const sources =
    data?.sources?.join(", ") || sourceMode || "showMe option-chain reference";

  // ---- table columns -----------------------------------------------------
  const smileCols = useMemo<DataGridColumn<SmileRow>[]>(
    () => [
      {
        key: "strike",
        header: "Strike",
        numeric: true,
        width: 90,
        sortable: true,
        sortValue: (r) => r.strike,
        render: (r) => <span style={primaryNum}>{numFmt(r.strike, 2)}</span>,
      },
      {
        key: "call",
        header: "Call IV",
        numeric: true,
        width: 90,
        sortable: true,
        sortValue: (r) => r.call ?? null,
        render: (r) => <span style={mutedNum}>{pct(r.call)}</span>,
      },
      {
        key: "put",
        header: "Put IV",
        numeric: true,
        width: 90,
        sortable: true,
        sortValue: (r) => r.put ?? null,
        render: (r) => <span style={mutedNum}>{pct(r.put)}</span>,
      },
      {
        key: "spread",
        header: "Put − Call",
        numeric: true,
        width: 110,
        sortable: true,
        sortValue: (r) => r.spread ?? null,
        render: (r) =>
          r.spread != null ? (
            <DeltaChip value={r.spread * 100} format="raw" fractionDigits={2} />
          ) : (
            "—"
          ),
      },
    ],
    [],
  );

  const csvCols = useMemo<GridCsvColumn<SmileRow>[]>(
    () => [
      { key: "strike", header: "Strike", value: (r) => r.strike },
      { key: "call", header: "Call IV", value: (r) => r.call ?? "" },
      { key: "put", header: "Put IV", value: (r) => r.put ?? "" },
      { key: "spread", header: "Put-Call", value: (r) => r.spread ?? "" },
    ],
    [],
  );

  const exportCsv = useCallback(() => {
    const csv = buildGridCsv(csvCols, smileRows);
    downloadGridCsv(
      gridCsvFilename(
        `ivol-smile-${payload.symbol ?? symbol ?? "surface"}-${effectiveExpiry || "all"}`,
      ),
      csv,
    );
  }, [csvCols, smileRows, payload.symbol, symbol, effectiveExpiry]);

  const hasSurface = surfaceCells.length > 0;

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Implied vol surface — ${payload.symbol ?? symbol ?? "—"}`}
          subtitle={`${payload.symbol ?? symbol ?? "—"} · spot ${spot != null ? numFmt(spot, 2) : "—"} · ${expiries.length} exp · poll ${REFRESH_MS / 1000}s`}
          trailing={
            <FunctionControlGroup>
              <Pill
                tone={isLive ? "positive" : "warn"}
                variant="soft"
                aria-label={`surface mode ${modeLabel}`}
              >
                {modeLabel}
              </Pill>
              <LoadStatePill state={state} status={envelopeStatus} />
              <button
                type="button"
                className="btn"
                onClick={exportCsv}
                disabled={smileRows.length === 0}
                title="Download smile CSV"
                aria-label={`Download ${smileRows.length} smile rows as CSV`}
              >
                CSV
              </button>
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <PaneState
            state={state}
            error={error}
            empty={!hasSurface}
            emptyTitle="No implied-vol surface"
            emptyBody={
              providerReason ??
              `No implied-vol points for ${payload.symbol ?? symbol ?? "this underlying"}.`
            }
            onRetry={refetch}
            loadingRows={3}
          >
            <div className="u-grid-gap-14">
              {/* Single honesty notice — mode is stated once in the pill above. */}
              {!isLive ? (
                <div
                  data-testid="ivol-reference-notice"
                  role="status"
                  style={noticeStyle}
                >
                  <strong className="u-text-warn">
                    {isSynthetic ? "Synthetic surface" : "Reference surface"}
                  </strong>
                  <span className="u-text-secondary">
                    {`Deterministic skew template anchored on ${anchorLabel} — not a live OPRA/CBOE chain.`}
                    {providerReason ? ` Provider: ${providerReason}.` : ""}
                  </span>
                </div>
              ) : null}

              {/* KPI ribbon — 4 real summary numbers, one caption each. */}
              <section style={kpiGridStyle} aria-label="IVOL KPI ribbon">
                <StatCard
                  label="ATM IV (front)"
                  value={pct(summary.atm_iv_front)}
                  caption={`${frontLabel} expiry`}
                />
                <StatCard
                  label="ATM IV (back)"
                  value={pct(summary.atm_iv_back)}
                  caption={`${backLabel} expiry`}
                />
                <StatCard
                  label="Skew (90-110)"
                  value={pct(summary.skew)}
                  caption={`${frontLabel} expiry · K/S wings`}
                />
                <StatCard
                  label="Term slope"
                  value={signedPct(summary.term_slope)}
                  caption="back − front"
                />
              </section>

              {/* Primary visual: real-vol surface heatmap. */}
              {heat.rows.length > 0 && heat.buckets.length > 0 ? (
                <section aria-label="IV surface">
                  <div style={sectionHeadStyle}>
                    <span style={sectionLabel}>
                      {/* FIX R2-#10/R1-F13: name the metric so the merged
                          call+put average cannot be read as the KPI's
                          single-side front ATM (33.5 vs 32.00). */}
                      IV surface · K/S buckets · cell = call+put avg (%)
                    </span>
                    <span className="u-text-mute" style={tinyMeta}>
                      {pct(heat.lo, 1)} – {pct(heat.hi, 1)}
                    </span>
                  </div>
                  <SurfaceHeatmap
                    rows={heat.rows}
                    buckets={heat.buckets}
                    lo={heat.lo}
                    hi={heat.hi}
                    activeExpiry={effectiveExpiry}
                    onSelect={selectExpiry}
                  />
                </section>
              ) : null}

              {/* Secondary table: real per-side smile for the active expiry. */}
              {smileRows.length > 0 ? (
                <section aria-label="IV smile — call vs put by strike">
                  <div style={sectionHeadStyle}>
                    <span style={sectionLabel}>
                      Smile · call vs put by strike
                    </span>
                    {expiries.length > 1 ? (
                      <Tabs
                        variant="segmented"
                        ariaLabel="Surface expiry"
                        items={expiries.map((e) => ({ id: e, label: e }))}
                        active={effectiveExpiry}
                        onChange={selectExpiry}
                      />
                    ) : null}
                  </div>
                  <DataGrid
                    columns={smileCols}
                    rows={smileRows}
                    rowKey={(r) => String(r.strike)}
                    density="compact"
                    ariaLabel={`IV smile — ${effectiveExpiry} call vs put by strike`}
                    defaultSortKey="strike"
                    defaultSortDir="ascending"
                    keyboardNavigable
                  />
                  <div className="u-text-mute" style={noteTextStyle}>
                    {`${smileRows.length} strike${smileRows.length === 1 ? "" : "s"} · ${effectiveExpiry || "—"}`}
                  </div>
                </section>
              ) : null}
            </div>
          </PaneState>
        </PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={sources} />
          <StatusDivider />
          <StatusSection
            label="status"
            value={envelopeStatus ?? "—"}
            tone={isLive ? "positive" : "warn"}
          />
          <StatusDivider />
          <StatusSection label="cells" value={surfaceCells.length} />
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

/* ── surface heatmap (primary visual, roving-tabindex keyboard grid) ── */

function SurfaceHeatmap({
  rows,
  buckets,
  lo,
  hi,
  activeExpiry,
  onSelect,
}: {
  rows: HeatRow[];
  buckets: string[];
  lo: number;
  hi: number;
  activeExpiry: string;
  onSelect: (expiry: string) => void;
}) {
  const [focusPos, setFocusPos] = useState({ r: 0, c: 0 });
  const tableRef = useRef<HTMLTableElement | null>(null);

  const focusAt = useCallback(
    (r: number, c: number) => {
      const rr = Math.min(Math.max(r, 0), Math.max(0, rows.length - 1));
      const cc = Math.min(Math.max(c, 0), Math.max(0, buckets.length - 1));
      setFocusPos({ r: rr, c: cc });
      tableRef.current
        ?.querySelector<HTMLButtonElement>(
          `button[data-cell="1"][data-r="${rr}"][data-c="${cc}"]`,
        )
        ?.focus();
    },
    [rows.length, buckets.length],
  );

  const onKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLTableElement>) => {
      const target = event.target as HTMLElement;
      const cell = target.closest?.('button[data-cell="1"]') as HTMLElement | null;
      if (!cell) return;
      const r = Number(cell.dataset.r);
      const c = Number(cell.dataset.c);
      let next: { r: number; c: number } | null = null;
      switch (event.key) {
        case "ArrowRight":
          next = { r, c: c + 1 };
          break;
        case "ArrowLeft":
          next = { r, c: c - 1 };
          break;
        case "ArrowDown":
          next = { r: r + 1, c };
          break;
        case "ArrowUp":
          next = { r: r - 1, c };
          break;
        case "Home":
          next = { r, c: 0 };
          break;
        case "End":
          next = { r, c: buckets.length - 1 };
          break;
        default:
          return;
      }
      event.preventDefault();
      focusAt(next.r, next.c);
    },
    [buckets.length, focusAt],
  );

  return (
    <div style={surfaceWrap}>
      <table
        ref={tableRef}
        role="grid"
        aria-label="IV surface heatmap — expiry rows by moneyness columns"
        onKeyDown={onKeyDown}
        style={surfaceTable}
      >
        <thead>
          <tr>
            <th scope="col" style={cornerTh}>
              Exp \ K/S
            </th>
            {buckets.map((key) => (
              <th
                key={key}
                scope="col"
                style={{ ...colTh, ...(isAtmBucket(key) ? colThAtm : null) }}
              >
                {`${Math.round(Number(key) * 100)}%`}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => {
            const isActive = row.expiry === activeExpiry;
            return (
              <tr key={row.expiry}>
                <th scope="row" role="rowheader" style={rowTh}>
                  <button
                    type="button"
                    className="focus-ring"
                    aria-pressed={isActive}
                    onClick={() => onSelect(row.expiry)}
                    title={`Select ${row.expiry} for the smile table`}
                    style={rowHeaderBtn(isActive)}
                  >
                    {row.expiry}
                  </button>
                </th>
                {buckets.map((key, c) => {
                  const agg = row.cells.get(key);
                  if (!agg) {
                    return (
                      <td key={key} role="gridcell" style={missingTd}>
                        <span className="u-text-mute">—</span>
                      </td>
                    );
                  }
                  const callV = agg.call.length ? mean(agg.call) : undefined;
                  const putV = agg.put.length ? mean(agg.put) : undefined;
                  const vol = mean([...agg.call, ...agg.put, ...agg.other]);
                  const wings = [
                    callV != null ? `call ${(callV * 100).toFixed(2)}%` : null,
                    putV != null ? `put ${(putV * 100).toFixed(2)}%` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ");
                  const label = `${row.expiry} · K/S ${Math.round(Number(key) * 100)}% · IV ${(vol * 100).toFixed(2)}%`;
                  const title = wings ? `${label} (${wings})` : label;
                  const selected = focusPos.r === r && focusPos.c === c;
                  return (
                    <td key={key} role="gridcell" style={heatTd}>
                      <button
                        type="button"
                        data-cell="1"
                        data-r={r}
                        data-c={c}
                        tabIndex={selected ? 0 : -1}
                        aria-label={title}
                        title={title}
                        className="focus-ring"
                        onFocus={() => {
                          if (!selected) setFocusPos({ r, c });
                        }}
                        onClick={() => onSelect(row.expiry)}
                        style={heatCellBtn(heatBackground(vol, lo, hi))}
                      >
                        {/* FIX R1-F13: carry the unit in the visible label —
                            the merged cell value is a percent. */}
                        {(vol * 100).toFixed(1)}%
                      </button>
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ── styles (existing tokens/classes only — no new global CSS) ──────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const noticeStyle: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  background: "var(--warn-soft)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
  fontSize: "var(--font-size-md)",
};

const sectionHeadStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 10,
  marginBottom: 6,
  flexWrap: "wrap",
};

const sectionLabel: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-2xs)",
  letterSpacing: "var(--tracking-label)",
  color: "var(--text-mute)",
};

const tinyMeta: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontVariantNumeric: "tabular-nums",
  fontSize: "var(--font-size-2xs)",
};

const noteTextStyle: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-2xs)",
  marginTop: 4,
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
  fontFamily: "var(--font-mono)",
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
  fontSize: "var(--font-size-xs)",
  letterSpacing: "0.04em",
  whiteSpace: "nowrap",
};

const colTh: CSSProperties = {
  padding: "4px 6px",
  color: "var(--text-secondary)",
  fontWeight: 600,
  textAlign: "center",
  fontSize: "var(--font-size-xs)",
  whiteSpace: "nowrap",
};

const colThAtm: CSSProperties = {
  color: "var(--text-display)",
  fontWeight: 700,
};

const rowTh: CSSProperties = {
  position: "sticky",
  left: 0,
  zIndex: 1,
  padding: 0,
  background: "var(--surface-2)",
  borderTop: "1px solid var(--grid-color)",
  textAlign: "left",
};

const rowHeaderBtn = (isActive: boolean): CSSProperties => ({
  all: "unset",
  display: "block",
  boxSizing: "border-box",
  width: "100%",
  textAlign: "left",
  padding: "5px 8px",
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-2xs)",
  fontWeight: 600,
  fontVariantNumeric: "tabular-nums",
  whiteSpace: "nowrap",
  cursor: "pointer",
  color: isActive ? "var(--text-display)" : "var(--text-secondary)",
  background: isActive ? "var(--accent-soft)" : "transparent",
});

const heatTd: CSSProperties = {
  padding: 0,
  borderTop: "1px solid var(--grid-color)",
  verticalAlign: "middle",
};

const missingTd: CSSProperties = {
  textAlign: "center",
  padding: "5px 6px",
  borderTop: "1px solid var(--grid-color)",
  fontSize: "var(--font-size-2xs)",
};

const heatCellBtn = (background: string): CSSProperties => ({
  all: "unset",
  display: "block",
  boxSizing: "border-box",
  width: "100%",
  textAlign: "center",
  padding: "5px 6px",
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-2xs)",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-display)",
  background,
  cursor: "pointer",
});

const primaryNum: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-display)",
};

const mutedNum: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
};

export default IVOLPane;
