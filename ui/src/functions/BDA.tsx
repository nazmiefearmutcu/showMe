/**
 * BDA — Bot Dev Assistant. Sub-system J.
 *
 * Layout: standard pane chrome (PaneHeader / PaneBody / PaneFooter).
 *  - Request card : strategy textarea + example fillers + Suggest /
 *                   Suggest + save actions.
 *  - Result card  : the generated rule spec rendered in STRA's visual
 *                   language (indicators / entry rules / exit rules /
 *                   position) plus severity-coded honesty notes.
 *  - Explain card : strategy picker fed from /api/strategies + rule-based
 *                   plain-English explanation.
 *
 * HONESTY: this pane is a keyword/regex helper, NOT a real NLP/LLM. The help
 * caption says so and the backend's "ignored concept" / "default disclosure"
 * notes are surfaced with severity styling (warn / info / negative) instead of
 * a flat gray list, so the user can see exactly what was understood, what was
 * defaulted, and what was silently dropped.
 */
import {
  useEffect, useRef, useState,
  type CSSProperties, type KeyboardEvent,
} from "react";
import {
  Empty, Pane, PaneBody, PaneFooter, PaneHeader, Pill, Skeleton,
  StatusDivider, StatusSection,
} from "@/design-system";
import { useAssistantStore } from "@/lib/assistant-store";
import { useStrategyStore } from "@/lib/strategy-store";
import { toast } from "@/lib/toast";
import {
  FunctionControlGroup, LoadStatePill, RefreshButton,
} from "./function-controls";
import type { LoadState } from "./function-control-state";

/** Indicators the keyword parser actually recognises (mirrors the backend
 * ``_KNOWN_INDICATORS`` table — keep accurate). */
const SUPPORTED_INDICATORS =
  "RSI, MACD, EMA, SMA, Bollinger, Stochastic, ATR, ADX, CCI, OBV, " +
  "Williams %R, VWAP, Ichimoku, PSAR, KDJ";

const HELP_CAPTION =
  "Keyword-based assistant \u2014 not real NLP. Recognized indicators: " +
  SUPPORTED_INDICATORS +
  ". Complex expressions (divergence, multi-indicator, risk sizing) are ignored. " +
  "KAOS Multibot — the default engine — runs without a rule spec; this assistant " +
  "is for the classic rule engine.";

/** One-click example fillers. Phrasings mirror the parser's supported
 * patterns, so clicking one yields a real spec (or honest notes). */
const EXAMPLES: { label: string; text: string }[] = [
  { label: "RSI 30/70", text: "buy RSI below 30, sell above 70, BTC/USDT 1h" },
  {
    label: "EMA cross",
    text: "buy when EMA 20 crosses above EMA 50, sell when EMA 20 crosses below EMA 50, ETH/USDT 4h",
  },
  {
    label: "MACD flip",
    text: "buy on MACD crosses above, exit on MACD crosses below, SOL/USDT 15m",
  },
];

type NoteTone = "warn" | "info" | "negative" | "neutral";

/** Classify a backend note string into a severity tone for honest styling.
 *
 * The backend emits ENGLISH notes ("catalog validation failed", "… is not
 * supported — ignored", "defaulted to 30/70"), so the classifier keys on
 * English tokens. A regression test pins each class so a translated note can
 * never silently downgrade a warning to neutral. */
function classifyNote(note: string): NoteTone {
  const low = note.toLowerCase();
  if (
    low.includes("failed") ||
    low.includes("validation") ||
    low.includes("catalog")
  ) {
    return "negative";
  }
  if (
    note.includes("⚠") ||
    low.includes("ignored") ||
    low.includes("not supported") ||
    low.includes("unsupported") ||
    low.includes("was used")
  ) {
    return "warn";
  }
  if (low.includes("default")) {
    return "info";
  }
  return "neutral";
}

const NOTE_CLASS: Record<NoteTone, string> = {
  warn: "u-text-warn",
  negative: "u-text-negative",
  info: "u-text-mute",
  neutral: "",
};

// ── House-style layout constants (mirroring STRA's editor sections) ────────

