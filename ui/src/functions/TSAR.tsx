/**
 * TSAR — Transcript Sentiment Analyzer (+ archive search).
 *
 * The backend declares TSAR as "Transcript Sentiment Analyzer" (`news/tsar.py`):
 * pasted text → `_analyze` returns `summary/speaker_rollups/utterances`; the
 * legacy FTS archive surface (search/stats/ingest) is retained for the agent
 * runtime and back-compat. The pane therefore exposes BOTH modes via a VIEW
 * toggle:
 *
 *   Sentiment (default) — paste a transcript (or look one up by symbol) and
 *     score it; renders the dominant tone, speaker rollups and the utterance
 *     ladder, with an honest data_mode pill (live_official / modeled /
 *     not_configured).
 *   Search — the day-to-day FTS5 query over the local archive; never fires
 *     on mount so the empty-archive path cannot look like a broken render.
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
  Tabs,
} from "@/design-system";
import { runFunction, type FunctionCallResult } from "@/lib/functions";
import {
  FunctionControlGroup,
  LoadStatePill,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface TSARHit {
  id?: number;
  symbol?: string;
  company?: string;
  quarter?: string;
  fiscal_year?: string | number;
  event_date?: string;
  source?: string;
  url?: string;
  snippet?: string;
  summary?: string;
  sentiment?: string;
  status?: string;
}

interface TSARSummary {
  dominant_tone?: string;
  net_score?: number;
  management_score?: number;
  analyst_score?: number;
  utterance_count?: number;
  model_set?: string[];
  source?: string | null;
}

interface TSARSpeakerRollup {
  role?: string;
  speaker?: string;
  score?: number;
  count?: number;
  sentiment?: string;
}

interface TSARUtterance {
  position?: number;
  section?: string;
  speaker?: string;
  role?: string;
  utterance?: string;
  sentiment?: string;
  score?: number;
  model?: string;
}

interface TSARPayload {
  status?: string;
  reason?: string;
  query?: string;
  items?: TSARHit[];
  next_actions?: string[];
  data_mode?: string;
  summary?: TSARSummary;
  speaker_rollups?: TSARSpeakerRollup[];
  utterances?: TSARUtterance[];
  rows?: TSARUtterance[];
}

interface ArchiveStats {
  total?: number;
  by_symbol?: Record<string, number>;
  latest_event_date?: string;
}

const VIEWS = [
  { id: "sentiment", label: "Sentiment" },
  { id: "search", label: "Search" },
] as const;
type ViewId = (typeof VIEWS)[number]["id"];
const VIEW_IDS = VIEWS.map((v) => v.id);

export function TSARPane({ code, symbol }: FunctionPaneProps) {
  const [view, setView] = usePersistentOption<ViewId>(
    "showme.tsar-view",
    VIEW_IDS,
    "sentiment",
  );
  // — Search mode state —
  const [query, setQuery] = useState("");
  const [filterSymbol, setFilterSymbol] = useState(symbol ?? "");
  const [state, setState] = useState<"idle" | "loading" | "ok" | "error">("idle");
  const [result, setResult] = useState<FunctionCallResult<unknown> | null>(null);
  const [error, setError] = useState<Error | null>(null);
  // — Sentiment mode state —
  const [text, setText] = useState("");
  const [analysisResult, setAnalysisResult] = useState<FunctionCallResult<unknown> | null>(null);
  const [analysisState, setAnalysisState] = useState<"idle" | "loading" | "ok" | "error">("idle");
  const [analysisError, setAnalysisError] = useState<Error | null>(null);
  // — Archive stats (search mode) —
  const [stats, setStats] = useState<ArchiveStats | null>(null);
  const [statsState, setStatsState] = useState<"idle" | "loading" | "error">("idle");

  const payload = useMemo<TSARPayload>(() => {
    const d = result?.data;
    return d && typeof d === "object" && !Array.isArray(d) ? (d as TSARPayload) : {};
  }, [result]);

  const items = useMemo<TSARHit[]>(
    () => (Array.isArray(payload.items) ? payload.items : []),
    [payload.items],
  );

  const analysisPayload = useMemo<TSARPayload>(() => {
    const d = analysisResult?.data;
    return d && typeof d === "object" && !Array.isArray(d) ? (d as TSARPayload) : {};
  }, [analysisResult]);

  const summary = useMemo<TSARSummary>(
    () => analysisPayload.summary ?? {},
    [analysisPayload.summary],
  );
  const rollups = useMemo<TSARSpeakerRollup[]>(
    () => (Array.isArray(analysisPayload.speaker_rollups) ? analysisPayload.speaker_rollups : []),
    [analysisPayload.speaker_rollups],
  );
  const utterances = useMemo<TSARUtterance[]>(() => {
    const raw = Array.isArray(analysisPayload.utterances)
      ? analysisPayload.utterances
      : Array.isArray(analysisPayload.rows)
        ? analysisPayload.rows
        : [];
    return raw.filter((u): u is TSARUtterance => typeof u === "object" && u !== null);
  }, [analysisPayload.utterances, analysisPayload.rows]);

  const search = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      const params: Record<string, unknown> = { action: "search", query, limit: 50 };
      if (filterSymbol.trim()) params.symbol = filterSymbol.trim().toUpperCase();
      const res = await runFunction(code, { params });
      setResult(res);
      setState("ok");
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
      setState("error");
    }
  }, [code, query, filterSymbol]);

  // Analyzer path: the backend's DEFAULT route (no `action`) with pasted text
  // and/or a symbol lookup in the transcript archive.
  const analyze = useCallback(async () => {
    const pasted = text.trim();
    const sym = filterSymbol.trim() || symbol || "";
    if (!pasted && !sym) {
      setAnalysisState("error");
      setAnalysisError(
        new Error("Paste transcript text, or provide a symbol with an archived transcript."),
      );
      return;
    }
    setAnalysisState("loading");
    setAnalysisError(null);
    try {
      const params: Record<string, unknown> = {};
      if (pasted) params.text = text;
      if (sym) params.symbol = sym.toUpperCase();
      const res = await runFunction(code, { params });
      setAnalysisResult(res);
      setAnalysisState("ok");
    } catch (e) {
      setAnalysisError(e instanceof Error ? e : new Error(String(e)));
      setAnalysisState("error");
    }
  }, [code, text, filterSymbol, symbol]);

  const loadStats = useCallback(async () => {
    setStatsState("loading");
    try {
      const res = await runFunction(code, { params: { action: "stats" } });
      const d = res?.data;
      if (d && typeof d === "object" && !Array.isArray(d)) {
        setStats(d as ArchiveStats);
      }
      setStatsState("idle");
    } catch {
      setStats(null);
      setStatsState("error");
    }
  }, [code]);

  const cols = useMemo<DataGridColumn<TSARHit>[]>(
    () => [
      {
        key: "symbol",
        header: "Symbol",
        width: 90,
        render: (r) => (
          <span style={symbolCell}>{(r.symbol ?? "—").toUpperCase()}</span>
        ),
      },
      {
        key: "quarter",
        header: "Quarter",
        width: 100,
        render: (r) => (
          <span style={fiscalCell}>
            {r.quarter ?? "—"}
            {r.fiscal_year ? ` FY${r.fiscal_year}` : ""}
          </span>
        ),
      },
      {
        key: "event",
        header: "Event date",
        width: 110,
        render: (r) => (
          <span className="u-mono u-text-secondary" style={{ fontSize: "var(--font-size-xs)" }}>
            {r.event_date ?? "—"}
          </span>
        ),
      },
      {
        key: "snippet",
        header: "Match",
        render: (r) => {
          const text = r.snippet ?? r.summary ?? r.company ?? "—";
          return <span style={snippetCell}>{text}</span>;
        },
      },
      {
        key: "sentiment",
        header: "Sent.",
        width: 90,
        render: (r) =>
          r.sentiment ? (
            <Pill tone={sentimentTone(r.sentiment)} variant="soft" withDot={false}>
              {r.sentiment}
            </Pill>
          ) : (
            "—"
          ),
      },
      {
        key: "source",
        header: "Source",
        width: 160,
        render: (r) =>
          r.url ? (
            <a
              href={r.url}
              target="_blank"
              rel="noreferrer"
              style={linkStyle}
            >
              {r.source ?? "open"}
            </a>
          ) : (
            <span className="u-text-mute">{r.source ?? "—"}</span>
          ),
      },
    ],
    [],
  );

  const rollupCols = useMemo<DataGridColumn<TSARSpeakerRollup>[]>(
    () => [
      {
        key: "role",
        header: "Speaker role",
        width: 140,
        render: (r) => <span style={fiscalCell}>{r.role ?? r.speaker ?? "—"}</span>,
      },
      {
        key: "score",
        header: "Score",
        numeric: true,
        width: 90,
        render: (r) => (
          <span style={{ ...symbolCell, color: scoreTone(r.score) }}>
            {fmtScore(r.score)}
          </span>
        ),
      },
      {
        key: "count",
        header: "Utterances",
        numeric: true,
        width: 100,
        render: (r) => <span style={fiscalCell}>{r.count ?? "—"}</span>,
      },
      {
        key: "sentiment",
        header: "Tone",
        width: 100,
        render: (r) =>
          r.sentiment ? (
            <Pill tone={sentimentTone(r.sentiment)} variant="soft" withDot={false}>
              {r.sentiment}
            </Pill>
          ) : (
            "—"
          ),
      },
    ],
    [],
  );

  const utteranceCols = useMemo<DataGridColumn<TSARUtterance>[]>(
    () => [
      {
        key: "position",
        header: "#",
        numeric: true,
        width: 48,
        render: (r) => <span style={fiscalCell}>{r.position ?? "—"}</span>,
      },
      {
        key: "section",
        header: "Section",
        width: 120,
        render: (r) => (
          <Pill tone="muted" variant="soft" withDot={false}>
            {r.section ?? "—"}
          </Pill>
        ),
      },
      {
        key: "speaker",
        header: "Speaker",
        width: 140,
        render: (r) => <span style={symbolCell}>{r.speaker ?? "—"}</span>,
      },
      {
        key: "role",
        header: "Role",
        width: 110,
        render: (r) => <span style={fiscalCell}>{r.role ?? "—"}</span>,
      },
      {
        key: "score",
        header: "Score",
        numeric: true,
        width: 80,
        render: (r) => (
          <span style={{ ...symbolCell, color: scoreTone(r.score) }}>
            {fmtScore(r.score)}
          </span>
        ),
      },
      {
        key: "sentiment",
        header: "Tone",
        width: 100,
        render: (r) =>
          r.sentiment ? (
            <Pill tone={sentimentTone(r.sentiment)} variant="soft" withDot={false}>
              {r.sentiment}
            </Pill>
          ) : (
            "—"
          ),
      },
      {
        key: "utterance",
        header: "Utterance",
        render: (r) => <span style={snippetCell}>{r.utterance ?? "—"}</span>,
      },
    ],
    [],
  );

  const archiveEmpty =
    payload.status === "provider_unavailable" || items.some((i) => i.status === "archive_unavailable");

  const isSentiment = view === "sentiment";
  const activeState = isSentiment ? analysisState : state;
  const analysisStatus = analysisPayload.status;
  const analysisBlocked =
    analysisStatus === "not_configured" || analysisStatus === "no_text" || analysisStatus === "empty";
  const blockedReason =
    analysisPayload.next_actions?.[0] ??
    analysisPayload.reason ??
    "No transcript text was resolved.";

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={isSentiment ? "Transcript sentiment analyzer" : "Transcript search"}
          subtitle={
            isSentiment
              ? `${symbol ?? "pasted text"} · ${utterances.length} scored utterances · ${analysisPayload.data_mode ?? "—"}`
              : `FTS5 over local archive · ${items.length} hits · ${stats?.total ?? "—"} stored`
          }
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {isSentiment ? `${utterances.length} utt` : `${items.length} hits`}
              </Pill>
              {isSentiment ? (
                analysisPayload.data_mode ? (
                  <Pill
                    tone={analysisPayload.data_mode === "live_official" ? "positive" : "warn"}
                    variant="soft"
                    withDot={false}
                  >
                    {analysisPayload.data_mode}
                  </Pill>
                ) : null
              ) : (
                <>
                  <Pill tone="accent" variant="soft" withDot={false}>
                    {stats?.total ? `${stats.total} stored` : "stats?"}
                  </Pill>
                  {statsState === "error" ? (
                    <Pill tone="warn" variant="soft" withDot={false}>
                      stats failed
                    </Pill>
                  ) : null}
                  <button
                    type="button"
                    onClick={loadStats}
                    disabled={statsState === "loading"}
                    style={secondaryActionStyle}
                  >
                    {statsState === "loading" ? "Stats…" : "Stats"}
                  </button>
                </>
              )}
              <LoadStatePill state={activeState} />
              {isSentiment ? (
                <button
                  type="button"
                  onClick={analyze}
                  disabled={analysisState === "loading"}
                  style={primaryActionStyle}
                >
                  {analysisState === "loading" ? "Analyzing…" : "Analyze"}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={search}
                  disabled={state === "loading" || !query.trim()}
                  style={primaryActionStyle}
                >
                  {state === "loading" ? "Searching…" : "Search"}
                </button>
              )}
            </FunctionControlGroup>
          }
        />
        <div style={tabBarStyle}>
          <Tabs
            variant="segmented"
            items={VIEWS.map((v) => ({ id: v.id, label: v.label }))}
            active={view}
            onChange={(id) => setView(id as ViewId)}
          />
        </div>
        <PaneBody>
          <div className="u-grid-gap-14">
            {isSentiment ? (
              <section style={sentimentInputs} aria-label="Sentiment inputs">
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="Paste transcript text… e.g. `CEO: We grew revenue 20% YoY.`"
                  rows={5}
                  aria-label="Transcript text"
                  style={textareaStyle}
                />
                <div style={searchBar}>
                  <input
                    type="text"
                    value={filterSymbol}
                    onChange={(e) => setFilterSymbol(e.target.value)}
                    placeholder="Symbol (optional archive lookup)"
                    style={{ ...inputStyle, maxWidth: 240 }}
                  />
                </div>
              </section>
            ) : (
              <section style={searchBar} aria-label="Search inputs">
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search transcripts… e.g. guidance, margin, AI"
                  onKeyDown={(e) => e.key === "Enter" && search()}
                  style={inputStyle}
                />
                <input
                  type="text"
                  value={filterSymbol}
                  onChange={(e) => setFilterSymbol(e.target.value)}
                  placeholder="Symbol (optional)"
                  onKeyDown={(e) => e.key === "Enter" && search()}
                  style={{ ...inputStyle, maxWidth: 140 }}
                />
              </section>
            )}

            {isSentiment ? (
              analysisState === "loading" ? (
                <Skeleton height={300} />
              ) : analysisState === "error" ? (
                <Empty title="Function error" body={analysisError?.message ?? "—"} icon="!" />
              ) : analysisState !== "ok" ? (
                <Empty
                  title="No analysis yet"
                  body="Paste a transcript (or load one by symbol) and press Analyze."
                />
              ) : analysisBlocked ? (
                <div style={noticeStyle}>
                  <strong className="u-text-warn">
                    {analysisStatus === "not_configured"
                      ? "Analyzer not configured"
                      : analysisStatus === "no_text"
                        ? "No transcript text"
                        : "No scorable utterances"}
                  </strong>
                  <span className="u-text-secondary">{blockedReason}</span>
                </div>
              ) : (
                <div className="u-grid-gap-14">
                  <section style={kpiGrid} aria-label="TSAR sentiment KPI ribbon">
                    <StatCard
                      label="Dominant tone"
                      value={summary.dominant_tone ?? "—"}
                      caption={summary.source ?? "call tone"}
                      tone={
                        summary.dominant_tone === "positive"
                          ? "positive"
                          : summary.dominant_tone === "negative"
                            ? "negative"
                            : "neutral"
                      }
                    />
                    <StatCard
                      label="Net score"
                      value={fmtScore(summary.net_score)}
                      caption={`${summary.utterance_count ?? utterances.length} utterances`}
                      tone={scoreStatTone(summary.net_score)}
                    />
                    <StatCard
                      label="Management"
                      value={fmtScore(summary.management_score)}
                      caption="length-weighted"
                      tone={scoreStatTone(summary.management_score)}
                    />
                    <StatCard
                      label="Analyst"
                      value={fmtScore(summary.analyst_score)}
                      caption="length-weighted"
                      tone={scoreStatTone(summary.analyst_score)}
                    />
                  </section>
                  {rollups.length ? (
                    <section aria-label="Speaker polarity rollups">
                      <div style={sectionLabel}>Speaker polarity</div>
                      <DataGrid
                        columns={rollupCols}
                        rows={rollups}
                        rowKey={(r, i) => `${r.role ?? r.speaker ?? "role"}-${i}`}
                        density="compact"
                        ariaLabel="TSAR speaker rollups"
                      />
                    </section>
                  ) : null}
                  <section aria-label="Utterance ladder">
                    <div style={sectionLabel}>Utterance ladder</div>
                    <DataGrid
                      columns={utteranceCols}
                      rows={utterances}
                      rowKey={(r, i) => `${r.position ?? i}-${r.model ?? "m"}`}
                      density="compact"
                      ariaLabel="TSAR utterances"
                    />
                  </section>
                </div>
              )
            ) : state === "loading" ? (
              <Skeleton height={300} />
            ) : state === "error" ? (
              <Empty title="Function error" body={error?.message ?? "—"} icon="!" />
            ) : items.length === 0 ? (
              archiveEmpty ? (
                <div style={noticeStyle}>
                  <strong className="u-text-warn">Archive unavailable</strong>
                  <span className="u-text-secondary">
                    {payload.reason ??
                      "No stored transcript matches were found. Ingest transcripts via action=ingest first."}
                  </span>
                </div>
              ) : (
                <Empty
                  title="No results yet"
                  body={query ? `No hits for "${query}".` : "Enter a query and press Search."}
                />
              )
            ) : (
              <div className="u-grid-gap-14">
                <section style={kpiGrid} aria-label="TSAR KPI ribbon">
                  <StatCard
                    label="Hits"
                    value={`${items.length}`}
                    caption={`Query · "${truncate(query || "—", 22)}"`}
                    tone="neutral"
                  />
                  <StatCard
                    label="Unique symbols"
                    value={`${uniqueSymbols(items)}`}
                    caption={items[0]?.symbol ?? "—"}
                    tone="positive"
                  />
                  <StatCard
                    label="Archive total"
                    value={`${stats?.total ?? "—"}`}
                    caption={stats?.latest_event_date ?? "stats not loaded"}
                    tone="neutral"
                  />
                </section>
                <DataGrid
                  columns={cols}
                  rows={items}
                  rowKey={(r, i) => `${r.id ?? r.symbol ?? "row"}-${i}`}
                  density="compact"
                  ariaLabel="TSAR search hits"
                />
              </div>
            )}
          </div>
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="provider"
            value={
              isSentiment
                ? analysisResult?.sources?.join(", ") || "transcripts_archive"
                : result?.sources?.join(", ") || "transcripts_archive"
            }
          />
          <StatusDivider />
          <StatusSection
            label="query"
            value={isSentiment ? truncate(text.trim() || symbol || "—", 24) : query || "—"}
          />
          <StatusDivider />
          <StatusSection label="rows" value={isSentiment ? utterances.length : items.length} />
          <StatusDivider />
          <StatusSection label="archive" value={stats?.total ?? "—"} />
          <StatusDivider />
          <StatusSection
            label="status"
            value={isSentiment ? analysisPayload.status ?? analysisState : payload.status ?? state}
            tone="accent"
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function uniqueSymbols(items: TSARHit[]): number {
  return new Set(items.map((i) => (i.symbol ?? "").toUpperCase()).filter(Boolean)).size;
}

function sentimentTone(sentiment: string): "positive" | "negative" | "warn" | "muted" | "accent" {
  const lower = sentiment.toLowerCase();
  if (lower.includes("pos") || lower.includes("bull")) return "positive";
  if (lower.includes("neg") || lower.includes("bear")) return "negative";
  if (lower.includes("mixed") || lower.includes("neutral")) return "muted";
  return "accent";
}

function fmtScore(score: number | undefined | null): string {
  if (typeof score !== "number" || !Number.isFinite(score)) return "—";
  return `${score > 0 ? "+" : ""}${score.toFixed(2)}`;
}

function scoreTone(score: number | undefined): string {
  if (typeof score !== "number" || !Number.isFinite(score)) return "var(--text-secondary)";
  if (score > 0) return "var(--positive)";
  if (score < 0) return "var(--negative)";
  return "var(--text-secondary)";
}

function scoreStatTone(score: number | undefined): "positive" | "negative" | "neutral" {
  if (typeof score !== "number" || !Number.isFinite(score)) return "neutral";
  if (score > 0) return "positive";
  if (score < 0) return "negative";
  return "neutral";
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

const tabBarStyle: CSSProperties = {
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const sentimentInputs: CSSProperties = {
  display: "grid",
  gap: 8,
};

const textareaStyle: CSSProperties = {
  width: "100%",
  minHeight: 110,
  resize: "vertical",
  background: "var(--surface-2)",
  color: "var(--text-primary)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
  lineHeight: 1.5,
};

const sectionLabel: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  marginBottom: 6,
};

const searchBar: CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "center",
};

const inputStyle: CSSProperties = {
  flex: 1,
  minWidth: 0,
  background: "var(--surface-2)",
  color: "var(--text-primary)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "6px 10px",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
};

const symbolCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontWeight: 700,
  color: "var(--text-display)",
};

const fiscalCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-secondary)",
};

const snippetCell: CSSProperties = {
  display: "block",
  color: "var(--text-primary)",
  whiteSpace: "normal",
  fontSize: "var(--font-size-sm)",
};

const linkStyle: CSSProperties = {
  color: "var(--accent)",
  textDecoration: "none",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
};

const kpiGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
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

const secondaryActionStyle: CSSProperties = {
  background: "transparent",
  color: "var(--text-secondary)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "4px 10px",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
  fontWeight: 600,
  cursor: "pointer",
};
