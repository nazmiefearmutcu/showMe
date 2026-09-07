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
  symbol_match?: string;
}

interface FTSData {
  status?: string;
  reason?: string;
  next_actions?: string[];
  rows?: FTSRow[];
  query?: string;
  forms?: string[] | null;
  methodology?: string;
}

const QUERY_STORAGE_KEY = "showme.fts.last";
const FORMS_STORAGE_KEY = "showme.fts.forms";
const DEFAULT_QUERY = "risk factors";

function readPersisted(key: string): string {
  if (typeof localStorage === "undefined") return "";
  return localStorage.getItem(key) ?? "";
}

export function FTSPane({ code }: FunctionPaneProps) {
  const [draftQuery, setDraftQuery] = useState<string>(
    () => readPersisted(QUERY_STORAGE_KEY) || DEFAULT_QUERY,
  );
  const [query, setQuery] = useState<string>(
    () => readPersisted(QUERY_STORAGE_KEY) || DEFAULT_QUERY,
  );
  const [draftForms, setDraftForms] = useState<string>(() => readPersisted(FORMS_STORAGE_KEY));
  const [forms, setForms] = useState<string>(() => readPersisted(FORMS_STORAGE_KEY));

  const { state, data, error, refetch } = useFunction<FTSData>({
    code,
    params: {
      query,
      live: true,
      ...(forms ? { forms } : {}),
      limit: 50,
      timeout: 12,
    },
  });

  const payload = data?.data;
  const rows = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";

  function applySearch(event: FormEvent) {
    event.preventDefault();
    const nextQuery = draftQuery.trim();
    const nextForms = draftForms.trim().toUpperCase();
    setQuery(nextQuery || DEFAULT_QUERY);
    setForms(nextForms);
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(QUERY_STORAGE_KEY, nextQuery || DEFAULT_QUERY);
      localStorage.setItem(FORMS_STORAGE_KEY, nextForms);
    }
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
        title={`No filings matched "${payload?.query ?? query}"`}
        body="EDGAR full-text search returned no hits for this query and form filter."
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
          {rows.length} filing hit{rows.length === 1 ? "" : "s"} for “
          {payload?.query ?? query}”
          {forms ? ` · forms ${forms}` : ""} · source {data?.sources?.join(", ") || "—"}
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
          subtitle={`"${query}"${forms ? ` · forms ${forms}` : ""} · EDGAR live search`}
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

const snippetSectionStyle: CSSProperties = {
  display: "grid",
  gap: 6,
};

const sectionTitleStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: 1,
  color: "var(--text-mute)",
};

const snippetStyle: CSSProperties = {
  fontSize: 12,
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
  fontSize: 12,
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
