/**
 * WATCH — Bloomberg-grade live watchlist with inline sparklines.
 *
 * Each row is a dense quote line: symbol (accent link), tag, last (tabular),
 * delta chip, sparkline, age, stream pill, source, remove. Top KPI strip
 * surfaces #symbols / median Δ% / advancers / decliners.
 *
 * S02 — quote+stream lifecycle now lives in `lib/market-data`. WATCH no longer
 * owns bespoke polling, WebSocket subscription, or per-symbol state shapes.
 * It consumes `useLiveQuotes(symbols)`, which preserves last-good snapshots
 * across refreshes, exposes `connecting / live / stale / reconnecting /
 * offline / error` transport states, and tears sockets/timers down cleanly on
 * symbol change. Sparkline fetch stays local — S03 owns the chart contract.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
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
} from "@/design-system";
import {
  addSymbol,
  loadWatchlist,
  removeSymbol,
  saveWatchlist,
  type WatchlistRow,
} from "@/lib/watchlist";
import { useLiveQuotes, type TransportState } from "@/lib/market-data";
import { sidecarFetch } from "@/lib/sidecar";
import { inferAssetClassName } from "@/lib/symbols";
import { useAppStore } from "@/lib/store";
import { isInTauri } from "@/lib/tauri";
import { useWorkspace } from "@/lib/workspace";
import { navigate } from "@/lib/router";
import { formatMissing, formatPercent, formatPrice } from "@/lib/format";
import {
  formatTime as formatTzTime,
  readTimezone as readTzId,
  timezoneOffsetLabel as tzOffset,
} from "@/lib/timezone";
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface SparkPoint {
  time: string;
  value: number;
}

const REFRESH_MS = 30_000;
/**
 * Beyond this freshness threshold the row shows a STALE badge + Refresh
 * button instead of an ever-growing "10m · stale" / "1h · stale" string.
 * Pre-QA the duration grew without bound; the user is asked to refresh once
 * we've crossed the cliff.
 */
const STALE_CAP_MS = 5 * 60_000;
const WATCH_SYMBOL_OPTIONS = [
  "AAPL",
  "MSFT",
  "NVDA",
  "TSLA",
  "SPY",
  "QQQ",
  "BTCUSDT",
  "ETHUSDT",
  "SOLUSDT",
  "EURUSD",
  "GBPUSD=X",
  "GC=F",
  "CL=F",
  "BZ=F",
  "US10Y",
];

