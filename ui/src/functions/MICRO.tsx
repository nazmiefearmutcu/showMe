/**
 * MICRO — Market microstructure (L2 order-book depth ladder).
 *
 * Bloomberg-terminal style order-book microstructure pane. Renders a
 * two-sided cumulative depth ladder (bids green / asks red, bar width =
 * cumulative size), a mid / spread / microprice header and a full-book
 * imbalance gauge. Only Binance exposes a real L2 depth feed in the
 * showMe adapter list, so crypto symbols render the live ladder while
 * every other asset class surfaces an honest `explicit_unavailable`
 * state instead of a fabricated ladder.
 *
 * Real payload (data?.data) keys consumed — from backend MICROFunction:
 *   status, data_mode, as_of, symbol, reason,
 *   bids[], asks[]  (each level: { price, size }),
 *   rows[]          (each: { side, price, size, cum_size, notional }),
 *   best_bid, best_ask, mid, spread, spread_bps, microprice,
 *   imbalance (top-of-book), surface[]/depth_table[] (buckets w/ imbalance),
 *   top10_imbalance, kyle_lambda_proxy, methodology.
 * Plus envelope: data.sources, data.warnings, data.elapsed_ms.
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
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface MicroLevel {
  price?: number;
  size?: number;
}

interface MicroRow {
  side?: string;
  price?: number;
  size?: number;
  cum_size?: number;
  notional?: number;
}

interface MicroBucket {
  bucket?: string;
  levels?: number;
  imbalance?: number;
}

interface MicroPayload {
  status?: string;
  data_mode?: string;
  as_of?: string;
  symbol?: string;
  asset_class?: string;
  reason?: string;
  bids?: MicroLevel[];
  asks?: MicroLevel[];
  rows?: MicroRow[];
  surface?: MicroBucket[];
  depth_table?: MicroBucket[];
  best_bid?: number | null;
  best_ask?: number | null;
  mid?: number | null;
  spread?: number | null;
  spread_bps?: number | null;
  microprice?: number | null;
  imbalance?: number | null;
  top10_imbalance?: number | null;
  kyle_lambda_proxy?: number | null;
  methodology?: string;
}

interface LadderLevel {
  price: number;
  size: number;
  cum: number;
}

// Mirrors backend `_normalize_depth_limit` allowed set (Binance depth limits).
const DEPTHS = [
  { id: "10", label: "10" },
  { id: "20", label: "20" },
  { id: "50", label: "50" },
  { id: "100", label: "100" },
] as const;
type DepthId = (typeof DEPTHS)[number]["id"];
const DEPTH_IDS = DEPTHS.map((d) => d.id);

// Book moves fast — 5s visibility-aware poll (Bundle D / PERF-04).
const REFRESH_MS = 5_000;

export function MICROPane({ code, symbol }: FunctionPaneProps) {
  const [depthOpt, setDepthOpt] = usePersistentOption<DepthId>(
    "showme.micro-depth",
    DEPTH_IDS,
    "20",
  );
  const tick = useVisibilityTick(REFRESH_MS);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    symbol,
    params: { depth_levels: Number(depthOpt), tick },
  });

  const payload = useMemo<MicroPayload>(
    () =>
      data?.data && typeof data.data === "object" && !Array.isArray(data.data)
        ? (data.data as MicroPayload)
        : {},
    [data?.data],
  );

  // Per-side ladders. Backend gives bids/asks best-first ({price,size}) and a
  // flat rows[] carrying the running cum_size — we merge cum_size back per side.
  const cumBySide = useMemo(() => {
    const bid = new Map<number, number>();
    const ask = new Map<number, number>();
    for (const r of Array.isArray(payload.rows) ? payload.rows : []) {
      const px = num(r.price);
      const cum = num(r.cum_size);
      if (px == null || cum == null) continue;
      (r.side === "ask" ? ask : bid).set(px, cum);
    }
    return { bid, ask };
  }, [payload.rows]);

  const bids = useMemo<LadderLevel[]>(
    () => toLadder(payload.bids, cumBySide.bid),
    [payload.bids, cumBySide.bid],
  );
  const asks = useMemo<LadderLevel[]>(
    () => toLadder(payload.asks, cumBySide.ask),
    [payload.asks, cumBySide.ask],
  );

  const sourceMode = payload.data_mode ?? "unavailable";
  const status = payload.status ?? "";
  const isLive = status === "ok" && sourceMode === "live_exchange";
  const isProviderDown = sourceMode === "provider_unavailable";
  const isUnavailable =
    sourceMode === "explicit_unavailable" ||
    isProviderDown ||
    status === "empty" ||
    (status !== "ok" && bids.length === 0 && asks.length === 0);

  const warnings = useMemo<string[]>(
    () => (Array.isArray(data?.warnings) ? (data?.warnings as string[]) : []),
    [data?.warnings],
  );

  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 19), [tick]);
  const sym = payload.symbol ?? symbol ?? "—";

  // Bar scaling: longest cumulative across both sides anchors the bar width.
  const maxCum = useMemo(() => {
    let m = 0;
    for (const b of bids) m = Math.max(m, b.cum);
    for (const a of asks) m = Math.max(m, a.cum);
    return m || 1;
  }, [bids, asks]);

  // Full-book size totals + imbalance (the ladder's deepest cumulative).
  const totalBid = bids.length ? bids[bids.length - 1].cum : 0;
  const totalAsk = asks.length ? asks[asks.length - 1].cum : 0;
  const bookImbalance =
    totalBid + totalAsk > 0 ? (totalBid - totalAsk) / (totalBid + totalAsk) : 0;

  const topImbalance = num(payload.imbalance) ?? 0;
  const mid = num(payload.mid);
  const microprice = num(payload.microprice);
  const spread = num(payload.spread);
  const spreadBps = num(payload.spread_bps);
  const bestBid = num(payload.best_bid);
  const bestAsk = num(payload.best_ask);

  const pillLabel = isLive
    ? "live"
    : isProviderDown
      ? "provider down"
      : isUnavailable
        ? "unavailable"
        : sourceMode;

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Order-book microstructure"
          subtitle={`${sym} · depth ${depthOpt} · poll ${REFRESH_MS / 1000}s · ${sourceMode}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {sym}
              </Pill>
              <Pill tone="accent" variant="soft" withDot={false}>
                {utcStamp} UTC
              </Pill>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {pillLabel}
              </Pill>
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <div style={tabBarStyle}>
          <span style={tabLabelStyle}>Depth</span>
          <div style={segWrapStyle} role="tablist" aria-label="Order-book depth">
            {DEPTHS.map((d) => {
              const on = d.id === depthOpt;
              return (
                <button
                  key={d.id}
                  type="button"
                  role="tab"
                  aria-selected={on}
                  onClick={() => setDepthOpt(d.id)}
                  style={{ ...segBtnStyle, ...(on ? segBtnActiveStyle : null) }}
                >
                  {d.label}
                </button>
              );
            })}
          </div>
        </div>
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <Skeleton height={360} />
          ) : state === "error" ? (
            <Empty title="Function error" body={error?.message ?? "—"} icon="!" />
          ) : isUnavailable ? (
            <div className="u-grid-gap-14">
              <Empty
                title={
                  isProviderDown
                    ? "Depth provider unavailable"
                    : "Order book unavailable"
                }
                body={
                  payload.reason ??
                  `${sym} (${payload.asset_class ?? "non-crypto"}) has no configured L2 depth provider. MICRO renders a live ladder only for crypto symbols on a Binance depth feed — it never fabricates levels.`
                }
                icon="∅"
              />
              {warnings.length ? <WarningBox warnings={warnings} /> : null}
              {payload.methodology ? (
                <MethodologyBox text={payload.methodology} />
              ) : null}
            </div>
          ) : bids.length === 0 && asks.length === 0 ? (
            <Empty title="Empty book" body={`No depth levels returned for ${sym}.`} />
          ) : (
            <div className="u-grid-gap-14">
              <section style={kpiGrid} aria-label="MICRO KPI ribbon">
                <StatCard
                  label="Mid"
                  value={mid != null ? fmtPx(mid) : "—"}
                  caption={
                    bestBid != null && bestAsk != null
                      ? `${fmtPx(bestBid)} / ${fmtPx(bestAsk)}`
                      : `AS OF ${utcStamp} UTC`
                  }
                  tone="neutral"
                />
                <StatCard
                  label="Spread"
                  value={spread != null ? fmtPx(spread) : "—"}
                  caption={spreadBps != null ? `${spreadBps.toFixed(2)} bps` : "—"}
                  tone={
                    spreadBps == null
                      ? "neutral"
                      : spreadBps <= 2
                        ? "positive"
                        : spreadBps >= 10
                          ? "negative"
                          : "neutral"
                  }
                />
                <StatCard
                  label="Microprice"
                  value={microprice != null ? fmtPx(microprice) : "—"}
                  caption={
                    microprice != null && mid != null
                      ? `${microprice >= mid ? "+" : ""}${fmtPx(microprice - mid)} vs mid`
                      : "size-weighted mid"
                  }
                  tone={
                    microprice == null || mid == null
                      ? "neutral"
                      : microprice >= mid
                        ? "positive"
                        : "negative"
                  }
                />
                <StatCard
                  label="Imbalance (TOB)"
                  value={`${topImbalance >= 0 ? "+" : ""}${(topImbalance * 100).toFixed(1)}%`}
                  caption={
                    topImbalance >= 0.005
                      ? "bid-heavy"
                      : topImbalance <= -0.005
                        ? "ask-heavy"
                        : "balanced"
                  }
                  tone={
                    topImbalance > 0.04
                      ? "positive"
                      : topImbalance < -0.04
                        ? "negative"
                        : "neutral"
                  }
                />
              </section>

              <ImbalanceGauge
                bookImbalance={bookImbalance}
                totalBid={totalBid}
                totalAsk={totalAsk}
              />

              <DepthLadder
                asks={asks}
                bids={bids}
                maxCum={maxCum}
                mid={mid}
                spread={spread}
                spreadBps={spreadBps}
              />

              {warnings.length ? <WarningBox warnings={warnings} /> : null}
              {payload.methodology ? (
                <MethodologyBox text={payload.methodology} />
              ) : null}
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="provider"
            value={data?.sources?.join(", ") || (isLive ? "Binance depth" : sourceMode)}
          />
          <StatusDivider />
          <StatusSection label="poll" value={`${REFRESH_MS / 1000}s`} />
          <StatusDivider />
          <StatusSection label="levels" value={bids.length + asks.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="symbol" value={sym} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── Imbalance gauge ─────────────────────────────────────────────── */

