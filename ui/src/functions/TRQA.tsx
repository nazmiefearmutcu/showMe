/**
 * TRQA — Transcript Q&A.
 *
 * The sidecar accepts a transcript (`text` / `audio_url` / `audio_path`)
 * plus a `questions[]` list, runs them through the LLM router, and falls
 * back to a local extractive ranker when no router is configured. The
 * pane gives the user a textarea + question list, a "Run" trigger, and
 * a Q&A grid with model / confidence / cost columns. We start in
 * `enabled: false` so the sidecar isn't called with an empty transcript
 * on mount; the user explicitly hits Run.
 */
import { useCallback, useMemo, useState, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { runFunction, type FunctionCallResult } from "@/lib/functions";
import {
  FunctionControlGroup,
  LoadStatePill,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface TRQAAnswer {
  q?: string;
  a?: string;
  evidence?: string;
  confidence?: number;
  model?: string;
  cost_usd?: number;
  tokens?: number;
}

interface TRQAPayload {
  status?: string;
  reason?: string;
  text_chars?: number;
  answers?: TRQAAnswer[];
  total_cost_usd?: number;
  next_actions?: string[];
}

const DEFAULT_QUESTIONS = [
  "What was the headline revenue and EPS for the quarter?",
  "Did the company raise or lower full-year guidance, and by how much?",
  "What were the most-discussed risks or headwinds?",
  "Quote the CEO's most forward-looking statement.",
  "What capital allocation moves (buybacks, dividends, M&A) were mentioned?",
];

export function TRQAPane({ code }: FunctionPaneProps) {
  const [text, setText] = useState("");
  const [questionsRaw, setQuestionsRaw] = useState(DEFAULT_QUESTIONS.join("\n"));
  const [state, setState] = useState<"idle" | "loading" | "ok" | "error">("idle");
  const [result, setResult] = useState<FunctionCallResult<unknown> | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const payload = useMemo<TRQAPayload>(() => {
    const d = result?.data;
    return d && typeof d === "object" && !Array.isArray(d) ? (d as TRQAPayload) : {};
  }, [result]);

  const answers = useMemo<TRQAAnswer[]>(
    () => (Array.isArray(payload.answers) ? payload.answers : []),
    [payload.answers],
  );

  const run = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      const questions = questionsRaw
        .split("\n")
        .map((q) => q.trim())
        .filter(Boolean);
      const res = await runFunction(code, {
        params: { text, questions },
      });
      setResult(res);
      setState("ok");
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
      setState("error");
    }
  }, [code, questionsRaw, text]);

  const cols = useMemo<DataGridColumn<TRQAAnswer>[]>(
    () => [
      {
        key: "q",
        header: "Question",
        width: 280,
        render: (r) => (
          <span style={questionCell}>{r.q ?? "—"}</span>
        ),
      },
      {
        key: "a",
        header: "Answer",
        render: (r) => (
          <span style={answerCell}>
            {r.a ?? "—"}
            {r.evidence && r.evidence !== r.a ? (
              <span className="u-text-mute" style={evidenceLine}>
                — {r.evidence}
              </span>
            ) : null}
          </span>
        ),
      },
      {
        key: "model",
        header: "Model",
        width: 130,
        render: (r) => (
          <Pill
            tone={r.model === "local_extractive" ? "warn" : "accent"}
            variant="soft"
            withDot={false}
          >
            {r.model ?? "—"}
          </Pill>
        ),
      },
      {
        key: "confidence",
        header: "Conf.",
        numeric: true,
        width: 80,
        render: (r) =>
          r.confidence == null ? "—" : (
            <span style={numCell}>{(r.confidence * 100).toFixed(0)}%</span>
          ),
      },
      {
        key: "cost",
        header: "Cost",
        numeric: true,
        width: 90,
        render: (r) =>
          r.cost_usd ? (
            <span style={numCell}>${r.cost_usd.toFixed(4)}</span>
          ) : (
            <span className="u-text-mute">free</span>
          ),
      },
    ],
    [],
  );

  const usedLocal = answers.some((a) => a.model === "local_extractive");
  const needsInput = !text.trim() && payload.status === "input_required";

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Transcript Q&A"
          subtitle={`${answers.length} answers · ${payload.text_chars ?? text.length} chars · cost $${(payload.total_cost_usd ?? 0).toFixed(4)}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>{answers.length} Q</Pill>
              <Pill tone={usedLocal ? "warn" : "accent"} variant="soft">
                {usedLocal ? "local extractive" : answers.length ? "LLM" : "idle"}
              </Pill>
              <LoadStatePill state={state} />
              <button
                type="button"
                onClick={run}
                disabled={state === "loading" || !text.trim()}
                style={primaryActionStyle}
              >
                {state === "loading" ? "Running…" : "Run Q&A"}
              </button>
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <div className="u-grid-gap-14">
            <section style={formSection} aria-label="Transcript and questions">
              <label style={fieldLabel} htmlFor="trqa-text">
                Transcript text
                <span className="u-text-mute" style={hintText}>
                  Paste an earnings call transcript or other source text. Audio
                  URLs/paths can be passed via the Advanced params surface.
                </span>
              </label>
              <textarea
                id="trqa-text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Paste earnings call transcript here…"
                style={textareaStyle}
                rows={10}
              />
              <label style={fieldLabel} htmlFor="trqa-questions">
                Questions
                <span className="u-text-mute" style={hintText}>
                  One question per line · {questionsRaw.split("\n").filter((q) => q.trim()).length} queued
                </span>
              </label>
              <textarea
                id="trqa-questions"
                value={questionsRaw}
                onChange={(e) => setQuestionsRaw(e.target.value)}
                style={textareaStyle}
                rows={6}
              />
            </section>
            {state === "loading" ? (
              <Skeleton height={180} />
            ) : state === "error" ? (
              <Empty title="Function error" body={error?.message ?? "—"} icon="!" />
            ) : answers.length === 0 ? (
              needsInput ? (
                <div style={noticeStyle}>
                  <strong className="u-text-warn">Transcript required</strong>
                  <span className="u-text-secondary">
                    {payload.reason ??
                      "TRQA needs transcript text, audio_url, or audio_path before it can answer."}
                  </span>
                </div>
              ) : (
                <Empty
                  title="No answers yet"
                  body="Paste a transcript, add a question, and hit Run Q&A."
                />
              )
            ) : (
              <div className="u-grid-gap-14">
                {usedLocal ? (
                  <div style={warningBox}>
                    <strong className="u-text-warn">Local extractive fallback</strong>
                    <span className="u-text-secondary">
                      The LLM router returned no usable answer; rows are produced
                      by the local extractive ranker (regex sentence scoring).
                      Configure an LLM provider for grounded Q&A.
                    </span>
                  </div>
                ) : null}
                <section style={kpiGrid} aria-label="TRQA KPI ribbon">
                  <StatCard
                    label="Answers"
                    value={`${answers.length}`}
                    caption={`Transcript ${payload.text_chars ?? text.length} chars`}
                    tone="neutral"
                  />
                  <StatCard
                    label="Avg confidence"
                    value={`${(avgConfidence(answers) * 100).toFixed(0)}%`}
                    caption={`${answers.filter((a) => (a.confidence ?? 0) >= 0.6).length} above 60%`}
                    tone="positive"
                  />
                  <StatCard
                    label="Total cost"
                    value={`$${(payload.total_cost_usd ?? 0).toFixed(4)}`}
                    caption={`${answers.reduce((s, a) => s + (a.tokens ?? 0), 0).toLocaleString()} tokens`}
                    tone="neutral"
                  />
                </section>
                <DataGrid
                  columns={cols}
                  rows={answers}
                  rowKey={(r, i) => `${r.q ?? "row"}-${i}`}
                  density="compact"
                />
              </div>
            )}
          </div>
        </PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={result?.sources?.join(", ") || "—"} />
          <StatusDivider />
          <StatusSection label="answers" value={answers.length} />
          <StatusDivider />
          <StatusSection label="tokens" value={answers.reduce((s, a) => s + (a.tokens ?? 0), 0)} />
          <StatusDivider />
          <StatusSection label="cost" value={`$${(payload.total_cost_usd ?? 0).toFixed(4)}`} />
          <StatusDivider />
          <StatusSection label="status" value={payload.status ?? state} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function avgConfidence(answers: TRQAAnswer[]): number {
  const valid = answers.filter((a) => typeof a.confidence === "number");
  if (!valid.length) return 0;
  return valid.reduce((s, a) => s + (a.confidence ?? 0), 0) / valid.length;
}

const formSection: CSSProperties = {
  display: "grid",
  gap: 6,
};

const fieldLabel: CSSProperties = {
  display: "grid",
  gap: 2,
  fontFamily: "JetBrains Mono, monospace",
  fontWeight: 600,
  color: "var(--text-display)",
  fontSize: "var(--font-size-sm)",
};

const hintText: CSSProperties = {
  fontSize: "var(--font-size-xs)",
  fontWeight: 400,
};

const textareaStyle: CSSProperties = {
  width: "100%",
  background: "var(--surface-2)",
  color: "var(--text-primary)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
  resize: "vertical",
};

const questionCell: CSSProperties = {
  display: "block",
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-display)",
  fontWeight: 600,
  whiteSpace: "normal",
};

const answerCell: CSSProperties = {
  display: "block",
  color: "var(--text-primary)",
  whiteSpace: "normal",
  fontSize: "var(--font-size-sm)",
};

const evidenceLine: CSSProperties = {
  display: "block",
  marginTop: 4,
  fontSize: "var(--font-size-xs)",
  fontStyle: "italic",
};

const numCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
};

const kpiGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const noticeStyle: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  background: "var(--warn-soft)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
};

const warningBox: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 30%, transparent)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
  display: "grid",
  gap: 4,
};

const primaryActionStyle: CSSProperties = {
  background: "var(--accent)",
  color: "var(--accent-on)",
  border: "1px solid var(--accent)",
  borderRadius: "var(--radius-sm)",
  padding: "4px 12px",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
  fontWeight: 700,
  cursor: "pointer",
  textTransform: "uppercase",
  letterSpacing: "0.05em",
};
