/**
 * ASK — ASKB-style natural-language query pane.
 *
 * Routes the query to the sidecar's `/api/ask` endpoint, renders the
 * planner's intent + rationale, the deterministic narrative, and the
 * Viz Agent's pane hint. Clicking "Open" on the hint pushes the suggested
 * pane (DES / FA / GP / PORT / SCAN) into the focused leaf.
 */
import { useState } from "react";
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
  Skeleton,
} from "@/design-system";
import {
  ask,
  type AskEvidence,
  type AskFanoutBranch,
  type AskHighlight,
  type AskResponse,
} from "@/lib/ask";
import { useWorkspace } from "@/lib/workspace";
import { navigate } from "@/lib/router";
import { FunctionControlGroup, LoadStatePill } from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

const SAMPLES = [
  "morning briefing — what should I watch",
  "find me crypto opportunities high conviction",
  "describe AAPL",
  "what's TSLA doing today",
  "show me my portfolio",
  "open FA on MSFT",
];

export function ASKPane({ code }: FunctionPaneProps) {
  const [query, setQuery] = useState(SAMPLES[0]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);

  const run = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const r = await ask(query);
      setResult(r);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  };

  const onOpenHint = (paneCode: string, symbol?: string) => {
    setFocusedTarget(paneCode, symbol);
    if (symbol) navigate(`/symbol/${symbol}/${paneCode}`);
    else navigate(`/fn/${paneCode}`);
  };

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="Ask Agent"
          subtitle={result ? result.plan.intent : "Planner · Search · Summarize · Viz"}
          trailing={
            <FunctionControlGroup>
              <LoadStatePill state={running ? "loading" : error ? "error" : result ? "ok" : "idle"} />
              <button
                type="button"
                className="btn btn--accent"
                onClick={run}
                disabled={running || !query.trim()}
                style={{ height: 24 }}
              >
                {running ? "Thinking..." : "Ask"}
              </button>
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  run();
                }
              }}
              rows={3}
              spellCheck={false}
              placeholder="Ask anything — DES on AAPL, find crypto opportunities, show my portfolio…"
              style={{
                width: "100%",
                resize: "vertical",
                background: "var(--bg-elev-2)",
                color: "var(--text-primary)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-md)",
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 12,
                padding: 8,
                outline: "none",
              }}
            />
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {SAMPLES.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => setQuery(s)}
                  style={{ fontSize: 10, fontFamily: "JetBrains Mono" }}
                >
                  {s}
                </button>
              ))}
              <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--text-mute)" }}>
                <span className="kbd">⌘↵</span> run
              </span>
            </div>

            {error && <Empty title="Ask failed" body={error} icon="!" />}
            {running && (
              <div style={{ display: "grid", gap: 6 }}>
                <Skeleton height={14} />
                <Skeleton height={14} width="80%" />
                <Skeleton height={14} width="65%" />
              </div>
            )}

            {result && !running && (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)",
                  gap: 14,
                }}
              >
                <Card>
                  <CardHeader
                    trailing={
                      <span style={{ display: "flex", gap: 4 }}>
                        {result.phases.map((p) => (
                          <Pill key={p.name} tone="muted" withDot={false}>
                            {p.name} · {formatMs(p.elapsed_ms)}
                          </Pill>
                        ))}
                      </span>
                    }
                  >
                    Narrative
                  </CardHeader>
                  <CardBody>
                    <p
                      style={{
                        margin: 0,
                        fontSize: 13,
                        lineHeight: 1.5,
                        color: "var(--text-primary)",
                      }}
                    >
                      {result.narrative}
                    </p>
                    {result.highlights.length > 0 && (
                      <div
                        style={{
                          display: "flex",
                          gap: 6,
                          marginTop: 10,
                          flexWrap: "wrap",
                        }}
                      >
                        {result.highlights.map((h) => (
                          <HighlightChip key={h.label} h={h} />
                        ))}
                      </div>
                    )}
                  </CardBody>
                </Card>

                <Card>
                  <CardHeader>Plan</CardHeader>
                  <CardBody>
                    <dl
                      style={{
                        display: "grid",
                        gridTemplateColumns: "80px 1fr",
                        gap: "4px 10px",
                        fontSize: 11,
                        margin: 0,
                      }}
                    >
                      <dt style={DT}>intent</dt>
                      <dd style={DD}>
                        <Pill tone="accent" withDot={false}>
                          {result.plan.intent}
                        </Pill>
                      </dd>
                      <dt style={DT}>action</dt>
                      <dd style={DD}>{result.plan.action}</dd>
                      <dt style={DT}>agents</dt>
                      <dd style={DD}>
                        {result.plan.agents.length === 0
                          ? "—"
                          : result.plan.agents.join(" → ")}
                      </dd>
                      <dt style={DT}>rationale</dt>
                      <dd style={{ ...DD, color: "var(--text-secondary)" }}>
                        {result.plan.rationale}
                      </dd>
                    </dl>
                  </CardBody>
                </Card>

                {result.search.branches && (
                  <Card style={{ gridColumn: "1 / -1" }}>
                    <CardHeader trailing={`${Object.keys(result.search.branches).length} legs`}>
                      Briefing branches
                    </CardHeader>
                    <CardBody>
                      <FanoutBranches
                        branches={result.search.branches}
                        onOpen={onOpenHint}
                      />
                    </CardBody>
                  </Card>
                )}

                {collectEvidence(result).length > 0 && (
                  <Card style={{ gridColumn: "1 / -1" }}>
                    <CardHeader trailing={`${collectEvidence(result).length} refs`}>
                      Evidence
                    </CardHeader>
                    <CardBody>
                      <EvidenceTable evidence={collectEvidence(result)} />
                    </CardBody>
                  </Card>
                )}

                <Card style={{ gridColumn: "1 / -1" }}>
                  <CardHeader>Suggested view</CardHeader>
                  <CardBody>
                    <VizPanel
                      result={result}
                      onOpen={onOpenHint}
                    />
                  </CardBody>
                </Card>
              </div>
            )}
          </div>
        </PaneBody>
        <PaneFooter>
          <span>elapsed · {result ? formatMs(result.elapsed_ms) : "—"}</span>
          {result?.warnings?.length ? (
            <span>{result.warnings.length} warn</span>
          ) : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

function formatMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "—";
  if (ms > 0 && ms < 1) return "<1ms";
  return `${Math.max(1, Math.round(ms))}ms`;
}