const BODY_STYLE: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
  gap: 12,
  padding: 12,
  overflowY: "auto",
  alignContent: "start",
  minHeight: 0,
};

const CARD_STYLE: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-2)",
  padding: 12,
  minWidth: 0,
  display: "flex",
  flexDirection: "column",
  gap: 10,
};

const SECTION_TITLE_STYLE: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-2xs)",
  letterSpacing: "var(--tracking-label)",
  textTransform: "uppercase",
  color: "var(--text-mute)",
};

const MONO_SMALL_STYLE: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-sm)",
};

const TEXTAREA_STYLE: CSSProperties = {
  width: "100%",
  minHeight: 110,
  resize: "vertical",
  background: "var(--surface-3)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  color: "var(--text-primary)",
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-sm)",
  lineHeight: 1.5,
  padding: "8px 10px",
  boxSizing: "border-box",
};

const CHIP_STYLE: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "2px 8px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "var(--surface-3)",
  fontFamily: "var(--font-mono)",
  fontSize: "var(--font-size-xs)",
  minWidth: 0,
};

const RULE_KIND_LABEL: Record<string, string> = {
  crosses_above: "crosses above",
  crosses_below: "crosses below",
  greater_than: "is greater than",
  less_than: "is less than",
  equals_approximately: "is approximately",
};

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
}

function asArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function asString(v: unknown): string {
  if (typeof v === "string") return v;
  if (v == null) return "";
  return String(v);
}

function formatOperand(raw: unknown): string {
  const s = asString(raw) || "—";
  return s.startsWith("literal:") ? s.slice("literal:".length) : s;
}

function indicatorParams(params: unknown): string {
  const rec = asRecord(params);
  return Object.entries(rec)
    .map(([k, v]) => `${k}=${asString(v)}`)
    .join(", ");
}

