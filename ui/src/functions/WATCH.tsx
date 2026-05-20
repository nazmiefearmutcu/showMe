/**
 * WATCH — Bloomberg-grade live watchlist with inline sparklines.
 *
 * Each row is a dense quote line: symbol (accent link), tag, last (tabular),
 * delta chip, sparkline, age, stream pill, source, remove. Top KPI strip
 * surfaces #symbols / median Δ% / advancers / decliners. Sidecar `/api/quote`
 * polls every 30s; the WS stream overlays sub-second ticks.
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
import { fetchQuote, type QuoteSnapshot } from "@/lib/quotes";
import { subscribeQuote, type StreamStatus } from "@/lib/stream";
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

interface PriceSnapshot {
  symbol: string;
  last: number | null;
  prev: number | null;
  change_pct: number | null;
  fetched_at: number;
  source?: string;
  error?: string;
}

interface SparkPoint {
  time: string;
  value: number;
}

const REFRESH_MS = 30_000;
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
  const [prices, setPrices] = useState<Record<string, PriceSnapshot>>({});
  const [sparks, setSparks] = useState<Record<string, SparkPoint[]>>({});
  const [streamStatus, setStreamStatus] = useState<Record<string, StreamStatus>>({});
  const [draft, setDraft] = useState("");
  const [lastRemoved, setLastRemoved] = useState<WatchlistRow | null>(null);
  const [busy, setBusy] = useState(false);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);
  const sidecarStatus = useAppStore((s) => s.sidecarStatus);
  const sidecarReady = !isInTauri() || sidecarStatus === "healthy";
  const suggestions = useMemo(
    () => Array.from(new Set([...rows.map((r) => r.symbol), ...WATCH_SYMBOL_OPTIONS])).slice(0, 24),
    [rows],
  );
  const quoteErrorCount = useMemo(
    () => rows.filter((row) => Boolean(prices[row.symbol]?.error)).length,
    [prices, rows],
  );
  const liveStreamCount = useMemo(
    () =>
      rows.filter((row) => streamStatus[row.symbol] === "live" && !prices[row.symbol]?.error)
        .length,
    [prices, rows, streamStatus],
  );

  const summary = useMemo(() => {
    const changes: number[] = [];
    let advancers = 0;
    let decliners = 0;
    let unchanged = 0;
    for (const r of rows) {
      const c = prices[r.symbol]?.change_pct;
      if (c == null || !Number.isFinite(c)) continue;
      changes.push(c);
      if (c > 0) advancers += 1;
      else if (c < 0) decliners += 1;
      else unchanged += 1;
    }
    const sorted = [...changes].sort((a, b) => a - b);
    const median =
      sorted.length === 0
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
    };
  }, [prices, rows]);

  useEffect(() => {
    loadWatchlist().then(setRows);
  }, []);

  const refreshPrices = useCallback(async () => {
    if (rows.length === 0 || !sidecarReady) return;
    setBusy(true);
    try {
      const snapshots = await Promise.all(
        rows.map(async (r) => {
          try {
            const quote = await fetchQuote(r.symbol);
            return [r.symbol, quoteToPriceSnapshot(quote)] as const;
          } catch (err) {
            return [r.symbol, errorSnapshot(r.symbol, err)] as const;
          }
        }),
      );
      setPrices((prev) => {
        const next: Record<string, PriceSnapshot> = { ...prev };
        for (const [symbol, snap] of snapshots) {
          if (snap.error && next[symbol]?.last != null) continue;
          next[symbol] =
            snap.last == null && next[symbol]?.last != null ? next[symbol] : snap;
        }
        return next;
      });
      const sparkResults = await Promise.all(
        rows.map(async (r) => {
          try {
            return [r.symbol, await fetchSparkline(r.symbol)] as const;
          } catch {
            return [r.symbol, [] as SparkPoint[]] as const;
          }
        }),
      );
      setSparks((prev) => {
        const next: Record<string, SparkPoint[]> = { ...prev };
        for (const [symbol, points] of sparkResults) {
          if (points.length >= 2) next[symbol] = points;
        }
        return next;
      });
    } finally {
      setBusy(false);
    }
  }, [rows, sidecarReady]);

  useEffect(() => {
    refreshPrices();
    const id = setInterval(refreshPrices, REFRESH_MS);
    return () => clearInterval(id);
  }, [refreshPrices]);

  useEffect(() => {
    if (rows.length === 0 || !sidecarReady) return;
    const handles = rows.map((r) =>
      subscribeQuote(r.symbol, {
        onTick: (tick) => {
          setPrices((prev) => ({
            ...prev,
            [r.symbol]: {
              symbol: r.symbol,
              last: tick.price,
              prev: prev[r.symbol]?.prev ?? null,
              change_pct: tick.change_pct ?? prev[r.symbol]?.change_pct ?? null,
              fetched_at: Date.now(),
              source: tick.source,
            },
          }));
        },
        onStatus: (status) =>
          setStreamStatus((s) => ({ ...s, [r.symbol]: status })),
      }),
    );
    return () => {
      for (const h of handles) h.close();
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
    setPrices((p) => {
      const { [sym]: _gone, ...rest } = p;
      void _gone;
      return rest;
    });
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
          const p = prices[r.symbol];
          if (!p) return <span className="u-text-mute">—</span>;
          if (p.error)
            return <span className="u-text-negative">err</span>;
          const tone = (p.change_pct ?? 0) >= 0 ? "positive" : "negative";
          return p.last != null ? (
            <span
              key={`${r.symbol}-last-${p.fetched_at}-${p.last}`}
              className={liveCellClass(tone)}
            >
              {/* Adaptive precision: keeps sub-dollar prices readable. */}
              {formatPrice(p.last)}
            </span>
          ) : (
            <span className="u-text-mute">{formatMissing}</span>
          );
        },
      },
      {
        key: "change_pct",
        header: "Δ %",
        numeric: true,
        width: 96,
        render: (r) => {
          const c = prices[r.symbol]?.change_pct;
          if (c == null || !Number.isFinite(c))
            return <span className="u-text-mute">—</span>;
          return (
            <span
              key={`${r.symbol}-change-${prices[r.symbol]?.fetched_at ?? 0}-${c}`}
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
          const c = prices[r.symbol]?.change_pct ?? 0;
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
        width: 80,
        render: (r) => {
          const p = prices[r.symbol];
          if (!p) return <span className="u-text-mute">—</span>;
          return (
            <span className="u-mono-xs u-text-secondary">{formatAge(p.fetched_at)}</span>
          );
        },
      },
      {
        key: "stream",
        header: "Stream",
        width: 84,
        render: (r) => {
          const status = prices[r.symbol]?.error
            ? "error"
            : streamStatus[r.symbol] ?? "connecting";
          const tone =
            status === "live"
              ? "positive"
              : status === "offline"
                ? "muted"
                : status === "error"
                  ? "negative"
                  : "warn";
          return (
            <span className={`showme-watch__stream showme-watch__stream--${status}`}>
              <Pill tone={tone} variant="soft" withDot={status === "live"}>
                {status}
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
          const p = prices[r.symbol];
          if (p?.error) {
            return (
              <span title={p.error} className="u-text-negative u-text-11">
                quote err
              </span>
            );
          }
          return (
            <span className="u-text-secondary u-text-11">{p?.source ?? "—"}</span>
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
    [prices, sparks, streamStatus, setFocusedTarget, onRemove],
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
                Prices come from the quote endpoint. Provider failures are shown as err instead of template prices.
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
                onClick={() => refreshPrices()}
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
                value={formatPercent(summary.median, { signed: true })}
                caption={`${summary.sampled} sampled`}
                tone={medianTone}
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
          ) : Object.keys(prices).length === 0 ? (
            <Skeleton height={120} />
          ) : (
            <DataGrid
              className="showme-watch__grid showme-motion-grid"
              columns={cols}
              rows={rows}
              rowKey={(r) => r.symbol}
              rowClassName={(r, idx) =>
                [
                  "showme-motion-grid__row",
                  "showme-row-reveal",
                  `showme-motion-grid__row--${Math.min(idx, 10)}`,
                  prices[r.symbol]?.error ? "showme-motion-grid__row--error" : "",
                  streamStatus[r.symbol] === "live" ? "showme-motion-grid__row--live" : "",
                ].filter(Boolean).join(" ")
              }
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

function errorSnapshot(symbol: string, err: unknown): PriceSnapshot {
  return {
    symbol,
    last: null,
    prev: null,
    change_pct: null,
    fetched_at: Date.now(),
    error: err instanceof Error ? err.message : String(err),
  };
}

function quoteToPriceSnapshot(quote: QuoteSnapshot): PriceSnapshot {
  return {
    symbol: quote.symbol,
    last: quote.last,
    prev: quote.previous_close ?? null,
    change_pct: quote.change_pct ?? null,
    fetched_at: Date.parse(quote.fetched_at) || Date.now(),
    source: quote.source,
  };
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

function formatAge(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 1500) return "now";
  if (diff < 60_000) return `${Math.round(diff / 1000)}s`;
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m`;
  return `${Math.round(diff / 3_600_000)}h`;
}
