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
  Skeleton,
  StatCard,
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

  const COLS: DataGridColumn<PEOPItem>[] = useMemo(
    () => [
      {
        key: "full_name",
        header: "Name",
        width: 170,
        render: (r) => <span style={monoStrongStyle}>{r.full_name ?? "—"}</span>,
      },
      {
        key: "role",
        header: "Role / title",
        width: 320,
        render: (r) => <span style={titleStyle}>{r.role ?? "—"}</span>,
      },
      {
        key: "company",
        header: "Firm",
        width: 120,
        render: (r) => <span style={titleStyle}>{r.company ?? "—"}</span>,
      },
      {
        key: "contact_status",
        header: "Contact",
        width: 170,
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
    ],
    [],
  );

  const body = !hasSearched ? (
    <Empty
      title="Search for a person"
      body="Type a name, company, or role and press Search — the local directory is checked first, then the public-reference set."
      icon="⌕"
    />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={56} />
      <Skeleton height={20} />
      <Skeleton height={20} />
      <Skeleton height={20} width="80%" />
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
  ) : items.length === 0 ? (
    <Empty
      title="No people matched"
      body={
        payload?.next_actions?.[0] ??
        `The local directory and public-reference set returned nothing for "${query}".`
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
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
      />
    </div>
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
  fontSize: 12,
  color: "var(--text-primary)",
};

const linkStyle: CSSProperties = {
  color: "var(--accent)",
  textDecoration: "none",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
};