export function WATCHPane({ code }: FunctionPaneProps) {
  const [rows, setRows] = useState<WatchlistRow[]>([]);
  const [sparks, setSparks] = useState<Record<string, SparkPoint[]>>({});
  const [draft, setDraft] = useState("");
  const [lastRemoved, setLastRemoved] = useState<WatchlistRow | null>(null);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);
  const sidecarStatus = useAppStore((s) => s.sidecarStatus);
  const sidecarReady = !isInTauri() || sidecarStatus === "healthy";

  const watchedSymbols = useMemo(() => rows.map((r) => r.symbol), [rows]);
  const quotes = useLiveQuotes(watchedSymbols, {
    enabled: sidecarReady,
    pollMs: REFRESH_MS,
  });

  const refetch = useCallback(() => {
    const first = Object.values(quotes)[0];
    first?.refetch();
  }, [quotes]);

  const busy = useMemo(
    () => Object.values(quotes).some((v) => v.loading || v.refreshing),
    [quotes],
  );
  const quoteErrorCount = useMemo(
    () => Object.values(quotes).filter((v) => Boolean(v.error) && v.price == null).length,
    [quotes],
  );
  const liveStreamCount = useMemo(
    () =>
      Object.values(quotes).filter(
        // QA-2026-05-24 (A12): align header/footer counters with the per-row
        // pill rule — only count rows with both a live transport AND a price
        // payload. Otherwise KPI says "LIVE · 1" while every row reads idle.
        (v) => v.transportState === "live" && !v.error && v.price != null,
      ).length,
    [quotes],
  );

  const suggestions = useMemo(
    () => Array.from(new Set([...rows.map((r) => r.symbol), ...WATCH_SYMBOL_OPTIONS])).slice(0, 24),
    [rows],
  );

  const summary = useMemo(() => {
    const changes: number[] = [];
    let advancers = 0;
    let decliners = 0;
    let unchanged = 0;
    let completed = 0;
    for (const r of rows) {
      const view = quotes[r.symbol];
      // QA-2026-05-23: median was computed mid-flight, so the UI flashed
      // "MEDIAN Δ% -3.28% (1 SAMPLED)" before the other 6 fetches resolved.
      // Treat a row as completed only once its first fetch has settled.
      const settled = Boolean(view && !view.loading && (view.snapshot || view.lastTick || view.error));
      if (settled) completed += 1;
      if (!view) continue;
      const c = view.changePct;
      if (c == null || !Number.isFinite(c)) continue;
      changes.push(c);
      if (c > 0) advancers += 1;
      else if (c < 0) decliners += 1;
      else unchanged += 1;
    }
    const total = rows.length;
    const allCompleted = total > 0 && completed === total;
    const sorted = [...changes].sort((a, b) => a - b);
    const median =
      !allCompleted
        ? null
        : sorted.length === 0
          ? null
          : sorted.length % 2 === 1
            ? sorted[Math.floor(sorted.length / 2)]
            : (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2;
    return {
      median,
      advancers,
      decliners,
      unchanged,
      sampled: changes.length,
      completed,
      total,
      allCompleted,
    };
  }, [quotes, rows]);

  useEffect(() => {
    loadWatchlist().then(setRows);
  }, []);

  // Sparkline fetch — small historical preview, intentionally separate from
  // the live quote layer. S03 will fold this into the chart-series contract.
  useEffect(() => {
    if (rows.length === 0 || !sidecarReady) return;
    let cancelled = false;
    void (async () => {
      const results = await Promise.all(
        rows.map(async (r) => {
          try {
            return [r.symbol, await fetchSparkline(r.symbol)] as const;
          } catch {
            return [r.symbol, [] as SparkPoint[]] as const;
          }
        }),
      );
      if (cancelled) return;
      setSparks((prev) => {
        const next: Record<string, SparkPoint[]> = { ...prev };
        for (const [symbol, points] of results) {
          if (points.length >= 2) next[symbol] = points;
        }
        return next;
      });
    })();
    return () => {
      cancelled = true;
    };
  }, [rows, sidecarReady]);

  const onAdd = async () => {
    const sym = draft.trim().toUpperCase();
    if (!sym) return;
    setRows(await addSymbol(sym));
    setDraft("");
    setLastRemoved(null);
  };

  const onRemove = useCallback(async (sym: string) => {
    const row = rows.find((r) => r.symbol === sym) ?? { symbol: sym };
    setRows(await removeSymbol(sym));
    setLastRemoved(row);
    setSparks((p) => {
      const { [sym]: _gone, ...rest } = p;
      void _gone;
      return rest;
    });
  }, [rows]);

  const onUndoRemove = async () => {
    if (!lastRemoved) return;
    const current = await loadWatchlist();
    if (current.some((r) => r.symbol === lastRemoved.symbol)) {
      setRows(current);
      setLastRemoved(null);
      return;
    }
    const next = [...current, lastRemoved];
    await saveWatchlist(next);
    setRows(next);
    setLastRemoved(null);
  };

  const cols = useMemo<DataGridColumn<WatchlistRow>[]>(
    () => [
      {
        key: "symbol",
        header: "Symbol",
        width: 110,
        render: (r) => (
          <button
            type="button"
            onClick={() => {
              setFocusedTarget("DES", r.symbol);
              navigate(`/symbol/${r.symbol}/DES`);
            }}
            className="u-symbol-link"
          >
            {r.symbol}
          </button>
        ),
      },
      {
        key: "label",
        header: "Tag",
        width: 90,
        render: (r) =>
          r.label ? (
            <Pill tone="muted" variant="soft" withDot={false}>
              {r.label}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
      {
        key: "last",
        header: "Last",
        numeric: true,
        width: 110,
        render: (r) => {
          const view = quotes[r.symbol];
          if (!view) return <span className="u-text-mute">—</span>;
          if (view.error && view.price == null)
            return <span className="u-text-negative">err</span>;
          if (view.price == null)
            return <span className="u-text-mute">{formatMissing}</span>;
          const tone = (view.changePct ?? 0) >= 0 ? "positive" : "negative";
          return (
            <span
              key={`${r.symbol}-last-${view.fetchedAt ?? 0}-${view.price}`}
              className={liveCellClass(tone)}
            >
              {/* Adaptive precision: keeps sub-dollar prices readable. */}
              {formatPrice(view.price)}
            </span>
          );
        },
      },
      {
        key: "change_pct",
        header: "Δ %",
        numeric: true,
        width: 96,
        render: (r) => {
          const c = quotes[r.symbol]?.changePct;
          if (c == null || !Number.isFinite(c))
            return <span className="u-text-mute">—</span>;
          return (
            <span
              key={`${r.symbol}-change-${quotes[r.symbol]?.fetchedAt ?? 0}-${c}`}
            >
              <DeltaChip value={c} format="percent" fractionDigits={2} />
            </span>
          );
        },
      },
      {
        key: "sparkline",
        header: "Trend",
        width: 96,
        render: (r) => {
          const points = sparks[r.symbol] ?? [];
          if (points.length < 2)
            return <span className="u-text-mute">—</span>;
          const c = quotes[r.symbol]?.changePct ?? 0;
          const tone: "positive" | "negative" | "neutral" =
            c > 0 ? "positive" : c < 0 ? "negative" : "neutral";
          return (
            <span key={`${r.symbol}-spark-${sparkMotionKey(points)}`}>
              <Sparkline
                values={points.map((p) => p.value)}
                width={80}
                height={22}
                tone={tone}
              />
            </span>
          );
        },
      },
      {
        key: "fetched_at",
        header: "Updated",
        width: 110,
        render: (r) => {
          const view = quotes[r.symbol];
          if (!view) return <span className="u-text-mute">—</span>;
          if (view.fetchedAt == null)
            return <span className="u-text-mute">—</span>;
          // QA-2026-05-23: cap the "Xm · stale" stamp at 5 minutes. Past that
          // we stop counting up forever and present a STALE chip + a per-row
          // Refresh affordance instead.
          const freshness = view.freshnessMs ?? 0;
          if (freshness >= STALE_CAP_MS) {
            return (
              <span
                className="showme-watch__stale-cap"
                data-testid={`watch-row-stale-${r.symbol}`}
              >
                <Pill tone="warn" variant="soft" withDot={false}>
                  STALE
                </Pill>
                <button
                  type="button"
                  className="btn btn--ghost watch-row-refresh"
                  onClick={() => view.refetch()}
                  data-testid={`watch-row-refresh-${r.symbol}`}
                  title={`Refresh ${r.symbol}`}
                  aria-label={`Refresh ${r.symbol}`}
                >
                  ↻
                </button>
              </span>
            );
          }
          return (
            <span className="u-mono-xs u-text-secondary">
              {formatFreshness(freshness)}
              {view.stale ? " · stale" : ""}
            </span>
          );
        },
      },
      {
        key: "stream",
        header: "Stream",
        width: 92,
        render: (r) => {
          const view = quotes[r.symbol];
          // QA-2026-05-24 (A12): pill was painting "live" for rows whose
          // socket reported `live` but had no price payload yet — the header
          // KPI said "LIVE · 1", footer "ws · 1/7", but every row glowed
          // green. A row is only truly live when transport reports `live`
          // AND we have a price tick to back it up. Otherwise fall through
          // to "snapshot" (snapshot fetch landed) or "idle" (nothing yet).
          let state: TransportState | "error" | "snapshot";
          if (view?.error && view.price == null) {
            state = "error";
          } else if (view?.transportState === "live" && view.price != null) {
            state = "live";
          } else if (view?.price != null) {
            state = "snapshot";
          } else if (view?.transportState === "live") {
            // Transport says live but no price yet — demote to "connecting"
            // so the row stops glowing green ahead of real data.
            state = "connecting";
          } else {
            state = view?.transportState ?? "idle";
          }
          const { tone, label, withDot } = streamPillStyling(state);
          return (
            <span className={`showme-watch__stream showme-watch__stream--${state}`}>
              <Pill tone={tone} variant="soft" withDot={withDot}>
                {label}
              </Pill>
            </span>
          );
        },
      },
      {
        key: "source",
        header: "Source",
        width: 96,
        render: (r) => {
          const view = quotes[r.symbol];
          if (!view) {
            return <span className="u-text-mute u-text-11">—</span>;
          }
          if (view.error && view.price == null) {
            return (
              <span title={view.error} className="u-text-negative u-text-11">
                quote err
              </span>
            );
          }
          return (
            <span
              className="u-text-secondary u-text-11"
              title={view.sourceKind === "tick" ? "live tick overlay" : "snapshot fetch"}
            >
              {view.source ?? "—"}
              {view.sourceKind === "tick" ? " · live" : ""}
            </span>
          );
        },
      },
      {
        key: "remove",
        header: "",
        width: 36,
        render: (r) => (
          <button
            type="button"
            className="btn btn--ghost watch-remove-btn"
            onClick={() => onRemove(r.symbol)}
            title={`Remove ${r.symbol}`}
          >
            ✕
          </button>
        ),
      },
    ],
    [quotes, sparks, setFocusedTarget, onRemove],
  );

  const utcNow = formatTzTime(new Date()) + " " + tzOffset(readTzId(), new Date());
  const medianTone: "positive" | "negative" | "neutral" =
    summary.median == null
      ? "neutral"
      : summary.median > 0
        ? "positive"
        : summary.median < 0
          ? "negative"
          : "neutral";

  const hasAnyData = rows.length > 0 && Object.values(quotes).some(
    (v) => v.snapshot != null || v.lastTick != null,
  );

  return (
    <div className="showme-watch showme-watch-motion port-pane-host">
      <h2 className="u-sr-only">{code} — Watchlist</h2>
      <Pane>
        <PaneHeader
          code={code}
          title="Watchlist"
          subtitle={`${rows.length} symbol(s) · refresh ${REFRESH_MS / 1000}s`}
          help={
            <div className="fn-help-grid">
              <strong>WATCH · Live watchlist</strong>
              <span className="fn-help-grid__hint">
                Add symbols such as AAPL or BTCUSDT, refresh live quotes, open a symbol by clicking it, and remove rows with the x button.
              </span>
              <span className="fn-help-grid__hint-mute">
                Prices come from the canonical market-data layer (snapshot + tick overlay). Provider failures are shown as err instead of template prices.
              </span>
            </div>
          }
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} sym
              </Pill>
              <Pill
                tone={liveStreamCount > 0 ? "positive" : "muted"}
                variant="soft"
                withDot={liveStreamCount > 0}
              >
                {liveStreamCount > 0 ? `LIVE · ${liveStreamCount}` : "OFFLINE"}
              </Pill>
              <LoadStatePill state={busy ? "loading" : rows.length ? "ok" : "idle"} />
              <RefreshButton
                loading={busy}
                onClick={refetch}
                disabled={rows.length === 0}
                title="Refresh watchlist prices"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          {/* Top KPI strip */}
          {rows.length > 0 ? (
            <div className="watch-kpi-strip">
              <h3 className="u-sr-only">Watchlist KPIs</h3>
              <StatCard
                label="Symbols"
                value={String(rows.length)}
                caption={`AS OF ${utcNow}`}
                tone="neutral"
              />
              <StatCard
                label="Median Δ%"
                value={
                  summary.allCompleted
                    ? formatPercent(summary.median, { signed: true })
                    : "—"
                }
                caption={
                  summary.allCompleted
                    ? `${summary.sampled} sampled`
                    : `computing · ${summary.completed}/${summary.total}`
                }
                tone={summary.allCompleted ? medianTone : "neutral"}
              />
              <StatCard
                label="Advancers"
                value={String(summary.advancers)}
                caption={`${summary.unchanged} flat`}
                tone={summary.advancers > summary.decliners ? "positive" : "neutral"}
              />
              <StatCard
                label="Decliners"
                value={String(summary.decliners)}
                caption={`live · ${liveStreamCount}/${rows.length}`}
                tone={summary.decliners > summary.advancers ? "negative" : "neutral"}
              />
            </div>
          ) : null}

          {/* Composer */}
          <form
            className="showme-watch__composer watch-composer"
            onSubmit={(e) => {
              e.preventDefault();
              onAdd();
            }}
          >
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="add symbol — AAPL, BTCUSDT…"
              list="watch-symbol-options"
              className="watch-composer__input"
            />
            <datalist id="watch-symbol-options">
              {suggestions.map((item) => (
                <option key={item} value={item} />
              ))}
            </datalist>
            <button type="submit" className="btn btn--accent u-btn-26">
              Add
            </button>
          </form>
          {lastRemoved ? (
            <div className="showme-watch__undo watch-undo">
              <span>Removed {lastRemoved.symbol}</span>
              <button
                type="button"
                className="btn btn--ghost watch-undo__btn"
                onClick={onUndoRemove}
              >
                Undo
              </button>
            </div>
          ) : null}

          {rows.length === 0 ? (
            <Empty title="Empty watchlist" body="Add a symbol above to start." />
          ) : !hasAnyData ? (
            <Skeleton height={120} />
          ) : (
            <DataGrid
              className="showme-watch__grid showme-motion-grid"
              columns={cols}
              rows={rows}
              rowKey={(r) => r.symbol}
              rowClassName={(r, idx) => {
                const view = quotes[r.symbol];
                const hasError = Boolean(view?.error) && view?.price == null;
                // QA-2026-05-24 (A12): "live" row class also requires price
                // data — keeps row-glow in lockstep with the pill.
                const live = view?.transportState === "live" && view?.price != null;
                return [
                  "showme-motion-grid__row",
                  "showme-row-reveal",
                  `showme-motion-grid__row--${Math.min(idx, 10)}`,
                  hasError ? "showme-motion-grid__row--error" : "",
                  live ? "showme-motion-grid__row--live" : "",
                ].filter(Boolean).join(" ");
              }}
              density="compact"
            />
          )}
        </PaneBody>
        <PaneFooter>
          <span>polling quote · {REFRESH_MS / 1000}s</span>
          <span>
            ws · {liveStreamCount}
            /{rows.length} live
          </span>
          {quoteErrorCount > 0 ? <span>errors · {quoteErrorCount}</span> : null}
          <span>{busy ? "refreshing…" : "idle"}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function formatFreshness(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1500) return "now";
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`;
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m`;
  return `${Math.round(ms / 3_600_000)}h`;
}

function streamPillStyling(state: TransportState | "error" | "snapshot"): {
  tone: "positive" | "negative" | "muted" | "warn" | "accent";
  label: string;
  withDot: boolean;
} {
  switch (state) {
    case "live":
      return { tone: "positive", label: "live", withDot: true };
    case "snapshot":
      // Snapshot fetched but no live tick yet — neutral, not green.
      return { tone: "muted", label: "snapshot", withDot: false };
    case "stale":
      return { tone: "warn", label: "stale", withDot: false };
    case "reconnecting":
      return { tone: "warn", label: "retry", withDot: false };
    case "connecting":
      return { tone: "warn", label: "connecting", withDot: false };
    case "offline":
      return { tone: "muted", label: "offline", withDot: false };
    case "error":
      return { tone: "negative", label: "error", withDot: false };
    case "idle":
    default:
      return { tone: "muted", label: "idle", withDot: false };
  }
}

async function fetchSparkline(symbol: string): Promise<SparkPoint[]> {
  const qs = new URLSearchParams({
    symbol,
    asset_class: inferAssetClassName(symbol),
    days: "45",
    range: "1M",
    interval: "1d",
    bars: "90",
  });
  const payload = await sidecarFetch<{
    data?: {
      ohlcv?: Array<Record<string, unknown>>;
      bars?: Array<Record<string, unknown>>;
      rows?: Array<Record<string, unknown>>;
    };
  }>(`/api/fn/GP?${qs.toString()}`);
  const rows = payload.data?.ohlcv ?? payload.data?.bars ?? payload.data?.rows ?? [];
  return rows
    .map((row) => {
      const rawValue = row.close ?? row.value ?? row.price;
      const value = typeof rawValue === "number" ? rawValue : Number(rawValue);
      const rawTime = row.date ?? row.time ?? row.ts;
      const time = typeof rawTime === "string" ? rawTime.slice(0, 10) : "";
      return Number.isFinite(value) && time ? { time, value } : null;
    })
    .filter((point): point is SparkPoint => Boolean(point))
    .slice(-36);
}

function sparkMotionKey(points: SparkPoint[]): string {
  const last = points[points.length - 1];
  return last ? `${points.length}-${last.time}-${last.value}` : "empty";
}

function liveCellClass(tone: "positive" | "negative", compact = false): string {
  return [
    "showme-live-value",
    "showme-live-cell",
    "is-showme-updated",
    compact ? "showme-live-value--compact" : "",
    `showme-live-value--${tone}`,
    `showme-live-cell--${tone === "positive" ? "up" : "down"}`,
  ].filter(Boolean).join(" ");
}
