/**
 * TLDR — Daily TL;DR digest.
 *
 * The backend composes live quotes + top news + the economic calendar and
 * asks the cheapest configured LLM for a 5-bullet markdown briefing (a
 * deterministic local template when no LLM answered in the latency budget).
 * Header: symbol-scope input (persisted) + status pills + refresh. Body:
 * count KPI ribbon, the markdown briefing (pre-wrapped prose — no markdown
 * renderer by design), quote movers table with per-quote source stamps,
 * news headline bullets, calendar events, and a generated-at stamp.
 *
 * Honesty: news items arrive as plain titles (no per-item URLs in the
 * payload), so headlines render WITHOUT invented links; the summary-model
 * pill states "local template" when the LLM leg did not respond.
 */
import { useMemo, useState, type CSSProperties, type FormEvent } from "react";
import {
  ChangeText,
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
import { usePersistentString } from "./function-control-state";
import { formatNumber } from "@/lib/format";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface TLDRQuote {
  symbol?: string;
  last?: number | null;
  change_pct?: number | null;
  quote_source?: string;
}

interface TLDREvent {
  Country?: string;
  Event?: string;
  [key: string]: unknown;
}

interface TLDRData {
  status?: string;
  reason?: string;
  next_actions?: string[];
  markdown?: string;
  quotes?: TLDRQuote[];
  news?: string[];
  events?: TLDREvent[];
  watchlist?: string[];
  summary_model?: string;
  quote_count?: number;
  mover_count?: number;
}

const SYMBOLS_STORAGE_KEY = "showme.tldr.symbols";

export function TLDRPane({ code, symbol }: FunctionPaneProps) {
  // Free-text scope: persisted last value wins; a freshly opened symbol
  // prefills the box only when nothing was persisted yet. Empty scope =
  // server-side portfolio + watchlist mode.
  const [applied, setApplied] = usePersistentString(
    SYMBOLS_STORAGE_KEY, symbol ? symbol.toUpperCase() : "",
  );
  const [draft, setDraft] = useState<string>(applied);

  const { state, data, error, refetch } = useFunction<TLDRData>({
    code,
    params: {
      ...(applied ? { symbols: applied } : {}),
      timeout: 9,
      // Leave latency budget for the news/calendar/LLM legs after quotes.
      quote_timeout: 2.5,
    },
  });

  const payload = data?.data;
  const status = payload?.status ?? "ok";
  const quotes = useMemo(() => payload?.quotes ?? [], [payload]);
  const news = useMemo(() => payload?.news ?? [], [payload]);
  const events = useMemo(() => payload?.events ?? [], [payload]);
  const markdown = payload?.markdown ?? "";
  const summaryModel = payload?.summary_model ?? data?.metadata?.summary_model;
  const isLlmSummary =
    typeof summaryModel === "string" && summaryModel.startsWith("llm:");
  const generatedAt = data?.asOf ?? data?.fetched_at;
  const isLive = state === "ok" && status !== "provider_unavailable";

  function applyScope(event: FormEvent) {
    event.preventDefault();
    const next = draft.trim().toUpperCase();
    setDraft(next);
    setApplied(next);
  }

  const QUOTE_COLS: DataGridColumn<TLDRQuote>[] = useMemo(
    () => [
      {
        key: "symbol",
        header: "Symbol",
        width: 120,
        render: (r) => <span style={monoStrongStyle}>{r.symbol ?? "—"}</span>,
      },
      {
        key: "last",
        header: "Last",
        numeric: true,
        width: 120,
        render: (r) => <span style={monoPrimaryStyle}>{fmtNum(r.last)}</span>,
      },
      {
        key: "change_pct",
        header: "Change",
        numeric: true,
        width: 100,
        render: (r) => (
          <ChangeText value={r.change_pct ?? null} suffix="%" />
        ),
      },
      {
        key: "quote_source",
        header: "Source",
        width: 150,
        render: (r) =>
          r.quote_source ? (
            <Pill tone="muted" variant="soft" withDot={false}>
              {r.quote_source}
            </Pill>
          ) : (
            <span className="u-text-mute">no quote</span>
          ),
      },
    ],
    [],
  );

  const hasDigest = Boolean(markdown) || quotes.length > 0 || news.length > 0;

  const body =
    state === "loading" || state === "idle" ? (
      <div className="u-grid-gap-8">
        <Skeleton height={56} />
        <Skeleton height={120} />
        <Skeleton height={20} width="70%" />
      </div>
    ) : state === "error" ? (
      <Empty
        title="Function error"
        body={error?.message ?? "—"}
        icon="!"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : status === "provider_unavailable" || !hasDigest ? (
      <Empty
        title="No digest available"
        body={
          payload?.reason ??
          "TLDR providers returned no usable quote, news, calendar, or LLM content."
        }
        icon="✳"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : (
      <div className="u-grid-gap-14">
        <section style={kpiGridStyle} aria-label="TLDR digest counts">
          <StatCard
            label="Quotes"
            value={String(payload?.quote_count ?? quotes.length)}
            caption={`${quotes.length} requested`}
            tone="neutral"
          />
          <StatCard
            label="Movers"
            value={String(payload?.mover_count ?? 0)}
            caption="WITH LIVE CHANGE"
            tone="neutral"
          />
          <StatCard
            label="Headlines"
            value={String(news.length)}
            caption="TOP NEWS PASS"
            tone="neutral"
          />
          <StatCard
            label="Events"
            value={String(events.length)}
            caption="CALENDAR TODAY"
            tone="neutral"
          />
        </section>

        {markdown ? (
          <section aria-label="TL;DR summary" style={proseSectionStyle}>
            <div style={sectionTitleStyle}>Briefing</div>
            <div style={proseStyle}>{markdown}</div>
          </section>
        ) : null}

        {quotes.length ? (
          <section aria-label="TLDR quote movers">
            <div style={sectionTitleStyle}>Movers</div>
            <DataGrid
              columns={QUOTE_COLS}
              rows={quotes}
              rowKey={(r, i) => `${r.symbol ?? ""}-${i}`}
              density="compact"
              ariaLabel="TLDR quote movers"
            />
          </section>
        ) : null}

        {news.length ? (
          <section aria-label="TLDR news headlines">
            <div style={sectionTitleStyle}>News headlines</div>
            <ul style={bulletListStyle}>
              {news.slice(0, 8).map((title, i) => (
                <li key={`${i}-${title.slice(0, 24)}`} style={bulletStyle}>
                  {title}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {events.length ? (
          <section aria-label="TLDR calendar events">
            <div style={sectionTitleStyle}>Calendar</div>
            <ul style={bulletListStyle}>
              {events.slice(0, 10).map((e, i) => (
                <li key={`${i}-${String(e.Event ?? i).slice(0, 24)}`} style={bulletStyle}>
                  <span style={monoPrimaryStyle}>{e.Country || "—"}</span>
                  {" · "}
                  {e.Event || "—"}
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Daily TL;DR"
          subtitle={`${applied ? applied : "portfolio + watchlist"}${
            generatedAt ? ` · generated ${generatedAt.slice(0, 16).replace("T", " ")}Z` : ""
          }`}
          trailing={
            <FunctionControlGroup>
              <form onSubmit={applyScope} style={scopeFormStyle}>
                <label htmlFor="tldr-scope" style={scopeLabelStyle}>
                  Scope
                  <input
                    id="tldr-scope"
                    type="text"
                    aria-label="TLDR symbol scope, comma separated"
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    placeholder="AAPL, MSFT — empty = portfolio"
                    className="btmm-search-input"
                    style={scopeInputStyle}
                  />
                </label>
                <button type="submit" className="btn" title="Apply symbol scope">
                  Apply
                </button>
              </form>
              <Pill tone={isLlmSummary ? "accent" : "muted"} variant="soft" withDot={false}>
                {isLlmSummary ? "llm summary" : "local template"}
              </Pill>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : status}
              </Pill>
              <LoadStatePill state={state} status={status} />
              <RefreshButton loading={state === "loading"} onClick={refetch} title="Refresh digest" />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="scope" value={applied || "portfolio"} />
          <StatusDivider />
          <StatusSection label="engine" value={String(summaryModel ?? "—")} />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="elapsed" value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`} />
          <StatusDivider />
          <StatusSection label="sources" value={data?.sources?.join(", ") || "—"} />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function fmtNum(v: unknown): string {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  const digits = abs >= 1000 ? 2 : abs >= 1 ? 2 : 4;
  return formatNumber(n, digits);
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
  gap: 10,
};

const proseSectionStyle: CSSProperties = {
  display: "grid",
  gap: 6,
};

const sectionTitleStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: 1,
  color: "var(--text-mute)",
};

const proseStyle: CSSProperties = {
  whiteSpace: "pre-wrap",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
  lineHeight: 1.55,
  color: "var(--text-primary)",
  background: "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "10px 12px",
  maxHeight: 260,
  overflowY: "auto",
};

const bulletListStyle: CSSProperties = {
  margin: 0,
  paddingLeft: 18,
  display: "grid",
  gap: 4,
  fontSize: 12,
  color: "var(--text-primary)",
};

const bulletStyle: CSSProperties = {
  lineHeight: 1.45,
};

const scopeFormStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
};

const scopeLabelStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 5,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.06em",
};

const scopeInputStyle: CSSProperties = {
  width: 210,
  background: "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  padding: "6px 8px",
  font: "inherit",
  textTransform: "none",
  letterSpacing: 0,
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const monoPrimaryStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
};
