/**
 * ASK — ASKB-style natural-language query pane.
 *
 * Routes the query to the sidecar's `/api/ask` endpoint, renders the
 * planner's intent + rationale, the deterministic narrative, and the
 * Viz Agent's pane hint. Clicking "Open" on the hint pushes the suggested
 * pane (DES / FA / GP / PORT / SCAN) into the focused leaf.
 *
 * Layout: chat-led — header strip, conversation thread (user bubble right,
 * agent bubble left with reasoning trace expandable), suggestion chips,
 * and a sticky composer at the bottom.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import {
  ask,
  type AskEvidence,
  type AskFanoutBranch,
  type AskHighlight,
  type AskResponse,
} from "@/lib/ask";
import { useAbortableFetch } from "@/lib/useAbortableFetch";
import { useWorkspace } from "@/lib/workspace";
import { navigate } from "@/lib/router";
import { formatCurrency } from "@/lib/format";
import type { FunctionPaneProps } from "./registry-types";

const SUGGESTION_CHIPS = [
  "What's driving NVDA today?",
  "Compare AAPL vs MSFT",
  "Earnings risk this week",
  "Find me crypto opportunities",
  "Show my portfolio",
  "Open FA on MSFT",
];

interface ChatTurn {
  id: string;
  role: "user" | "agent";
  query?: string;
  result?: AskResponse;
  error?: string;
  ts: number;
}

const COST_CAP_USD = 1.0;

// HONESTY: the answer (narrative + highlights) is composed DETERMINISTICALLY
// from real function outputs — it is NOT AI-written. Only the PLAN step may
// call an LLM (and only a small Haiku/4o-mini model, gated on API keys + a
// daily cap). When no LLM is used the plan is rule-based and costs $0.00.
const DETERMINISTIC_PLAN_LABEL = "kural-tabanlı plan";
const ANSWER_DISCLOSURE =
  "Yanıt (özet + öne çıkanlar) gerçek fonksiyon çıktılarından DETERMİNİSTİK " +
  "olarak derlenir — yapay zekâ tarafından yazılmaz. Yalnızca PLAN adımı, " +
  "API anahtarları ve günlük bütçe uygunsa bir LLM kullanabilir.";

/** Honest model label for the header/status pills. */
function modelLabel(result: AskResponse | null): string {
  if (result?.was_llm_called && result.model_used) return result.model_used;
  return DETERMINISTIC_PLAN_LABEL;
}

