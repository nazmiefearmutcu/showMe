/**
 * NSE — News Search Engine.
 *
 * Query-driven live news search (backend tries the local Meilisearch/SQLite
 * index first, then RSS, then optional deep GDELT). Header: persisted search
 * box (last query in `showme.nse.last`) + deep-fallback toggle + result-limit
 * control + status pills + refresh. Body: a result-count note and the ranked
 * result list — headline, source, time, relevance and matched terms — where
 * the headline links out ONLY from the payload's own absolute URL (rows
 * without a link render unlinked, never with an invented target).
 *
 * Honesty: NSE is search-only — the backend refuses to fabricate rows and
 * answers `provider_unavailable` when no live provider returns hits; that
 * reason is surfaced verbatim instead of an invented result list.
 */
import { useMemo, useState, type CSSProperties, type FormEvent } from "react";
import {
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  NewsLimitControl,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption, NEWS_LIMITS, type NewsLimit } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface NSEResult {
  title?: string | null;
  source?: string | null;
  feed?: string | null;
  publisher?: string | null;
  url?: string | null;
  link?: string | null;
  published_at?: string | null;
  age_minutes?: number | null;
  importance_score?: number | null;
  relevance_score?: number | null;
  severity?: string | null;
  matched_terms?: string[];
}

interface NSEUnavailable {
  status?: string;
  reason?: string;
  next_actions?: string[];
}

type NSEPayload = NSEResult[] | NSEUnavailable | null;

interface NSEData {
  status?: string;
  reason?: string;
  query?: string;
}

const QUERY_STORAGE_KEY = "showme.nse.last";
const DEEP_STORAGE_KEY = "showme.nse.deep";
const DEFAULT_QUERY = "inflation";

type DeepToggle = "off" | "on";
const DEEP_OPTIONS: { value: DeepToggle; label: string }[] = [
  { value: "off", label: "Std" },
  { value: "on", label: "Deep" },
];

function readPersisted(key: string): string {
  if (typeof localStorage === "undefined") return "";
  return localStorage.getItem(key) ?? "";
}

