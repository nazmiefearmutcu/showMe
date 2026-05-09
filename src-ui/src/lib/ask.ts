/**
 * ASKB orchestrator client — talks to the sidecar's `/api/ask` endpoint.
 */
import { sidecarBaseUrl } from "./sidecar";

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
}

export async function ask(query: string): Promise<AskResponse> {
  const res = await fetch(`${sidecarBaseUrl()}/api/ask`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`ask: ${res.status} ${body}`);
  }
  return res.json();
}