export function ASKPane({ code }: FunctionPaneProps) {
  const [draft, setDraft] = useState("");
  const [running, setRunning] = useState(false);
  const [thread, setThread] = useState<ChatTurn[]>([]);
  const [costSpentUsd, setCostSpentUsd] = useState(0);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);
  const threadRef = useRef<HTMLDivElement>(null);
  // Bundle D / ABORT-01. Aborts the in-flight `ask()` if the user navigates
  // away or fires another query before the previous one resolves.
  const askFetch = useAbortableFetch();

  // Auto-scroll to bottom when thread grows
  useEffect(() => {
    const el = threadRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [thread.length, running]);

  const run = async () => {
    // Round 24 MEDIUM 19 — Enter+Enter stale-closure used to spawn two
    // ChatTurns because the second Enter handler captured `running=false`
    // from the closure that fired right before setRunning(true) flushed.
    // Reading the React state inside run() short-circuits cleanly.
    if (running) return;
    const q = draft.trim();
    if (!q) return;
    const userTurn: ChatTurn = {
      id: `u-${Date.now()}`,
      role: "user",
      query: q,
      ts: Date.now(),
    };
    setThread((prev) => [...prev, userTurn]);
    setDraft("");
    setRunning(true);
    try {
      const r = await askFetch.run((signal) => ask(q, signal));
      if (!askFetch.isMounted()) return;
      const agentTurn: ChatTurn = {
        id: `a-${Date.now()}`,
        role: "agent",
        result: r,
        ts: Date.now(),
      };
      setThread((prev) => [...prev, agentTurn]);
      // HONEST cost: the REAL ledger delta the backend measured for this ask.
      // On the deterministic (rule-based) path this is genuinely $0.00 — no
      // fake minimum. We accumulate it for the session-total pill.
      const incr = Number.isFinite(r.cost_usd) ? Number(r.cost_usd) : 0;
      setCostSpentUsd((prev) => Math.min(COST_CAP_USD, prev + Math.max(0, incr)));
    } catch (err) {
      if (!askFetch.isMounted()) return;
      // Don't surface AbortError as a chat-bubble error — the user already
      // saw the unmount or fired another query.
      if (err instanceof DOMException && err.name === "AbortError") return;
      const message = err instanceof Error ? err.message : String(err);
      setThread((prev) => [
        ...prev,
        {
          id: `e-${Date.now()}`,
          role: "agent",
          error: message,
          ts: Date.now(),
        },
      ]);
    } finally {
      if (askFetch.isMounted()) setRunning(false);
    }
  };

  // U2 — cancel the in-flight ask (Esc or the Stop button). The abortable
  // fetch aborts the request; the run()'s catch swallows the AbortError and
  // finally restores `running`. We also flip running immediately so the
  // composer/Stop affordance updates without waiting for the rejection.
  const cancel = () => {
    if (!running) return;
    askFetch.cancel();
    setRunning(false);
  };

  const onOpenHint = (paneCode: string, symbol?: string) => {
    setFocusedTarget(paneCode, symbol);
    if (symbol) navigate(`/symbol/${symbol}/${paneCode}`);
    else navigate(`/fn/${paneCode}`);
  };

  const toggleExpanded = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const lastResult = useMemo(() => {
    for (let i = thread.length - 1; i >= 0; i--) {
      const turn = thread[i];
      if (turn.role === "agent" && turn.result) return turn.result;
    }
    return null;
  }, [thread]);

  const costPct = Math.min(100, (costSpentUsd / COST_CAP_USD) * 100);
  const costTone = costPct >= 90 ? "negative" : costPct >= 60 ? "warn" : "positive";

  const isEmpty = thread.length === 0;

  return (
    <div className="u-pane-host--bb">
      <Pane>
        <PaneHeader
          code={code}
          title="Ask"
          subtitle={
            lastResult
              ? lastResult.plan.intent
              : "Planla · Ara · Derle (deterministik) · Görselleştir"
          }
          trailing={
            <div style={headerTrailing}>
              <Pill
                tone={lastResult?.was_llm_called ? "accent" : "muted"}
                variant="soft"
                withDot={false}
              >
                {modelLabel(lastResult)}
              </Pill>
              <Pill tone={costTone} variant="soft" withDot={false}>
                {formatCurrency(costSpentUsd, { fractionDigits: 4 })} /{" "}
                {formatCurrency(COST_CAP_USD, { fractionDigits: 2 })}
              </Pill>
              <Pill
                tone={running ? "warn" : "muted"}
                variant="soft"
                withDot={running}
              >
                {running ? "çalışıyor" : "hazır"}
              </Pill>
            </div>
          }
        />
        {/* Status strip with HONEST model + cost detail */}
        <section style={statusStrip}>
          <StatusSection
            label="PLAN"
            value={modelLabel(lastResult)}
            tone={lastResult?.was_llm_called ? "accent" : "muted"}
            withDot={Boolean(lastResult?.was_llm_called)}
          />
          <StatusDivider />
          <StatusSection
            label="COST"
            value={formatCurrency(costSpentUsd, { fractionDigits: 4 })}
            tone={costTone}
          />
          <StatusDivider />
          <StatusSection
            label="CAP"
            value={formatCurrency(COST_CAP_USD, { fractionDigits: 2 })}
            tone="muted"
          />
          <StatusDivider />
          <StatusSection label="TURNS" value={String(thread.filter((t) => t.role === "user").length)} tone="neutral" />
          <StatusDivider />
          <StatusSection
            label="ELAPSED"
            value={lastResult ? formatMs(lastResult.elapsed_ms) : "—"}
            tone="neutral"
          />
        </section>

        <PaneBody className="ask-body">
          {/* Conversation thread */}
          <div ref={threadRef} style={threadColumn}>
            {isEmpty ? (
              <EmptyAskState />
            ) : (
              thread.map((turn) => (
                <ChatBubble
                  key={turn.id}
                  turn={turn}
                  expanded={expanded.has(turn.id)}
                  onToggle={() => toggleExpanded(turn.id)}
                  onOpen={onOpenHint}
                />
              ))
            )}
            {running ? <ThinkingBubble /> : null}
          </div>

          {/* Answer-vs-plan honesty disclosure (F3) */}
          <p style={disclosureRow} data-testid="ask-disclosure">
            {ANSWER_DISCLOSURE}
          </p>

          {/* Suggestion chips above composer — U1: disabled while a query is
              in flight so a click can't silently overwrite the running draft. */}
          <div style={suggestionRow}>
            {SUGGESTION_CHIPS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setDraft(s)}
                style={suggestionChip}
                title={s}
                disabled={running}
              >
                {s}
              </button>
            ))}
          </div>

          {/* Composer */}
          <form
            style={composer}
            onSubmit={(e) => {
              e.preventDefault();
              if (!running && draft.trim()) run();
            }}
          >
            {/* A1 — visually-hidden but programmatically bound label. */}
            <label htmlFor="ask-composer-input" className="u-sr-only">
              Sorgunuzu yazın
            </label>
            <textarea
              id="ask-composer-input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  if (!running && draft.trim()) run();
                } else if (e.key === "Escape" && running) {
                  // U2 — Esc cancels the in-flight query.
                  e.preventDefault();
                  cancel();
                }
              }}
              rows={2}
              spellCheck={false}
              placeholder="Ask anything — DES on AAPL, find crypto opportunities, show my portfolio…"
              style={composerInput}
            />
            <div style={composerActions}>
              <button
                type="button"
                className="btn btn--ghost"
                style={composerSecondary}
                title="Attach context (coming soon)"
                disabled
              >
                + Attach
              </button>
              <span className="ask-run-hint">
                <span className="kbd">⌘↵</span> çalıştır · <span className="kbd">Esc</span> durdur
              </span>
              {running ? (
                // U2 — visible Stop affordance mirrors the Esc cancel.
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={cancel}
                  style={composerRun}
                  aria-label="Sorguyu durdur"
                  title="Sorguyu durdur (Esc)"
                  data-testid="ask-stop"
                >
                  Durdur
                </button>
              ) : null}
              <button
                type="submit"
                className="btn btn--accent"
                disabled={running || !draft.trim()}
                aria-busy={running}
                aria-label={
                  running
                    ? "Sorgu çalışıyor"
                    : !draft.trim()
                      ? "Çalıştırmak için önce bir sorgu yazın"
                      : "Sorguyu çalıştır"
                }
                title={
                  running
                    ? "Sorgu çalışıyor…"
                    : !draft.trim()
                      ? "Çalıştırmak için önce bir sorgu yazın"
                      : "Sorguyu çalıştır (⌘↵)"
                }
                style={composerRun}
              >
                {running ? "Çalışıyor…" : "Run"}
              </button>
            </div>
          </form>
        </PaneBody>
        <PaneFooter>
          <span>turns · {thread.filter((t) => t.role === "user").length}</span>
          <span>
            elapsed · {lastResult ? formatMs(lastResult.elapsed_ms) : "—"}
          </span>
          <span>cost · {formatCurrency(costSpentUsd, { fractionDigits: 4 })}</span>
          {lastResult?.warnings?.length ? (
            <span>{lastResult.warnings.length} warn</span>
          ) : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

function EmptyAskState() {
  return (
    <div style={emptyShell}>
      <div className="ask-empty-eyebrow">Conversational query</div>
      <h2 className="ask-empty-h2">What can I help you with?</h2>
      <p className="ask-empty-body">
        Bir soru yazın ya da bir öneri seçin. Sorgu planlanır, ilgili fonksiyonlar
        çalıştırılır ve yanıt bu çıktılardan DETERMİNİSTİK olarak derlenir
        (yapay zekâ yazımı değil); ardından derine inmek için bir panel önerilir.
      </p>
    </div>
  );
}

function ThinkingBubble() {
  return (
    <div style={agentRow}>
      <div style={agentBubbleLoading}>
        <span style={dotPulse} />
        <span style={dotPulse} />
        <span style={dotPulse} />
        <span className="ask-thinking-meta">
          planlanıyor · aranıyor · derleniyor
        </span>
      </div>
    </div>
  );
}

function ChatBubble({
  turn,
  expanded,
  onToggle,
  onOpen,
}: {
  turn: ChatTurn;
  expanded: boolean;
  onToggle: () => void;
  onOpen: (code: string, symbol?: string) => void;
}) {
  if (turn.role === "user") {
    return (
      <div style={userRow}>
        <div style={userBubble}>{turn.query}</div>
      </div>
    );
  }
  if (turn.error) {
    return (
      <div style={agentRow}>
        {/* A3 — failures are announced. */}
        <div style={agentBubble} role="status" aria-live="polite">
          <Empty title="Ask failed" body={turn.error} icon="!" />
        </div>
      </div>
    );
  }
  const r = turn.result;
  if (!r) return null;
  const llmPlanned = Boolean(r.was_llm_called && r.model_used);
  return (
    <div style={agentRow}>
      {/* A3 — a blocking request resolves once, so a single polite
          announcement on arrival (no streaming spam). */}
      <div style={agentBubble} role="status" aria-live="polite">
        {/* Plan summary chip row */}
        <div style={planChipRow}>
          {/* F3 — honest per-turn plan-method badge. */}
          <span data-testid="ask-plan-method">
            <Pill
              tone={llmPlanned ? "accent" : "muted"}
              variant="soft"
              withDot={false}
            >
              {llmPlanned ? `Plan: AI (${r.model_used})` : "Plan: kural-tabanlı"}
            </Pill>
          </span>
          <Pill tone="accent" variant="soft" withDot={false}>
            intent · {r.plan.intent}
          </Pill>
          {r.plan.action ? (
            <Pill tone="muted" variant="soft" withDot={false}>
              action · {r.plan.action}
            </Pill>
          ) : null}
          {r.phases.map((p) => (
            <Pill key={p.name} tone="muted" variant="soft" withDot={false}>
              {p.name} · {formatMs(p.elapsed_ms)}
            </Pill>
          ))}
        </div>

        {/* Narrative */}
        <p style={agentNarrative}>{r.narrative}</p>

        {/* Highlights with ACTIONABLE citation chips (A4). Each [n] resolves
            to the matching evidence ref's function code (by index, then the
            first available) and opens that pane on click/Enter/Space. */}
        {r.highlights.length > 0 ? (
          <div style={highlightRow}>
            {r.highlights.map((h, i) => {
              const ev = collectEvidence(r);
              const cite = ev[i] ?? ev[0];
              return (
                <HighlightWithCitation
                  key={`${h.label}-${i}`}
                  h={h}
                  index={i + 1}
                  code={cite?.code}
                  onOpen={onOpen}
                />
              );
            })}
          </div>
        ) : null}

        {/* Reasoning trace expandable */}
        <button type="button" onClick={onToggle} style={traceToggle} aria-expanded={expanded}>
          <span className="u-text-accent">{expanded ? "▾" : "▸"}</span>
          <span>{expanded ? "Hide reasoning trace" : "Show reasoning trace"}</span>
        </button>

        {expanded ? (
          <div style={tracePanel}>
            {/* Plan detail */}
            <Card variant="elev-2" density="compact">
              <CardHeader>Plan</CardHeader>
              <CardBody>
                <dl style={dlGrid}>
                  <dt style={DT}>intent</dt>
                  <dd style={DD}>
                    <Pill tone="accent" variant="soft" withDot={false}>
                      {r.plan.intent}
                    </Pill>
                  </dd>
                  <dt style={DT}>action</dt>
                  <dd style={DD}>{r.plan.action}</dd>
                  <dt style={DT}>agents</dt>
                  <dd style={DD}>
                    {r.plan.agents.length === 0 ? "—" : r.plan.agents.join(" → ")}
                  </dd>
                  <dt style={DT}>rationale</dt>
                  <dd style={DD} className="u-text-secondary">{r.plan.rationale}</dd>
                </dl>
              </CardBody>
            </Card>

            {/* Branch fan-out */}
            {r.search.branches ? (
              <Card variant="elev-2" density="compact">
                <CardHeader trailing={`${Object.keys(r.search.branches).length} legs`}>
                  Briefing branches
                </CardHeader>
                <CardBody>
                  <FanoutBranches branches={r.search.branches} onOpen={onOpen} />
                </CardBody>
              </Card>
            ) : null}

            {/* Evidence */}
            {collectEvidence(r).length > 0 ? (
              <Card variant="elev-2" density="compact">
                <CardHeader trailing={`${collectEvidence(r).length} refs`}>Evidence</CardHeader>
                <CardBody>
                  <EvidenceTable evidence={collectEvidence(r)} onOpen={onOpen} />
                </CardBody>
              </Card>
            ) : null}
          </div>
        ) : null}

        {/* Suggested view (always visible) */}
        <div style={vizRow}>
          <VizPanel result={r} onOpen={onOpen} />
        </div>
      </div>
    </div>
  );
}

function HighlightWithCitation({
  h,
  index,
  code,
  onOpen,
}: {
  h: AskHighlight;
  index: number;
  code?: string;
  onOpen?: (code: string, symbol?: string) => void;
}) {
  const tone =
    h.tone === "neutral"
      ? "muted"
      : (h.tone as "positive" | "negative" | "warn" | "muted");
  // A4 — when the citation resolves to a function code, the [n] chip is a
  // focusable button that opens that pane (keyboard via native <button>).
  const actionable = Boolean(code && onOpen);
  return (
    <span className="u-inline-flex u-items-center u-gap-4">
      <Pill tone={tone} variant="soft" withDot={false}>
        {h.label} · {h.value}
      </Pill>
      {actionable ? (
        <button
          type="button"
          style={citationButton}
          onClick={() => onOpen!(code!)}
          aria-label={`Kaynak [${index}] — ${code} panelini aç`}
          title={`Kaynak [${index}] · ${code} panelini aç`}
        >
          [{index}]
        </button>
      ) : (
        <span style={citationChip} title={`citation [${index}]`}>
          [{index}]
        </span>
      )}
    </span>
  );
}

function formatMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "—";
  if (ms > 0 && ms < 1) return "<1ms";
  return `${Math.max(1, Math.round(ms))}ms`;
}