function ImbalanceGauge({
  bookImbalance,
  totalBid,
  totalAsk,
}: {
  bookImbalance: number;
  totalBid: number;
  totalAsk: number;
}) {
  const denom = totalBid + totalAsk;
  const bidPct = denom ? (totalBid / denom) * 100 : 50;
  const askPct = denom ? (totalAsk / denom) * 100 : 50;
  // Marker mapped from imbalance [-1,+1] to [0,100] (left=ask, right=bid).
  const markerPct = Math.max(0, Math.min(100, ((bookImbalance + 1) / 2) * 100));
  return (
    <section style={gaugeWrap} aria-label="Bid/ask imbalance gauge">
      <div style={gaugeHeader}>
        <span style={gaugeAskLabel}>ASK {askPct.toFixed(1)}%</span>
        <span style={metaLabel}>BOOK IMBALANCE</span>
        <span style={gaugeBidLabel}>BID {bidPct.toFixed(1)}%</span>
      </div>
      <div style={gaugeTrack} aria-hidden>
        <div style={{ ...gaugeAskFill, width: `${askPct}%` }} />
        <div style={{ ...gaugeBidFill, width: `${bidPct}%` }} />
        <div style={gaugeCenterTick} />
        <div style={{ ...gaugeMarker, left: `${markerPct}%` }}>
          <span style={gaugeMarkerDot} />
        </div>
      </div>
      <div style={gaugeCaption}>
        (Σbid − Σask) / Σ ={" "}
        <strong
          style={{
            color: bookImbalance >= 0 ? "var(--positive)" : "var(--negative)",
          }}
        >
          {bookImbalance >= 0 ? "+" : ""}
          {bookImbalance.toFixed(4)}
        </strong>{" "}
        · range [−1, +1] · positive = bid-heavy
      </div>
    </section>
  );
}

