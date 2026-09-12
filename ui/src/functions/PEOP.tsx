/**
 * PEOP — People Search.
 *
 * Searches the local SQLite people directory first and falls back to the
 * backend's small public-reference set (both honest about which answered).
 * Header: query input + search commit. Body: result count / source-mode
 * cards + the people table (name, role, firm, contact-status chip, source
 * link). An unmatched query renders the backend's honest needs_data state
 * with its next actions — no phantom contacts.
 */
import { useMemo, useState, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { PaneState } from "@/design-system/PaneState";
import { buildTsvRow, copyTextToClipboard } from "@/design-system/clipboard";
import {
  buildGridCsv,
  downloadGridCsv,
  gridCsvFilename,
  type GridCsvColumn,
} from "@/design-system/grid-csv";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface PEOPItem {
  full_name?: string;
  role?: string;
  company?: string;
  bio?: string;
  tags?: string[];
  profile_url?: string;
  source?: string;
  source_url?: string;
  source_date?: string;
  contact_status?: string;
  match_score?: number;
}

interface PEOPData {
  status?: string;
  query?: string;
  items?: PEOPItem[];
  rows?: PEOPItem[];
  source_mode?: string;
  connection_status?: { source?: string; status?: string }[];
  next_actions?: string[];
  methodology?: string;
}

export function PEOPPane({ code }: FunctionPaneProps) {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");

  const { state, data, error, refetch } = useFunction<PEOPData>({
    code,
    params: { action: "search", query },
    enabled: query.trim().length > 0,
  });

  const payload = data?.data;
  const items = useMemo(() => payload?.items ?? payload?.rows ?? [], [payload]);
  const status = payload?.status ?? (query ? "—" : "idle");
  const hasSearched = query.trim().length > 0;

  const commit = () => setQuery(draft.trim());

  // CSV export of the people results — RAW payload fields (match_score stays
  // a number, never the formatted row strings).
  const csvColumns = useMemo<GridCsvColumn<PEOPItem>[]>(
    () => [
      { key: "full_name", header: "Name", value: (r) => r.full_name ?? "" },
      { key: "role", header: "Role / title", value: (r) => r.role ?? "" },
      { key: "company", header: "Firm", value: (r) => r.company ?? "" },
      { key: "bio", header: "Bio", value: (r) => r.bio ?? "" },
      {
        key: "contact_status",
        header: "Contact",
        value: (r) => r.contact_status ?? "",
      },
      { key: "source", header: "Source", value: (r) => r.source ?? "" },
      {
        key: "source_url",
        header: "Source URL",
        value: (r) => r.source_url ?? "",
      },
      {
        key: "source_date",
        header: "Source date",
        value: (r) => r.source_date ?? "",
      },
      {
        key: "match_score",
        header: "Match score",
        value: (r) => r.match_score ?? "",
      },
    ],
    [],
  );

  const exportCsv = () => {
    const slug =
      query
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "") || "results";
    const csv = buildGridCsv(csvColumns, items);
    downloadGridCsv(gridCsvFilename(`peop-${slug}`), csv);
  };

  const COLS: DataGridColumn<PEOPItem>[] = useMemo(
    () => [
      {
        key: "full_name",
        header: "Name",
        width: 170,
        sortable: true,
        sortValue: (r) => r.full_name ?? "",
        render: (r) => <span style={monoStrongStyle}>{r.full_name ?? "—"}</span>,
      },
      {
        key: "role",
        header: "Role / title",
        width: 320,
        sortable: true,
        sortValue: (r) => r.role ?? "",
        render: (r) => <span style={titleStyle}>{r.role ?? "—"}</span>,
      },
      {
        key: "company",
        header: "Firm",
        width: 120,
        sortable: true,
        sortValue: (r) => r.company ?? "",
        render: (r) => <span style={titleStyle}>{r.company ?? "—"}</span>,
      },
      {
        key: "contact_status",
        header: "Contact",
        width: 170,
        sortable: true,
        sortValue: (r) => r.contact_status ?? "",
        render: (r) =>
          r.contact_status ? (
            <Pill
              tone={r.contact_status === "public_profile_only" ? "muted" : "accent"}
              variant="soft"
              withDot={false}
            >
              {r.contact_status}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
      {
        key: "source",
        header: "Source",
        width: 140,
        render: (r) =>
          r.source_url ? (
            <a
              href={r.source_url}
              target="_blank"
              rel="noreferrer"
              style={linkStyle}
              aria-label={`Open source for ${r.full_name ?? "person"}`}
            >
              open ↗
            </a>
          ) : (
            <span style={monoMutedStyle}>{r.source ?? "—"}</span>
          ),
      },
      {
        key: "copy",
        header: "",
        width: 74,
        render: (r) => (
          <button
            type="button"
            className="btn"
            title={`Copy ${r.full_name ?? "person"} contact row`}
            aria-label={`Copy ${r.full_name ?? "person"} contact row`}
            onClick={() =>
              copyTextToClipboard(
                buildTsvRow([
                  r.full_name,
                  r.role,
                  r.company,
                  r.contact_status,
                  r.source_url ?? r.source,
                ]),
              )
            }
            style={copyButtonStyle}
          >
            ⧉ copy
          </button>
        ),
      },
    ],
    [],
  );

  const body = !hasSearched ? (
    <Empty
      title="Search for a person"
      body="Type a name, company, or role and press Search — the local directory is checked first, then the public-reference set."
      icon="⌕"
    />
  ) : (
    <PaneState
      state={state}
      error={error}
      empty={items.length === 0}
      emptyTitle="No people matched"
      emptyBody={
        payload?.next_actions?.[0] ??
        `The local directory and public-reference set returned nothing for "${query}".`
      }
      onRetry={refetch}
    >
      <div className="u-grid-gap-14">
        <section style={kpiGridStyle} aria-label="PEOP summary">
          <StatCard
            label="Matches"
            value={String(items.length)}
            caption={`QUERY "${query.toUpperCase()}"`}
            tone="neutral"
          />
          <StatCard
            label="Result source"
            value={payload?.source_mode ?? "—"}
            caption="LOCAL DIRECTORY FIRST, THEN PUBLIC REFERENCE"
            tone="neutral"
          />
          <StatCard
            label="Top match"
            value={items[0]?.full_name ?? "—"}
            caption={items[0]?.company ?? ""}
            tone="neutral"
          />
        </section>
        <DataGrid
          columns={COLS}
          rows={items}
          rowKey={(r, i) => `${r.full_name ?? "person"}-${i}`}
          density="compact"
          ariaLabel="PEOP people results"
          defaultSortKey="full_name"
          defaultSortDir="none"
        />
      </div>
    </PaneState>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="People Search"
          subtitle={hasSearched ? `query: ${query} · ${items.length} matches` : "search the people directory"}
          trailing={
            <FunctionControlGroup>
              <form
                className="fn-control-group"
                onSubmit={(e) => {
                  e.preventDefault();
                  commit();
                }}
              >
                <input
                  type="text"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder="name, firm, or role…"
                  aria-label="People search query"
                  style={inputStyle}
                />
                <button
                  type="submit"
                  className="btn"
                  disabled={!draft.trim()}
                  title="Search people"
                >
                  Search
                </button>
              </form>
              <button
                type="button"
                className="btn"
                onClick={exportCsv}
                disabled={items.length === 0}
                title="Download CSV"
                aria-label={`Download ${items.length} people results as CSV`}
              >
                CSV
              </button>
              <LoadStatePill state={hasSearched ? state : "idle"} status={status === "idle" ? null : status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!hasSearched}
                title="Re-run people search"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || (hasSearched ? "—" : "people_directory")}
          />
          <StatusDivider />
          <StatusSection label="status" value={hasSearched ? status : "waiting_for_query"} />
          <StatusDivider />
          <StatusSection label="matches" value={items.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={hasSearched ? `${data?.elapsed_ms?.toFixed(0) ?? "—"} ms` : "—"}
          />
          <StatusDivider />
          <StatusSection
            label="query"
            value={hasSearched ? query : "—"}
            tone="accent"
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const inputStyle: CSSProperties = {
  width: 180,
};

const copyButtonStyle: CSSProperties = {
  fontSize: "var(--font-size-xs)",
  padding: "0 6px",
  height: 20,
  lineHeight: "20px",
  whiteSpace: "nowrap",
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
};

const titleStyle: CSSProperties = {
  fontSize: "var(--font-size-md)",
  color: "var(--text-primary)",
};

const linkStyle: CSSProperties = {
  color: "var(--accent)",
  textDecoration: "none",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
};
