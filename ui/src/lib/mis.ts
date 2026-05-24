/**
 * MIS (Multi Indicator Scan) — typed HTTP client.
 *
 * Talks to the `/api/mis/*` routes registered by
 * `backend/showme/server_routes/mis.py`. The bundle shape mirrors the
 * Python dataclasses 1:1 so the React side can pass straight through
 * to `<DataGrid>` without remapping.
 */
import { sidecarFetch } from "./sidecar";

export type MisMarket =
  | "CRYPTO"
  | "EQUITY"
  | "ETF"
  | "FX"
  | "COMMODITY"
  | "BOND";

export const MIS_MARKETS: readonly MisMarket[] = [
  "CRYPTO",
  "EQUITY",
  "ETF",
  "FX",
  "COMMODITY",
  "BOND",
] as const;

export interface MisMarketSummary {
  key: MisMarket;
  default_timeframe: string;
  size: number;
  asset_class: string;
  /** Every TF this market knows weights for (e.g. CRYPTO ships TBV3's 12 TFs). */
  default_tfs: string[];
  /** TFs the user has actually enabled. Subset of default_tfs. */
  active_tfs: string[];
  /** ZAK weight per TF (0–100, higher = more influence on the aggregate). */
  tf_weights: Record<string, number>;
}

export interface MisMarketsResponse {
  markets: MisMarketSummary[];
  supported: MisMarket[];
  default_timeframes: Record<MisMarket, string>;
}

export interface MisIndicatorThresholds {
  [paramName: string]: number | string;
}

export interface MisMarketConfig {
  indicator_weights: Record<string, number>;
  indicator_thresholds: Record<string, MisIndicatorThresholds>;
  consensus: {
    strong_buy_threshold: number;
    buy_threshold: number;
    sell_threshold: number;
    strong_sell_threshold: number;
    conflict_ratio_threshold: number;
    min_active_signals: number;
  };
  no_trade: {
    adx_min: number;
    atr_high_percentile: number;
    min_confidence: number;
  };
  risk: {
    confidence_threshold: number;
    max_risk_level: string;
  };
  /** ZAK weight per timeframe (0–100). Mirrors TBV3 ``bot_service._ZAK``. */
  tf_weights: Record<string, number>;
  /** Active TFs to scan; subset of tf_weights keys. */
  tf_set: string[];
  universe_override: string[];
}

export interface MisConfigBundle {
  version: number;
  markets: Record<MisMarket, MisMarketConfig>;
}

export interface MisTopIndicator {
  name: string | null;
  signal: string | null;
  weighted_score: number | null;
  reason: string | null;
  tf?: string | null;
}

export interface MisPerTfResult {
  tf: string;
  weight: number;
  direction: "LONG" | "SHORT" | "NEUTRAL";
  final_signal: string;
  score: number;
  confidence: number;
  contribution: number;
  skipped?: string | null;
}

export interface MisIndicatorResult {
  name: string;
  signal: string;
  score: number;
  reason: string;
  raw_values?: Record<string, unknown>;
}

export interface MisScanRow {
  symbol: string;
  market: MisMarket;
  asset_class: string;
  /** ``·``-joined list of every TF the aggregator visited (e.g. ``"1h·4h·1d"``). */
  timeframe: string;
  direction: "LONG" | "SHORT" | "NEUTRAL";
  final_signal: string;
  weighted_score: number;
  /** TF-count-invariant score in [-1, +1]. Backend sorts on this so a
   * 12-TF row doesn't beat a 4-TF row purely because more TFs fired. */
  normalized_score: number;
  confidence: number;
  last: number | null;
  change_pct: number | null;
  top_indicators: MisTopIndicator[];
  indicator_breakdown: MisIndicatorResult[];
  /** Per-TF breakdown — drives the multi-TF chip strip in the results table. */
  per_tf: MisPerTfResult[];
  tf_count_scanned: number;
  tf_count_with_signal: number;
  skipped: string | null;
}

export interface MisPerMarketCount {
  requested: number;
  completed: number;
  skipped: number;
}

