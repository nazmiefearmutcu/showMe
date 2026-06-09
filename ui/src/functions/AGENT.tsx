/**
 * AGENT — Symbol Agent. Ranks candidate symbols across all native functions
 * and returns the best one with per-function evidence.
 *
 * HONESTY: the ranking engine is a DETERMINISTIC heuristic, NOT an LLM/AI.
 * The default "Hızlı probe" mode scores candidates using TRANSPARENT SYNTHETIC
 * `agent_fast_probe` payloads — it does NOT execute real per-symbol functions.
 * An opt-in "Canlı çalıştır" mode runs the real functions (slower). The backend
 * already returns honest `method`/`methodology` strings describing which path
 * produced the result; this UI surfaces them rather than overclaiming.
 *
 * The per-evidence `confidence` is signal DENSITY (keyword-match count, see
 * `_agent_runtime.py`), NOT model/probabilistic uncertainty — it is relabelled
 * "sinyal yoğ." and disclosed as such wherever shown.
 */
import {
  type CSSProperties,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
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
  Skeleton,
  Sparkline,
} from "@/design-system";
import {
  parseCandidateText,
  runBestSymbolAgent,
  type AgentCandidateResult,
  type AgentFunctionEvidence,
  type BestSymbolAgentResult,
} from "@/lib/agent";
import { navigate } from "@/lib/router";
import { useWorkspace } from "@/lib/workspace";
import { formatNumber } from "@/lib/format";
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

// HONESTY (H2): the backend's per-evidence "confidence" is keyword/signal
// DENSITY, not a probabilistic confidence. One source-of-truth tooltip string,
// reused everywhere the metric is shown.
const SIGNAL_DENSITY_TITLE =
  "Sinyal yoğunluğu = eşleşen sinyal anahtar sayısına dayalı yoğunluk skoru " +
  "(olasılıksal/model güveni DEĞİL).";

// HONESTY (H1): static pre-run disclosure of HOW the ranker works.
const STATIC_METHODOLOGY =
  "Bu DETERMİNİSTİK bir sezgisel sıralayıcıdır (yapay zekâ/LLM değil). " +
  "Varsayılan “Hızlı probe” modu adayları ŞEFFAF SENTETİK probe verileriyle " +
  "puanlar — gerçek, sembol-başına fonksiyon yürütmesi yapmaz. Gerçek " +
  "yürütme için “Canlı çalıştır” modunu açın (yavaş).";

function isLiveMethod(method: string | undefined): boolean {
  return Boolean(method && /live/i.test(method));
}

