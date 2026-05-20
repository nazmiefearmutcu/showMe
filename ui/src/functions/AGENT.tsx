import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  Field,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Sparkline,
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

  // Round-2B (TS-LINT-04 P1): abort the in-flight agent request on unmount
  // so a closed pane never sets state on a dead component.
  useEffect(() => () => abortRef.current?.abort(), []);
  const evidence = result?.best?.top_evidence ?? [];
  const exclusions = result?.excluded_functions ?? [];

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
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code="AGENT"
          title="Symbol Agent"
          subtitle={result ? `${result.function_count} functions` : "all-function ranker"}
          trailing={
            <div className="u-flex u-gap-8 u-items-center btn btn--accent u-btn-26">
              <Pill
                tone={
                  state === "error"
                    ? "negative"
                    : state === "loading"
                      ? "warn"
                      : state === "ok"
                        ? "positive"
                        : "muted"
                }
                variant="soft"
                withDot={state !== "idle"}
              >
                {state}
              </Pill>
              <Pill tone="accent" variant="soft" withDot={false}>
                {candidates.length} cand
              </Pill>
              <Pill tone="muted" variant="ghost" withDot={false}>
                {timeout}s/fn
              </Pill>
              <button
                type="button"
                
                onClick={run}
                disabled={state === "loading" || candidates.length === 0}
                
              >
                {state === "loading" ? "Running…" : "Run Agent"}
              </button>
            </div>
          }
        />
        <PaneBody className="u-p-0">
          <section className="agent-layout">
            <aside className="agent-aside">
              <label className="agent-candidates-label">
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
                trailing={<span className="u-text-mute u-text-10">sec</span>}
              />
              <div style={metricGrid}>
                <Metric label="candidates" value={candidates.length} />
                <Metric label="functions" value={result?.function_count ?? "-"} />
                <Metric label="catalog" value={result?.catalog_count ?? "-"} />
                <Metric label="excluded" value={exclusions.length || "-"} />
                <Metric label="elapsed" value={result ? formatMs(result.elapsed_ms) : "-"} />
              </div>
              {result?.best && (
                <div style={winnerBox}>
                  <div className="u-flex u-items-center u-justify-between u-gap-6">
                    <span style={labelStyle} className="u-text-accent-strong">Best candidate</span>
                    <Pill tone="accent" variant="filled" withDot={false}>
                      {formatScore(result.best.score)}
                    </Pill>
                  </div>
                  <div className="agent-best-symbol">
                    {result.best.symbol}
                  </div>
                  <div className="agent-best-asset">{result.best.asset_class}</div>
                  <div className="agent-best-meta">
                    {result.best.signal_functions} signal · {evidence.length} evidence rows
                  </div>
                  {result.ranked.length > 1 && (
                    <Sparkline
                      values={result.ranked.slice(0, 12).map((r) => r.score)}
                      width={200}
                      height={24}
                      tone="accent"
                      ariaLabel="rank distribution"
                    />
                  )}
                </div>
              )}
              {exclusions.length > 0 ? (
                <div style={excludedBox}>
                  <div style={labelStyle}>Excluded</div>
                  {exclusions.map((row) => (
                    <div key={row.code} style={excludedRow}>
                      <strong>{row.code}</strong>
                      <span>{row.reason}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </aside>

            <main className="agent-main">
              {error && (
                <div className="agent-error">{error}</div>
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
                  title="Ready to scan"
                  body={`Symbol Agent will rank ${candidates.length} candidates across all native functions, return per-symbol score + per-function evidence.`}
                  action={
                    <button
                      type="button"
                      className="btn btn--accent agent-run-btn"
                      onClick={run}
                      disabled={candidates.length === 0}
                    >
                      Run agent · {timeout}s/fn
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
          <span>catalog {result?.catalog_count ?? "-"}</span>
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
      <div className="agent-help-block">
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
  gridTemplateColumns: "repeat(2, 1fr)",
  gap: 10,
};

const winnerBox: CSSProperties = {
  border: "1px solid var(--accent)",
  borderRadius: "var(--radius-md)",
  background: "var(--accent-soft)",
  padding: 12,
  display: "grid",
  gap: 6,
  boxShadow: "var(--shadow-elev-1)",
};

const excludedBox: CSSProperties = {
  borderTop: "1px solid var(--border-subtle)",
  paddingTop: 10,
  display: "grid",
  gap: 6,
  minWidth: 0,
};

const excludedRow: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "52px minmax(0, 1fr)",
  gap: 8,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  lineHeight: 1.35,
};
