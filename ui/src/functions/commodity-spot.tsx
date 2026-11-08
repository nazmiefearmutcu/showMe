/**
 * Shared pane body for the commodity spot quotes: BGAS / BOIL / NGAS.
 *
 * Backend (engine/functions/commodity/_funcs.py) serves live yfinance
 * front-month futures snapshots:
 *  - BGAS/NGAS → one Henry Hub NG=F row + daily OHLCV history;
 *  - BOIL      → WTI CL=F + Brent BZ=F rows, plus the computed spread.
 *
 * Honesty contract: `source_mode === "model"` (status reference_model) is a
 * labelled deterministic reference row, NOT a live market print — the pane
 * shows a prominent reference-model pill + inline notice for it, and an
 * honest empty state when the provider returns nothing usable.
 */
import { Fragment, useMemo, type CSSProperties } from "react";
import {
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
import { defaultSymbolForFunction } from "@/lib/symbols";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface SpotRow {
  symbol?: string;
  name?: string;
  unit?: string;
  exchange?: string;
  contract?: string;
  last?: number | null;
  prev?: number | null;
  change?: number | null;
  change_pct?: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  volume?: number | null;
  source?: string;
  source_mode?: string;
  as_of?: string | null;
  /** EIA raw series fields — normalized to `last`/`as_of` on read so a
   *  backend that still ships `value`/`period` can never silently drop rows. */
  value?: number | string | null;
  period?: string | null;
}

interface SpotHistoryPoint {
  date?: string;
  close?: number | null;
}

interface SpotData {
  status?: string;
  /** Which input problem an input_error is (e.g. unsupported_contract). */
  error_kind?: string;
  reason?: string;
  source_mode?: string;
  rows?: SpotRow[];
  history?: SpotHistoryPoint[];
  /** BOIL: each leg's own closes, keyed by symbol (BOIL#1). */
  history_by_symbol?: Record<string, SpotHistoryPoint[] | null | undefined>;
  spread?: number | null;
  /** Envelope-level quote date (yfinance tier); rows carry their own as_of. */
  as_of?: string | null;
  next_actions?: string[];
  methodology?: string;
}

const DAYS_OPTIONS = [
  { value: 90, label: "3m" },
  { value: 180, label: "6m" },
  { value: 365, label: "1y" },
  { value: 1095, label: "3y" },
] as const;
const DAYS_IDS = DAYS_OPTIONS.map((o) => o.value);

/** BGAS and its NGAS alias take the advertised `range` window (1M..1Y) so the
 *  backend honours the selection; BOIL keeps the legacy `days` window. */
const RANGE_WINDOW_CODES = new Set(["BGAS", "NGAS"]);
const RANGE_OPTIONS = [
  { value: "1M", label: "1m" },
  { value: "3M", label: "3m" },
  { value: "6M", label: "6m" },
  { value: "1Y", label: "1y" },
] as const;
type RangeId = (typeof RANGE_OPTIONS)[number]["value"];
const RANGE_IDS = RANGE_OPTIONS.map((o) => o.value);

const CHART_W = 620;
const CHART_H = 150;
const PAD = { top: 10, right: 12, bottom: 20, left: 44 };

export interface CommoditySpotPaneProps extends FunctionPaneProps {
  /** Short market label used in the header title (e.g. "Natural Gas"). */
  title: string;
}

export function CommoditySpotPane({ code, symbol, title }: CommoditySpotPaneProps) {
  const isRangeWindow = RANGE_WINDOW_CODES.has(code.toUpperCase());
  const [days, setDays] = usePersistentOption<number>(
    `showme.${code.toLowerCase()}.days`,
    DAYS_IDS,
    365,
  );
  const [range, setRange] = usePersistentOption<RangeId>(
    `showme.${code.toLowerCase()}.range`,
    RANGE_IDS,
    "1Y",
  );
  const effectiveSymbol =
    symbol || defaultSymbolForFunction(code, ["COMMODITY"]);
  // NGAS#1: NGAS serves only Henry Hub (NG=F). The route's compatibility guard
  // rejects a TTF=F symbol as unsupported_asset before NGAS can name the
  // contract, so the pane does not send it and shows the explicit state itself.
  const unservedContract =
    code.toUpperCase() === "NGAS" &&
    !!effectiveSymbol &&
    effectiveSymbol.trim().toUpperCase() !== "NG=F";
  const { state, data, error, refetch } = useFunction<SpotData>({
    code,
    symbol: effectiveSymbol,
    params: isRangeWindow ? { range, live: true } : { days, live: true },
    enabled: !!effectiveSymbol && !unservedContract,
  });

  const payload = data?.data;
  const rows = useMemo(
    () =>
      (payload?.rows ?? [])
        .map(normaliseSpotRow)
        .filter((r): r is SpotRow => r !== null),
    [payload],
  );
  const closes = useMemo(
    () =>
      (payload?.history ?? [])
        .filter((h) => typeof h.close === "number")
        .map((h) => ({ date: String(h.date ?? ""), close: h.close as number })),
    [payload],
  );
  // BOIL#1: when the backend ships per-leg history, every row and chart
  // reads its own symbol's closes; the shared `history` is never reused.
  const legCloses = useMemo(
    () => toLegCloses(payload?.history_by_symbol),
    [payload],
  );
  const historyCount = legCloses
    ? Object.values(legCloses).reduce((n, pts) => n + pts.length, 0)
    : closes.length;

  const status = payload?.status ?? "—";
  const sourceMode = payload?.source_mode ?? "—";
  const isReferenceModel =
    sourceMode === "model" || status === "reference_model";
  const isProviderDown = status === "provider_unavailable";
  // NGAS#1: a contract the pane cannot serve is an explicit state, never a
  // substituted quote. The backend sends the reason; the pane shows it.
  const isUnsupported =
    status === "unsupported_contract" ||
    (status === "input_error" && payload?.error_kind === "unsupported_contract");
  // Honesty: "live" is earned by the backend's live_* source modes only
  // (live_yfinance, live_eia, …). Model/fallback envelopes never claim it.
  const primary = rows[0];
  // BGAS#2: "live quote" is earned only by a yfinance quote stamped with
  // today's UTC date. A quote from an earlier session (weekend, holiday,
  // pre-open) is the last quote, labelled with its own AS OF date.
  const quoteDay = String(primary?.as_of ?? payload?.as_of ?? "").slice(0, 10);
  const isPriorSessionQuote =
    sourceMode === "live_yfinance" &&
    quoteDay !== "" &&
    quoteDay !== new Date().toISOString().slice(0, 10);
  const isLive =
    status === "ok" && /^live_/.test(sourceMode) && !isPriorSessionQuote;
  const spread =
    typeof payload?.spread === "number" ? (payload.spread as number) : null;

  const body = !effectiveSymbol ? (
    <Empty
      title="Pick a contract"
      body={`${title} needs a commodity futures symbol (e.g. NG=F, CL=F).`}
      icon="⌖"
    />
  ) : unservedContract ? (
    <Empty
      title="Contract not served"
      body={`${effectiveSymbol} is not served by NGAS. NGAS only serves the Henry Hub contract (NG=F, USD/MMBtu); no other contract's rows are substituted.`}
      icon="∅"
    />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={56} />
      <Skeleton height={CHART_H} />
      <Skeleton height={20} width="70%" />
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
      title={
        isUnsupported
          ? "Contract not served"
          : isProviderDown
            ? "No live quote returned"
            : "No spot rows returned"
      }
      body={
        payload?.reason ??
        "The quote provider returned no usable live snapshot. Retry once the provider recovers."
      }
      icon="∅"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {isReferenceModel ? (
        <div role="note" style={noticeStyle}>
          <strong>Reference model.</strong> This is a deterministic labelled
          reference row, NOT a live market price.
        </div>
      ) : null}
      <section style={kpiGridStyle} aria-label={`${code} spot cards`}>
        {rows.map((row) => (
          <StatCard
            key={row.symbol ?? row.name}
            label={row.symbol ?? "Spot"}
            value={fmtPrice(row.last)}
            caption={`${row.unit ?? ""} · ${fmtSignedPct(row.change_pct)} · ${fmtAsOf(row.as_of)}`}
            tone={changeTone(row.change_pct)}
            trend={trendFor(
              legCloses ? (legCloses[row.symbol ?? ""] ?? []) : closes,
            )}
          />
        ))}
        {spread != null ? (
          <StatCard
            label="Brent − WTI"
            value={fmtSigned(spread)}
            caption={spread >= 0 ? "BRENT ABOVE WTI" : "WTI ABOVE BRENT"}
            tone="neutral"
          />
        ) : null}
        {/* BOIL#4: a multi-leg pane reports each leg's own range and volume,
            labelled by symbol; a single-leg pane keeps the plain cards. */}
        {rows.length > 1
          ? rows.map((row) => (
              <Fragment key={`range-${row.symbol ?? row.name}`}>
                <StatCard
                  label={`${row.symbol ?? "Spot"} day range`}
                  value={`${fmtPrice(row.low)} – ${fmtPrice(row.high)}`}
                  caption={`${row.symbol ?? ""} OPEN ${fmtPrice(row.open)}`}
                  tone="neutral"
                />
                <StatCard
                  label={`${row.symbol ?? "Spot"} volume`}
                  value={fmtCompact(row.volume)}
                  caption={row.exchange ?? ""}
                  tone="neutral"
                />
              </Fragment>
            ))
          : (
            <>
              <StatCard
                label="Day range"
                value={`${fmtPrice(primary?.low)} – ${fmtPrice(primary?.high)}`}
                caption={`${primary?.symbol ?? ""} OPEN ${fmtPrice(primary?.open)}`}
                tone="neutral"
              />
              <StatCard
                label="Volume"
                value={fmtCompact(primary?.volume)}
                caption={primary?.exchange ?? ""}
                tone="neutral"
              />
            </>
          )}
      </section>
      {legCloses
        ? Object.entries(legCloses)
            .filter(([, pts]) => pts.length > 1)
            .map(([sym, pts]) => (
              <figure
                key={sym}
                style={figureStyle}
                aria-label={`${code} ${sym} history chart`}
              >
                <CloseChart
                  points={pts}
                  unit={rows.find((r) => r.symbol === sym)?.unit ?? ""}
                />
                <figcaption style={captionStyle}>
                  <span>
                    {sym} · {pts.length} daily closes
                  </span>
                  <span>
                    {pts[0]?.date.slice(0, 10)} →{" "}
                    {pts[pts.length - 1]?.date.slice(0, 10)}
                  </span>
                </figcaption>
              </figure>
            ))
        : closes.length > 1 ? (
          <figure style={figureStyle} aria-label={`${code} history chart`}>
            <CloseChart points={closes} unit={primary?.unit ?? ""} />
            <figcaption style={captionStyle}>
              <span>{closes.length} daily closes</span>
              <span>
                {closes[0]?.date.slice(0, 10)} →{" "}
                {closes[closes.length - 1]?.date.slice(0, 10)}
              </span>
            </figcaption>
          </figure>
        ) : null}
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`${title} — ${effectiveSymbol || ""}`}
          subtitle={`${rows.map((r) => r.symbol ?? "").filter(Boolean).join(" · ") || effectiveSymbol || "—"} · ${historyCount} history points`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {sourceMode === "live_yfinance" ? `${historyCount} pts` : sourceMode}
              </Pill>
              <Pill
                tone={isReferenceModel || isProviderDown ? "warn" : isLive ? "positive" : "muted"}
                variant="soft"
                withDot={isLive}
              >
                {isReferenceModel
                  ? "reference model"
                  : isProviderDown
                    ? "provider down"
                    : isLive
                      ? "live quote"
                      : isPriorSessionQuote
                        ? "last quote"
                        : sourceMode}
              </Pill>
              {isRangeWindow ? (
                <SegmentedControl
                  label="HISTORY"
                  value={range}
                  options={RANGE_OPTIONS}
                  onChange={setRange}
                />
              ) : (
                <SegmentedControl
                  label="HISTORY"
                  value={days}
                  options={DAYS_OPTIONS}
                  onChange={setDays}
                />
              )}
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title={`Refresh ${title} snapshot`}
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
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="mode" value={sourceMode} />
          <StatusDivider />
          <StatusSection label="contracts" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection
            label="history"
            value={isRangeWindow ? range : days}
            tone="accent"
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── chart ─────────────────────────────────────────────────────────── */

function CloseChart({
  points,
  unit,
}: {
  points: Array<{ date: string; close: number }>;
  unit: string;
}) {
  const geom = useMemo(() => {
    const vals = points.map((p) => p.close);
    const minY = Math.min(...vals);
    const maxY = Math.max(...vals);
    const spanY = maxY - minY || 1;
    const innerW = CHART_W - PAD.left - PAD.right;
    const innerH = CHART_H - PAD.top - PAD.bottom;
    const x = (i: number) => PAD.left + (i / Math.max(points.length - 1, 1)) * innerW;
    const y = (v: number) => PAD.top + (1 - (v - minY) / spanY) * innerH;
    return {
      line: points
        .map((p, i) => `${x(i).toFixed(1)},${y(p.close).toFixed(1)}`)
        .join(" "),
      last: { x: x(points.length - 1), y: y(points[points.length - 1].close) },
      grid: [0, 0.5, 1].map((f) => ({
        y: PAD.top + f * innerH,
        v: maxY - f * spanY,
      })),
    };
  }, [points]);

  return (
    <svg
      viewBox={`0 0 ${CHART_W} ${CHART_H}`}
      role="img"
      aria-label={`${unit || "close"} history with ${points.length} points`.trim()}
      style={svgStyle}
    >
      {geom.grid.map((g, i) => (
        <g key={i}>
          <line
            x1={PAD.left}
            x2={CHART_W - PAD.right}
            y1={g.y}
            y2={g.y}
            stroke="var(--grid-color, var(--text-mute))"
            strokeWidth={1}
          />
          <text x={4} y={g.y + 3} style={axisTextStyle}>
            {fmtPrice(g.v)}
          </text>
        </g>
      ))}
      <polyline
        points={geom.line}
        fill="none"
        stroke="var(--accent)"
        strokeWidth={1.5}
      />
      <circle cx={geom.last.x} cy={geom.last.y} r={3} fill="var(--accent)">
        <title>
          {`${points[points.length - 1].date.slice(0, 10)}: ${fmtPrice(points[points.length - 1].close)} ${unit}`}
        </title>
      </circle>
    </svg>
  );
}

/** Per-symbol closes from `history_by_symbol`; null when the field is absent. */
function toLegCloses(
  raw: SpotData["history_by_symbol"] | null | undefined,
): Record<string, Array<{ date: string; close: number }>> | null {
  if (!raw || typeof raw !== "object") return null;
  const out: Record<string, Array<{ date: string; close: number }>> = {};
  for (const [sym, pts] of Object.entries(raw)) {
    out[sym] = (pts ?? [])
      .filter((h) => typeof h.close === "number")
      .map((h) => ({ date: String(h.date ?? ""), close: h.close as number }));
  }
  return out;
}

function trendFor(
  closes: Array<{ date: string; close: number }>,
): number[] | undefined {
  if (closes.length < 2) return undefined;
  return closes.slice(-30).map((c) => c.close);
}

/* ── formatting ────────────────────────────────────────────────────── */

/** Coerce numbers and numeric strings (EIA ships its `value` as either). */
function toFiniteNumber(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/**
 * Normalize one backend row to the shared SpotRow contract.
 *
 * The EIA tier ships `value`/`period` (backend `live_eia`); the yfinance tier
 * ships `last`/`as_of`. Rows that carry neither are dropped rather than
 * rendered as fake zeros — but a usable `value` row is always kept
 * (audit A3-H: the old `last`-only filter dropped every EIA row silently).
 */
function normaliseSpotRow(raw: SpotRow | null | undefined): SpotRow | null {
  if (!raw || typeof raw !== "object") return null;
  const last = toFiniteNumber(raw.last) ?? toFiniteNumber(raw.value);
  if (last === null) return null;
  const asOf =
    raw.as_of ??
    (raw.period != null && String(raw.period).trim() !== ""
      ? String(raw.period)
      : null);
  return { ...raw, last, as_of: asOf };
}

function changeTone(
  v: number | null | undefined,
): "positive" | "negative" | "neutral" {
  const n = toFiniteNumber(v);
  if (n === null) return "neutral";
  return n >= 0 ? "positive" : "negative";
}

function fmtPrice(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  const digits = a >= 1000 ? 1 : a >= 100 ? 2 : 3;
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtSigned(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${fmtPrice(v)}`;
}

/** Percent caption: `change_pct` is already a percent, so stamp the unit. */
function fmtSignedPct(v: number | null | undefined): string {
  const base = fmtSigned(v);
  return base === "—" ? base : `${base}%`;
}

function fmtCompact(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(v);
}

function fmtAsOf(v: string | null | undefined): string {
  if (!v) return "—";
  return `AS OF ${String(v).slice(0, 10)}`;
}

/* ── styles ────────────────────────────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const noticeStyle: CSSProperties = {
  border: "1px solid var(--warn, var(--text-mute))",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: "var(--font-size-md)",
  color: "var(--text-primary)",
};

const figureStyle: CSSProperties = {
  margin: 0,
};

const captionStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
  marginTop: 4,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
};

const svgStyle: CSSProperties = {
  width: "100%",
  height: "auto",
  display: "block",
};

const axisTextStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  fill: "var(--text-mute)",
};