export function AGENTPane(_props: FunctionPaneProps) {
  const [candidateText, setCandidateText] = useState(DEFAULT_CANDIDATES);
  const [timeout, setTimeoutValue] = useState("12");
  const [liveMode, setLiveMode] = useState(false);
  const [state, setState] = useState<LoadState>("idle");
  const [result, setResult] = useState<BestSymbolAgentResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);

  const candidates = useMemo(() => parseCandidateText(candidateText), [candidateText]);

  // Round-2B (TS-LINT-04 P1): abort the in-flight agent request on unmount
  // so a closed pane never sets state on a dead component.
  useEffect(() => () => abortRef.current?.abort(), []);
  const evidence = result?.best?.top_evidence ?? [];
  const exclusions = result?.excluded_functions ?? [];
  const resultIsLive = isLiveMethod(result?.method);

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
          execute_functions: liveMode,
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

  const jumpToDES = useCallback(
    (sym: string) => {
      if (!sym) return;
      setFocusedTarget("DES", sym);
      navigate(`/symbol/${sym}/DES`);
    },
    [setFocusedTarget],
  );

  const candidateColumns = useMemo(
    () => buildCandidateColumns(jumpToDES),
    [jumpToDES],
  );

  const subtitle = result
    ? `${result.function_count} fn · ${result.method}`
    : "deterministik sezgisel sıralayıcı";

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code="AGENT"
          title="Symbol Agent"
          subtitle={subtitle}
          trailing={
            <div className="u-flex u-gap-8 u-items-center">
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
              {/* H3: which mode produced the displayed result, derived from
                  result.method (live vs probe). */}
              {result && (
                <Pill
                  tone={resultIsLive ? "accent" : "muted"}
                  variant="soft"
                  withDot={false}
                >
                  {resultIsLive ? "canlı" : "hızlı probe"}
                </Pill>
              )}
              {/* D1: the btn classes now live on the BUTTON itself, not the
                  wrapper div (which was the bug). */}
              <button
                type="button"
                className="btn btn--accent u-btn-26"
                onClick={run}
                disabled={state === "loading" || candidates.length === 0}
                aria-busy={state === "loading"}
                aria-label="Sıralamayı çalıştır"
              >
                {state === "loading" ? "Running…" : "Run Agent"}
              </button>
            </div>
          }
        />
        <PaneBody className="u-p-0">
          <section className="agent-layout">
            <aside className="agent-aside">
              <label className="agent-candidates-label" htmlFor="agent-candidates">
                <span style={labelStyle}>Candidates</span>
                <textarea
                  id="agent-candidates"
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

              {/* H3: live/probe mode toggle, DEFAULT OFF = transparent synthetic
                  fast probe. Does NOT auto-run; the user clicks Run. */}
              <label className="agent-mode-toggle">
                <input
                  type="checkbox"
                  checked={liveMode}
                  onChange={(e) => setLiveMode(e.target.checked)}
                />
                <span>
                  <strong>Canlı çalıştır</strong>
                  <span className="agent-mode-hint">
                    gerçek fonksiyon yürütme (yavaş). Kapalıyken: şeffaf
                    sentetik hızlı probe.
                  </span>
                </span>
              </label>

              {/* H1: static, honest disclosure of HOW the ranker works. */}
              <p
                data-testid="agent-methodology"
                className="agent-methodology"
                title={result?.methodology ?? STATIC_METHODOLOGY}
              >
                {result?.methodology ?? STATIC_METHODOLOGY}
                {result && (
                  <span className="agent-methodology-method">
                    {" "}
                    yöntem: {result.method}
                  </span>
                )}
              </p>

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
              {/* D2: announced error region. */}
              {error && (
                <div
                  data-testid="agent-error"
                  role="status"
                  aria-live="polite"
                  className="agent-error u-text-negative"
                >
                  {error}
                </div>
              )}

              {/* U2: result count + best summary, announced. */}
              {result && (
                <div className="agent-summary" role="status" aria-live="polite">
                  {result.ranked.length} aday sıralandı
                  {result.best ? ` · en iyi: ${result.best.symbol}` : ""}
                  {` · ${resultIsLive ? "canlı yürütme" : "hızlı probe"}`}
                </div>
              )}

              {/* DI2: loading skeleton in the results area. */}
              {state === "loading" && (
                <div data-testid="agent-loading" className="agent-skeletons">
                  <Skeleton height={64} />
                  <Skeleton height={20} />
                  <Skeleton height={20} />
                  <Skeleton height={20} width="80%" />
                </div>
              )}

              {state !== "loading" && result ? (
                <>
                  <DataGrid
                    rows={result.ranked}
                    columns={candidateColumns}
                    rowKey={(row) => row.symbol}
                    density="compact"
                    ariaLabel="Sıralanan adaylar"
                  />
                  <DataGrid
                    rows={evidence}
                    columns={evidenceColumns}
                    rowKey={(row) => row.code}
                    density="compact"
                    empty="no signal evidence"
                    ariaLabel="En iyi aday için fonksiyon kanıtları"
                  />
                </>
              ) : state !== "loading" ? (
                <Empty
                  title="Ready to scan"
                  body={`Symbol Agent ${candidates.length} adayı tüm yerel fonksiyonlar üzerinde sıralar; sembol-başına skor + fonksiyon-başına kanıt döndürür. Varsayılan mod şeffaf sentetik probe kullanır.`}
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
              ) : null}
            </main>
          </section>
        </PaneBody>
        <PaneFooter>
          <span>method {result?.method ?? "—"}</span>
          <span>mode {result ? (resultIsLive ? "live" : "fast_probe") : "-"}</span>
          <span>best {result?.best?.symbol ?? "-"}</span>
          <span>catalog {result?.catalog_count ?? "-"}</span>
          <span>fail {result?.ranked.reduce((sum, row) => sum + row.fail, 0) ?? 0}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function buildCandidateColumns(
  onJumpDES: (sym: string) => void,
): DataGridColumn<AgentCandidateResult>[] {
  return [
    {
      key: "symbol",
      header: "symbol",
      width: "104px",
      // U1: each ranked symbol is a focusable launch affordance (Enter/Space)
      // that navigates to DES — mirrors SCAN.tsx.
      render: (row) => (
        <button
          type="button"
          className="agent-symbol-btn u-mono"
          onClick={(e) => {
            e.stopPropagation();
            onJumpDES(row.symbol);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              e.stopPropagation();
              onJumpDES(row.symbol);
            }
          }}
          aria-label={`${row.symbol} DES'te aç`}
          title="DES'te aç"
        >
          {row.symbol}
        </button>
      ),
    },
    { key: "asset_class", header: "asset", width: "82px" },
    {
      key: "score",
      header: "score",
      width: "108px",
      numeric: true,
      // DI1: visual meter for score (signed band ±3), with the numeric value
      // always present — color is never the sole signal.
      render: (row) => <ScoreMeter value={row.score} />,
    },
    { key: "pass", header: "pass", width: "52px", numeric: true },
    { key: "fail", header: "fail", width: "52px", numeric: true },
    { key: "fallback", header: "tpl", width: "52px", numeric: true },
    { key: "signal_functions", header: "signals", width: "72px", numeric: true },
  ];
}

