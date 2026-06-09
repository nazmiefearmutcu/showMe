/**
 * ASKB orchestrator client — talks to the sidecar's `/api/ask` endpoint.
 */
import { sidecarFetch } from "./sidecar";

export type AskIntent =
  | "scan"
  | "portfolio_overview"
  | "function"
  | "lookup"
  | "compare"
  | "news"
  | "unknown";

export interface AskPlan {
  intent: AskIntent;
  action: string;
  rationale: string;
  args: Record<string, unknown>;
  agents: string[];
}

export interface AskHighlight {
  label: string;
  value: number | string;
  tone: "neutral" | "positive" | "negative" | "warn" | "muted";
}

export interface AskPhase {
  name: string;
  elapsed_ms: number;
  output: Record<string, unknown>;
}

export interface AskVizPaneHint {
  code: string;
  symbol?: string;
}

export interface AskViz {
  kind: "table" | "chart" | "cards" | "metric" | "split" | "none";
  title?: string;
  code?: string;
  rows_n?: number;
  open_pane_hint?: AskVizPaneHint;
  panes?: AskVizPaneHint[];
}

export interface AskFanoutBranch {
  kind?: string;
  code?: string;
  data?: unknown;
  warnings?: string[];
  evidence?: AskEvidence[];
}

export interface AskEvidence {
  branch?: string;
  code?: string;
  sources?: string[];
  status?: string;
  rows?: number;
  top?: string[];
  elapsed_ms?: number | null;
  reason?: string | null;
}

export interface AskResponse {
  query: string;
  plan: AskPlan;
  search: {
    kind?: string;
    code?: string;
    data?: unknown;
    warnings?: string[];
    /** Present when intent === "briefing" — keys are leg names. */
    branches?: Record<string, AskFanoutBranch>;
    branch_names?: string[];
    evidence?: AskEvidence[];
  };
  narrative: string;
  highlights: AskHighlight[];
  viz: AskViz;
  phases: AskPhase[];
  elapsed_ms: number;
  warnings: string[];
  /**
   * Honest provenance for the PLAN step. The ANSWER (narrative + highlights)
   * is ALWAYS a deterministic composition from real function outputs; only
   * the PLAN may call an LLM. These describe the plan step truthfully.
   */
  plan_method?: "llm" | "deterministic";
  /** Real model id when an LLM actually planned (e.g. "claude-haiku-4-5"). */
  model_used?: string | null;
  provider?: string | null;
  /** Real ledger delta in USD for this ask ($0.00 on the deterministic path). */
  cost_usd?: number;
  was_llm_called?: boolean;
}

export async function ask(query: string, signal?: AbortSignal): Promise<AskResponse> {
  // Routed through sidecarFetch so the auth token + port-discovery layer
  // both apply. See ARCH-05 P2 in the quality audit.
  return sidecarFetch<AskResponse>("/api/ask", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query }),
    signal,
  });
}
