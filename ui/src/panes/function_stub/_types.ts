import type { Time } from "lightweight-charts";
import type { DataGridColumn } from "@/design-system";
import type { FunctionCallResult } from "@/lib/functions";

export type LoadState = "idle" | "loading" | "ok" | "error";
export type RecordRow = Record<string, unknown>;
export type QueryParam = "query" | "topic" | "bbox" | "symbols" | "watchlist" | "universe";
export type TicketSide = "BUY" | "SELL";
export type TicketType = "MARKET" | "LIMIT" | "STOP" | "STOP_LIMIT";
export type TicketTif = "DAY" | "GTC" | "IOC" | "FOK";
export type OptionType = "CALL" | "PUT";
export type OptionStrategy = "CALL_SPREAD" | "LONG_CALL" | "STRADDLE";
export type BacktestStrategy = "ALL" | "sma_crossover" | "rsi_meanrev" | "buy_and_hold";
export type MLHorizon = "1" | "5" | "20";
export type SimpleParamSpec = { key: string; label: string; hint?: string };

export type ChartKind = "line" | "ohlc" | "bar" | "heatmap" | "curve";

export interface ChartPoint {
  xLabel: string;
  y: number;
  x?: number;
  time?: Time;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
}

export interface ChartSeries {
  kind: ChartKind;
  title: string;
  rows: RecordRow[];
  xKey: string | null;
  labelKey: string | null;
  yKey: string;
  points: ChartPoint[];
}

export interface MetricCard {
  label: string;
  value: unknown;
}

export interface MediaItem {
  label: string;
  src: string;
  note?: string;
  isSatellite?: boolean;
}

export interface PayloadStatus {
  state: "live" | "degraded" | "unavailable" | "empty";
  label: string;
  title: string;
  reasons: string[];
  actions: string[];
}

export interface ResultSummary {
  shape: string;
  rows: RecordRow[];
  columns: DataGridColumn<RecordRow>[];
  fields: string[];
  keyValues: Array<[string, unknown]>;
}

export interface ControlProfile {
  limitParam?: "limit" | "top_n";
  rangeParam?: "days" | "weeks" | "horizon_days";
  queryParam?: QueryParam;
  queryLabel?: string;
  queryHint?: string;
  tradeTicket: boolean;
  transcriptText: boolean;
  limit: boolean;
  days: boolean;
}

export const STUB_RANGES = [
  { id: "1M", label: "1M", days: 30 },
  { id: "3M", label: "3M", days: 90 },
  { id: "6M", label: "6M", days: 180 },
  { id: "1Y", label: "1Y", days: 365 },
  { id: "3Y", label: "3Y", days: 365 * 3 },
] as const;
export type StubRangeId = (typeof STUB_RANGES)[number]["id"];
export const STUB_RANGE_IDS = STUB_RANGES.map((r) => r.id);

export const TABLE_KEYS = [
  "accounts",
  "articles",
  "bars",
  "cells",
  "constituents",
  "data",
  "events",
  "equity_curve",
  "holdings",
  "items",
  "news",
  "ohlcv",
  "orders",
  "positions",
  "records",
  "results",
  "rows",
  "securities",
  "signals",
  "surface",
  "top_10_by_sharpe",
  "trades",
  "transcripts",
];

export const CHART_KEYS = [
  "equity_curve",
  "ohlcv",
  "bars",
  "history",
  "series",
  "curve",
  "drawdown",
  "efficient_frontier",
  "returns",
  "matrix",
  "risk_contributions",
  "surface",
  "rows",
  "data",
];

export const TIME_KEYS = [
  "published_at",
  "publishedAt",
  "published_on",
  "published",
  "ts",
  "date",
  "datetime",
  "time",
  "timestamp",
  "period",
];

export const VALUE_KEYS = [
  "change_pct",
  "changePercent",
  "daily_change_pct",
  "forecast_value",
  "forecast",
  "forward",
  "forward_rate",
  "count",
  "dark_pool_pct",
  "fair_value_per_share",
  "wacc",
  "target_price",
  "price_target",
  "actual",
  "estimate",
  "surprisePercent",
  "shares",
  "pct_outstanding",
  "importance_score",
  "relevance_score",
  "sentiment_score",
  "temp_c",
  "precip_mm",
  "correlation",
  "total_effect",
  "total_pnl",
  "total_return_pct",
  "amount_usd_bn",
  "offering_amount",
  "pd_1y_pct",
  "spread_bps_of_price",
  "allocation_effect",
  "selection_effect",
  "interaction_effect",
  "component_pct_of_portfolio_risk",
  "risk_contribution_pct",
  "risk_contribution",
  "loading",
  "shock_return",
  "loss_pct",
  "drift_pct",
  "notional_delta",
  "estimated_tax_savings",
  "market_value",
  "unrealized_pnl",
  "equity",
  "close",
  "value",
  "price",
  "return",
  "total_return",
  "drawdown",
  "pnl",
  "score",
  "sharpe",
  "calmar",
  "importance",
  "weight",
  "market_weight",
  "optimal_weight",
  "posterior_return",
  "component_var",
  "yield",
  "rate",
  "vol_pct",
  "realized_vol",
  "vol",
  "iv",
  "gex",
  "mid",
  "y",
];

export const NUMERIC_X_KEYS = ["vol", "volatility", "spot", "strike", "moneyness", "window_days", "tenor_years", "shock_pct", "ytm_pct"];

export const METRIC_RECORD_KEYS = [
  "metrics",
  "summary",
  "stats",
  "performance",
  "risk",
  "health",
  "best",
  "best_by_sharpe",
];

export const SYNTHETIC_MARKERS = [
  "baseline",
  "model",
  "template",
  "sample",
  "placeholder",
  "synthetic",
  "continuity",
];

export const STABLE_ROW_ID_KEYS = [
  "id",
  "symbol",
  "ticker",
  "isin",
  "cusip",
  "headline",
  "title",
  "name",
  "date",
  "datetime",
  "time",
  "timestamp",
  "published_at",
  "period",
  "bucket",
];

// Re-export for convenience
export type { FunctionCallResult };
