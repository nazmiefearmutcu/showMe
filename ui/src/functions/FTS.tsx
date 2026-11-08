/**
 * FTS — SEC EDGAR Full-Text Search.
 *
 * The backend needs `live: true` (plus a configured sec_efts adapter) and
 * returns relevance-scored filing hits: company, form type, filing date,
 * accession, optional URL, optional snippet. Header: persisted search box
 * (last query in `showme.fts.last`) + optional form-type filter + status
 * pills + refresh. Body: result-count note, a results table (form, company,
 * date, score, link out), and per-row snippet evidence when the provider
 * supplies one.
 *
 * Honesty: the filing link is rendered ONLY from the payload's own `url`;
 * rows without a URL show the bare accession number instead of an invented
 * link. A provider_unavailable payload renders its reason verbatim.
 */
import { useMemo, useState, type CSSProperties, type FormEvent } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Skeleton,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { usePersistentString } from "./function-control-state";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface FTSRow {
  company?: string | null;
  form?: string | null;
  filing_date?: string | null;
  accession?: string | null;
  url?: string | null;
  score?: number | null;
  snippet?: string | null;
  symbol?: string | null;
  cik?: string | null;
  issuer_match?: boolean | null;
}

interface FTSData {
  status?: string;
  reason?: string;
  next_actions?: string[];
  rows?: FTSRow[];
  query?: string;
  forms?: string[] | null;
  methodology?: string;
  total_hits?: number | null;
  date_from?: string | null;
  date_to?: string | null;
}