export function BDAPane() {
  const text = useAssistantStore((s) => s.text);
  const result = useAssistantStore((s) => s.result);
  const explanation = useAssistantStore((s) => s.explanation);
  const loadingGenerate = useAssistantStore((s) => s.loadingGenerate);
  const loadingExplain = useAssistantStore((s) => s.loadingExplain);
  const error = useAssistantStore((s) => s.error);
  const setText = useAssistantStore((s) => s.setText);
  const generate = useAssistantStore((s) => s.generate);
  const explainStrategy = useAssistantStore((s) => s.explainStrategy);

  const strategies = useStrategyStore((s) => s.strategies);
  const strategiesLoading = useStrategyStore((s) => s.loading);
  const loadStrategies = useStrategyStore((s) => s.loadList);

  const [selectedStrategy, setSelectedStrategy] = useState("");
  // Track the last result we cleared the box for, so the post-save clear
  // (and the save toast) fires exactly once per successful save.
  const lastClearedSavedId = useRef<string | null>(null);

  useEffect(() => { if (strategies.length === 0) loadStrategies(); },
            [strategies.length, loadStrategies]);

  // F3 — clear the textarea after a successful save (saved_id set) and
  // confirm the persist with a toast (same single-fire guard as the clear).
  useEffect(() => {
    const sid = result?.saved_id ?? null;
    if (sid && lastClearedSavedId.current !== sid) {
      lastClearedSavedId.current = sid;
      setText("");
      toast.success(
        "Strategy saved",
        `${sid.slice(0, 8)} — open the STRA pane to edit it.`,
      );
    }
  }, [result?.saved_id, setText]);

  const hasText = text.trim().length > 0;
  const generateTitle = !hasText
    ? "Strategy text required."
    : loadingGenerate
      ? "Generating strategy…"
      : undefined;
  const explainTitle = !selectedStrategy
    ? "A strategy must be selected."
    : loadingExplain
      ? "Loading explanation…"
      : undefined;
  const listState: LoadState =
    strategiesLoading && strategies.length === 0 ? "loading" : "ok";

  // F2/F3 — Cmd/Ctrl+Enter triggers generate from the textarea.
  function onTextKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      void runSuggest(false);
    }
  }

  /** Run a suggest; on a hard failure (store returns null after catching)
   * surface the inline error AND a toast so the failure is never silent. */
  async function runSuggest(save: boolean) {
    if (!hasText || loadingGenerate) return;
    const r = await generate(save);
    if (!r) {
      toast.error(
        "Strategy request failed",
        useAssistantStore.getState().error ?? "Assistant request failed.",
      );
    }
  }

  async function runExplain() {
    if (!selectedStrategy || loadingExplain) return;
    const e = await explainStrategy(selectedStrategy);
    if (e == null) {
      toast.error(
        "Explain request failed",
        useAssistantStore.getState().error ?? "Assistant request failed.",
      );
    }
  }

  const showGenerateSkeleton = loadingGenerate && !result;
  const showEmpty = !hasText && !result && !loadingGenerate;

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code="BDA"
          title="Bot dev assistant"
          subtitle={"keyword → strategy-spec helper (classic rule engine)"}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                keyword parser
              </Pill>
              <LoadStatePill state={listState} status={error ? "error" : "ok"} />
              <RefreshButton
                loading={strategiesLoading}
                onClick={() => void loadStrategies()}
                title="Reload strategy list"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody style={BODY_STYLE}>
          {/* ── Strategy request card ─────────────────────────────────── */}
          <section style={CARD_STYLE} aria-labelledby="bda-request-title">
            <span id="bda-request-title" style={SECTION_TITLE_STYLE}>Request</span>
            <p id="bda-help" data-testid="bda-help"
               style={{ color: "var(--text-secondary)",
                        fontSize: "var(--font-size-xs)",
                        lineHeight: 1.5, margin: 0 }}>
              {HELP_CAPTION}
            </p>

            <label htmlFor="bda-text" className="ds-field__label"
                   style={{ display: "block" }}>
              Strategy request
            </label>
            <textarea id="bda-text"
                      value={text}
                      onChange={(e) => setText(e.target.value)}
                      onKeyDown={onTextKeyDown}
                      rows={4}
                      style={TEXTAREA_STYLE}
                      placeholder='e.g. "buy RSI below 30, sell above 70, BTC/USDT 1h"'
                      aria-describedby={error ? "bda-help bda-error" : "bda-help"} />

            <div style={{ display: "flex", gap: 6, alignItems: "center",
                          flexWrap: "wrap" }}>
              <span style={SECTION_TITLE_STYLE}>Examples</span>
              {EXAMPLES.map((ex, i) => (
                <button
                  key={ex.label}
                  type="button"
                  className="btn btn--ghost"
                  data-testid={`bda-example-${i}`}
                  title={ex.text}
                  onClick={() => setText(ex.text)}
                  style={{ fontSize: "var(--font-size-2xs)", padding: "2px 8px" }}
                >
                  {ex.label}
                </button>
              ))}
            </div>

            <div style={{ display: "flex", gap: 8, alignItems: "center",
                          flexWrap: "wrap" }}>
              {/* H-UI-7 — only disable the generate buttons while generate
                  is in-flight, not when explain is running. */}
              <button type="button"
                      className="btn btn--accent"
                      onClick={() => void runSuggest(false)}
                      data-testid="bda-generate-button"
                      aria-busy={loadingGenerate}
                      aria-label={loadingGenerate ? "Generating…" : "Suggest strategy"}
                      title={generateTitle}
                      disabled={!hasText || loadingGenerate}>
                {loadingGenerate ? "…" : "Suggest strategy"}
              </button>
              <button type="button"
                      className="btn"
                      onClick={() => void runSuggest(true)}
                      data-testid="bda-generate-save-button"
                      aria-busy={loadingGenerate}
                      aria-label={loadingGenerate ? "Generating…" : "Suggest + save strategy"}
                      title={generateTitle}
                      disabled={!hasText || loadingGenerate}>
                {loadingGenerate ? "…" : "Suggest + save"}
              </button>
              {hasText && !loadingGenerate && (
                <button type="button"
                        className="btn btn--ghost"
                        data-testid="bda-clear-button"
                        onClick={() => setText("")}>
                  Clear
                </button>
              )}
              <span className="u-text-mute"
                    style={{ fontSize: "var(--font-size-2xs)" }}>
                ⌘/Ctrl+Enter
              </span>
            </div>

            {error && (
              <div id="bda-error" role="status"
                   data-testid="bda-error"
                   className="u-text-negative"
                   style={{ fontSize: "var(--font-size-sm)",
                            border: "1px solid var(--border-card)",
                            background: "var(--surface-3)",
                            borderRadius: "var(--radius-md)",
                            padding: "6px 8px" }}>
                {error}
              </div>
            )}
          </section>

          {/* ── Result card ───────────────────────────────────────────── */}
          <section style={CARD_STYLE} role="region"
                   aria-label="Strategy generation result" aria-live="polite"
                   data-testid="bda-result">
            <span style={SECTION_TITLE_STYLE}>Result</span>

            {/* F3 — initial empty state before the first parse. */}
            {showEmpty && (
              <div data-testid="bda-empty">
                <Empty
                  title="No strategy generated yet"
                  body="Type an indicator + condition in the request card (or pick an example), then press Suggest strategy."
                />
              </div>
            )}

            {/* F3 — loading skeleton while no previous result is on screen. */}
            {showGenerateSkeleton && (
              <div data-testid="bda-generate-loading"
                   style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <Skeleton height={16} />
                <Skeleton height={16} width="80%" />
                <Skeleton height={16} width="60%" />
              </div>
            )}

            {loadingGenerate && result && (
              <div data-testid="bda-result-refreshing" role="status"
                   className="u-text-mute" style={MONO_SMALL_STYLE}>
                ◌ updating…
              </div>
            )}

            {result && (
              <div style={{ display: "flex", flexDirection: "column", gap: 10,
                            minWidth: 0 }}>
                {result.saved_id && (
                  <div data-testid="bda-saved-indicator">
                    <Pill tone="positive">
                      Saved: {result.saved_id.slice(0, 8)} — edit it in the STRA pane
                    </Pill>
                  </div>
                )}

                {result.spec ? (
                  <SpecView spec={result.spec} />
                ) : (
                  <div data-testid="bda-no-spec" className="u-text-secondary"
                       style={{ fontSize: "var(--font-size-sm)" }}>
                    No spec was produced from this text — review the notes below
                    and adjust the request.
                  </div>
                )}

                <div>
                  <span style={SECTION_TITLE_STYLE}>Notes</span>
                  <ul style={{ fontSize: "var(--font-size-sm)", margin: "4px 0 0",
                               paddingLeft: 18, display: "flex",
                               flexDirection: "column", gap: 2 }}>
                    {result.notes.map((n, i) => {
                      const tone = classifyNote(n);
                      const isWarn = tone === "warn" || tone === "negative";
                      return (
                        <li key={i}
                            className={NOTE_CLASS[tone]}
                            data-testid={isWarn ? "bda-note-warn" : "bda-note"}
                            style={isWarn
                              ? { fontWeight: "var(--font-weight-semibold)" }
                              : undefined}>
                          {n}
                        </li>
                      );
                    })}
                  </ul>
                </div>

                {result.spec && (
                  <details>
                    <summary style={{ fontSize: "var(--font-size-xs)",
                                      color: "var(--text-secondary)",
                                      cursor: "pointer" }}>
                      Spec JSON (debug)
                    </summary>
                    <pre style={{ background: "var(--surface-3)", padding: 8,
                                  border: "1px solid var(--border-subtle)",
                                  borderRadius: "var(--radius-md)",
                                  fontFamily: "var(--font-mono)",
                                  fontSize: "var(--font-size-xs)",
                                  overflow: "auto", maxHeight: 240 }}>
                      {JSON.stringify(result.spec, null, 2)}
                    </pre>
                  </details>
                )}
              </div>
            )}
          </section>

          {/* ── Explain card (full width under the split) ─────────────── */}
          <section style={{ ...CARD_STYLE, gridColumn: "1 / -1" }}
                   aria-label="Explain strategy">
            <span style={SECTION_TITLE_STYLE}>Explain strategy</span>
            <p id="bda-explain-help"
               style={{ color: "var(--text-secondary)",
                        fontSize: "var(--font-size-xs)",
                        lineHeight: 1.5, margin: 0 }}>
              See a rule-based plain-English summary of a saved strategy —
              generated from the template, not AI-written.
            </p>

            {strategies.length === 0 && !strategiesLoading ? (
              <div data-testid="bda-explain-empty" className="u-text-mute"
                   style={{ fontSize: "var(--font-size-sm)" }}>
                No saved strategies yet — use Suggest + save, or create one in
                the STRA pane.
              </div>
            ) : (
              <div style={{ display: "flex", gap: 8, alignItems: "center",
                            flexWrap: "wrap" }}>
                <label htmlFor="bda-strategy-select"
                       style={{ fontSize: "var(--font-size-xs)",
                                color: "var(--text-secondary)" }}>
                  Strategy:
                </label>
                <select id="bda-strategy-select"
                        className="ds-field__input"
                        aria-label="Strategy to explain"
                        value={selectedStrategy}
                        onChange={(e) => setSelectedStrategy(e.target.value)}
                        style={{ maxWidth: 340 }}>
                  <option value="">— select —</option>
                  {strategies.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
                <button type="button"
                        className="btn"
                        onClick={() => void runExplain()}
                        data-testid="bda-explain-button"
                        aria-busy={loadingExplain}
                        aria-label={loadingExplain ? "Loading explanation…" : "Explain"}
                        title={explainTitle}
                        disabled={!selectedStrategy || loadingExplain}>
                  {loadingExplain ? "…" : "Explain"}
                </button>
              </div>
            )}

            {!explanation && strategies.length > 0 && (
              <div data-testid="bda-explain-hint" className="u-text-mute"
                   style={{ fontSize: "var(--font-size-sm)" }}>
                Pick a strategy and press Explain.
              </div>
            )}

            {explanation && (
              <div role="status" aria-live="polite"
                   data-testid="bda-explanation"
                   style={{ background: "var(--surface-3)",
                            border: "1px solid var(--border-subtle)",
                            borderRadius: "var(--radius-md)",
                            padding: 12, fontFamily: "var(--font-mono)",
                            fontSize: "var(--font-size-sm)", lineHeight: 1.5,
                            whiteSpace: "pre-wrap" }}>
                {renderInlineBold(explanation)}
              </div>
            )}
          </section>
        </PaneBody>
        <PaneFooter>
          <StatusSection label="parser" value="keyword" tone="muted" />
          <StatusDivider />
          <StatusSection label="strategies" value={strategies.length} />
          <StatusDivider />
          <StatusSection label="api" value="/api/assistant/*" tone="muted" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/**
 * Readable rendering of a generated spec — same visual language as the STRA
 * editor's indicator / rule / position sections, minus the editing controls.
 * Defensive against partial specs (the parser can return any subset).
 */
function SpecView({ spec }: { spec: Record<string, unknown> }) {
  const name = asString(spec.name) || "(unnamed spec)";
  const timeframe = asString(spec.timeframe) || "—";
  const description = asString(spec.description);
  const indicators = asArray(spec.indicators);
  const entryRules = asArray(spec.entry_rules);
  const exitRules = asArray(spec.exit_rules);
  const entryLogic = asString(spec.entry_logic) || "all";
  const exitLogic = asString(spec.exit_logic) || "any";
  const position = asRecord(spec.position);
  const assetFilter = asRecord(spec.asset_filter);
  const symbols = asArray(assetFilter.symbols).map(asString).filter(Boolean);

  const sizingValue = asString(position.sizing_value);
  const positionLine = [
    asString(position.side) || "long",
    `${asString(position.sizing_kind) || "fixed_quote"}${sizingValue ? ` ${sizingValue}` : ""}`,
    position.stop_loss_pct != null ? `SL ${asString(position.stop_loss_pct)}%` : null,
    position.take_profit_pct != null ? `TP ${asString(position.take_profit_pct)}%` : null,
    position.entry_order_type ? `entry ${asString(position.entry_order_type)}` : null,
  ].filter(Boolean).join(" · ");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10,
                  minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                    flexWrap: "wrap" }}>
        <strong data-testid="bda-spec-name"
                style={{ fontSize: "var(--font-size-md)" }}>
          {name}
        </strong>
        <Pill tone="muted" variant="soft" withDot={false}>
          <span data-testid="bda-spec-timeframe">{timeframe}</span>
        </Pill>
        {symbols.map((s) => (
          <span key={s} style={CHIP_STYLE}>{s}</span>
        ))}
      </div>
      {description && (
        <span className="u-text-secondary"
              style={{ fontSize: "var(--font-size-sm)" }}>
          {description}
        </span>
      )}

      <div>
        <span style={SECTION_TITLE_STYLE}>Indicators ({indicators.length})</span>
        <ul data-testid="bda-spec-indicators"
            style={{ listStyle: "none", margin: "4px 0 0", padding: 0,
                     display: "flex", gap: 6, flexWrap: "wrap" }}>
          {indicators.map((raw, i) => {
            const ind = asRecord(raw);
            const params = indicatorParams(ind.params);
            return (
              <li key={i} style={CHIP_STYLE}>
                <strong>{asString(ind.alias) || `indicator_${i + 1}`}</strong>
                <span className="u-text-mute">{asString(ind.id)}</span>
                {params && <span className="u-text-secondary">{params}</span>}
              </li>
            );
          })}
          {indicators.length === 0 && (
            <li className="u-text-mute" style={{ fontSize: "var(--font-size-sm)" }}>
              (none)
            </li>
          )}
        </ul>
      </div>

      <div>
        <span style={SECTION_TITLE_STYLE}>
          Entry rules ({entryRules.length}) · {entryLogic}
        </span>
        <ul data-testid="bda-spec-entries"
            style={{ listStyle: "none", margin: "4px 0 0", padding: 0,
                     display: "grid", gap: 3 }}>
          {entryRules.map((r, i) => <RuleLine key={i} rule={r} />)}
          {entryRules.length === 0 && (
            <li className="u-text-mute" style={{ fontSize: "var(--font-size-sm)" }}>
              (none)
            </li>
          )}
        </ul>
      </div>

      <div>
        <span style={SECTION_TITLE_STYLE}>
          Exit rules ({exitRules.length}) · {exitLogic}
        </span>
        <ul data-testid="bda-spec-exits"
            style={{ listStyle: "none", margin: "4px 0 0", padding: 0,
                     display: "grid", gap: 3 }}>
          {exitRules.map((r, i) => <RuleLine key={i} rule={r} />)}
          {exitRules.length === 0 && (
            <li className="u-text-mute" style={{ fontSize: "var(--font-size-sm)" }}>
              (none)
            </li>
          )}
        </ul>
      </div>

      <div>
        <span style={SECTION_TITLE_STYLE}>Position</span>
        <div data-testid="bda-spec-position"
             className="terminal-grid-numeric"
             style={{ ...MONO_SMALL_STYLE, marginTop: 4 }}>
          {positionLine}
        </div>
      </div>
    </div>
  );
}

/** One humanized rule row: `rsi14 crosses below 30.0`. */
function RuleLine({ rule }: { rule: unknown }) {
  const r = asRecord(rule);
  const kind = asString(r.kind);
  const label = RULE_KIND_LABEL[kind] ?? (kind ? kind.replace(/_/g, " ") : "—");
  return (
    <li data-testid="bda-rule"
        style={{ ...MONO_SMALL_STYLE, display: "flex", gap: 6,
                 flexWrap: "wrap" }}>
      <span>{formatOperand(r.left)}</span>
      <span className="u-text-mute">{label}</span>
      <span>{formatOperand(r.right)}</span>
    </li>
  );
}

/**
 * Minimal inline-markdown renderer for the backend explanation: the rule
 * engine emits ``**name**`` for the strategy name. Everything else stays
 * verbatim text (deterministic, no markdown lib).
 */
function renderInlineBold(text: string) {
  const parts = text.split("**");
  if (parts.length === 1) return text;
  return parts.map((part, i) =>
    i % 2 === 1
      ? <strong key={i}>{part}</strong>
      : <span key={i}>{part}</span>,
  );
}

export default BDAPane;