/* ── Two-sided depth ladder ──────────────────────────────────────── */

function DepthLadder({
  asks,
  bids,
  maxCum,
  mid,
  spread,
  spreadBps,
}: {
  asks: LadderLevel[];
  bids: LadderLevel[];
  maxCum: number;
  mid: number | null;
  spread: number | null;
  spreadBps: number | null;
}) {
  // Asks rendered high→low so the spread row sits at the seam (best ask just
  // above mid, best bid just below). Backend gives bids/asks best-first.
  const askRows = [...asks].reverse();
  return (
    <section style={ladderWrap} aria-label="Order-book depth ladder">
      <div style={ladderHeadRow}>
        <span style={ladderHeadCell}>Price</span>
        <span style={{ ...ladderHeadCell, textAlign: "right" }}>Size</span>
        <span style={ladderHeadCellBar}>Cumulative</span>
      </div>

      <div style={ladderSide}>
        {askRows.map((lvl, i) => (
          <LadderRow key={`a-${i}`} lvl={lvl} maxCum={maxCum} side="ask" />
        ))}
      </div>

      <div style={spreadRow}>
        <span style={spreadMidStyle}>
          {mid != null ? fmtPx(mid) : "—"}
          <span style={spreadMidTag}>MID</span>
        </span>
        <span style={spreadValStyle}>
          {spread != null ? `${fmtPx(spread)} spread` : "—"}
          {spreadBps != null ? (
            <span style={spreadBpsTag}>{spreadBps.toFixed(2)} bps</span>
          ) : null}
        </span>
      </div>

      <div style={ladderSide}>
        {bids.map((lvl, i) => (
          <LadderRow key={`b-${i}`} lvl={lvl} maxCum={maxCum} side="bid" />
        ))}
      </div>
    </section>
  );
}