const evidenceColumns: DataGridColumn<AgentFunctionEvidence>[] = [
  {
    key: "code",
    header: "fn",
    width: "72px",
    render: (row) => <span className="u-mono">{row.code}</span>,
  },
  { key: "category", header: "cat", width: "92px" },
  {
    key: "score",
    header: "score",
    width: "108px",
    numeric: true,
    render: (row) => <ScoreMeter value={row.score} />,
  },
  {
    // H2: relabelled from "conf" → honest "sinyal yoğ." (signal density), with
    // a clarifying tooltip on the header and the cell.
    key: "confidence",
    header: (
      <span title={SIGNAL_DENSITY_TITLE}>sinyal yoğ.</span>
    ),
    width: "96px",
    numeric: true,
    render: (row) => <SignalDensityMeter value={row.confidence} />,
  },
  {
    key: "signals",
    header: "signal",
    render: (row) => <span className="u-mono">{row.signals[0]?.path ?? "-"}</span>,
  },
  {
    key: "elapsed_ms",
    header: "ms",
    width: "70px",
    numeric: true,
    render: (row) => row.elapsed_ms,
  },
];

/**
 * DI1 — score rendered as a meter. Score is a signed quantity; we map it onto a
 * ±SCORE_BAND band for the fill, keep the signed numeric value always visible,
 * and expose role=meter semantics so it is never color-only.
 */
const SCORE_BAND = 3;
function ScoreMeter({ value }: { value: number }) {
  const text = formatScore(value);
  const pct = Math.max(0, Math.min(100, (Math.abs(value) / SCORE_BAND) * 100));
  const tone = value > 0 ? "positive" : value < 0 ? "negative" : "neutral";
  return (
    <span
      role="meter"
      aria-label={`score ${text}`}
      aria-valuenow={Number(
        Math.max(-SCORE_BAND, Math.min(SCORE_BAND, value)).toFixed(3),
      )}
      aria-valuemin={-SCORE_BAND}
      aria-valuemax={SCORE_BAND}
      className={`agent-meter agent-meter--${tone}`}
    >
      <span
        aria-hidden
        className="agent-meter__fill"
        style={{ ["--u-pct" as string]: `${pct}%` }}
      />
      <span className="agent-meter__label u-mono">{text}</span>
    </span>
  );
}

/**
 * H2 + DI1 — "signal density" (the backend's `confidence`) as a meter. Value is
 * 0..1 → 0..100%. Labelled honestly as density, NOT probabilistic confidence.
 */
function SignalDensityMeter({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value * 100));
  return (
    <span
      role="meter"
      aria-label={`sinyal yoğunluğu ${Math.round(pct)}%`}
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      title={SIGNAL_DENSITY_TITLE}
      className="agent-meter agent-meter--accent"
    >
      <span
        aria-hidden
        className="agent-meter__fill"
        style={{ ["--u-pct" as string]: `${pct}%` }}
      />
      <span className="agent-meter__label u-mono">{Math.round(pct)}%</span>
    </span>
  );
}

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
  // DI1: score via the shared formatter for sign/precision consistency.
  return `${value >= 0 ? "+" : "-"}${formatNumber(Math.abs(value), 3, {
    minimumFractionDigits: 3,
  })}`;
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