function VizPanel({
  result,
  onOpen,
}: {
  result: AskResponse;
  onOpen: (code: string, symbol?: string) => void;
}) {
  const v = result.viz;
  if (v.kind === "none") {
    return (
      <span className="u-text-mute u-text-11">
        No visualization picked.
      </span>
    );
  }
  const hint = v.open_pane_hint;
  const panes = v.panes ?? (hint ? [hint] : []);
  return (
    <div className="u-flex u-gap-8 u-flex-wrap u-items-center">
      <Pill tone="muted" variant="soft" withDot={false}>
        viz · {v.kind}
      </Pill>
      {v.title ? (
        <Pill tone="muted" variant="soft" withDot={false}>
          {v.title}
        </Pill>
      ) : null}
      {v.rows_n != null ? (
        <Pill tone="muted" variant="soft" withDot={false}>
          {v.rows_n} rows
        </Pill>
      ) : null}
      <span className="u-flex-1" />
      {panes.map((p, i) => (
        <button
          key={`${p.code}-${p.symbol ?? "_"}-${i}`}
          type="button"
          className="btn btn--accent ask-open-btn"
          onClick={() => onOpen(p.code, p.symbol)}
        >
          Open {p.code}
          {p.symbol ? ` · ${p.symbol}` : ""}
        </button>
      ))}
    </div>
  );
}