function LadderRow({
  lvl,
  maxCum,
  side,
}: {
  lvl: LadderLevel;
  maxCum: number;
  side: "bid" | "ask";
}) {
  const width = Math.max(1.5, Math.min(100, (lvl.cum / maxCum) * 100));
  const tone = side === "bid" ? "var(--positive)" : "var(--negative)";
  return (
    <div style={ladderRow}>
      <span style={{ ...ladderPrice, color: tone }}>{fmtPx(lvl.price)}</span>
      <span style={ladderSize}>{fmtSize(lvl.size)}</span>
      <div style={ladderBarCell}>
        <div
          aria-hidden
          style={{
            ...ladderBarFill,
            width: `${width}%`,
            // Bids fill from the right edge, asks from the left — mirrored book.
            marginLeft: side === "bid" ? "auto" : 0,
            background: `linear-gradient(${side === "bid" ? "270deg" : "90deg"}, color-mix(in srgb, ${tone} 55%, transparent), color-mix(in srgb, ${tone} 16%, transparent))`,
            borderInlineStart: side === "ask" ? `2px solid ${tone}` : undefined,
            borderInlineEnd: side === "bid" ? `2px solid ${tone}` : undefined,
          }}
        />
        <span style={ladderCumLabel}>{fmtCompact(lvl.cum)}</span>
      </div>
    </div>
  );
}

function WarningBox({ warnings }: { warnings: string[] }) {
  return (
    <section style={warningBox}>
      <strong className="u-text-warn">Provider warnings</strong>
      <ul style={warningList}>
        {warnings.slice(0, 3).map((w, i) => (
          <li key={i} className="u-text-secondary">
            {String(w)}
          </li>
        ))}
      </ul>
    </section>
  );
}

function MethodologyBox({ text }: { text: string }) {
  return (
    <section style={methodologyBox}>
      <div style={metaLabel}>Methodology</div>
      <p style={methodText}>{text}</p>
    </section>
  );
}

/* ── helpers ─────────────────────────────────────────────────────── */

/**
 * Build a ladder side from the backend's {price,size} levels, threading the
 * running cumulative from rows[].cum_size (keyed by price). Falls back to a
 * locally-accumulated running sum if rows[] is absent.
 */
function toLadder(
  levels: MicroLevel[] | undefined,
  cumByPrice: Map<number, number>,
): LadderLevel[] {
  if (!Array.isArray(levels)) return [];
  let running = 0;
  const out: LadderLevel[] = [];
  for (const lvl of levels) {
    const price = num(lvl.price);
    const size = num(lvl.size);
    if (price == null || size == null) continue;
    running += size;
    out.push({ price, size, cum: cumByPrice.get(price) ?? running });
  }
  return out;
}

function num(v: unknown): number | null {
  if (v == null) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function fmtPx(v: number): string {
  const a = Math.abs(v);
  const digits = a >= 1000 ? 2 : a >= 1 ? 4 : 6;
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: digits,
  });
}

function fmtSize(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(3)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(3)}K`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function fmtCompact(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(2)}K`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/* ── styles ──────────────────────────────────────────────────────── */

const tabBarStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const tabLabelStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const segWrapStyle: CSSProperties = {
  display: "inline-flex",
  gap: 2,
  padding: 2,
  background: "var(--surface-3)",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border-subtle)",
};

const segBtnStyle: CSSProperties = {
  border: "none",
  background: "transparent",
  color: "var(--text-secondary)",
  cursor: "default",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  fontWeight: 600,
  padding: "3px 11px",
  borderRadius: "calc(var(--radius-sm) - 2px)",
  transition: "background var(--motion-base), color var(--motion-base)",
};

const segBtnActiveStyle: CSSProperties = {
  background: "var(--accent)",
  color: "var(--accent-contrast, #0a0a0a)",
};

const kpiGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 10,
};

/* imbalance gauge */
const gaugeWrap: CSSProperties = {
  display: "grid",
  gap: 8,
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-2)",
  padding: "12px 14px",
};

const gaugeHeader: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const gaugeAskLabel: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  fontWeight: 700,
  color: "var(--negative)",
  fontVariantNumeric: "tabular-nums",
};