function HighlightChip({ h }: { h: AskHighlight }) {
  return (
    <Pill
      tone={
        h.tone === "neutral"
          ? "muted"
          : (h.tone as "positive" | "negative" | "warn" | "muted")
      }
      withDot={false}
    >
      {h.label} · {h.value}
    </Pill>
  );
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
      <span style={{ color: "var(--text-mute)", fontSize: 12 }}>
        No visualization picked.
      </span>
    );
  }
  const hint = v.open_pane_hint;
  const panes = v.panes ?? (hint ? [hint] : []);
  return (
    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
      <Pill tone="muted" withDot={false}>
        viz · {v.kind}
      </Pill>
      {v.title && (
        <Pill tone="muted" withDot={false}>
          {v.title}
        </Pill>
      )}
      {v.rows_n != null && (
        <Pill tone="muted" withDot={false}>
          {v.rows_n} rows
        </Pill>
      )}
      <div style={{ flex: 1 }} />
      {panes.map((p, i) => (
        <button
          key={`${p.code}-${p.symbol ?? "_"}-${i}`}
          type="button"
          className="btn btn--accent"
          onClick={() => onOpen(p.code, p.symbol)}
          style={{ height: 22, fontSize: 11 }}
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
    <div
      style={{
        display: "grid",
        gap: 8,
      }}
    >
      {evidence.map((item, index) => {
        const top = item.top?.filter(Boolean).slice(0, 4) ?? [];
        return (
          <div
            key={`${item.branch ?? "root"}-${item.code ?? "?"}-${index}`}
            style={{
              display: "grid",
              gridTemplateColumns: "90px 72px 82px 70px minmax(0, 1fr)",
              gap: 8,
              alignItems: "start",
              borderBottom: "1px solid var(--border-subtle)",
              paddingBottom: 8,
              fontSize: 11,
            }}
          >
            <Pill tone="accent" withDot={false}>
              {item.branch ?? "root"}
            </Pill>
            <strong style={{ color: "var(--accent)" }}>{item.code ?? "—"}</strong>
            <span style={{ color: "var(--text-secondary)" }}>
              {item.status ?? "ok"}
            </span>
            <span style={{ color: "var(--text-secondary)" }}>
              {item.rows ?? 0} rows
            </span>
            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  color: "var(--text-primary)",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={top.join(" · ")}
              >
                {top.length ? top.join(" · ") : item.reason ?? "No row evidence"}
              </div>
              <div style={{ color: "var(--text-mute)", marginTop: 2 }}>
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

const DT: React.CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
};
const DD: React.CSSProperties = {
  margin: 0,
  color: "var(--text-primary)",
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
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${order.length || 1}, minmax(0, 1fr))`,
        gap: 12,
      }}
    >
      {order.map((key) => {
        const branch = branches[key];
        const meta = BRANCH_PANE[key] ?? { code: "HOME", label: key };
        const summary = describeBranch(key, branch);
        return (
          <div
            key={key}
            style={{
              background: "var(--bg-elev-2)",
              border: "1px solid var(--border-subtle)",
              borderRadius: "var(--radius-md)",
              padding: 12,
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <header
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 8,
              }}
            >
              <strong
                style={{
                  fontFamily: "JetBrains Mono, monospace",
                  fontSize: 11,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  color: "var(--accent)",
                }}
              >
                {meta.label}
              </strong>
              <Pill
                tone={summary.tone}
                withDot={false}
              >
                {summary.tag}
              </Pill>
            </header>
            <p
              style={{
                margin: 0,
                fontSize: 12,
                lineHeight: 1.45,
                color: "var(--text-secondary)",
              }}
            >
              {summary.line}
            </p>
            {summary.bullets && (
              <ul
                style={{
                  margin: 0,
                  paddingLeft: 16,
                  fontSize: 11,
                  color: "var(--text-secondary)",
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                }}
              >
                {summary.bullets.slice(0, 5).map((b, i) => (
                  <li key={i}>{b}</li>
                ))}
              </ul>
            )}
            <div style={{ marginTop: "auto" }}>
              <button
                type="button"
                className="btn btn--accent"
                onClick={() => onOpen(meta.code)}
                style={{ height: 22, fontSize: 10, width: "100%" }}
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