function collectEvidence(result: AskResponse): AskEvidence[] {
  const direct = result.search.evidence ?? [];
  if (direct.length) return direct;
  const branches = result.search.branches ?? {};
  return Object.entries(branches).flatMap(([branch, value]) =>
    (value.evidence ?? []).map((item) => ({ branch, ...item })),
  );
}

function EvidenceTable({
  evidence,
  onOpen,
}: {
  evidence: AskEvidence[];
  onOpen?: (code: string, symbol?: string) => void;
}) {
  return (
    <div className="u-grid-gap-8">
      {evidence.map((item, index) => {
        const top = item.top?.filter(Boolean).slice(0, 4) ?? [];
        // A4 — each evidence ref opens its cited function/pane. The whole
        // [n]+code becomes a single focusable button when a code is present.
        const code = item.code && item.code !== "—" ? item.code : undefined;
        const actionable = Boolean(code && onOpen);
        return (
          <div
            key={`${item.branch ?? "root"}-${item.code ?? "?"}-${index}`}
            style={evidenceRow}
          >
            {actionable ? (
              <button
                type="button"
                style={citationButton}
                onClick={() => onOpen!(code!)}
                aria-label={`Kaynak [${index + 1}] — ${code} panelini aç`}
                title={`Kaynak [${index + 1}] · ${code} panelini aç`}
              >
                [{index + 1}]
              </button>
            ) : (
              <span style={citationChip} title={`reference [${index + 1}]`}>
                [{index + 1}]
              </span>
            )}
            <Pill tone="accent" variant="soft" withDot={false}>
              {item.branch ?? "root"}
            </Pill>
            {actionable ? (
              <button
                type="button"
                className="ask-evidence-code"
                style={evidenceCodeButton}
                onClick={() => onOpen!(code!)}
                aria-label={`${code} panelini aç`}
                title={`${code} panelini aç`}
              >
                {code}
              </button>
            ) : (
              <strong className="ask-evidence-code">{item.code ?? "—"}</strong>
            )}
            <span className="u-text-secondary u-text-10">
              {item.status ?? "ok"}
            </span>
            <span className="u-text-secondary u-text-10">
              {item.rows ?? 0} rows
            </span>
            <div className="ask-evidence-detail">
              <div className="ask-evidence-top" title={top.join(" · ")}>
                {top.length ? top.join(" · ") : item.reason ?? "No row evidence"}
              </div>
              <div className="ask-evidence-source">
                source · {(item.sources ?? []).join(" + ") || "—"} · elapsed ·{" "}
                {formatMs(item.elapsed_ms)}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

const DT: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
};
const DD: CSSProperties = {
  margin: 0,
  color: "var(--text-primary)",
  fontSize: 11,
};

// ── Fan-out branch render (briefing intent) ──────────────────────────────

const BRANCH_PANE: Record<string, { code: string; label: string }> = {
  portfolio: { code: "PORT", label: "Portfolio" },
  scan: { code: "SCAN", label: "Scan" },
  news: { code: "TOP", label: "News" },
};

function FanoutBranches({
  branches,
  onOpen,
}: {
  branches: Record<string, AskFanoutBranch>;
  onOpen: (code: string, symbol?: string) => void;
}) {
  const order = ["portfolio", "scan", "news"].filter((k) => branches[k]);
  return (
    <div
      className="ask-fanout-grid"
      style={{ ["--u-cols" as string]: `${order.length || 1}` }}
    >
      {order.map((key) => {
        const branch = branches[key];
        const meta = BRANCH_PANE[key] ?? { code: "HOME", label: key };
        const summary = describeBranch(key, branch);
        return (
          <div key={key} style={branchCard}>
            <header style={branchHeader}>
              <strong style={branchTitle}>{meta.label}</strong>
              <Pill tone={summary.tone} variant="soft" withDot={false}>
                {summary.tag}
              </Pill>
            </header>
            <p style={branchLine}>{summary.line}</p>
            {summary.bullets ? (
              <ul style={branchBullets}>
                {summary.bullets.slice(0, 5).map((b, i) => (
                  <li key={i}>{b}</li>
                ))}
              </ul>
            ) : null}
            <div className="ask-branch-action">
              <button
                type="button"
                className="btn btn--accent ask-branch-btn"
                onClick={() => onOpen(meta.code)}
              >
                Open {meta.code}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface BranchSummary {
  tag: string;
  tone: "neutral" | "positive" | "negative" | "warn" | "muted" | "accent";
  line: string;
  bullets?: string[];
}

function describeBranch(key: string, branch: AskFanoutBranch): BranchSummary {
  if (!branch || branch.kind === "error") {
    return {
      tag: "error",
      tone: "negative",
      line: (branch?.warnings ?? ["unknown error"]).slice(0, 1).join(" · "),
    };
  }
  const data = (branch.data ?? {}) as Record<string, unknown>;
  const inner =
    typeof data === "object" && data && "data" in data
      ? (data as { data?: unknown }).data
      : data;

  if (key === "portfolio") {
    const totals =
      inner && typeof inner === "object"
        ? ((inner as Record<string, unknown>).totals as
            | Record<string, unknown>
            | undefined)
        : undefined;
    const n = (totals?.n_positions as number | undefined) ?? 0;
    const mv = totals?.market_value as number | undefined;
    return {
      tag: `${n} pos`,
      tone: n > 0 ? "neutral" : "muted",
      line: mv
        ? `Market value ≈ $${Math.round(mv).toLocaleString()}`
        : "No live market value (book may be empty).",
    };
  }
  if (key === "scan") {
    const rows =
      inner && typeof inner === "object"
        ? ((inner as Record<string, unknown>).rows as
            | Array<Record<string, unknown>>
            | undefined)
        : undefined;
    const n = rows?.length ?? 0;
    if (!n) {
      return { tag: "empty", tone: "muted", line: "Scanner produced no candidates." };
    }
    const long = rows!.filter((r) => r.direction === "LONG").length;
    const short = rows!.filter((r) => r.direction === "SHORT").length;
    const top = rows!.slice(0, 5).map((r) => {
      const sym = String(r.symbol ?? "?");
      const dir = String(r.direction ?? "?")[0] ?? "?";
      const conf = typeof r.confidence === "number" ? r.confidence : 0;
      return `${sym} (${dir} ${conf.toFixed(0)})`;
    });
    return {
      tag: `${long}L / ${short}S`,
      tone: long >= short ? "positive" : "negative",
      line: `${n} candidates surfaced.`,
      bullets: top,
    };
  }
  if (key === "news") {
    let count = 0;
    let titles: string[] = [];
    if (Array.isArray(inner)) {
      count = inner.length;
      titles = inner
        .slice(0, 5)
        .map((it) =>
          typeof it === "object" && it
            ? String((it as Record<string, unknown>).title ?? "")
            : "",
        )
        .filter(Boolean);
    } else if (inner && typeof inner === "object") {
      const items = (inner as Record<string, unknown>).items;
      if (Array.isArray(items)) {
        count = items.length;
        titles = items
          .slice(0, 5)
          .map((it) =>
            typeof it === "object" && it
              ? String((it as Record<string, unknown>).title ?? "")
              : "",
          )
          .filter(Boolean);
      }
    }
    return {
      tag: `${count} headlines`,
      tone: count ? "neutral" : "muted",
      line: count ? "Latest headlines via TOP." : "No headlines pulled.",
      bullets: titles,
    };
  }
  return { tag: branch.kind ?? "data", tone: "muted", line: "(opaque)" };
}

// ─── styles ────────────────────────────────────────────────────────────

const headerTrailing: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
};

const statusStrip: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 0,
  height: 22,
  padding: "0 8px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  fontFamily: "JetBrains Mono, monospace",
};

const threadColumn: CSSProperties = {
  flex: "1 1 auto",
  minHeight: 0,
  overflow: "auto",
  padding: "16px 14px",
  display: "flex",
  flexDirection: "column",
  gap: 12,
  background: "var(--bg)",
};

const emptyShell: CSSProperties = {
  margin: "auto",
  textAlign: "center",
  padding: 32,
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
};

const userRow: CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
};

const userBubble: CSSProperties = {
  maxWidth: "78%",
  padding: "10px 14px",
  background: "var(--accent-soft)",
  border: "1px solid color-mix(in srgb, var(--accent) 40%, transparent)",
  borderRadius: "var(--radius-lg)",
  borderTopRightRadius: 4,
  color: "var(--text-primary)",
  fontSize: 12,
  lineHeight: 1.5,
  whiteSpace: "pre-wrap",
  overflowWrap: "anywhere",
};

const agentRow: CSSProperties = {
  display: "flex",
  justifyContent: "flex-start",
};

const agentBubble: CSSProperties = {
  maxWidth: "92%",
  width: "92%",
  padding: "12px 14px",
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderLeft: "2px solid var(--accent)",
  borderRadius: "var(--radius-lg)",
  borderTopLeftRadius: 4,
  display: "grid",
  gap: 10,
};

const agentBubbleLoading: CSSProperties = {
  ...agentBubble,
  display: "inline-flex",
  width: "auto",
  alignItems: "center",
  padding: "10px 14px",
  gap: 5,
};

const dotPulse: CSSProperties = {
  width: 6,
  height: 6,
  borderRadius: "50%",
  background: "var(--accent)",
  animation: "showme-ask-pulse 1.2s infinite ease-in-out",
};

const planChipRow: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
  alignItems: "center",
};

const agentNarrative: CSSProperties = {
  margin: 0,
  fontSize: 13,
  lineHeight: 1.55,
  color: "var(--text-primary)",
  whiteSpace: "pre-wrap",
  overflowWrap: "anywhere",
};

const highlightRow: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
  alignItems: "center",
};

const traceToggle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  width: "fit-content",
  padding: "4px 8px",
  background: "transparent",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-secondary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  cursor: "pointer",
};

const tracePanel: CSSProperties = {
  display: "grid",
  gap: 8,
  padding: 8,
  background: "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
};

const dlGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "84px 1fr",
  gap: "4px 10px",
  margin: 0,
};

const vizRow: CSSProperties = {
  paddingTop: 8,
  borderTop: "1px solid var(--border-subtle)",
};

const branchCard: CSSProperties = {
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  padding: 10,
  display: "flex",
  flexDirection: "column",
  gap: 6,
  minWidth: 0,
};

const branchHeader: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 6,
};

const branchTitle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--accent)",
};

const branchLine: CSSProperties = {
  margin: 0,
  fontSize: 11,
  lineHeight: 1.45,
  color: "var(--text-secondary)",
};

const branchBullets: CSSProperties = {
  margin: 0,
  paddingLeft: 14,
  fontSize: 10,
  color: "var(--text-secondary)",
  display: "flex",
  flexDirection: "column",
  gap: 2,
};

const evidenceRow: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "auto 90px 60px 60px 50px",
  gap: 6,
  alignItems: "center",
  borderBottom: "1px solid var(--border-subtle)",
  paddingBottom: 6,
};