const gaugeBidLabel: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  fontWeight: 700,
  color: "var(--positive)",
  fontVariantNumeric: "tabular-nums",
};

const gaugeTrack: CSSProperties = {
  position: "relative",
  display: "flex",
  height: 16,
  borderRadius: 999,
  overflow: "hidden",
  background: "var(--surface-3)",
  border: "1px solid var(--border-subtle)",
};

const gaugeAskFill: CSSProperties = {
  height: "100%",
  background:
    "linear-gradient(90deg, color-mix(in srgb, var(--negative) 75%, transparent), color-mix(in srgb, var(--negative) 30%, transparent))",
  transition: "width var(--motion-base)",
};

const gaugeBidFill: CSSProperties = {
  height: "100%",
  background:
    "linear-gradient(90deg, color-mix(in srgb, var(--positive) 30%, transparent), color-mix(in srgb, var(--positive) 75%, transparent))",
  transition: "width var(--motion-base)",
};

const gaugeCenterTick: CSSProperties = {
  position: "absolute",
  top: 0,
  bottom: 0,
  left: "50%",
  width: 1,
  background: "var(--text-mute)",
  opacity: 0.6,
};

const gaugeMarker: CSSProperties = {
  position: "absolute",
  top: -3,
  bottom: -3,
  width: 0,
  transform: "translateX(-50%)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  transition: "left var(--motion-base)",
};

const gaugeMarkerDot: CSSProperties = {
  width: 3,
  height: "100%",
  borderRadius: 2,
  background: "var(--text-display)",
  boxShadow: "0 0 6px var(--accent)",
};

const gaugeCaption: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: 10,
  letterSpacing: "0.02em",
  fontFamily: "JetBrains Mono, monospace",
};

/* ladder */
const ladderWrap: CSSProperties = {
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-1)",
  overflow: "hidden",
};

const ladderHeadRow: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(96px, 1.1fr) minmax(80px, 0.9fr) minmax(0, 2.4fr)",
  alignItems: "center",
  gap: 8,
  padding: "6px 12px",
  background: "var(--surface-2)",
  borderBottom: "1px solid var(--border-subtle)",
};

const ladderHeadCell: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.07em",
};

const ladderHeadCellBar: CSSProperties = {
  ...ladderHeadCell,
  textAlign: "right",
};

const ladderSide: CSSProperties = {
  display: "grid",
};

const ladderRow: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(96px, 1.1fr) minmax(80px, 0.9fr) minmax(0, 2.4fr)",
  alignItems: "center",
  gap: 8,
  padding: "2px 12px",
  borderBottom:
    "1px solid color-mix(in srgb, var(--border-subtle) 50%, transparent)",
};

const ladderPrice: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontWeight: 700,
  fontSize: 12,
};

const ladderSize: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
  fontSize: 12,
  textAlign: "right",
};

const ladderBarCell: CSSProperties = {
  position: "relative",
  height: 18,
  display: "flex",
  alignItems: "center",
};

const ladderBarFill: CSSProperties = {
  height: 14,
  borderRadius: 2,
  transition: "width var(--motion-base)",
};

const ladderCumLabel: CSSProperties = {
  position: "absolute",
  right: 4,
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: 10,
  color: "var(--text-secondary)",
  pointerEvents: "none",
};

const spreadRow: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  padding: "6px 12px",
  background: "var(--surface-3)",
  borderTop: "1px solid var(--border-subtle)",
  borderBottom: "1px solid var(--border-subtle)",
};

const spreadMidStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "baseline",
  gap: 6,
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontWeight: 700,
  fontSize: 14,
  color: "var(--text-display)",
};

const spreadMidTag: CSSProperties = {
  fontSize: 9,
  fontWeight: 700,
  letterSpacing: "0.1em",
  color: "var(--text-mute)",
};

const spreadValStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: 11,
  color: "var(--text-secondary)",
};

const spreadBpsTag: CSSProperties = {
  padding: "1px 7px",
  borderRadius: 999,
  background: "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  color: "var(--accent)",
  fontSize: 10,
  fontWeight: 600,
};

/* shared */
const warningBox: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 30%, transparent)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
  display: "grid",
  gap: 4,
};

const warningList: CSSProperties = {
  margin: 0,
  paddingLeft: 18,
  fontSize: "var(--font-size-xs)",
};

const metaLabel: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
};

const methodologyBox: CSSProperties = {
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  padding: 12,
  background: "var(--surface-2)",
};

const methodText: CSSProperties = {
  margin: "6px 0 0",
  color: "var(--text-secondary)",
  lineHeight: 1.5,
  fontSize: 12,
};
