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
  type WatchlistRow,
} from "@/lib/watchlist";
import { fetchQuote, type QuoteSnapshot } from "@/lib/quotes";
import { subscribeQuote, type StreamStatus } from "@/lib/stream";
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

const REFRESH_MS = 30_000;

export function WATCHPane({ code }: FunctionPaneProps) {
  const [rows, setRows] = useState<WatchlistRow[]>([]);
  const [prices, setPrices] = useState<Record<string, PriceSnapshot>>({});
  const [streamStatus, setStreamStatus] = useState<Record<string, StreamStatus>>({});
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);
  const sidecarStatus = useAppStore((s) => s.sidecarStatus);
  const sidecarReady = !isInTauri() || sidecarStatus === "healthy";

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
  };

  const onRemove = async (sym: string) => {
    setRows(await removeSymbol(sym));
    setPrices((p) => {
      const { [sym]: _gone, ...rest } = p;
      void _gone;
      return rest;
    });
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
          return p.last != null ? p.last.toLocaleString(undefined, { maximumFractionDigits: 4 }) : "—";
        },
      },
      {
        key: "change_pct",
        header: "Δ %",
        numeric: true,
        width: 90,
        render: (r) => {
          const p = prices[r.symbol];
          return <ChangeText value={p?.change_pct ?? null} digits={2} suffix="%" />;
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
          const status = streamStatus[r.symbol] ?? "connecting";
          const tone =
            status === "live"
              ? "positive"
              : status === "offline"
                ? "muted"
                : status === "error"
                  ? "negative"
                  : "warn";
          return (
            <Pill tone={tone} withDot={status === "live"}>
              {status}
            </Pill>
          );
        },
      },
      {
        key: "source",
        header: "Source",
        width: 96,
        render: (r) => prices[r.symbol]?.source ?? "—",
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
    [prices, streamStatus, setFocusedTarget],
  );

  return (
    <div style={{ padding: 18, height: "100%" }}>
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
            <button type="submit" className="btn btn--accent" style={{ height: 26 }}>
              Add
            </button>
          </form>

          {rows.length === 0 ? (
            <Empty title="Empty watchlist" body="Add a symbol above to start." />
          ) : Object.keys(prices).length === 0 ? (
            <Skeleton height={120} />
          ) : (
            <DataGrid
              columns={cols}
              rows={rows}
              rowKey={(r) => r.symbol}
              density="compact"
            />
          )}
        </PaneBody>
        <PaneFooter>
          <span>polling quote · {REFRESH_MS / 1000}s</span>
          <span>
            ws · {Object.values(streamStatus).filter((s) => s === "live").length}
            /{rows.length} live
          </span>
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

function formatAge(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 1500) return "now";
  if (diff < 60_000) return `${Math.round(diff / 1000)}s`;
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m`;
  return `${Math.round(diff / 3_600_000)}h`;
}
