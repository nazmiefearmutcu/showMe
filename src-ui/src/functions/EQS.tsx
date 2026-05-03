/**
 * EQS — Equity screener.
 *
 * The ShowMe EQS function takes a DSL string + optional universe/limit and
 * returns a list of matching tickers with their evaluated metrics.
 */
import { useMemo, useState } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  Field,
  FieldRow,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
} from "@/design-system";
import { runFunction, FunctionCallError } from "@/lib/functions";
import { navigate } from "@/lib/router";
import {
  FunctionControlGroup,
  LoadStatePill,
  RowLimitControl,
} from "./function-controls";
import {
  ROW_LIMITS,
  type RowLimit,
  usePersistentOption,
} from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface EQSData {
  rows?: Array<Record<string, unknown>>;
  query?: string;
  evaluated?: number;
  matched?: number;
  [key: string]: unknown;
}

const SAMPLES = [
  'sector = "Information Technology" AND market_cap > 50_000_000_000',
  'pe < 15 AND div_yield > 0.03 AND beta < 1',
  'sector = "Energy" AND debt_to_equity < 0.5',
];

export function EQSPane({ code }: FunctionPaneProps) {
  const [query, setQuery] = useState(SAMPLES[0]);
  const [limit, setLimit] = usePersistentOption<RowLimit>(
    "showme.eqs-limit",
    ROW_LIMITS,
    50,
  );
  const [universe, setUniverse] = useState("SP500");
  const [running, setRunning] = useState(false);
  const [data, setData] = useState<EQSData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);

  const run = async () => {
    setRunning(true);
    setError(null);
    setData(null);
    setElapsed(null);
    try {
      const res = await runFunction<EQSData>(code, {
        params: { query, limit, universe },
      });
      setData(res.data);
      setElapsed(res.elapsed_ms);
    } catch (err) {
      const msg =
        err instanceof FunctionCallError
          ? `${err.status}: ${err.body}`
          : err instanceof Error
            ? err.message
            : String(err);
      setError(msg);
    } finally {
      setRunning(false);
    }
  };

  const rows = useMemo(() => data?.rows ?? [], [data?.rows]);
  const cols = useMemo<DataGridColumn<Record<string, unknown>>[]>(() => {
    if (!rows.length) return [];
    const sample = rows[0];
    return Object.keys(sample).map((key) => ({
      key,
      header: key,
      numeric: typeof sample[key] === "number",
      render: (r) => {
        const v = r[key];
        if (key === "symbol" || key === "ticker") {
          return (
            <button
              type="button"
              onClick={() => navigate(`/symbol/${String(v)}/DES`)}
              style={{
                background: "transparent",
                border: "none",
                color: "var(--accent)",
                cursor: "default",
                font: "inherit",
                padding: 0,
              }}
            >
              {String(v)}
            </button>
          );
        }
        if (typeof v === "number") {
          const a = Math.abs(v);
          if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
          if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
          return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
        }
        return v == null ? "—" : String(v);
      },
    }));
  }, [rows]);

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="Equity screener"
          subtitle={`Universe · ${universe}`}
          trailing={
            <FunctionControlGroup>
              <RowLimitControl
                value={limit}
                onChange={(next) => setLimit(next as RowLimit)}
                disabled={running}
              />
              <LoadStatePill state={running ? "loading" : error ? "error" : data ? "ok" : "idle"} />
              <button
                type="button"
                onClick={run}
                disabled={running || !query.trim()}
                className="btn btn--accent"
                style={{ height: 24 }}
              >
                {running ? "Running..." : "Run"}
              </button>
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              <span
                style={{
                  fontSize: 10,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  color: "var(--text-mute)",
                  display: "block",
                  marginBottom: 4,
                }}
              >
                DSL query
              </span>
              <textarea
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                rows={3}
                spellCheck={false}
                style={{
                  width: "100%",
                  resize: "vertical",
                  background: "var(--bg-elev-2)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "var(--radius-md)",
                  fontFamily: "JetBrains Mono, monospace",
                  fontSize: 12,
                  padding: 8,
                  outline: "none",
                }}
              />
              <div
                style={{
                  display: "flex",
                  gap: 6,
                  marginTop: 6,
                  flexWrap: "wrap",
                }}
              >
                {SAMPLES.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="btn btn--ghost"
                    onClick={() => setQuery(s)}
                    style={{ fontSize: 10, fontFamily: "JetBrains Mono" }}
                  >
                    {s.length > 50 ? s.slice(0, 50) + "…" : s}
                  </button>
                ))}
              </div>
            </div>
            <FieldRow>
              <Field
                label="Universe"
                value={universe}
                onChange={(e) => setUniverse(e.target.value)}
                placeholder="SP500"
              />
            </FieldRow>

            {error && <Empty title="Function error" body={error} icon="!" />}
            {running && (
              <div style={{ display: "grid", gap: 6 }}>
                <Skeleton height={14} />
                <Skeleton height={14} width="80%" />
                <Skeleton height={14} width="64%" />
              </div>
            )}
            {!running && data && (
              <>
                <div
                  style={{
                    display: "flex",
                    gap: 8,
                    fontSize: 11,
                    color: "var(--text-secondary)",
                  }}
                >
                  <Pill tone="positive" withDot={false}>
                    matched · {data.matched ?? rows.length}
                  </Pill>
                  {data.evaluated != null && (
                    <Pill tone="muted" withDot={false}>
                      evaluated · {data.evaluated}
                    </Pill>
                  )}
                </div>
                {rows.length === 0 ? (
                  <Empty title="No matches" />
                ) : (
                  <DataGrid columns={cols} rows={rows} density="compact" />
                )}
              </>
            )}
          </div>
        </PaneBody>
        <PaneFooter>
          <span>elapsed · {elapsed != null ? elapsed.toFixed(0) : "—"} ms</span>
          <span>rows · {rows.length}/{limit}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}
