/**
 * TSAR — Transcript Search.
 *
 * The sidecar exposes search / list / stats / get / delete / ingest on a
 * shared SQLite + FTS5 archive (`engine/services/transcripts_archive`).
 * Pane focuses on the day-to-day "search across stored transcripts" flow
 * and exposes the alternate actions via a small command menu. We never
 * fire on mount — the user types a query and presses Search, which keeps
 * the empty-archive path from looking like a broken render.
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

interface TSARPayload {
  status?: string;
  reason?: string;
  query?: string;
  items?: TSARHit[];
  next_actions?: string[];
}

interface ArchiveStats {
  total?: number;
  by_symbol?: Record<string, number>;
  latest_event_date?: string;
}

export function TSARPane({ code, symbol }: FunctionPaneProps) {
  const [query, setQuery] = useState("");
  const [filterSymbol, setFilterSymbol] = useState(symbol ?? "");
  const [state, setState] = useState<"idle" | "loading" | "ok" | "error">("idle");
  const [result, setResult] = useState<FunctionCallResult<unknown> | null>(null);
  const [stats, setStats] = useState<ArchiveStats | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const payload = useMemo<TSARPayload>(() => {
    const d = result?.data;
    return d && typeof d === "object" && !Array.isArray(d) ? (d as TSARPayload) : {};
  }, [result]);

  const items = useMemo<TSARHit[]>(
    () => (Array.isArray(payload.items) ? payload.items : []),
    [payload.items],
  );

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

  const loadStats = useCallback(async () => {
    try {
      const res = await runFunction(code, { params: { action: "stats" } });
      const d = res?.data;
      if (d && typeof d === "object" && !Array.isArray(d)) {
        setStats(d as ArchiveStats);
      }
    } catch {
      setStats(null);
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

  const archiveEmpty =
    payload.status === "provider_unavailable" || items.some((i) => i.status === "archive_unavailable");

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Transcript search"
          subtitle={`FTS5 over local archive · ${items.length} hits · ${stats?.total ?? "—"} stored`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>{items.length} hits</Pill>
              <Pill tone="accent" variant="soft" withDot={false}>
                {stats?.total ? `${stats.total} stored` : "stats?"}
              </Pill>
              <LoadStatePill state={state} />
              <button
                type="button"
                onClick={loadStats}
                style={secondaryActionStyle}
              >
                Stats
              </button>
              <button
                type="button"
                onClick={search}
                disabled={state === "loading" || !query.trim()}
                style={primaryActionStyle}
              >
                {state === "loading" ? "Searching…" : "Search"}
              </button>
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <div className="u-grid-gap-14">
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
            {state === "loading" ? (
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
                />
              </div>
            )}
          </div>
        </PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={result?.sources?.join(", ") || "transcripts_archive"} />
          <StatusDivider />
          <StatusSection label="query" value={query || "—"} />
          <StatusDivider />
          <StatusSection label="hits" value={items.length} />
          <StatusDivider />
          <StatusSection label="archive" value={stats?.total ?? "—"} />
          <StatusDivider />
          <StatusSection label="status" value={payload.status ?? state} tone="accent" />
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

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

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