export function NSEPane({ code, symbol }: FunctionPaneProps) {
  const [draftQuery, setDraftQuery] = useState<string>(
    () => readPersisted(QUERY_STORAGE_KEY) || DEFAULT_QUERY,
  );
  const [query, setQuery] = useState<string>(
    () => readPersisted(QUERY_STORAGE_KEY) || DEFAULT_QUERY,
  );
  const [limit, setLimit] = usePersistentOption<NewsLimit>(
    "showme.nse.limit",
    NEWS_LIMITS,
    25,
  );
  const [deep, setDeep] = usePersistentOption<DeepToggle>(
    DEEP_STORAGE_KEY,
    DEEP_OPTIONS.map((o) => o.value),
    "off",
  );

  const { state, data, error, refetch } = useFunction<NSEData>({
    code,
    symbol: symbol || undefined,
    params: {
      query,
      live: true,
      limit,
      ...(deep === "on" ? { include_gdelt: true } : {}),
    },
  });

  const payload = data?.data as NSEPayload;
  const envelopeStatus = data?.status;
  const status =
    (payload && !Array.isArray(payload) ? payload.status : undefined) ??
    envelopeStatus ??
    "—";
  const results = useMemo(
    () => (Array.isArray(payload) ? payload : []),
    [payload],
  );
  const unavailableReason =
    (payload && !Array.isArray(payload) ? payload.reason : undefined) ??
    data?.reason;
  const nextActions = useMemo(
    () =>
      (payload && !Array.isArray(payload) ? payload.next_actions : []) ?? [],
    [payload],
  );
  const activeQuery = data?.metadata?.query as string | undefined;

  function applySearch(event: FormEvent) {
    event.preventDefault();
    const nextQuery = draftQuery.trim();
    setQuery(nextQuery || DEFAULT_QUERY);
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(QUERY_STORAGE_KEY, nextQuery || DEFAULT_QUERY);
    }
  }

  const body =
    state === "loading" || state === "idle" ? (
      <div className="u-grid-gap-8">
        <Skeleton height={20} />
        <Skeleton height={48} />
        <Skeleton height={48} />
        <Skeleton height={48} width="85%" />
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
    ) : status === "provider_unavailable" ? (
      <Empty
        title={`No live news for "${activeQuery ?? query}"`}
        body={
          unavailableReason ??
          "No live news provider returned rows for this query — nothing is fabricated while feeds are unreachable."
        }
        icon="⌕"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : results.length === 0 ? (
      <Empty
        title={`No results for "${activeQuery ?? query}"`}
        body="The search index and live feeds returned no hits for this query. Try a more specific company, ticker, or topic."
        icon="⌕"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : (
      <div className="u-grid-gap-14">
        <div role="status" aria-label="NSE result count" style={countNoteStyle}>
          {results.length} result{results.length === 1 ? "" : "s"} for “
          {activeQuery ?? query}” · source {data?.sources?.join(", ") || "—"}
        </div>
        {nextActions.length > 0 && (
          <div style={hintStyle} aria-label="NSE search hints">
            {nextActions.join(" ")}
          </div>
        )}
        <ul style={listStyle} aria-label="News search results">
          {results.map((r, i) => (
            <ResultItem key={`${r.url ?? r.link ?? r.title ?? "row"}-${i}`} row={r} />
          ))}
        </ul>
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="News Search"
          subtitle={`"${query}"${symbol ? ` · boost ${symbol}` : ""}${deep === "on" ? " · deep GDELT" : ""}`}
          trailing={
            <FunctionControlGroup>
              <form onSubmit={applySearch} style={searchFormStyle}>
                <label htmlFor="nse-query" style={searchLabelStyle}>
                  Query
                  <input
                    id="nse-query"
                    type="search"
                    aria-label="News search query"
                    value={draftQuery}
                    onChange={(event) => setDraftQuery(event.target.value)}
                    placeholder="company, ticker, topic…"
                    className="btmm-search-input"
                    style={searchInputStyle}
                  />
                </label>
                <button type="submit" className="btn" title="Run news search">
                  Search
                </button>
              </form>
              <SegmentedControl
                label="FALLBACK"
                value={deep}
                options={DEEP_OPTIONS}
                onChange={setDeep}
                title="Include the slower GDELT deep fallback"
              />
              <NewsLimitControl value={limit} onChange={setLimit} />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Re-run news search"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="query" value={activeQuery ?? query} />
          <StatusDivider />
          <StatusSection label="hits" value={results.length} />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="sources" value={data?.sources?.join(", ") || "—"} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="last" value={limit} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/**
 * One search hit: the headline links out ONLY from the payload's own
 * absolute URL (`url` first, `link` fallback); otherwise the headline stays
 * unlinked with an honest "no link provided" note (BRIEF convention).
 */
function ResultItem({ row }: { row: NSEResult }) {
  const raw = [row.url, row.link].find(
    (c): c is string => typeof c === "string" && /^https?:\/\//.test(c.trim()),
  );
  const href = raw ? raw.trim() : null;
  const title = row.title?.trim() || "Untitled result";
  const severity = (row.severity ?? "").toLowerCase();
  return (
    <li style={rowStyle}>
      {severity === "critical" && (
        <Pill tone="negative" variant="soft" withDot={false}>
          critical
        </Pill>
      )}
      {severity === "high" && (
        <Pill tone="warn" variant="soft" withDot={false}>
          high
        </Pill>
      )}
      <div style={contentStyle}>
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            style={linkStyle}
          >
            {title} ↗
          </a>
        ) : (
          <>
            <span style={unlinkedTitleStyle}>{title}</span>
            <span className="u-text-mute" style={noLinkStyle}>
              no link provided
            </span>
          </>
        )}
        <div style={metaStyle}>
          {[
            row.source ?? row.publisher ?? row.feed ?? "—",
            row.age_minutes != null
              ? fmtAge(row.age_minutes)
              : fmtStamp(row.published_at ?? ""),
            row.relevance_score != null
              ? `relevance ${Number(row.relevance_score).toFixed(1)}`
              : null,
            (row.matched_terms ?? []).length > 0
              ? `matched: ${(row.matched_terms ?? []).slice(0, 4).join(", ")}`
              : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </div>
      </div>
    </li>
  );
}

function fmtAge(minutes: number): string {
  if (!Number.isFinite(minutes)) return "—";
  if (minutes < 90) return `${Math.round(minutes)}m`;
  if (minutes < 60 * 48) return `${(minutes / 60).toFixed(1)}h`;
  return `${(minutes / (60 * 24)).toFixed(1)}d`;
}

/** UTC ISO string → "YYYY-MM-DD HH:MM UTC" (slicing keeps the payload value verbatim). */
function fmtStamp(iso: string): string {
  if (!iso) return "—";
  if (iso.length < 16) return iso;
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
}

const searchFormStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
};

const searchLabelStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 5,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.06em",
};

const searchInputStyle: CSSProperties = {
  width: 190,
  background: "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  padding: "6px 8px",
  font: "inherit",
  textTransform: "none",
  letterSpacing: 0,
};

const countNoteStyle: CSSProperties = {
  fontSize: 12,
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-mute)",
};

const hintStyle: CSSProperties = {
  fontSize: 11,
  color: "var(--text-mute)",
  border: "1px dashed var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "6px 10px",
};

const listStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "grid",
  gap: 8,
};

const rowStyle: CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  gap: 10,
  padding: "8px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: 6,
};

const contentStyle: CSSProperties = {
  minWidth: 0,
  display: "grid",
  gap: 2,
};

const linkStyle: CSSProperties = {
  color: "var(--accent)",
  fontWeight: 600,
  fontSize: 13,
  textDecoration: "none",
  overflowWrap: "anywhere",
};

const unlinkedTitleStyle: CSSProperties = {
  color: "var(--text-primary)",
  fontWeight: 600,
  fontSize: 13,
  overflowWrap: "anywhere",
};

const noLinkStyle: CSSProperties = { fontSize: 11, marginLeft: 6 };

const metaStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-mute)",
};
