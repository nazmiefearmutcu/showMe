/**
 * GEX — Dealer gamma exposure ladder (options-family redesign 2026-09-12).
 *
 * "One screen, one job": a strike-ordered net-GEX ladder with the cumulative
 * GEX trace as a second encoding in its own strip beside the bars, a ≤4 KPI
 * strip and a single provenance footer. Rebuilt from the real wire payload
 * (sidecar probe 2026-09-12, raw: options-redesign/raw/gex-*.json):
 *
 *   rows[]  { label, strike, gex, value, cumulative_gex }   (cumulative real)
 *   summary { net_gex, call_gex_total, put_gex_total, gamma_flip,
 *             call_wall, put_wall, n_strikes, source_mode, synthetic, degraded }
 *   call_wall / put_wall objects { strike, gex }
 *
 * Honesty contract: the synthetic reference model (live yfinance chain
 * unavailable) gets exactly ONE header pill (mode) plus ONE notice block —
 * never the old double-warning stack — and `provider_unavailable` payloads
 * render the empty branch with the provider reason, never seeded numbers.
 * Removed decoration: per-pane SymbolBar, `N k` count pill, bar gradients,
 * chart legend, empty counterpart spans, emoji glyphs, duplicate expiry
 * labels. Keyboard: roving tabindex on the ladder options, Arrow/Home/End
 * move the selected strike, and a compact readout echoes the selection.
 */
import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import {
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  PaneState,
  Pill,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { defaultSymbolForFunction } from "@/lib/symbols";
import { SymbolBar } from "@/shell/SymbolBar";
import { formatCurrency, formatPrice } from "@/lib/format";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface GEXSummary {
  net_gex?: number | null;
  call_gex_total?: number | null;
  put_gex_total?: number | null;
  gamma_flip?: number | { strike?: number } | null;
  call_wall?: number | { strike?: number; gex?: number } | null;
  put_wall?: number | { strike?: number; gex?: number } | null;
  n_strikes?: number;
  source_mode?: string;
  /** True when the backend served the synthetic reference model rather
   * than a real options chain (live chain unavailable). */
  synthetic?: boolean;
  degraded?: boolean;
}

interface GEXRow {
  label?: string;
  strike?: number;
  gex?: number;
  value?: number;
  cumulative_gex?: number;
}

interface GEXData {
  status?: "ok" | "empty" | "input_error" | "provider_unavailable";
  reason?: string;
  symbol?: string;
  spot?: number;
  expiries?: string[];
  rows?: GEXRow[];
  curve?: GEXRow[];
  summary?: GEXSummary;
  call_wall?: number | { strike?: number; gex?: number } | null;
  put_wall?: number | { strike?: number; gex?: number } | null;
  gamma_flip?: number | { strike?: number } | null;
  methodology?: string;
  /** Human-readable degradation note surfaced verbatim when the synthetic
   * reference model is in use. */
  warning?: string;
}

/* ── formatting + parsing helpers ─────────────────────────────────── */

function strikeOf(
  value: number | { strike?: number } | null | undefined,
): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (value && typeof value === "object" && typeof value.strike === "number") {
    return value.strike;
  }
  return null;
}

function gexOf(
  value: number | { strike?: number; gex?: number } | null | undefined,
): number | null {
  if (value && typeof value === "object" && typeof value.gex === "number") {
    return value.gex;
  }
  return null;
}