const citationChip: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  minWidth: 22,
  height: 16,
  padding: "0 4px",
  borderRadius: 4,
  background: "var(--accent-soft)",
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  fontWeight: 600,
  letterSpacing: "0.02em",
};

// A4 — actionable variant of the citation chip (clickable/focusable button).
const citationButton: CSSProperties = {
  ...citationChip,
  border: "1px solid color-mix(in srgb, var(--accent) 40%, transparent)",
  cursor: "pointer",
};

const evidenceCodeButton: CSSProperties = {
  background: "transparent",
  border: "none",
  padding: 0,
  cursor: "pointer",
  textAlign: "left",
  textDecoration: "underline",
  textUnderlineOffset: 2,
};

const disclosureRow: CSSProperties = {
  margin: 0,
  padding: "6px 14px",
  borderTop: "1px solid var(--border-subtle)",
  background: "var(--surface-1)",
  color: "var(--text-mute)",
  fontSize: 10,
  lineHeight: 1.45,
};

const suggestionRow: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
  padding: "8px 14px",
  borderTop: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const suggestionChip: CSSProperties = {
  height: 24,
  padding: "0 10px",
  borderRadius: 12,
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-1)",
  color: "var(--text-secondary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  letterSpacing: "0.03em",
  cursor: "pointer",
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
  maxWidth: 220,
};

const composer: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
  padding: "8px 14px 12px",
  borderTop: "1px solid var(--border-subtle)",
  background: "var(--surface-1)",
};

const composerInput: CSSProperties = {
  width: "100%",
  resize: "vertical",
  minHeight: 48,
  background: "var(--surface-2)",
  color: "var(--text-primary)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
  padding: 10,
  outline: "none",
};

const composerActions: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const composerSecondary: CSSProperties = {
  height: 24,
  fontSize: 10,
  fontFamily: "JetBrains Mono, monospace",
};

const composerRun: CSSProperties = {
  height: 28,
  padding: "0 16px",
  fontWeight: 600,
};
