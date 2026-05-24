/**
 * Scanner client — talks to the sidecar's `/api/scanner/*` endpoints.
 */
import { sidecarFetch } from "./sidecar";

export interface UniverseSummary {
  key: string;
  asset_class: string;
  size: number;
}

export interface ScanContribution {
  tf: string;
  weight: number;
  direction: "LONG" | "SHORT" | "NEUTRAL";
  confidence: number;
  contribution: number;
}

export interface OverextensionInfo {
  z_score_30d: number;
  deviation_label: "OVERBOUGHT" | "OVERSOLD" | "OK";
  overextended: boolean;
  change_pct_today: number | null;
}

export interface ScanFineBlock {
  quote?: { last?: number; previous_close?: number; change_pct?: number | null };
  overextension?: OverextensionInfo;
  contributions?: ScanContribution[];
}

export interface PositionOverlap {
  held: boolean;
  high_concentration?: boolean;
}

export interface ScanRow {
  symbol: string;
  asset_class: string;
  direction?: "LONG" | "SHORT" | "NEUTRAL";
  confidence?: number;
  score?: number;
  timeframes?: string[];
  contributions?: ScanContribution[];
  fine?: ScanFineBlock;
  position_overlap?: PositionOverlap;
  skipped?: string;
}

export interface ScanPhase {
  name: string;
  elapsed_ms: number;
  output: Record<string, unknown>;
}

export interface ScanResult {
  intent: string;
  universe_key: string;
  asset_class: string;
  timeframes: string[];
  rows: ScanRow[];
  phases: ScanPhase[];
  elapsed_ms: number;
  warnings: string[];
}

export interface ScanRequest {
  intent?: string;
  universe?: string;
  asset_class?: string;
  timeframes?: string[];
  top_n?: number;
  /** Phases to execute, e.g. ["A","B","C","D"]; default ["A","B"]. */
  phases?: string[] | string;
  /** Top-K from Phase B fed into Phase C (defaults to min(top_n, 8)). */
  fine_top_k?: number;
}

export async function listUniverses(signal?: AbortSignal): Promise<UniverseSummary[]> {
  // Routed through sidecarFetch so the auth header + port-discovery layer
  // both apply. See ARCH-05 P2.
  return sidecarFetch<UniverseSummary[]>("/api/scanner/universes", { signal });
}

export async function runScan(req: ScanRequest, signal?: AbortSignal): Promise<ScanResult> {
  return sidecarFetch<ScanResult>("/api/scanner/run", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
    signal,
  });
}
