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
import {
  runFunction,
  FunctionCallError,
  type FunctionCallResult,
} from "@/lib/functions";
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

const SAMPLES = [
  'sector = "Technology" AND marketCap > 50000000000',
  "pe < 35 AND beta < 1.3",
  'country = "US" AND marketCap > 100000000000',
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
  const [result, setResult] = useState<FunctionCallResult<unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);

  const run = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    setElapsed(null);
    try {
      const parsedUniverse = parseUniverse(universe);
      const res = await runFunction<unknown>(code, {
        params: {
          query,
          limit,
          ...(parsedUniverse ? { universe: parsedUniverse } : {}),
        },
      });
      setResult(res);
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

  const rows = useMemo(() => normalizeRows(result?.data), [result?.data]);
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
              <LoadStatePill state={running ? "loading" : error ? "error" : result ? "ok" : "idle"} />
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
            {!running && result && (
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
                    matched · {Number(result.metadata?.matched ?? rows.length)}
                  </Pill>
                  {result.metadata?.scanned != null && (
                    <Pill tone="muted" withDot={false}>
                      scanned · {Number(result.metadata.scanned)}
                    </Pill>
                  )}
                  <Pill tone="muted" withDot={false}>
                    source · {(result.sources ?? []).join(", ") || "none"}
                  </Pill>
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

function normalizeRows(payload: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(payload)) return payload.filter(isRecord);
  if (!isRecord(payload)) return [];
  const rows = payload.rows ?? payload.data ?? payload.items;
  return Array.isArray(rows) ? rows.filter(isRecord) : [];
}

function parseUniverse(value: string): string[] | null {
  const trimmed = value.trim();
  if (!trimmed || trimmed.toUpperCase() === "SP500") return null;
  const symbols = trimmed
    .split(/[\s,]+/)
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean);
  return symbols.length ? symbols : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
