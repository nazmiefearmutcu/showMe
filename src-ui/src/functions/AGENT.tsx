import { type CSSProperties, useMemo, useRef, useState } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  Field,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
} from "@/design-system";
import {
  parseCandidateText,
  runBestSymbolAgent,
  type AgentCandidateResult,
  type AgentFunctionEvidence,
  type BestSymbolAgentResult,
} from "@/lib/agent";
import type { FunctionPaneProps } from "./registry-types";

const DEFAULT_CANDIDATES = [
  "BTCUSDT",
  "ETHUSDT",
  "SOLUSDT",
  "AAPL",
  "MSFT",
  "NVDA",
  "EURUSD",
  "GC=F",
].join("\n");

type LoadState = "idle" | "loading" | "ok" | "error";

export function AGENTPane(_props: FunctionPaneProps) {
  const [candidateText, setCandidateText] = useState(DEFAULT_CANDIDATES);
  const [timeout, setTimeoutValue] = useState("12");
  const [state, setState] = useState<LoadState>("idle");
  const [result, setResult] = useState<BestSymbolAgentResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const candidates = useMemo(() => parseCandidateText(candidateText), [candidateText]);
  const evidence = result?.best?.top_evidence ?? [];

  const run = async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState("loading");
    setError(null);
    try {
      const response = await runBestSymbolAgent(
        {
          candidates,
          max_candidates: Math.min(candidates.length || 1, 12),
          per_function_timeout: Number(timeout) || 12,
        },
        controller.signal,
      );
      setResult(response);
      setState("ok");
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : String(err));
      setState("error");
    }
  };

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code="AGENT"
          title="Symbol Agent"
          subtitle={result ? `${result.function_count} functions` : "all-function ranker"}
          trailing={
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span className={`pill pill--${state === "error" ? "crashed" : state === "loading" ? "booting" : "healthy"}`}>
                {state}
              </span>
              <button
                type="button"
                className="btn btn--accent"
                onClick={run}
                disabled={state === "loading" || candidates.length === 0}
                style={{ height: 26 }}
              >
                {state === "loading" ? "Running" : "Run"}
              </button>
            </div>
          }
        />
        <PaneBody style={{ padding: 0 }}>
          <section
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(260px, 340px) minmax(0, 1fr)",
              height: "100%",
              minHeight: 0,
            }}
          >
            <aside
              style={{
                borderRight: "1px solid var(--border-subtle)",
                padding: 14,
                display: "flex",
                flexDirection: "column",
                gap: 12,
                minHeight: 0,
              }}
            >
              <label style={{ display: "grid", gap: 6, minHeight: 180 }}>
                <span style={labelStyle}>Candidates</span>
                <textarea
                  value={candidateText}
                  onChange={(e) => setCandidateText(e.target.value)}
                  spellCheck={false}
                  style={textareaStyle}
                />
              </label>
              <Field
                label="Per Function Timeout"
                value={timeout}
                onChange={(e) => setTimeoutValue(e.target.value)}
                inputMode="numeric"
                trailing={<span style={{ color: "var(--text-mute)", fontSize: 10 }}>sec</span>}
              />
              <div style={metricGrid}>
                <Metric label="candidates" value={candidates.length} />
                <Metric label="functions" value={result?.function_count ?? "-"} />
                <Metric label="elapsed" value={result ? formatMs(result.elapsed_ms) : "-"} />
              </div>
              {result?.best && (
                <div style={winnerBox}>
                  <div style={labelStyle}>Best</div>
                  <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 22 }}>
                    {result.best.symbol}
                  </div>
                  <div style={{ color: "var(--text-secondary)", fontSize: 11 }}>
                    {result.best.asset_class} / {formatScore(result.best.score)}
                  </div>
                </div>
              )}
            </aside>

            <main
              style={{
                display: "grid",
                gridTemplateRows: "minmax(180px, 0.9fr) minmax(180px, 1fr)",
                gap: 12,
                padding: 14,
                minHeight: 0,
              }}
            >
              {error && (
                <div style={{ color: "var(--negative)", fontFamily: "JetBrains Mono, monospace" }}>
                  {error}
                </div>
              )}
              {result ? (
                <>
                  <DataGrid
                    rows={result.ranked}
                    columns={candidateColumns}
                    rowKey={(row) => row.symbol}
                    density="compact"
                  />
                  <DataGrid
                    rows={evidence}
                    columns={evidenceColumns}
                    rowKey={(row) => row.code}
                    density="compact"
                    empty="no signal evidence"
                  />
                </>
              ) : (
                <Empty
                  title="No scan yet"
                  body={`${candidates.length} candidates ready`}
                  action={
                    <button type="button" className="btn btn--accent" onClick={run}>
                      Run Agent
                    </button>
                  }
                />
              )}
            </main>
          </section>
        </PaneBody>
        <PaneFooter>
          <span>method {result?.method ?? "all_function_symbol_agent_v1"}</span>
          <span>best {result?.best?.symbol ?? "-"}</span>
          <span>fail {result?.ranked.reduce((sum, row) => sum + row.fail, 0) ?? 0}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

const candidateColumns: DataGridColumn<AgentCandidateResult>[] = [
  { key: "symbol", header: "symbol", width: "90px" },
  { key: "asset_class", header: "asset", width: "90px" },
  {
    key: "score",
    header: "score",
    width: "72px",
    numeric: true,
    render: (row) => formatScore(row.score),
  },
  { key: "pass", header: "pass", width: "58px", numeric: true },
  { key: "fail", header: "fail", width: "58px", numeric: true },
  { key: "fallback", header: "tpl", width: "58px", numeric: true },
  { key: "signal_functions", header: "signals", width: "78px", numeric: true },
];

const evidenceColumns: DataGridColumn<AgentFunctionEvidence>[] = [
  { key: "code", header: "fn", width: "72px" },
  { key: "category", header: "cat", width: "92px" },
  {
    key: "score",
    header: "score",
    width: "72px",
    numeric: true,
    render: (row) => formatScore(row.score),
  },
  {
    key: "confidence",
    header: "conf",
    width: "70px",
    numeric: true,
    render: (row) => `${Math.round(row.confidence * 100)}%`,
  },
  {
    key: "signals",
    header: "signal",
    render: (row) => row.signals[0]?.path ?? "-",
  },
  {
    key: "elapsed_ms",
    header: "ms",
    width: "70px",
    numeric: true,
    render: (row) => row.elapsed_ms,
  },
];

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <div style={labelStyle}>{label}</div>
      <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 13 }}>
        {value}
      </div>
    </div>
  );
}

function formatScore(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(3)}`;
}

function formatMs(value: number): string {
  if (value >= 60_000) return `${(value / 60_000).toFixed(1)}m`;
  return `${(value / 1000).toFixed(1)}s`;
}

const labelStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
};

const textareaStyle: CSSProperties = {
  flex: 1,
  minHeight: 180,
  resize: "vertical",
  background: "var(--bg-elev-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
  lineHeight: 1.45,
  padding: 10,
};

const metricGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(3, 1fr)",
  gap: 10,
};

const winnerBox: CSSProperties = {
  border: "1px solid rgba(255,122,0,0.32)",
  borderRadius: "var(--radius-md)",
  background: "rgba(255,122,0,0.08)",
  padding: 12,
};