function numOrNull(v: unknown): number | null {
  // null/undefined/"" must stay missing — Number(null) === 0 would turn a
  // missing net_gex into a fake "$0.00" with a positive tone.
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

/** GEX dollar magnitudes — compact "$" with 2 significant decimals via the
 * canonical formatter (missing → em-dash). */
function gexCurrency(n: number | null | undefined): string {
  return formatCurrency(n, { compact: true, fractionDigits: 2 });
}

/** Strike labels — price-grade precision from the canonical formatter. */
function gexStrike(n: number | null | undefined): string {
  return formatPrice(n);
}

/** Wire `gex`/`value` is a SIGNED net-GEX number, not a call/put decomposition.
 * Missing stays missing (FIX R1-F7): the old `?? 0` rendered a fabricated
 * call-side `$0.00` bar for a malformed row. */
function rowValue(row: GEXRow): number | null {
  return numOrNull(row.gex) ?? numOrNull(row.value);
}

/* ── ladder ────────────────────────────────────────────────────────── */

const ROW_HEIGHT = 24;
const BAR_HEIGHT = 12;
const STRIP_WIDTH = 72;
const STRIP_PAD = 6;

interface GexLadderProps {
  rows: GEXRow[];
  spot: number | null;
  callWallStrike: number | null;
  putWallStrike: number | null;
  flipStrike: number | null;
  symbol?: string;
}

function GexLadder({
  rows,
  spot,
  callWallStrike,
  putWallStrike,
  flipStrike,
  symbol,
}: GexLadderProps) {
  const [selected, setSelected] = useState<number | null>(null);
  const rowRefs = useRef<Array<HTMLDivElement | null>>([]);

  const maxAbs = useMemo(() => {
    let m = 0;
    for (const row of rows) {
      const v = rowValue(row);
      if (v != null && Math.abs(v) > m) m = Math.abs(v);
    }
    return m || 1;
  }, [rows]);

  const spotIdx = useMemo(() => {
    if (spot == null) return -1;
    let best = -1;
    let bestDist = Infinity;
    rows.forEach((row, index) => {
      const dist = Math.abs((row.strike ?? 0) - spot);
      if (dist < bestDist) {
        bestDist = dist;
        best = index;
      }
    });
    return bestDist < 0.01 ? best : -1;
  }, [rows, spot]);

  // Roving selection: explicit user choice wins; until then the strike that
  // matches spot (or the middle of the ladder) is active so the readout is
  // never empty and Tab lands somewhere meaningful.
  const activeIdx = useMemo(() => {
    if (!rows.length) return -1;
    if (selected != null) {
      return Math.min(Math.max(selected, 0), rows.length - 1);
    }
    if (spotIdx >= 0) return spotIdx;
    return Math.floor(rows.length / 2);
  }, [rows.length, selected, spotIdx]);

  const cum = useMemo(() => {
    const values = rows.map((row) => numOrNull(row.cumulative_gex));
    let min = Infinity;
    let max = -Infinity;
    for (const value of values) {
      if (value == null) continue;
      if (value < min) min = value;
      if (value > max) max = value;
    }
    const has = min <= max;
    return has ? { values, min, max } : null;
  }, [rows]);

  const cumPoints = useMemo(() => {
    if (!cum) return "";
    const span = cum.max - cum.min;
    const inner = STRIP_WIDTH - STRIP_PAD * 2;
    return cum.values
      .map((value, index) => {
        const x =
          value == null
            ? STRIP_WIDTH / 2
            : span <= 0
              ? STRIP_WIDTH / 2
              : STRIP_PAD + ((value - cum.min) / span) * inner;
        const y = index * ROW_HEIGHT + ROW_HEIGHT / 2;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  }, [cum]);

  const cumZeroX = useMemo(() => {
    if (!cum || cum.min >= 0 || cum.max <= 0) return null;
    const inner = STRIP_WIDTH - STRIP_PAD * 2;
    return STRIP_PAD + ((0 - cum.min) / (cum.max - cum.min)) * inner;
  }, [cum]);

  const focusRow = useCallback(
    (index: number) => {
      if (!rows.length) return;
      const next = Math.min(Math.max(index, 0), rows.length - 1);
      setSelected(next);
      const el = rowRefs.current[next];
      if (el) {
        el.focus();
        el.scrollIntoView?.({ block: "nearest" });
      }
    },
    [rows.length],
  );

  const onRowKeyDown = (
    event: ReactKeyboardEvent<HTMLDivElement>,
    index: number,
  ) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusRow(index + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      focusRow(index - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusRow(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusRow(rows.length - 1);
    }
  };

  const activeRow = activeIdx >= 0 ? rows[activeIdx] : null;
  const activeValue = activeRow ? rowValue(activeRow) : null;
  const activeCum = activeRow ? numOrNull(activeRow.cumulative_gex) : null;
  const activeTags: string[] = [];
  if (activeRow) {
    if (callWallStrike != null && activeRow.strike === callWallStrike) {
      activeTags.push("CALL WALL");
    }
    if (putWallStrike != null && activeRow.strike === putWallStrike) {
      activeTags.push("PUT WALL");
    }
    if (flipStrike != null && activeRow.strike === flipStrike) {
      activeTags.push("FLIP");
    }
    if (activeIdx === spotIdx) activeTags.push("SPOT");
  }

  const ladderHeight = rows.length * ROW_HEIGHT;

  return (
    <section className="gex-ladder" aria-label="Dealer gamma ladder">
      <div style={LADDER_HEAD}>
        <span style={LADDER_META}>Net GEX by strike</span>
        <span style={LADDER_META}>max ±{gexCurrency(maxAbs)}</span>
      </div>
      <div style={LADDER_COLS} aria-hidden="true">
        {/* FIX R2-#5: the bars encode SIGNED net GEX (the wire carries a
            single `gex` number), not a call/put split — label the sides by
            sign so a negative call-wall strike is not read as "the put side". */}
        <span style={{ textAlign: "right" }}>Net Γ −</span>
        <span style={{ textAlign: "center" }}>Strike</span>
        <span style={{ textAlign: "left" }}>Net Γ +</span>
        <span style={{ textAlign: "center" }}>Cum</span>
      </div>
      <div className="gex-ladder__scroll" style={LADDER_SCROLL}>
        <div style={LADDER_INNER}>
          {cum && cumPoints ? (
            <svg
              data-testid="gex-cum-strip"
              width={STRIP_WIDTH}
              height={ladderHeight}
              style={STRIP}
              aria-hidden="true"
            >
              {cumZeroX != null ? (
                <line
                  x1={cumZeroX}
                  x2={cumZeroX}
                  y1={0}
                  y2={ladderHeight}
                  stroke="var(--line)"
                  strokeWidth={1}
                />
              ) : null}
              <polyline
                points={cumPoints}
                fill="none"
                stroke="var(--text-secondary)"
                strokeWidth={1.25}
              />
            </svg>
          ) : null}
          <div
            role="listbox"
            aria-label={`Dealer gamma exposure by strike for ${symbol ?? "instrument"}, ${rows.length} strikes`}
          >
            {rows.map((row, index) => {
              const value = rowValue(row);
              const pct =
                value == null
                  ? 0
                  : Math.min(100, (Math.abs(value) / maxAbs) * 100);
              const selectedRow = index === activeIdx;
              const tags: string[] = [];
              if (callWallStrike != null && row.strike === callWallStrike) {
                tags.push("CALL WALL");
              }
              if (putWallStrike != null && row.strike === putWallStrike) {
                tags.push("PUT WALL");
              }
              if (flipStrike != null && row.strike === flipStrike) {
                tags.push("FLIP");
              }
              if (index === spotIdx) tags.push("SPOT");
              const tagText = tags.join(" · ");
              const cumValue = numOrNull(row.cumulative_gex);
              const ariaLabel =
                `Strike ${gexStrike(row.strike)}: ` +
                (value == null
                  ? "net gamma —"
                  : `${value >= 0 ? "positive" : "negative"} net gamma ${gexCurrency(Math.abs(value))}`) +
                (cumValue != null ? `, cumulative ${gexCurrency(cumValue)}` : "") +
                (tags.length ? ` (${tags.join(", ").toLowerCase()})` : "");
              const tagsNode = tagText ? (
                <span style={TAG} data-testid="gex-row-tags">
                  {tagText}
                </span>
              ) : null;
              return (
                <div
                  key={row.strike ?? index}
                  ref={(el) => {
                    rowRefs.current[index] = el;
                  }}
                  role="option"
                  aria-selected={selectedRow}
                  tabIndex={selectedRow ? 0 : -1}
                  aria-label={ariaLabel}
                  title={ariaLabel}
                  className="gex-ladder__row focus-ring"
                  data-testid="gex-ladder-row"
                  onFocus={() => setSelected(index)}
                  onClick={() => setSelected(index)}
                  onKeyDown={(event) => onRowKeyDown(event, index)}
                  style={{
                    ...ROW,
                    background: selectedRow
                      ? "var(--accent-soft)"
                      : "transparent",
                  }}
                >
                  <span style={CELL_LEFT}>
                    {/* FIX R2-#5: wall/role tags sit on the bar's own sign
                        side; a missing value renders an em-dash, never a
                        fabricated $0.00 call bar. */}
                    {value != null && value < 0 ? (
                      <span style={{ ...SIDE_BAR_ROW, justifyContent: "flex-end" }}>
                        {tagsNode}
                        <span
                          data-testid="gex-bar-neg"
                          style={barStyle("var(--negative)", pct)}
                        />
                      </span>
                    ) : value == null ? (
                      <span style={{ ...SIDE_BAR_ROW, justifyContent: "flex-end" }}>
                        {tagsNode}
                        <span data-testid="gex-bar-missing" style={MISSING}>
                          —
                        </span>
                      </span>
                    ) : null}
                  </span>
                  <span style={CELL_STRIKE}>{gexStrike(row.strike)}</span>
                  <span style={CELL_RIGHT}>
                    {value != null && value >= 0 ? (
                      <span style={{ ...SIDE_BAR_ROW, justifyContent: "flex-start" }}>
                        <span
                          data-testid="gex-bar-pos"
                          style={barStyle("var(--positive)", pct)}
                        />
                        {tagsNode}
                      </span>
                    ) : null}
                  </span>
                  <span />
                </div>
              );
            })}
          </div>
        </div>
      </div>
      {activeRow ? (
        <div
          style={READOUT}
          data-testid="gex-ladder-readout"
          className="terminal-grid-numeric"
        >
          <span style={READOUT_LABEL}>Selected</span>
          <span style={READOUT_VALUE}>{gexStrike(activeRow.strike)}</span>
          <span>GEX {gexCurrency(activeValue)}</span>
          <span>cum {gexCurrency(activeCum)}</span>
          {activeTags.length ? (
            <span style={READOUT_LABEL}>{activeTags.join(" · ")}</span>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

/* ── pane ──────────────────────────────────────────────────────────── */

export function GEXPane({ code, symbol }: FunctionPaneProps) {
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY"]);
  const { state, data, error, refetch } = useFunction<GEXData>({
    code,
    symbol: effectiveSymbol,
    // `live_options` switches the backend from the synthetic 3-strike
    // reference model to the real yfinance options chain + Black-Scholes
    // gamma path. The model fallback still kicks in when yfinance is
    // unreachable so the pane never goes blank.
    params: { live_options: true, max_expiries: 1 },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const status = payload?.status ?? (state === "ok" ? "ok" : undefined);
  const summary = payload?.summary;
  const spot = numOrNull(payload?.spot);
  const rows = useMemo<GEXRow[]>(() => {
    const candidate = payload?.curve ?? payload?.rows ?? [];
    return [...candidate].sort((a, b) => (a.strike ?? 0) - (b.strike ?? 0));
  }, [payload]);

  const callWallStrike =
    strikeOf(payload?.call_wall) ?? strikeOf(summary?.call_wall);
  const putWallStrike =
    strikeOf(payload?.put_wall) ?? strikeOf(summary?.put_wall);
  const flipStrike =
    strikeOf(summary?.gamma_flip) ?? strikeOf(payload?.gamma_flip);
  const netGex = numOrNull(summary?.net_gex);

  // Honest source detection: the backend flags the synthetic reference model
  // explicitly (`summary.synthetic`); older payloads are caught via the
  // `synthetic*` source_mode prefix.
  const sourceMode = summary?.source_mode ?? "";
  const isSynthetic =
    summary?.synthetic === true ||
    summary?.degraded === true ||
    sourceMode.startsWith("synthetic");
  const isLive = !isSynthetic && sourceMode.includes("live");
  const providerDown = status === "provider_unavailable";
  const syntheticNote =
    payload?.warning ??
    payload?.reason ??
    "Live options chain unavailable — showing a synthetic reference model, NOT real dealer positioning.";

  const expiries = payload?.expiries ?? [];
  const subtitleParts: string[] = [];
  if (status === "ok" && rows.length > 0) {
    // The strike count lives in the footer only (FIX R2-#8/R1-F3: header and
    // footer must not restate the same fact).
    subtitleParts.push(`spot ${gexStrike(spot)}`);
    if (expiries.length === 1) {
      subtitleParts.push(`nearest expiry ${expiries[0]}`);
    } else if (expiries.length > 1) {
      subtitleParts.push(`${expiries.length} expiries`);
    }
  } else if (providerDown) {
    subtitleParts.push("options provider unavailable");
  } else {
    subtitleParts.push("waiting for options chain");
  }

  const netTone: "neutral" | "positive" | "negative" =
    netGex == null ? "neutral" : netGex >= 0 ? "positive" : "negative";
  const flipCaption =
    flipStrike != null && spot != null
      ? `${(flipStrike - spot).toFixed(2)} vs spot`
      : flipStrike != null
        ? "first sign change"
        : "no sign change in range";
  const callWallGex = gexOf(payload?.call_wall);
  const putWallGex = gexOf(payload?.put_wall);

  const modePill = isSynthetic ? (
    <Pill tone="negative" variant="soft">
      synthetic
    </Pill>
  ) : isLive ? (
    <Pill tone="positive" variant="soft">
      live chain
    </Pill>
  ) : payload?.status === "ok" ? (
    <Pill tone="warn" variant="soft">
      reference
    </Pill>
  ) : null;
  // FIX R2-#10 (one pill policy): a green "ok" chip beside the synthetic /
  // reference mode pill + honesty notice restated a condition three ways.
  // The mode pill already conveys the state; the load pill only renders when
  // it adds information (loading / error / provider outage).
  const showLoadPill = state !== "ok" || !modePill;

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Dealer gamma — ${effectiveSymbol ?? "—"}`}
          subtitle={subtitleParts.join(" · ")}
          trailing={
            <FunctionControlGroup>
              {modePill}
              {showLoadPill && <LoadStatePill state={state} status={status} />}
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh GEX ladder"
              />
            </FunctionControlGroup>
          }
        />
        <SymbolBar code={code} symbol={effectiveSymbol} />
        <PaneBody className="u-grid-gap-14">
          <PaneState
            state={state}
            error={error}
            empty={providerDown || rows.length === 0}
            emptyTitle={providerDown ? "Options chain unavailable" : "No options chain"}
            emptyBody={
              payload?.reason ??
              "Try a liquid equity symbol such as SPY or NVDA."
            }
            emptyIcon="∅"
            onRetry={refetch}
            loadingRows={5}
          >
            {isSynthetic ? (
              <div
                className="gex-synthetic-note"
                role="status"
                data-testid="gex-synthetic-notice"
              >
                <strong className="gex-synthetic-note__title">
                  Synthetic model
                </strong>
                <span className="gex-synthetic-note__body">
                  {syntheticNote}
                </span>
              </div>
            ) : null}
            <section style={KPI_GRID} aria-label="GEX KPI ribbon">
              <StatCard
                label="Net GEX"
                value={
                  <span className="terminal-grid-numeric">
                    {gexCurrency(netGex)}
                  </span>
                }
                caption={`Calls ${gexCurrency(summary?.call_gex_total)} · Puts ${gexCurrency(summary?.put_gex_total)}`}
                tone={netTone}
              />
              <StatCard
                label="Zero-gamma"
                value={
                  <span className="terminal-grid-numeric">
                    {gexStrike(flipStrike)}
                  </span>
                }
                caption={flipCaption}
                tone="neutral"
              />
              <StatCard
                label="Call wall"
                value={
                  <span className="terminal-grid-numeric">
                    {gexStrike(callWallStrike)}
                  </span>
                }
                caption={`GEX ${gexCurrency(callWallGex)}`}
                tone="neutral"
              />
              <StatCard
                label="Put wall"
                value={
                  <span className="terminal-grid-numeric">
                    {gexStrike(putWallStrike)}
                  </span>
                }
                caption={`GEX ${gexCurrency(putWallGex)}`}
                tone="neutral"
              />
            </section>
            <GexLadder
              rows={rows}
              spot={spot}
              callWallStrike={callWallStrike}
              putWallStrike={putWallStrike}
              flipStrike={flipStrike}
              symbol={effectiveSymbol}
            />
          </PaneState>
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection label="status" value={status ?? "—"} />
          <StatusDivider />
          <StatusSection
            label="strikes"
            value={summary?.n_strikes ?? rows.length}
            tone="accent"
          />
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

const KPI_GRID: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const LADDER_HEAD: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  justifyContent: "space-between",
  gap: 12,
};

const LADDER_META: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-xs)",
  letterSpacing: "var(--tracking-label)",
  color: "var(--text-mute)",
  whiteSpace: "nowrap",
};

const LADDER_COLS: CSSProperties = {
  display: "grid",
  gridTemplateColumns: `minmax(0, 1fr) 84px minmax(0, 1fr) ${STRIP_WIDTH}px`,
  alignItems: "center",
  gap: 0,
  padding: "2px 0",
  color: "var(--text-mute)",
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-xs)",
  letterSpacing: "var(--tracking-label)",
};

const LADDER_SCROLL: CSSProperties = {
  maxHeight: 340,
  overflowY: "auto",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "var(--scrim-low)",
};

const LADDER_INNER: CSSProperties = {
  position: "relative",
  minWidth: 0,
};

const ROW: CSSProperties = {
  display: "grid",
  gridTemplateColumns: `minmax(0, 1fr) 84px minmax(0, 1fr) ${STRIP_WIDTH}px`,
  alignItems: "center",
  height: ROW_HEIGHT,
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-sm)",
  fontVariantNumeric: "tabular-nums",
  outlineOffset: -2,
};

const CELL_LEFT: CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  alignItems: "center",
  minWidth: 0,
  paddingRight: 6,
};

const CELL_STRIKE: CSSProperties = {
  height: "100%",
  lineHeight: `${ROW_HEIGHT}px`,
  textAlign: "center",
  color: "var(--text-primary)",
  borderLeft: "1px solid var(--line)",
  borderRight: "1px solid var(--line)",
};

const CELL_RIGHT: CSSProperties = {
  display: "flex",
  justifyContent: "flex-start",
  alignItems: "center",
  minWidth: 0,
  paddingLeft: 6,
};

const TAG: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: "var(--font-size-xs)",
  letterSpacing: "var(--tracking-label)",
  whiteSpace: "nowrap",
};

/** Bar + role-tag pairing on the bar's sign side (FIX R2-#5).
 *
 * `width: 100%` is load-bearing: the bars size themselves with
 * `width: <pct>%`, and a shrink-to-fit inline-flex resolves that percentage
 * cyclically → 0px. Rows without a wall tag then rendered NO bar at all and
 * tagged rows rendered a tiny stub (the "broken ladder" report). Filling the
 * grid cell makes the percentage resolve against the cell width. */
const SIDE_BAR_ROW: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  minWidth: 0,
  width: "100%",
};

/** Missing-value rendering — never a fabricated $0.00 bar (FIX R1-F7). */
const MISSING: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-sm)",
  flex: "0 0 auto",
};

const STRIP: CSSProperties = {
  position: "absolute",
  top: 0,
  right: 0,
  pointerEvents: "none",
};

const READOUT: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "baseline",
  gap: "2px 12px",
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-sm)",
  color: "var(--text-secondary)",
};

const READOUT_LABEL: CSSProperties = {
  fontSize: "var(--font-size-xs)",
  letterSpacing: "var(--tracking-label)",
  color: "var(--text-mute)",
};

const READOUT_VALUE: CSSProperties = {
  color: "var(--text-primary)",
  fontWeight: 600,
};

function barStyle(color: string, pct: number): CSSProperties {
  return {
    width: `${pct}%`,
    height: BAR_HEIGHT,
    borderRadius: "var(--radius-xs)",
    background: color,
    // Shrinkable so a large bar + its wall tag never overflow the cell; the
    // 2px floor keeps near-zero values visible instead of collapsing to a
    // hairline that reads as "no data".
    flex: "0 1 auto",
    minWidth: 2,
  };
}

export default GEXPane;
