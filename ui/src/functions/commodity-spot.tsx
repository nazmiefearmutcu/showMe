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
import { useMemo, type CSSProperties } from "react";
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
}

interface SpotHistoryPoint {
  date?: string;
  close?: number | null;
}

interface SpotData {
  status?: string;
  reason?: string;
  source_mode?: string;
  rows?: SpotRow[];
  history?: SpotHistoryPoint[];
  spread?: number | null;
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

const CHART_W = 620;
const CHART_H = 150;
const PAD = { top: 10, right: 12, bottom: 20, left: 44 };

export interface CommoditySpotPaneProps extends FunctionPaneProps {
  /** Short market label used in the header title (e.g. "Natural Gas"). */
  title: string;
}

export function CommoditySpotPane({ code, symbol, title }: CommoditySpotPaneProps) {
  const [days, setDays] = usePersistentOption<number>(
    `showme.${code.toLowerCase()}.days`,
    DAYS_IDS,
    365,
  );
  const effectiveSymbol =
    symbol || defaultSymbolForFunction(code, ["COMMODITY"]);
  const { state, data, error, refetch } = useFunction<SpotData>({
    code,
    symbol: effectiveSymbol,
    params: { days, live: true },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows = useMemo(
    () => (payload?.rows ?? []).filter((r) => r && typeof r.last === "number"),
    [payload],
  );
  const closes = useMemo(
    () =>
      (payload?.history ?? [])
        .filter((h) => typeof h.close === "number")
        .map((h) => ({ date: String(h.date ?? ""), close: h.close as number })),
    [payload],
  );

  const status = payload?.status ?? "—";
  const sourceMode = payload?.source_mode ?? "—";
  const isReferenceModel =
    sourceMode === "model" || status === "reference_model";
  const isProviderDown = status === "provider_unavailable";

  const primary = rows[0];
  const spread =
    typeof payload?.spread === "number" ? (payload.spread as number) : null;

  const body = !effectiveSymbol ? (
    <Empty
      title="Pick a contract"
      body={`${title} needs a commodity futures symbol (e.g. NG=F, CL=F).`}
      icon="⌖"
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
      title={isProviderDown ? "No live quote returned" : "No spot rows returned"}
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
            caption={`${row.unit ?? ""} · ${fmtSigned(row.change_pct)} · ${fmtAsOf(row.as_of)}`}
            tone={numOr(row.change_pct) >= 0 ? "positive" : "negative"}
            trend={trendFor(closes)}
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
      </section>
      {closes.length > 1 ? (
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
          subtitle={`${rows.map((r) => r.symbol ?? "").filter(Boolean).join(" · ") || effectiveSymbol || "—"} · ${closes.length} history points`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {sourceMode === "live_yfinance" ? `${closes.length} pts` : sourceMode}
              </Pill>
              <Pill
                tone={isReferenceModel || isProviderDown ? "warn" : "positive"}
                variant="soft"
                withDot={!isReferenceModel && !isProviderDown}
              >
                {isReferenceModel ? "reference model" : isProviderDown ? "provider down" : "live quote"}
              </Pill>
              <SegmentedControl
                label="HISTORY"
                value={days}
                options={DAYS_OPTIONS}
                onChange={setDays}
              />
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
          <StatusSection label="history" value={days} tone="accent" />
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

function trendFor(
  closes: Array<{ date: string; close: number }>,
): number[] | undefined {
  if (closes.length < 2) return undefined;
  return closes.slice(-30).map((c) => c.close);
}

/* ── formatting ────────────────────────────────────────────────────── */

function numOr(v: number | null | undefined): number {
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
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
