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

export const usePortfolioStore = create<PortfolioStoreShape>((set, get) => ({
  groups: [],
  totals: {},
  loading: false,
  error: null,
  lastFetchedAt: null,
  selectedCredentialIds: null,
  includeOrders: false,

  loadPortfolio: async () => {
    set({ loading: true, error: null });
    const params = new URLSearchParams();
    if (get().selectedCredentialIds) {
      params.set("credential_ids", get().selectedCredentialIds!.join(","));
    }
    if (get().includeOrders) params.set("include_orders", "true");
    const qs = params.toString();
    const path = qs ? `/api/portfolio/aggregate?${qs}` : "/api/portfolio/aggregate";
    try {
      const body = await sidecarFetch<PortfolioPayload>(path);
      set({
        groups: body.groups,
        totals: body.totals ?? {},
        lastFetchedAt: body.as_of,
        loading: false,
      });
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : String(e) });
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
