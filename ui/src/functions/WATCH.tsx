/**
 * WATCH — User-managed watchlist with live last/change% per symbol.
 *
 * Watchlist persists via the Round 16 preset filesystem (Tauri) or
 * localStorage (browser dev). Symbol prices come from the sidecar
 * `/api/quote/{symbol}` endpoint. Round 27+ also subscribes to the sidecar
 * websocket stream, which is backed by the same quote service.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChangeText,
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
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

  // Round 29 — Subscribe each watchlist symbol to the sidecar WS stream.
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
            style={{
              background: "transparent",
              border: "none",
              color: "var(--accent)",
              fontWeight: 700,
              cursor: "default",
              padding: 0,
              font: "inherit",
            }}
          >
            {r.symbol}
          </button>
        ),
      },
      {
        key: "label",
        header: "Tag",
        render: (r) =>
          r.label ? (
            <Pill tone="muted" withDot={false}>
              {r.label}
            </Pill>
          ) : (
            "—"
          ),
      },
      {
        key: "last",
        header: "Last",
        numeric: true,
        width: 100,
        render: (r) => {
          const p = prices[r.symbol];
          if (!p) return "—";
          if (p.error) return <span style={{ color: "var(--negative)" }}>err</span>;
          const tone = (p.change_pct ?? 0) >= 0 ? "positive" : "negative";
          return p.last != null ? (
            <span
              key={`${r.symbol}-last-${p.fetched_at}-${p.last}`}
              className={liveCellClass(tone)}
            >
              {p.last.toLocaleString(undefined, { maximumFractionDigits: 4 })}
            </span>
          ) : (
            "—"
          );
        },
      },
      {
        key: "change_pct",
        header: "Δ %",
        numeric: true,
        width: 90,
        render: (r) => {
          const p = prices[r.symbol];
          const tone = (p?.change_pct ?? 0) >= 0 ? "positive" : "negative";
          return (
            <span
              key={`${r.symbol}-change-${p?.fetched_at ?? 0}-${p?.change_pct ?? "na"}`}
              className={liveCellClass(tone, true)}
            >
              <ChangeText value={p?.change_pct ?? null} digits={2} suffix="%" />
            </span>
          );
        },
      },
      {
        key: "sparkline",
        header: "30D",
        width: 130,
        render: (r) => {
          const points = sparks[r.symbol] ?? [];
          return (
            <MiniSparkline
              key={`${r.symbol}-spark-${sparkMotionKey(points)}`}
              points={points}
              tone={(prices[r.symbol]?.change_pct ?? 0) >= 0 ? "positive" : "negative"}
            />
          );
        },
      },
      {
        key: "fetched_at",
        header: "Updated",
        width: 90,
        render: (r) => {
          const p = prices[r.symbol];
          return p ? formatAge(p.fetched_at) : "—";
        },
      },
      {
        key: "stream",
        header: "Stream",
        width: 80,
        render: (r) => {
          const status = prices[r.symbol]?.error ? "error" : streamStatus[r.symbol] ?? "connecting";
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
              <Pill tone={tone} withDot={status === "live"}>
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
              <span title={p.error} style={{ color: "var(--negative)" }}>
                quote error
              </span>
            );
          }
          return p?.source ?? "—";
        },
      },
      {
        key: "remove",
        header: "",
        width: 36,
        render: (r) => (
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => onRemove(r.symbol)}
            title={`Remove ${r.symbol}`}
            style={{ height: 18, fontSize: 10, padding: "0 6px" }}
          >
            ✕
          </button>
        ),
      },
    ],
    [prices, sparks, streamStatus, setFocusedTarget, onRemove],
  );

  return (
    <div className="showme-watch showme-watch-motion" style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="Watchlist"
          subtitle={`${rows.length} symbol(s) · refresh ${REFRESH_MS / 1000}s`}
          help={
            <div style={{ display: "grid", gap: 8 }}>
              <strong style={{ color: "var(--accent)", fontFamily: "JetBrains Mono, monospace" }}>
                WATCH · Live watchlist
              </strong>
              <span style={{ color: "var(--text-secondary)" }}>
                Add symbols such as AAPL or BTCUSDT, refresh live quotes, open a symbol by clicking it, and remove rows with the x button.
              </span>
              <span style={{ color: "var(--text-mute)" }}>
                Prices come from the quote endpoint. Provider failures are shown as err instead of template prices.
              </span>
            </div>
          }
          trailing={
            <FunctionControlGroup>
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
          <form
            className="showme-watch__composer"
            onSubmit={(e) => {
              e.preventDefault();
              onAdd();
            }}
            style={{ display: "flex", gap: 8, marginBottom: 12 }}
          >
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="add symbol — AAPL, BTCUSDT…"
              list="watch-symbol-options"
              style={{
                flex: 1,
                background: "var(--bg-elev-2)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-sm)",
                color: "var(--text-primary)",
                font: "inherit",
                fontSize: 12,
                padding: "0 10px",
                height: 26,
                fontFamily: "JetBrains Mono, monospace",
                textTransform: "uppercase",
              }}
            />
            <datalist id="watch-symbol-options">
              {suggestions.map((item) => (
                <option key={item} value={item} />
              ))}
            </datalist>
            <button type="submit" className="btn btn--accent" style={{ height: 26 }}>
              Add
            </button>
          </form>
          {lastRemoved ? (
            <div
              className="showme-watch__undo"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: 12,
                color: "var(--text-secondary)",
                fontSize: 12,
              }}
            >
              <span>Removed {lastRemoved.symbol}</span>
              <button
                type="button"
                className="btn btn--ghost"
                onClick={onUndoRemove}
                style={{ height: 22, padding: "0 8px" }}
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

function MiniSparkline({
  points,
  tone,
}: {
  points: SparkPoint[];
  tone: "positive" | "negative";
}) {
  if (points.length < 2) {
    return <span style={{ color: "var(--text-mute)" }}>—</span>;
  }
  const width = 108;
  const height = 28;
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const path = points
    .map((point, index) => {
      const x = (index / Math.max(1, points.length - 1)) * width;
      const y = height - ((point.value - min) / range) * height;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  const color = tone === "positive" ? "var(--positive)" : "var(--negative)";
  const last = points[points.length - 1];
  const lastX = width;
  const lastY = height - (((last?.value ?? min) - min) / range) * height;
  return (
    <span className="showme-sparkline-frame">
      <svg
        className="showme-sparkline"
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        role="img"
        aria-label={`${points.length} point price sparkline`}
        style={{ display: "block" }}
      >
        <path
          className="showme-sparkline__path"
          d={path}
          fill="none"
          pathLength={1}
          stroke={color}
          strokeWidth="1.6"
        />
        <circle
          className="showme-sparkline__dot"
          cx={lastX}
          cy={lastY}
          fill={color}
          r="2"
        />
      </svg>
    </span>
  );
}

function formatAge(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 1500) return "now";
  if (diff < 60_000) return `${Math.round(diff / 1000)}s`;
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m`;
  return `${Math.round(diff / 3_600_000)}h`;
}
