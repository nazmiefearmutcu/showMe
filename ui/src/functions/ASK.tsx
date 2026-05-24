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
const ASK_MODEL_LABEL = "claude-sonnet-4.6";

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
      // Approximate cost: each phase ~ $0.005 baseline + 0.0005/ms blended
      const elapsed = Number(r.elapsed_ms ?? 0);
      const incr = Math.min(0.05, 0.005 + elapsed * 0.000_05);
      setCostSpentUsd((prev) => Math.min(COST_CAP_USD, prev + incr));
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
          title="Ask Agent"
          subtitle={lastResult ? lastResult.plan.intent : "Planner · Search · Summarize · Viz"}
          trailing={
            <div style={headerTrailing}>
              <Pill tone="accent" variant="soft" withDot={false}>
                {ASK_MODEL_LABEL}
              </Pill>
              <Pill tone={costTone} variant="soft" withDot={false}>
                ${costSpentUsd.toFixed(3)} / ${COST_CAP_USD.toFixed(2)}
              </Pill>
              <Pill
                tone={running ? "warn" : "muted"}
                variant="soft"
                withDot={running}
              >
                {running ? "thinking" : "ready"}
              </Pill>
            </div>
          }
        />
        {/* Status strip with model + cost detail */}
        <section style={statusStrip}>
          <StatusSection label="MODEL" value={ASK_MODEL_LABEL} tone="accent" withDot />
          <StatusDivider />
          <StatusSection label="COST" value={`$${costSpentUsd.toFixed(3)}`} tone={costTone} />
          <StatusDivider />
          <StatusSection label="CAP" value={`$${COST_CAP_USD.toFixed(2)}`} tone="muted" />
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

          {/* Suggestion chips above composer */}
          <div style={suggestionRow}>
            {SUGGESTION_CHIPS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setDraft(s)}
                style={suggestionChip}
                title={s}
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
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  if (!running && draft.trim()) run();
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
                <span className="kbd">⌘↵</span> run
              </span>
              <button
                type="submit"
                className="btn btn--accent"
                disabled={running || !draft.trim()}
                style={composerRun}
              >
                {running ? "Thinking…" : "Run"}
              </button>
            </div>
          </form>
        </PaneBody>
        <PaneFooter>
          <span>turns · {thread.filter((t) => t.role === "user").length}</span>
          <span>
            elapsed · {lastResult ? formatMs(lastResult.elapsed_ms) : "—"}
          </span>
          <span>cost · ${costSpentUsd.toFixed(3)}</span>
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
        Type a question below or pick a suggestion. The agent will plan, search, and summarize, then
        suggest a pane to dig deeper.
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
          planning · searching · summarizing
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
        <div style={agentBubble}>
          <Empty title="Ask failed" body={turn.error} icon="!" />
        </div>
      </div>
    );
  }
  const r = turn.result;
  if (!r) return null;
  return (
    <div style={agentRow}>
      <div style={agentBubble}>
        {/* Plan summary chip row */}
        <div style={planChipRow}>
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

        {/* Highlights with citation chips */}
        {r.highlights.length > 0 ? (
          <div style={highlightRow}>
            {r.highlights.map((h, i) => (
              <HighlightWithCitation key={`${h.label}-${i}`} h={h} index={i + 1} />
            ))}
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
                  <EvidenceTable evidence={collectEvidence(r)} />
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

function HighlightWithCitation({ h, index }: { h: AskHighlight; index: number }) {
  const tone =
    h.tone === "neutral"
      ? "muted"
      : (h.tone as "positive" | "negative" | "warn" | "muted");
  return (
    <span className="u-inline-flex u-items-center u-gap-4">
      <Pill tone={tone} variant="soft" withDot={false}>
        {h.label} · {h.value}
      </Pill>
      <span style={citationChip} title={`citation [${index}]`}>
        [{index}]
      </span>
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

function EvidenceTable({ evidence }: { evidence: AskEvidence[] }) {
  return (
    <div className="u-grid-gap-8">
      {evidence.map((item, index) => {
        const top = item.top?.filter(Boolean).slice(0, 4) ?? [];
        return (
          <div
            key={`${item.branch ?? "root"}-${item.code ?? "?"}-${index}`}
            style={evidenceRow}
          >
            <span style={citationChip} title={`reference [${index + 1}]`}>
              [{index + 1}]
            </span>
            <Pill tone="accent" variant="soft" withDot={false}>
              {item.branch ?? "root"}
            </Pill>
            <strong className="ask-evidence-code">{item.code ?? "—"}</strong>
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
