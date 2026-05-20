/**
 * Read-only state.api wrappers — talk to Round 25's `/api/state/*`
 * endpoints over the Faz B portfolio.db. The native TRAN pane lives on
 * `listTrades`; PORT and the welcome card both consume `listPositions`.
 */
import { sidecarFetch } from "./sidecar";

export interface StatePosition {
  id: number;
  symbol: string;
  side: "LONG" | "SHORT" | string;
  quantity?: number;
  entry_price?: number;
  current_price?: number;
  unrealized_pnl?: number;
  realized_pnl?: number;
  leverage?: number;
  stop_loss?: number;
  take_profit?: number;
  trailing_stop_price?: number;
  opened_at?: string;
  mode?: string;
  imported_at?: string;
  source?: string;
  raw?: Record<string, unknown>;
}

export interface StateTrade {
  id: number;
  trade_id?: string;
  symbol: string;
  side: "LONG" | "SHORT" | string;
  quantity?: number;
  entry_price?: number;
  exit_price?: number;
  realized_pnl?: number;
  opened_at?: string;
  closed_at?: string;
  mode?: string;
  imported_at?: string;
  source?: string;
  raw?: Record<string, unknown>;
}

export interface StateMigration {
  id: number;
  source: string;
  started_at: string;
  finished_at?: string;
  summary?: Record<string, unknown>;
}

interface StateRead<T> {
  rows: T[];
  total: number;
  source: string;
}

async function get<T>(path: string): Promise<StateRead<T>> {
  // Routed through sidecarFetch so the auth token (X-ShowMe-Token) and the
  // shared port-discovery / health-wait pipeline both apply. See ARCH-05.
  return sidecarFetch<StateRead<T>>(path);
}

export const listPositions = (): Promise<StateRead<StatePosition>> =>
  get<StatePosition>("/api/state/positions");

export const listTrades = (params?: {
  limit?: number;
  symbol?: string;
}): Promise<StateRead<StateTrade>> => {
  const qs = new URLSearchParams();
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.symbol) qs.set("symbol", params.symbol.toUpperCase());
  return get<StateTrade>(`/api/state/trades${qs.size ? `?${qs}` : ""}`);
};

export const listMigrations = (
  limit = 50,
): Promise<StateRead<StateMigration>> =>
  get<StateMigration>(`/api/state/migrations?limit=${limit}`);