export interface MisScanResult {
  rows: MisScanRow[];
  markets: MisMarket[];
  per_market_counts: Record<MisMarket, MisPerMarketCount>;
  warnings: string[];
  elapsed_ms: number;
  started_at: string;
}

export interface MisScanRequest {
  markets: MisMarket[];
  /** Legacy single-TF override — kept for back-compat only. */
  timeframes?: Partial<Record<MisMarket, string>>;
  /** Multi-TF override: replaces the saved tf_set for this scan only. */
  tf_set?: Partial<Record<MisMarket, string[]>>;
  top_n?: number;
  min_confidence?: number;
  only_signals?: boolean;
  max_symbols_per_market?: number | null;
}

export async function fetchMisMarkets(): Promise<MisMarketsResponse> {
  return sidecarFetch<MisMarketsResponse>("/api/mis/markets");
}

export async function fetchMisIndicators(): Promise<string[]> {
  const r = await sidecarFetch<{ indicators: string[] }>("/api/mis/indicators");
  return r.indicators ?? [];
}

export async function fetchMisConfig(): Promise<MisConfigBundle> {
  return sidecarFetch<MisConfigBundle>("/api/mis/config");
}

export async function saveMisConfig(
  bundle: MisConfigBundle,
): Promise<MisConfigBundle> {
  return sidecarFetch<MisConfigBundle>("/api/mis/config", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(bundle),
  });
}

export async function runMisScan(req: MisScanRequest): Promise<MisScanResult> {
  return sidecarFetch<MisScanResult>("/api/mis/scan", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
  });
}

/** Live progress snapshot exposed by ``GET /api/mis/scan/progress``.
 * The UI polls this every ~250ms while the scan POST is in flight.
 *
 * ``status`` state machine:
 *   idle    — no scan since process start (or after a clear)
 *   running — scan in flight; ``completed / total`` ticks up
 *   done    — scan finished; rows have been returned
 *   error   — scan crashed; backend set this from the route handler
 */
export interface MisScanProgress {
  status: "idle" | "running" | "done" | "error";
  total: number;
  completed: number;
  in_flight: number;
  skipped: number;
  markets: MisMarket[];
  started_at: string;
  elapsed_ms: number;
  current_symbol: string;
  current_market: string;
  /** Pre-computed by the backend so the UI doesn't have to redo the
   * divide-by-zero guard on every tick. Range 0–100. */
  percent: number;
}

export async function fetchMisScanProgress(): Promise<MisScanProgress> {
  return sidecarFetch<MisScanProgress>("/api/mis/scan/progress");
}

/** Friendly Turkish labels used in the UI header chips. */
export const MIS_MARKET_LABELS: Record<MisMarket, string> = {
  CRYPTO: "Kripto",
  EQUITY: "Hisse",
  ETF: "ETF",
  FX: "Döviz",
  COMMODITY: "Emtia",
  BOND: "Tahvil",
};

/** Static fallback TF list per market — used only on the very first paint
 * before /api/mis/markets responds. The authoritative list comes from
 * ``MisMarketSummary.default_tfs`` and the active subset from
 * ``MisMarketSummary.active_tfs``.
 *
 * QA-2026-05-24 (#19): `1wk` and `1mo` removed from EQUITY/ETF/FX/COMMODITY/
 * BOND. The backend ships no ZAK weights for those TFs, so requesting them
 * hung the scan indefinitely. Add them back here only after weights land in
 * `backend/showme/mis.py` `_ZAK` and `_TF_WHITELIST_BY_MARKET`. */
export const MIS_FALLBACK_TFS: Record<MisMarket, string[]> = {
  CRYPTO: ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"],
  EQUITY: ["1h", "1d"],
  ETF: ["1h", "1d"],
  FX: ["1h", "4h", "1d"],
  COMMODITY: ["1h", "1d"],
  BOND: ["1d"],
};

/** Alias for callers that prefer the more literal name. Same object — both
 * symbols stay in sync. Tests should assert against this OR the legacy
 * MIS_FALLBACK_TFS export. */
export const MIS_TFS_BY_MARKET = MIS_FALLBACK_TFS;
