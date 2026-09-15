/**
 * TECH — Technical Indicators pane.
 *
 * Backend (`backend/showme/engine/functions/chart/`) returns live 60-bar
 * OHLCV plus 7 indicator families (moving averages, RSI, MACD, Bollinger
 * Bands, Stochastic, ADX, OBV) with exposed `indicator_params`.
 *
 * Layout: persisted per-family toggle chips (`showme.tech.families`) +
 * params strip derived from the payload, the in-house chart engine
 * (`@/chart/Chart` — it owns timeframes/types/indicators/zoom and fetches
 * its own /api/bars), and a compact latest-values card grid with honest
 * tones (RSI/Stoch overbought-oversold, MACD histogram sign, ADX trend
 * strength). Empty / error / degraded (warnings) states are explicit —
 * never fake numbers.
 *
 * Study sub-panes (OPP wave 2026-09-11): the SAME family chips drive two
 * inline sub-panes — RSI(14) on a fixed 0–100 domain (true 70/30 guides) and
 * MACD (line + signal + sign-coloured histogram) — mirroring the HP study
 * pattern. A sub-pane is offered only when the payload actually carries
 * per-bar values for that study; a missing series renders nothing rather
 * than a fabricated line.
 */
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
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
import { formatNumberFixed } from "@/lib/format";
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { defaultSymbolForFunction } from "@/lib/symbols";
import { Chart } from "@/chart/Chart";
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

/* ── payload types (probed live from /api/fn/TECH) ─────────────────── */

interface TechBar {
  date?: string;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  sma_fast?: number | null;
  sma_slow?: number | null;
  ema?: number | null;
  rsi?: number | null;
  macd?: number | null;
  macd_signal?: number | null;
  macd_hist?: number | null;
  atr?: number | null;
  adx?: number | null;
  stoch_k?: number | null;
  stoch_d?: number | null;
  obv?: number | null;
}

interface TechPoint {
  time?: string;
  value?: number;
}

interface TechSummary {
  last_price?: number;
  rsi?: number;
  atr?: number;
  adx?: number;
  macd?: number;
  macd_signal?: number;
  stoch_k?: number;
  stoch_d?: number;
  obv?: number;
  samples?: number;
}

interface TechData {
  status?: string;
  reason?: string;
  model?: string;
  ohlcv?: TechBar[];
  bars?: TechBar[];
  rows?: TechBar[];
  indicators?: Record<string, TechPoint[]>;
  summary?: TechSummary;
  bar_count?: number;
  resolution?: string;
  indicator_params?: Record<string, number>;
  methodology?: string;
}

interface TechEnvelope {
  data?: TechData;
  sources?: string[];
  elapsed_ms?: number;
  data_state?: string;
  warnings?: string[];
}

/* ── indicator families (persisted toggles) ────────────────────────── */

const FAMILIES = [
  { id: "ma", label: "MA" },
  { id: "rsi", label: "RSI" },
  { id: "macd", label: "MACD" },
  { id: "bb", label: "BB" },
  { id: "stoch", label: "STOCH" },
  { id: "adx", label: "ADX" },
  { id: "obv", label: "OBV" },
] as const;

type FamilyId = (typeof FAMILIES)[number]["id"];
const FAMILY_IDS: readonly string[] = FAMILIES.map((f) => f.id);
const FAMILIES_KEY = "showme.tech.families";

/** Live adoption: visibility-paused 30s poll (campaign 2026-09-11). */
const REFRESH_MS = 30_000;

/**
 * Persisted hidden-family set. Stores the DISABLED ids as a CSV under
 * `showme.tech.families`; an absent/empty value means "show every family".
 * Unknown ids are dropped on read; toggling the last family off is allowed
 * and renders an honest "all families hidden" note.
 */
