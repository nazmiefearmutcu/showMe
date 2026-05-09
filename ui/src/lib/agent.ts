import { sidecarFetch } from "./sidecar";

export interface AgentCandidateInput {
  symbol: string;
  asset_class?: string;
}

export interface AgentSignal {
  path: string;
  value: string | number;
  score: number;
}

export interface AgentFunctionEvidence {
  code: string;
  category: string;
  status: "pass" | "fail";
  reason: string;
  score: number;
  confidence: number;
  signal_count: number;
  fallback: boolean;
  elapsed_ms: number;
  signals: AgentSignal[];
}

export interface AgentCandidateResult {
  symbol: string;
  asset_class: string;
  score: number;
  pass: number;
  fail: number;
  fallback: number;
  signal_functions: number;
  function_count: number;
  top_evidence: AgentFunctionEvidence[];
}

export interface AgentExcludedFunction {
  code: string;
  reason: string;
}

export interface BestSymbolAgentResult {
  best: AgentCandidateResult | null;
  ranked: AgentCandidateResult[];
  function_count: number;
  catalog_count?: number;
  excluded_functions?: AgentExcludedFunction[];
  candidate_count: number;
  started_at: string;
  completed_at: string;
  elapsed_ms: number;
  method: string;
  methodology?: string;
}

export interface RunBestSymbolAgentRequest {
  candidates: Array<string | AgentCandidateInput>;
  max_candidates?: number;
  per_function_timeout?: number;
}

export function parseCandidateText(value: string): string[] {
  return value
    .split(/[\n,;]+/)
    .map((part) => part.trim().toUpperCase())
    .filter(Boolean);
}

export async function runBestSymbolAgent(
  request: RunBestSymbolAgentRequest,
  signal?: AbortSignal,
): Promise<BestSymbolAgentResult> {
  return sidecarFetch<BestSymbolAgentResult>("/api/agent/best-symbol", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
}
