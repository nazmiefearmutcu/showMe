/**
 * BQL — Query Language console.
 *
 * A DSL console over the backend's get()/for()/with()/by() query parser:
 * editable query (persisted as `showme.bql.last`), Run button, dynamic
 * results grid, and the backend's query_plan echoed in a collapsible.
 * The pane always sends live:true — without it the backend serves a
 * synthetic template — and surfaces the summary.mode pill, provider
 * warnings verbatim, and client-side parse notes when the query omits
 * get(...)/for(...) blocks (the parser silently defaults those).
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
  Pill,
  Skeleton,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { usePersistentString } from "./function-control-state";
import { useFunction } from "@/lib/useFunction";
import { defaultSymbolForFunction } from "@/lib/symbols";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface BQLSummary {
  mode?: string;
  symbols?: number;
  fields?: string;
  rows?: number;
  first_date?: string | null;
  last_date?: string | null;
  by?: string;
}

interface BQLPlanStep {
  step?: string;
  detail?: string;
}

interface BQLData {
  status?: string;
  reason?: string;
  rows?: Record<string, unknown>[];
  history?: Record<string, unknown>[];
  summary?: BQLSummary;
  query_plan?: BQLPlanStep[];
  warnings?: string[];
  next_actions?: string[];
}

const QUERY_KEY = "showme.bql.last";
const DEFAULT_QUERY = "get(close, volume) for(['AAPL','MSFT']) with(period='1mo') by(date)";

export function BQLPane({ code, symbol }: FunctionPaneProps) {
  const [query, setQuery] = usePersistentString(QUERY_KEY, DEFAULT_QUERY);
  const [input, setInput] = useState<string>(query);

  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF", "CRYPTO", "INDEX"]);
  // live:true is mandatory honesty here — the backend's offline branch is a
  // synthetic template (survey-3 gotcha), never a market read.
  const { state, data, error, refetch } = useFunction<BQLData>({
    code,
    symbol: effectiveSymbol,
    params: { query, live: true },
  });

  const payload = data?.data;
  const rows = useMemo(() => payload?.rows ?? [], [payload]);
  const summary = payload?.summary;
  const status = payload?.status ?? "—";
  const mode = summary?.mode ?? "—";

  // Parse notes: the regex parser never rejects text — it silently defaults
  // missing blocks. Surface that behaviour as content instead of hiding it.
  const parseNotes = useMemo(() => {
    const notes: string[] = [];
    const text = query.trim();
    if (text && !/get\s*\(/i.test(text)) {
      notes.push("no get(...) block — fields default to close, volume");
    }
    if (text && !/for\s*\(/i.test(text)) {
      notes.push(
        `no for([...]) block — universe falls back to the active symbol ${effectiveSymbol || "—"}`,
      );
    }
    return notes;
  }, [query, effectiveSymbol]);

  const fieldKeys = useMemo(() => {
    const keys: string[] = [];
    const seen = new Set<string>(["symbol", "date"]);
    for (const row of rows) {
      for (const key of Object.keys(row)) {
        if (!seen.has(key)) {
          seen.add(key);
          keys.push(key);
        }
      }
    }
    return keys;
  }, [rows]);

  const COLS: DataGridColumn<Record<string, unknown>>[] = useMemo(() => {
    const cols: DataGridColumn<Record<string, unknown>>[] = [
      {
        key: "symbol",
        header: "Symbol",
        width: 110,
        render: (r) => <span style={monoStrongStyle}>{str_(r.symbol)}</span>,
      },
      {
        key: "date",
        header: "Date",
        width: 124,
        render: (r) => <span style={monoPrimaryStyle}>{str_(r.date).slice(0, 10)}</span>,
      },
    ];
    for (const key of fieldKeys) {
      cols.push({
        key,
        header: key,
        numeric: true,
        render: (r) => (
          <span style={monoPrimaryStyle}>{fmtCell(r[key])}</span>
        ),
      });
    }
    return cols;
  }, [fieldKeys]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const next = input.trim();
    if (!next) return;
    setQuery(next);
  }

  const isLive = mode === "live";

  const body = state === "loading" || state === "idle" ? (
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
  ) : rows.length === 0 ? (
    <Empty
      title="No rows returned"
      body={
        payload?.reason ??
        payload?.next_actions?.[0] ??
        "The query parsed but the provider returned no rows for this universe/window."
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="BQL summary">
        <StatCard
          label="Rows"
          value={String(summary?.rows ?? rows.length)}
          caption={`${fieldKeys.length} FIELDS · BY ${summary?.by ?? "date"}`}
          tone="neutral"
        />
        <StatCard
          label="Universe"
          value={String(summary?.symbols ?? "—")}
          caption="SYMBOLS IN for([...])"
          tone="neutral"
        />
        <StatCard
          label="Window"
          value={`${(summary?.first_date ?? "—").slice(0, 10)} → ${(summary?.last_date ?? "—").slice(0, 10)}`}
          caption={`FIELDS ${summary?.fields ?? "—"}`}
          tone="neutral"
        />
        <StatCard
          label="Mode"
          value={mode}
          caption={isLive ? "PROVIDER OHLCV" : "SYNTHETIC TEMPLATE — NOT MARKET DATA"}
          tone={isLive ? "positive" : "negative"}
        />
      </section>
      {parseNotes.length > 0 ? (
        <div role="note" style={notesStyle} aria-label="BQL parse notes">
          {parseNotes.map((note) => (
            <div key={note}>· {note}</div>
          ))}
        </div>
      ) : null}
      {(payload?.warnings ?? []).length > 0 ? (
        <div role="note" style={warnStyle} aria-label="BQL provider warnings">
          {payload?.warnings?.map((warning) => (
            <div key={warning}>{warning}</div>
          ))}
        </div>
      ) : null}
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(r, i) => `${str_(r.symbol)}-${str_(r.date)}-${i}`}
        density="compact"
        ariaLabel="BQL results"
      />
      <details style={planStyle} aria-label="BQL query plan">
        <summary style={planSummaryStyle}>query plan</summary>
        <ol style={planListStyle}>
          {(payload?.query_plan ?? []).map((step, i) => (
            <li key={`${step.step ?? "step"}-${i}`}>
              <strong>{step.step ?? "—"}</strong> — {step.detail ?? ""}
            </li>
          ))}
        </ol>
      </details>
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Query Language"
          subtitle={`get()/for()/with()/by() · ${summary?.rows ?? 0} rows`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft" withDot={false}>
                {mode}
              </Pill>
              <form onSubmit={submit} style={formStyle}>
                <input
                  type="text"
                  aria-label="BQL query"
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  placeholder="get(close) for(['AAPL']) with(period='1mo') by(date)"
                  style={inputStyle}
                />
                <button type="submit" className="btn" title="Run BQL query">
                  Run
                </button>
              </form>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Re-run BQL query"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="sources" value={data?.sources?.join(", ") || "—"} />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="rows" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="query" value={query} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function str_(v: unknown): string {
  return v == null ? "—" : String(v);
}

function fmtCell(v: unknown): string {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (Number.isFinite(n)) {
    return Math.abs(n) >= 1e6
      ? n.toExponential(3)
      : n.toLocaleString("en-US", { maximumFractionDigits: 4 });
  }
  return String(v);
}

const formStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
};

const inputStyle: CSSProperties = {
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
  height: 24,
  padding: "0 6px",
  width: 260,
};

const notesStyle: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: 12,
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-mute)",
};

const warnStyle: CSSProperties = {
  border: "1px solid var(--warn, var(--text-mute))",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: 12,
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-primary)",
};

const planStyle: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: 6,
  padding: "6px 10px",
};

const planSummaryStyle: CSSProperties = {
  cursor: "pointer",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  letterSpacing: "0.06em",
  color: "var(--text-mute)",
};

const planListStyle: CSSProperties = {
  margin: "6px 0 4px",
  paddingLeft: 18,
  fontSize: 12,
  color: "var(--text-primary)",
};

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
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