function usePersistentFamilies(key: string): {
  hidden: ReadonlySet<string>;
  toggle: (id: FamilyId) => void;
} {
  const [hidden, setHidden] = useState<ReadonlySet<string>>(() => {
    if (typeof localStorage === "undefined") return new Set<string>();
    const raw = localStorage.getItem(key);
    if (!raw) return new Set<string>();
    return new Set(raw.split(",").filter((id) => FAMILY_IDS.includes(id)));
  });
  const toggle = (id: FamilyId) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      if (typeof localStorage !== "undefined") {
        localStorage.setItem(key, Array.from(next).join(","));
      }
      return next;
    });
  };
  return { hidden, toggle };
}

/* ── pane ──────────────────────────────────────────────────────────── */

export function TECHPane({ code, symbol }: FunctionPaneProps) {
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const { hidden, toggle } = usePersistentFamilies(FAMILIES_KEY);
  const { state, data, error, refetch } = useFunction<TechData>({
    code,
    symbol: effectiveSymbol,
    enabled: !!effectiveSymbol,
  });

  // Live adoption (campaign 2026-09-11): visibility-paused 30s refetch. The
  // tick only triggers `refetch()`; it must never enter `params` because
  // `useFunction` fingerprints params into the fetch key (UA-HIGH-16).
  const tick = useVisibilityTick(REFRESH_MS);
  useEffect(() => {
    if (tick === 0) return; // initial mount is useFunction's own load
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tick is the trigger
  }, [tick]);

  const envelope = data as unknown as TechEnvelope | undefined;
  const payload = envelope?.data;
  const bars: TechBar[] = useMemo(
    () => (payload?.rows && payload.rows.length ? payload.rows : payload?.ohlcv ?? payload?.bars ?? []),
    [payload],
  );
  const lastBar = bars.length ? bars[bars.length - 1] : undefined;
  const summary = payload?.summary;
  const params = useMemo(() => payload?.indicator_params ?? {}, [payload]);
  const indicators = useMemo(() => payload?.indicators ?? {}, [payload]);

  const closes = useMemo(
    () => bars.map((b) => b.close).filter((v): v is number => v != null && Number.isFinite(v)),
    [bars],
  );
  const status = payload?.status ?? "—";
  const isLive = envelope?.data_state === "live";
  const warnings = envelope?.warnings ?? [];

  // Per-bar study series for the RSI/MACD sub-panes (OPP wave). Values are
  // filtered to finite numbers and windowed to the most recent STUDY_MAX_BARS
  // so the 280px strip stays readable (and cheap); a series with fewer than
  // two real points never opens a pane (no fabricated lines).
  const rsiStudy = useMemo(
    () => seriesFromBars(bars, (b) => b.rsi).slice(-STUDY_MAX_BARS),
    [bars],
  );
  const macdLineStudy = useMemo(
    () => seriesFromBars(bars, (b) => b.macd).slice(-STUDY_MAX_BARS),
    [bars],
  );
  const macdSignalStudy = useMemo(
    () => seriesFromBars(bars, (b) => b.macd_signal).slice(-STUDY_MAX_BARS),
    [bars],
  );
  const macdHistStudy = useMemo(
    () => seriesFromBars(bars, (b) => b.macd_hist).slice(-STUDY_MAX_BARS),
    [bars],
  );
  const showRsiStudy = !hidden.has("rsi") && rsiStudy.length >= 2;
  const showMacdStudy =
    !hidden.has("macd") && (macdLineStudy.length >= 2 || macdHistStudy.length >= 2);

  const cards = useMemo(
    () => buildCards({ summary, lastBar, indicators, params, closes }),
    [summary, lastBar, indicators, params, closes],
  );
  const visibleCards = cards.filter((c) => !hidden.has(c.family));
  const paramsLine = formatParams(params);

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="TECH needs a ticker with OHLCV history." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8" aria-busy="true">
      <Skeleton height={72} />
      <Skeleton height={110} />
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
  ) : bars.length === 0 || status === "empty" ? (
    <Empty
      title="No indicator bars returned"
      body={payload?.reason ?? "Provider returned no OHLCV history for this symbol."}
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <div style={chipRowStyle} role="group" aria-label="Indicator family toggles">
        {FAMILIES.map((f) => {
          const off = hidden.has(f.id);
          return (
            <button
              key={f.id}
              type="button"
              aria-pressed={!off}
              onClick={() => toggle(f.id)}
              title={`${off ? "Show" : "Hide"} ${f.label} family`}
              className={`fn-segmented__opt${off ? " fn-segmented__opt--disabled" : " fn-segmented__opt--active"}`}
            >
              {f.label}
            </button>
          );
        })}
      </div>
      {paramsLine ? (
        <div className="u-text-mute" style={paramsStyle}>
          {paramsLine}
        </div>
      ) : null}
      <section style={chartCardStyle} aria-label="Price chart">
        <div style={chartHeadStyle}>
          <span className="u-text-mute" style={paramsStyle}>
            CLOSE · {bars.length} BARS · {(payload?.resolution ?? "—").toUpperCase()}
          </span>
          <FlashValue value={num(summary?.last_price ?? lastBar?.close)}>
            <span style={monoStrongStyle}>
              {fmtNum(summary?.last_price ?? lastBar?.close)}
            </span>
          </FlashValue>
        </div>
        <Chart symbol={effectiveSymbol} height={280} initialInterval="1D" />
      </section>
      {showRsiStudy ? (
        <RsiStudyPane values={rsiStudy} period={params.rsi_period ?? 14} />
      ) : null}
      {showMacdStudy ? (
        <MacdStudyPane
          macd={macdLineStudy}
          signal={macdSignalStudy}
          hist={macdHistStudy}
          fast={params.macd_fast ?? 12}
          slow={params.macd_slow ?? 26}
          signalPeriod={params.macd_signal ?? 9}
        />
      ) : null}
      {warnings.length > 0 ? (
        <Pill tone="warn" variant="soft">
          {`Degraded: ${warnings[0]}`}
        </Pill>
      ) : null}
      {visibleCards.length === 0 ? (
        <Empty
          title="All indicator families hidden"
          body="Re-enable a family chip above to see latest indicator values."
          icon="⌥"
        />
      ) : (
        <section style={cardGridStyle} aria-label="Latest indicator values">
          {visibleCards.map((c) => (
            <StatCard
              key={c.label}
              label={c.label}
              value={c.value}
              caption={c.caption}
              tone={c.tone}
              trend={c.trend}
            />
          ))}
        </section>
      )}
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Technical Indicators — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${bars.length} bars · RSI ${fmtNum(summary?.rsi)}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={isLive ? "positive" : "muted"} variant="soft" withDot={false}>
                {envelope?.data_state ?? status}
              </Pill>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh indicators"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="sources" value={envelope?.sources?.join(", ") || "—"} />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="bars" value={bars.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${envelope?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="model" value={payload?.model ?? "—"} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── study sub-panes (OPP wave) ────────────────────────────────────── */

const STUDY_WIDTH = 280;
/** Study panes window the most recent bars so the strip stays readable. */
const STUDY_MAX_BARS = 240;

/**
 * RSI(14) sub-pane — fixed 0–100 domain so the 70/30 guide lines sit at
 * their TRUE positions instead of being re-scaled to the data range. Only
 * real per-bar RSI values are plotted (the caller filters warm-up gaps).
 */
function RsiStudyPane({ values, period }: { values: number[]; period: number }) {
  const height = 56;
  const last = values[values.length - 1] as number;
  const step = values.length > 1 ? STUDY_WIDTH / (values.length - 1) : 0;
  const y = (v: number) => {
    const clamped = Math.min(100, Math.max(0, v));
    return height - (clamped / 100) * (height - 4) - 2;
  };
  const line = values
    .map((v, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${y(v).toFixed(1)}`)
    .join(" ");
  const stroke =
    last >= 70 ? "var(--negative)" : last <= 30 ? "var(--positive)" : "var(--accent)";
  const zone =
    last >= 70 ? "OVERBOUGHT ≥ 70" : last <= 30 ? "OVERSOLD ≤ 30" : "NEUTRAL 30–70";
  return (
    <section style={studyPaneStyle} data-testid="tech-study-rsi" aria-label={`RSI(${period}) study`}>
      <div style={studyHeadStyle}>
        <span style={studyTitleStyle}>{`RSI(${period})`}</span>
        <span className="u-text-mute" style={paramsStyle}>
          {`LAST ${fmtNum(last)} · ${zone} · ${values.length} BARS`}
        </span>
      </div>
      <svg
        width={STUDY_WIDTH}
        height={height}
        viewBox={`0 0 ${STUDY_WIDTH} ${height}`}
        role="img"
        aria-label={`RSI(${period}) study, ${values.length} bars, last ${fmtNum(last)}`}
        className="u-block"
      >
        <line
          x1={0}
          x2={STUDY_WIDTH}
          y1={y(70)}
          y2={y(70)}
          stroke="var(--grid-color)"
          strokeDasharray="3 3"
        />
        <line
          x1={0}
          x2={STUDY_WIDTH}
          y1={y(30)}
          y2={y(30)}
          stroke="var(--grid-color)"
          strokeDasharray="3 3"
        />
        <text x={2} y={Math.max(8, y(70) - 2)} fontSize={8} fill="var(--text-mute)">
          70
        </text>
        <text x={2} y={Math.min(height - 1, y(30) + 9)} fontSize={8} fill="var(--text-mute)">
          30
        </text>
        <path
          d={line}
          fill="none"
          stroke={stroke}
          strokeWidth={1.25}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </section>
  );
}

/**
 * MACD(12/26/9) sub-pane — line + signal + sign-coloured histogram on a
 * shared zero-anchored domain (the standard MACD read). Series are the real
 * per-bar fields from the payload; missing series simply don't draw.
 */
function MacdStudyPane({
  macd,
  signal,
  hist,
  fast,
  slow,
  signalPeriod,
}: {
  macd: number[];
  signal: number[];
  hist: number[];
  fast: number;
  slow: number;
  signalPeriod: number;
}) {
  const height = 64;
  const length = Math.max(macd.length, signal.length, hist.length, 2);
  let min = 0;
  let max = 0;
  for (const series of [macd, signal, hist]) {
    for (const v of series) {
      if (v < min) min = v;
      if (v > max) max = v;
    }
  }
  const span = max - min || 1;
  const x = (i: number) => (i / (length - 1)) * STUDY_WIDTH;
  const y = (v: number) => height - ((v - min) / span) * (height - 6) - 3;
  const path = (values: number[]) =>
    values
      .map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)
      .join(" ");
  const barWidth = Math.max(1, (STUDY_WIDTH / length) * 0.6);
  const lastOf = (values: number[]) =>
    values.length ? (values[values.length - 1] as number) : null;
  const lastMacd = lastOf(macd);
  const lastSignal = lastOf(signal);
  const lastHist = lastOf(hist);
  return (
    <section
      style={studyPaneStyle}
      data-testid="tech-study-macd"
      aria-label={`MACD(${fast}/${slow}/${signalPeriod}) study`}
    >
      <div style={studyHeadStyle}>
        <span style={studyTitleStyle}>{`MACD ${fast}/${slow}/${signalPeriod}`}</span>
        <span className="u-text-mute" style={paramsStyle}>
          {`MACD ${fmtNum(lastMacd)} · SIGNAL ${fmtNum(lastSignal)} · HIST ${fmtNum(lastHist)} · ${length} BARS`}
        </span>
      </div>
      <svg
        width={STUDY_WIDTH}
        height={height}
        viewBox={`0 0 ${STUDY_WIDTH} ${height}`}
        role="img"
        aria-label={`MACD(${fast}/${slow}/${signalPeriod}) study, line ${fmtNum(lastMacd)}, signal ${fmtNum(lastSignal)}, histogram ${fmtNum(lastHist)}`}
        className="u-block"
      >
        <line x1={0} x2={STUDY_WIDTH} y1={y(0)} y2={y(0)} stroke="var(--grid-color)" />
        {hist.map((v, i) => {
          const zero = y(0);
          const top = v >= 0 ? y(v) : zero;
          return (
            <rect
              key={`h-${i}`}
              x={x(i) - barWidth / 2}
              y={top}
              width={barWidth}
              height={Math.max(0.5, Math.abs(y(v) - zero))}
              fill={v >= 0 ? "var(--positive-soft)" : "var(--negative-soft)"}
            />
          );
        })}
        {macd.length > 1 ? (
          <path
            d={path(macd)}
            fill="none"
            stroke="var(--accent)"
            strokeWidth={1.25}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {signal.length > 1 ? (
          <path
            d={path(signal)}
            fill="none"
            stroke="var(--text-secondary)"
            strokeWidth={1.25}
            strokeDasharray="3 2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
      </svg>
    </section>
  );
}

/* ── card derivation ───────────────────────────────────────────────── */

interface TechCard {
  family: FamilyId;
  label: string;
  value: string;
  caption?: string;
  tone: "neutral" | "positive" | "negative";
  trend?: number[];
}

interface BuildArgs {
  summary?: TechSummary;
  lastBar?: TechBar;
  indicators: Record<string, TechPoint[]>;
  params: Record<string, number>;
  closes: number[];
}

function buildCards({
  summary,
  lastBar,
  indicators,
  params,
  closes,
}: BuildArgs): TechCard[] {
  const last = num(summary?.last_price ?? lastBar?.close);
  const cards: TechCard[] = [];

  // Moving averages — price above/below tone.
  const smaFast = num(lastBar?.sma_fast ?? seriesLast(indicators.sma_20));
  const smaSlow = num(lastBar?.sma_slow ?? seriesLast(indicators.sma_50));
  const ema = num(lastBar?.ema ?? seriesLast(indicators.ema_20));
  if (smaFast != null) {
    cards.push({
      family: "ma",
      label: `SMA ${params.sma_fast ?? 20}`,
      value: fmtNum(smaFast),
      caption: last != null ? priceVs(last, smaFast) : undefined,
      tone: last != null ? (last >= smaFast ? "positive" : "negative") : "neutral",
      trend: trendOf(closes),
    });
  }
  if (smaSlow != null) {
    cards.push({
      family: "ma",
      label: `SMA ${params.sma_slow ?? 50}`,
      value: fmtNum(smaSlow),
      caption: last != null ? priceVs(last, smaSlow) : undefined,
      tone: last != null ? (last >= smaSlow ? "positive" : "negative") : "neutral",
    });
  }
  if (ema != null) {
    cards.push({
      family: "ma",
      label: `EMA ${params.ema_period ?? 20}`,
      value: fmtNum(ema),
      caption: last != null ? priceVs(last, ema) : undefined,
      tone: last != null ? (last >= ema ? "positive" : "negative") : "neutral",
    });
  }

  // RSI — overbought / oversold tone.
  const rsi = num(summary?.rsi ?? lastBar?.rsi);
  if (rsi != null) {
    cards.push({
      family: "rsi",
      label: `RSI ${params.rsi_period ?? 14}`,
      value: fmtNum(rsi),
      caption: rsi >= 70 ? "OVERBOUGHT ≥ 70" : rsi <= 30 ? "OVERSOLD ≤ 30" : "NEUTRAL 30–70",
      tone: rsi >= 70 ? "negative" : rsi <= 30 ? "positive" : "neutral",
    });
  }

  // MACD — line / signal / histogram (histogram sign tone).
  const macd = num(summary?.macd ?? lastBar?.macd);
  const macdSignal = num(summary?.macd_signal ?? lastBar?.macd_signal);
  const macdHist = num(lastBar?.macd_hist);
  if (macd != null) {
    cards.push({
      family: "macd",
      label: "MACD LINE",
      value: fmtNum(macd),
      caption: macdSignal != null ? `SIGNAL ${fmtNum(macdSignal)}` : undefined,
      tone: macd >= 0 ? "positive" : "negative",
    });
  }
  if (macdHist != null) {
    cards.push({
      family: "macd",
      label: "MACD HIST",
      value: fmtNum(macdHist),
      caption: macdHist >= 0 ? "BULLISH MOMENTUM" : "BEARISH MOMENTUM",
      tone: macdHist >= 0 ? "positive" : "negative",
    });
  }

  // Bollinger Bands — upper / mid / lower + %B position.
  const bbUpper = num(seriesLast(indicators.bb_upper));
  const bbMid = num(seriesLast(indicators.bb_mid));
  const bbLower = num(seriesLast(indicators.bb_lower));
  if (bbUpper != null && bbLower != null) {
    const pctB = last != null && bbUpper !== bbLower ? (last - bbLower) / (bbUpper - bbLower) : null;
    cards.push({
      family: "bb",
      label: "BB UPPER",
      value: fmtNum(bbUpper),
      caption: pctB != null ? `%B ${fmtNum(pctB)}` : undefined,
      tone: pctB != null && pctB >= 1 ? "negative" : "neutral",
    });
    if (bbMid != null) {
      cards.push({ family: "bb", label: "BB MID", value: fmtNum(bbMid), tone: "neutral" });
    }
    cards.push({
      family: "bb",
      label: "BB LOWER",
      value: fmtNum(bbLower),
      tone: pctB != null && pctB <= 0 ? "positive" : "neutral",
    });
  }

  // Stochastic — %K / %D with 80/20 tone.
  const stochK = num(summary?.stoch_k ?? lastBar?.stoch_k);
  const stochD = num(summary?.stoch_d ?? lastBar?.stoch_d);
  if (stochK != null) {
    cards.push({
      family: "stoch",
      label: `STOCH %K ${params.stoch_k ?? 14}`,
      value: fmtNum(stochK),
      caption: stochK >= 80 ? "OVERBOUGHT ≥ 80" : stochK <= 20 ? "OVERSOLD ≤ 20" : "MID 20–80",
      tone: stochK >= 80 ? "negative" : stochK <= 20 ? "positive" : "neutral",
    });
  }
  if (stochD != null) {
    cards.push({
      family: "stoch",
      label: `STOCH %D ${params.stoch_d ?? 3}`,
      value: fmtNum(stochD),
      tone: "neutral",
    });
  }

  // ADX — trend strength (directionless, ≥25 = trending).
  const adx = num(summary?.adx ?? lastBar?.adx);
  if (adx != null) {
    cards.push({
      family: "adx",
      label: `ADX ${params.adx_period ?? 14}`,
      value: fmtNum(adx),
      caption: adx >= 25 ? "TRENDING ≥ 25" : "RANGING < 25",
      tone: adx >= 25 ? "positive" : "neutral",
    });
    const atr = num(summary?.atr ?? lastBar?.atr);
    if (atr != null) {
      cards.push({
        family: "adx",
        label: `ATR ${params.atr_period ?? 14}`,
        value: fmtNum(atr),
        caption: last != null && last !== 0 ? `${fmtNum((atr / last) * 100)}% OF PRICE` : undefined,
        tone: "neutral",
      });
    }
  }

  // OBV — cumulative volume with 5-bar slope caption.
  const obv = num(summary?.obv ?? lastBar?.obv);
  if (obv != null) {
    const obvSeries = indicatorSeries(indicators.obv, barsToObvFallback(lastBar));
    const back = obvSeries.length > 5 ? obvSeries[obvSeries.length - 6] : obvSeries[0];
    const slope = back != null ? obv - back : null;
    cards.push({
      family: "obv",
      label: "OBV",
      value: fmtCompact(obv),
      caption: slope == null ? undefined : slope > 0 ? "RISING (5B)" : slope < 0 ? "FALLING (5B)" : "FLAT (5B)",
      tone: slope == null || slope === 0 ? "neutral" : slope > 0 ? "positive" : "negative",
    });
  }

  return cards;
}

/* ── helpers ───────────────────────────────────────────────────────── */

function num(v: unknown): number | null {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

/** Finite per-bar study values (warm-up nulls/NaN are dropped, not filled). */
function seriesFromBars(bars: TechBar[], pick: (b: TechBar) => unknown): number[] {
  const out: number[] = [];
  for (const bar of bars) {
    const value = num(pick(bar));
    if (value != null) out.push(value);
  }
  return out;
}

function seriesLast(points?: TechPoint[]): number | null {
  if (!points || !points.length) return null;
  return num(points[points.length - 1]?.value);
}

function barsToObvFallback(bar?: TechBar): TechPoint[] {
  const v = num(bar?.obv);
  return v == null ? [] : [{ value: v }];
}

function indicatorSeries(points?: TechPoint[], fallback: TechPoint[] = []): number[] {
  const vals = (points ?? fallback).map((p) => num(p.value)).filter((v): v is number => v != null);
  return vals;
}

function priceVs(price: number, reference: number): string {
  return price >= reference ? "PRICE ABOVE" : "PRICE BELOW";
}

function trendOf(values: number[]): number[] {
  return values.slice(-22);
}

function formatParams(p: Record<string, number>): string {
  const parts: string[] = [];
  const has = (k: string) => typeof p[k] === "number" && Number.isFinite(p[k]);
  if (has("sma_fast")) parts.push(`SMA ${p.sma_fast}/${p.sma_slow ?? "—"}`);
  if (has("ema_period")) parts.push(`EMA ${p.ema_period}`);
  if (has("rsi_period")) parts.push(`RSI(${p.rsi_period})`);
  if (has("macd_fast")) parts.push(`MACD ${p.macd_fast}/${p.macd_slow ?? "—"}/${p.macd_signal ?? "—"}`);
  if (has("bb_period")) parts.push(`BB ${p.bb_period}×${p.bb_std ?? 2}σ`);
  if (has("stoch_k")) parts.push(`STOCH ${p.stoch_k}/${p.stoch_d ?? 3}`);
  if (has("adx_period")) parts.push(`ADX(${p.adx_period})`);
  if (has("atr_period")) parts.push(`ATR(${p.atr_period})`);
  return parts.join(" · ");
}

function fmtNum(v: unknown): string {
  const n = num(v);
  if (n == null) return "—";
  return formatNumberFixed(n, 2);
}

function fmtCompact(v: unknown): string {
  const n = num(v);
  if (n == null) return "—";
  const a = Math.abs(n);
  if (a >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return n.toFixed(2);
}

/* ── styles (tokens only) ──────────────────────────────────────────── */

const chipRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
  alignItems: "center",
};

const paramsStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  letterSpacing: "0.05em",
};

const chartCardStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
};

const chartHeadStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "baseline",
  gap: 12,
};

const studyPaneStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
  padding: "8px 12px 10px",
  border: "1px solid var(--border)",
  borderRadius: 8,
  background: "var(--bg-raised, transparent)",
};

const studyHeadStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "baseline",
  gap: 12,
  flexWrap: "wrap",
};

const studyTitleStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  letterSpacing: "0.08em",
  color: "var(--accent)",
  fontWeight: 600,
};

const cardGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
  gap: 10,
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};
