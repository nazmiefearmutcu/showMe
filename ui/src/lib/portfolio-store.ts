/**
 * Portfolio aggregation store. Backed by /api/portfolio/aggregate.
 *
 * Companion to exchange-store: exchange-store owns the catalog +
 * credential list (vault); portfolio-store owns the live read snapshot.
 */
import { create } from "zustand";
import { sidecarFetch } from "./sidecar";

export interface PortfolioPosition {
  symbol: string;
  side: string;
  quantity: number;
  entry_price?: number | null;
  current_price?: number | null;
  unrealized_pnl?: number | null;
}

export interface PortfolioGroup {
  credential_id: string;
  exchange_id: string;
  account_label: string;
  permissions: string[];
  account: {
    cash: number;
    equity: number;
    buying_power: number;
    currency: string;
  } | null;
  positions: PortfolioPosition[];
  orders: unknown[];
  error: string | null;
}

export interface PortfolioTotals {
  equity_by_currency?: Record<string, number>;
  stable_usd_equivalent?: number;
}

export interface PortfolioPayload {
  as_of: string;
  groups: PortfolioGroup[];
  totals: PortfolioTotals;
}

interface PortfolioStoreShape {
  groups: PortfolioGroup[];
  totals: PortfolioTotals;
  loading: boolean;
  error: string | null;
  lastFetchedAt: string | null;
  selectedCredentialIds: string[] | null;
  includeOrders: boolean;

  loadPortfolio: () => Promise<void>;
  setSelectedCredentialIds: (ids: string[] | null) => Promise<void>;
  setIncludeOrders: (v: boolean) => Promise<void>;
}

// Module-scoped abort plumbing for cascade-reload protection. Bursts of
// credential-toggle clicks (or include-orders flips) used to fan out N
// concurrent fan-outs to /api/portfolio/aggregate where the LAST one to
// resolve over-wrote the user's actual final selection. Now every new
// loadPortfolio aborts whatever is in flight.
let _loadCtl: AbortController | null = null;
let _pendingReload = false;

export const usePortfolioStore = create<PortfolioStoreShape>((set, get) => ({
  groups: [],
  totals: {},
  loading: false,
  error: null,
  lastFetchedAt: null,
  selectedCredentialIds: null,
  includeOrders: false,

  loadPortfolio: async () => {
    // CRITICAL FIX (audit S3): coalesce concurrent loads. If one is already
    // in flight, abort it AND queue a single "do once more" trailing call so
    // the latest selection still wins without spawning N parallel fetches.
    if (_loadCtl) {
      _loadCtl.abort();
      _pendingReload = true;
    }
    const ctl = new AbortController();
    _loadCtl = ctl;

    set({ loading: true, error: null });
    const params = new URLSearchParams();
    const selected = get().selectedCredentialIds;
    if (selected) {
      params.set("credential_ids", selected.join(","));
    }
    if (get().includeOrders) params.set("include_orders", "true");
    const qs = params.toString();
    const path = qs ? `/api/portfolio/aggregate?${qs}` : "/api/portfolio/aggregate";
    try {
      const body = await sidecarFetch<PortfolioPayload>(path, { signal: ctl.signal });
      // If we were aborted while awaiting, do not overwrite newer state.
      if (ctl.signal.aborted) return;
      set({
        groups: body.groups,
        totals: body.totals ?? {},
        lastFetchedAt: body.as_of,
        loading: false,
      });
    } catch (e) {
      if (ctl.signal.aborted) return; // swallow abort — newer load owns state
      const message = e instanceof Error ? e.message : String(e);
      // Treat fetch-level AbortError defensively (older fetch polyfills throw
      // DOMException with name "AbortError" instead of honoring signal.aborted).
      if (e instanceof Error && (e.name === "AbortError" || /aborted/i.test(message))) {
        return;
      }
      set({ loading: false, error: message });
    } finally {
      if (_loadCtl === ctl) _loadCtl = null;
      // If a setter fired while we were in flight, run one trailing reload
      // with the absolute-latest selection. Drop any further pending flag so
      // we never queue more than one trailing call.
      if (_pendingReload && _loadCtl == null) {
        _pendingReload = false;
        // Tail-call style: do NOT await to avoid awaiting our own caller.
        void get().loadPortfolio();
      }
    }
  },

  setSelectedCredentialIds: async (ids) => {
    set({ selectedCredentialIds: ids });
    await get().loadPortfolio();
  },

  setIncludeOrders: async (v) => {
    set({ includeOrders: v });
    await get().loadPortfolio();
  },
}));