const QUERY_STORAGE_KEY = "showme.fts.last";
const FORMS_STORAGE_KEY = "showme.fts.forms";
const FROM_STORAGE_KEY = "showme.fts.from";
const TO_STORAGE_KEY = "showme.fts.to";
const DEFAULT_QUERY = "risk factors";
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function FTSPane({ code }: FunctionPaneProps) {
  const [query, setQuery] = usePersistentString(QUERY_STORAGE_KEY, DEFAULT_QUERY);
  const [draftQuery, setDraftQuery] = useState<string>(query);
  const [forms, setForms] = usePersistentString(FORMS_STORAGE_KEY, "");
  const [draftForms, setDraftForms] = useState<string>(forms);
  const [dateFrom, setDateFrom] = usePersistentString(FROM_STORAGE_KEY, "");
  const [draftFrom, setDraftFrom] = useState<string>(dateFrom);
  const [dateTo, setDateTo] = usePersistentString(TO_STORAGE_KEY, "");
  const [draftTo, setDraftTo] = useState<string>(dateTo);

  const { state, data, error, refetch } = useFunction<FTSData>({
    code,
    params: {
      query,
      live: true,
      ...(forms ? { forms } : {}),
      ...(dateFrom ? { date_from: dateFrom } : {}),
      ...(dateTo ? { date_to: dateTo } : {}),
      limit: 50,
      timeout: 12,
    },
  });

  const payload = data?.data;
  const rows = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";
  const rangeLabel = dateFrom || dateTo ? ` · filed ${dateFrom || "…"} to ${dateTo || "today"}` : "";

  function applySearch(event: FormEvent) {
    event.preventDefault();
    const nextQuery = draftQuery.trim();
    const nextForms = draftForms.trim().toUpperCase();
    // Only well-formed ISO dates are sent; a half-typed date is not forwarded.
    const nextFrom = ISO_DATE.test(draftFrom) ? draftFrom : "";
    const nextTo = ISO_DATE.test(draftTo) ? draftTo : "";
    setQuery(nextQuery || DEFAULT_QUERY);
    setForms(nextForms);
    setDateFrom(nextFrom);
    setDateTo(nextTo);
  }

  const COLS: DataGridColumn<FTSRow>[] = useMemo(
    () => [
      {
        key: "form",
        header: "Form",
        width: 96,
        render: (r) => <span style={monoStrongStyle}>{r.form || "—"}</span>,
      },
      {
        key: "company",
        header: "Company",
        width: 240,
        render: (r) => <span style={monoPrimaryStyle}>{r.company || "—"}</span>,
      },
      {
        key: "filing_date",
        header: "Filed",
        width: 110,
        render: (r) => (
          <span style={monoMutedStyle}>{String(r.filing_date ?? "—").slice(0, 10)}</span>
        ),
      },
      {
        key: "score",
        header: "Score",
        numeric: true,
        width: 84,
        render: (r) => (
          <span style={monoMutedStyle}>
            {typeof r.score === "number" && Number.isFinite(r.score)
              ? r.score.toFixed(1)
              : "—"}
          </span>
        ),
      },
      {
        key: "filing",
        header: "Filing",
        width: 150,
        render: (r) =>
          r.url ? (
            <a
              href={r.url}
              target="_blank"
              rel="noreferrer"
              style={linkStyle}
              title={r.accession ?? r.url}
            >
              Open filing ↗
            </a>
          ) : (
            <span style={monoMutedStyle} title="No filing URL returned by the provider">
              {r.accession || "—"}
            </span>
          ),
      },
    ],
    [],
  );

  const body =
    state === "loading" || state === "idle" ? (
      <div className="u-grid-gap-8">
        <Skeleton height={56} />
        <Skeleton height={20} />
        <Skeleton height={20} width="85%" />
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
        title="Full-text search unavailable"
        body={payload?.reason ?? "SEC EDGAR full-text search is offline."}
        icon="⌕"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : rows.length === 0 ? (
      <Empty
        title={
          status === "empty" && payload?.reason
            ? "No search was run"
            : `No filings matched "${payload?.query ?? query}"`
        }
        body={
          status === "empty" && payload?.reason
            ? payload.reason
            : "EDGAR full-text search returned no hits for this query, form filter and date range."
        }
        icon="⌕"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : (
      <div className="u-grid-gap-14">
        <div role="status" aria-label="FTS result count" style={countNoteStyle}>
          {typeof payload?.total_hits === "number"
            ? `${payload.total_hits.toLocaleString("en-US")} EDGAR match${payload.total_hits === 1 ? "" : "es"} · showing ${rows.length}`
            : `${rows.length} filing hit${rows.length === 1 ? "" : "s"} (EDGAR total not reported)`}
          {` for “${payload?.query ?? query}”`}
          {forms ? ` · forms ${forms}` : ""}
          {payload?.date_from || payload?.date_to
            ? ` · filed ${payload?.date_from || "…"} to ${payload?.date_to || "today"}`
            : ""}
          {` · source ${data?.sources?.join(", ") || "—"}`}
        </div>
        <DataGrid
          columns={COLS}
          rows={rows}
          rowKey={(r, i) => `${r.accession ?? ""}-${i}`}
          density="compact"
          ariaLabel="SEC EDGAR full-text search results"
        />
        {rows.some((r) => r.snippet) ? (
          <section aria-label="FTS snippet evidence" style={snippetSectionStyle}>
            <div style={sectionTitleStyle}>Snippet evidence</div>
            {rows
              .filter((r) => r.snippet)
              .slice(0, 5)
              .map((r, i) => (
                <div key={`${r.accession ?? "row"}-${i}`} style={snippetStyle}>
                  <span style={monoStrongStyle}>{r.form || "?"}</span>
                  {" · "}
                  {r.company || "—"}: {r.snippet}
                </div>
              ))}
          </section>
        ) : null}
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="SEC Full-Text Search"
          subtitle={`"${query}"${forms ? ` · forms ${forms}` : ""}${rangeLabel} · EDGAR live search`}
          trailing={
            <FunctionControlGroup>
              <form onSubmit={applySearch} style={searchFormStyle}>
                <label htmlFor="fts-query" style={searchLabelStyle}>
                  Query
                  <input
                    id="fts-query"
                    type="search"
                    aria-label="SEC full-text search query"
                    value={draftQuery}
                    onChange={(event) => setDraftQuery(event.target.value)}
                    placeholder="risk factors, cybersecurity…"
                    className="btmm-search-input"
                    style={searchInputStyle}
                  />
                </label>
                <label htmlFor="fts-forms" style={searchLabelStyle}>
                  Forms
                  <input
                    id="fts-forms"
                    type="text"
                    aria-label="Form type filter, comma separated"
                    value={draftForms}
                    onChange={(event) => setDraftForms(event.target.value)}
                    placeholder="10-K, 8-K"
                    className="btmm-search-input"
                    style={{ ...searchInputStyle, width: 110 }}
                  />
                </label>
                <label htmlFor="fts-from" style={searchLabelStyle}>
                  From
                  <input
                    id="fts-from"
                    type="date"
                    aria-label="Filed from date"
                    value={draftFrom}
                    onChange={(event) => setDraftFrom(event.target.value)}
                    className="btmm-search-input"
                    style={{ ...searchInputStyle, width: 132 }}
                  />
                </label>
                <label htmlFor="fts-to" style={searchLabelStyle}>
                  To
                  <input
                    id="fts-to"
                    type="date"
                    aria-label="Filed to date"
                    value={draftTo}
                    onChange={(event) => setDraftTo(event.target.value)}
                    className="btmm-search-input"
                    style={{ ...searchInputStyle, width: 132 }}
                  />
                </label>
                <button type="submit" className="btn" title="Run search">
                  Search
                </button>
              </form>
              <LoadStatePill state={state} status={status} />
              <RefreshButton loading={state === "loading"} onClick={refetch} title="Re-run search" />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="query" value={payload?.query ?? query} />
          <StatusDivider />
          <StatusSection label="hits" value={rows.length} />
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
  fontSize: "var(--font-size-xs)",
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
  fontSize: "var(--font-size-md)",
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-mute)",
};

const snippetSectionStyle: CSSProperties = {
  display: "grid",
  gap: 6,
};

const sectionTitleStyle: CSSProperties = {
  fontSize: "var(--font-size-2xs)",
  letterSpacing: 1,
  color: "var(--text-mute)",
};

const snippetStyle: CSSProperties = {
  fontSize: "var(--font-size-md)",
  lineHeight: 1.5,
  color: "var(--text-primary)",
  background: "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
};

const linkStyle: CSSProperties = {
  color: "var(--accent)",
  textDecoration: "none",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-md)",
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

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
};
