import { sidecarFetch } from "./sidecar";

export interface QuoteSnapshot {
  symbol: string;
  asset_class: "CRYPTO" | "EQUITY" | string;
  last: number;
  price: number;
  previous_close: number | null;
  previousClose?: number | null;
  change_pct: number | null;
  regularMarketChangePercent?: number | null;
  volume: number | null;
  bid: number | null;
  ask: number | null;
  source: string;
  provider_symbol: string;
  currency: string | null;
  fetched_at: string;
  raw?: Record<string, unknown>;
}

export async function fetchQuote(symbol: string): Promise<QuoteSnapshot> {
  const target = symbol.trim().toUpperCase();
  if (!target) throw new Error("empty symbol");
  const payload = await sidecarFetch<{
    ok: boolean;
    data: QuoteSnapshot | null;
    error?: string;
  }>(
    `/api/quote/${encodeURIComponent(target)}`,
  );
  if (!payload.ok || !payload.data) {
    throw new Error(payload.error || `quote unavailable for ${target}`);
  }
  return payload.data;
}
