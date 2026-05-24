/**
 * EQS — Equity screener.
 *
 * Bloomberg-grade redesign: saved-screen presets, criteria filter chips,
 * KPI summary strip (matched count / median delta / source count) and a
 * dense factor-screening table with mini sparklines + delta chips.
 *
 * The ShowMe EQS function takes a DSL string + optional universe/limit and
 * returns a list of matching tickers with their evaluated metrics.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  CommandTile,
  DataGrid,
  type DataGridColumn,
  DeltaChip,
  Empty,
  Field,
  FieldRow,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatCard,
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
import sp500Data from "@/data/sp500.json";

const SAMPLES = [
  'sector = "Technology" AND marketCap > 50000000000',
  "pe < 35 AND beta < 1.3",
  'country = "US" AND marketCap > 100000000000',
];

const PRESET_SCREENS: Array<{
  code: string;
  description: string;
  query: string;
  universe?: string;
}> = [
  { code: "TECH-LG", description: "Tech mega-caps", query: 'sector = "Technology" AND marketCap > 50000000000' },
  { code: "VAL-LBT", description: "Low PE, low beta", query: "pe < 35 AND beta < 1.3" },
  { code: "US-MEGA", description: "US mega-caps", query: 'country = "US" AND marketCap > 100000000000' },
  { code: "DIV-Y", description: "High-yield dividends", query: "dividendYield > 0.04 AND marketCap > 10000000000" },
];

const NUMERIC_LIKE_KEYS = new Set([
  "change",
  "change_pct",
  "changePercent",
  "change_percent",
  "delta",
  "return",
  "returnPercent",
]);

const PERCENT_LIKE_KEYS = new Set([
  "change_pct",
  "changePercent",
  "change_percent",
  "returnPercent",
  "yield",
  "dividendYield",
  "growth",
]);

function deterministicTrend(seed: string, n = 20): number[] {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  const out: number[] = [];
  let v = 50;
  for (let i = 0; i < n; i++) {
    h = (h * 1664525 + 1013904223) >>> 0;
    const x = ((h & 0xff) / 255 - 0.5) * 12;
    v = Math.max(15, Math.min(85, v + x));
    out.push(v);
  }
  return out;
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function fmtCompact(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e12) return `${(v / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

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
  const abortRef = useRef<AbortController | null>(null);

  // TS-LINT-04 P1: cancel any in-flight EQS request on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  const run = async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
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
          // Session 16 BugHunt: without `live_screen` (or `deep`) the
          // backend short-circuits to `_screen_template_rows` and serves
          // five hard-coded sample rows. The dedicated EQS pane must run
          // the live yfinance-backed screener — match the generic
          // FunctionStub which already sets `live: true`.
          live_screen: true,
          ...(parsedUniverse ? { universe: parsedUniverse } : {}),
        },
        signal: controller.signal,
      });
      setResult(res);
      setElapsed(res.elapsed_ms);
    } catch (err) {
      if (controller.signal.aborted) return;
      const msg =
        err instanceof FunctionCallError
          ? `${err.status}: ${err.body}`
          : err instanceof Error
            ? err.message
            : String(err);
      setError(msg);
    } finally {
      if (!controller.signal.aborted) {
        setRunning(false);
      }
    }
  };

  const rows = useMemo(() => normalizeRows(result?.data), [result?.data]);

  // Derived KPI summaries
  const matchedCount = Number(result?.metadata?.matched ?? rows.length);
  const scannedCount = result?.metadata?.scanned != null ? Number(result.metadata.scanned) : null;
  const sources = result?.sources ?? [];

  const changeKey = useMemo(() => {
    if (!rows.length) return null;
    const sample = rows[0];
    return Object.keys(sample).find((k) => NUMERIC_LIKE_KEYS.has(k)) ?? null;
  }, [rows]);

  const medianChange = useMemo(() => {
    if (!changeKey) return null;
    const vals = rows
      .map((r) => r[changeKey])
      .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
    return median(vals);
  }, [rows, changeKey]);

  const topSector = useMemo(() => {
    const counts = new Map<string, number>();
    for (const r of rows) {
      const sector = (r["sector"] ?? r["industry"] ?? r["category"]) as
        | string
        | undefined;
      if (sector) counts.set(sector, (counts.get(sector) ?? 0) + 1);
    }
    let best: [string, number] | null = null;
    counts.forEach((count, sector) => {
      if (!best || count > best[1]) best = [sector, count];
    });
    return best;
  }, [rows]);

  const cols = useMemo<DataGridColumn<Record<string, unknown>>[]>(() => {
    if (!rows.length) return [];
    const sample = rows[0];
    const keys = Object.keys(sample);
    const numericMaxes = new Map<string, number>();
    for (const k of keys) {
      if (typeof sample[k] === "number") {
        let max = 0;
        for (const r of rows) {
          const v = r[k];
          if (typeof v === "number" && Number.isFinite(v)) {
            const a = Math.abs(v);
            if (a > max) max = a;
          }
        }
        numericMaxes.set(k, max);
      }
    }
    return keys.map((key) => ({
      key,
      header: key,
      numeric: typeof sample[key] === "number",
      render: (r) => {
        const v = r[key];
        if (key === "symbol" || key === "ticker") {
          return (
            <button
              type="button"
              onDoubleClick={() => navigate(`/symbol/${String(v)}/DES`)}
              className="scan-symbol"
              title="Double-click → DES"
            >
              {String(v)}
            </button>
          );
        }
        if (typeof v === "number" && Number.isFinite(v)) {
          if (PERCENT_LIKE_KEYS.has(key)) {
            return <DeltaChip value={v} format="percent" fractionDigits={2} />;
          }
          if (NUMERIC_LIKE_KEYS.has(key)) {
            return <DeltaChip value={v} format="raw" fractionDigits={2} />;
          }
          // Volume / dollar volume / market cap → bar fill
          if (
            key === "volume" ||
            key === "marketCap" ||
            key === "market_cap" ||
            key === "dollarVolume" ||
            key === "dollar_volume"
          ) {
            const max = numericMaxes.get(key) ?? 0;
            const ratio = max > 0 ? Math.abs(v) / max : 0;
            return <NumericBar value={fmtCompact(v)} ratio={ratio} />;
          }
          return (
            <span className="fa-cell-numeric">{fmtCompact(v)}</span>
          );
        }
        if (key === "sector" || key === "industry" || key === "category") {
          return v == null ? (
            <span className="u-text-mute">—</span>
          ) : (
            <Pill tone="muted" variant="soft" withDot={false}>
              {String(v)}
            </Pill>
          );
        }
        return v == null ? (
          <span className="u-text-mute">—</span>
        ) : (
          <span className="u-text-secondary">{String(v)}</span>
        );
      },
    }));
  }, [rows]);

  const activeFilters: Array<{ id: string; label: string; onRemove?: () => void }> = [];
  activeFilters.push({ id: "universe", label: `UNIV · ${universe}` });
  activeFilters.push({ id: "limit", label: `LIMIT · ${limit}` });
  if (query.trim()) {
    activeFilters.push({
      id: "dsl",
      label: `DSL · ${query.length > 36 ? query.slice(0, 36) + "…" : query}`,
    });
  }

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Equity screener"
          subtitle={`Universe · ${universe}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="accent" variant="soft" withDot={false}>
                MATCHED {matchedCount} / {scannedCount ?? "—"}
              </Pill>
              <Pill
                tone={running ? "warn" : result ? "positive" : "muted"}
                variant="soft"
                withDot
              >
                {running ? "RUNNING" : result ? "READY" : "IDLE"}
              </Pill>
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
                className="btn btn--accent u-btn-24"
                
              >
                {running ? "Running..." : "Run"}
              </button>
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <div className="u-flex u-flex-col u-gap-14">
            <Card variant="elev-2">
              <CardHeader
                trailing={
                  <Pill tone="muted" variant="soft" withDot={false}>
                    {PRESET_SCREENS.length} SAVED
                  </Pill>
                }
              >
                Saved screens
              </CardHeader>
              <CardBody>
                <div style={presetGridStyle}>
                  {PRESET_SCREENS.map((p) => (
                    <CommandTile
                      key={p.code}
                      code={p.code}
                      description={p.description}
                      active={query === p.query}
                      onClick={() => {
                        setQuery(p.query);
                        if (p.universe) setUniverse(p.universe);
                      }}
                    />
                  ))}
                </div>
              </CardBody>
            </Card>

            <Card>
              <CardHeader
                trailing={
                  <span className="u-inline-flex u-gap-6 u-items-center">
                    <button
                      type="button"
                      className="btn btn--ghost u-btn-mini"
                      onClick={() => {
                        setQuery(SAMPLES[0]);
                        setUniverse("SP500");
                      }}
                    >
                      Reset
                    </button>
                    <button
                      type="button"
                      className="btn btn--accent u-btn-mini"
                      onClick={run}
                      disabled={running || !query.trim()}
                    >
                      Apply
                    </button>
                  </span>
                }
              >
                Filter rail
              </CardHeader>
              <CardBody>
                <div className="u-flex u-flex-col u-gap-12">
                  <div style={filterChipRowStyle}>
                    {activeFilters.map((f) => (
                      <FilterChip key={f.id} label={f.label} onRemove={f.onRemove} />
                    ))}
                  </div>

                  <div>
                    <FieldLabel>DSL query</FieldLabel>
                    <textarea
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      rows={3}
                      spellCheck={false}
                      style={textareaStyle}
                    />
                    <div style={sampleRowStyle}>
                      {SAMPLES.map((s) => (
                        <button
                          key={s}
                          type="button"
                          className="btn btn--ghost u-text-10 u-mono"
                          onClick={() => setQuery(s)}
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
                </div>
              </CardBody>
            </Card>

            {error && <Empty title="Function error" body={error} icon="!" />}
            {running && (
              <Card>
                <CardBody>
                  <div className="u-grid-gap-8">
                    <Skeleton height={56} />
                    <Skeleton height={20} />
                    <Skeleton height={20} width="80%" />
                    <Skeleton height={20} width="64%" />
                  </div>
                </CardBody>
              </Card>
            )}
            {!running && result && (
              <>
                <div style={kpiStripStyle}>
                  <StatCard
                    label="Matched"
                    value={`${matchedCount}`}
                    caption={scannedCount != null ? `OF ${scannedCount} SCANNED` : "PROVIDER"}
                    trend={deterministicTrend(`m-${matchedCount}-${universe}`)}
                    tone="neutral"
                  />
                  <StatCard
                    label="Median Δ"
                    value={medianChange != null ? `${medianChange >= 0 ? "+" : ""}${medianChange.toFixed(2)}%` : "—"}
                    caption={changeKey ? `FIELD · ${changeKey}` : "NO Δ FIELD"}
                    trend={deterministicTrend(`d-${medianChange ?? 0}-${matchedCount}`)}
                    tone={medianChange == null ? "neutral" : medianChange >= 0 ? "positive" : "negative"}
                  />
                  <StatCard
                    label="Top sector"
                    value={topSector ? topSector[0] : "—"}
                    caption={topSector ? `${topSector[1]} TICKERS` : "NO SECTOR FIELD"}
                    trend={deterministicTrend(`s-${topSector?.[0] ?? "x"}-${matchedCount}`)}
                    tone="neutral"
                  />
                  <StatCard
                    label="Source"
                    value={(sources.join(", ") || "—").toUpperCase()}
                    caption={`ELAPSED ${elapsed != null ? elapsed.toFixed(0) : "—"}MS`}
                    trend={deterministicTrend(`x-${sources.join("-")}-${matchedCount}`)}
                    tone="neutral"
                  />
                </div>

                <Card>
                  <CardHeader
                    trailing={
                      <span className="u-inline-flex u-gap-6 u-flex-wrap">
                        <Pill tone="positive" variant="soft" withDot={false}>
                          MATCHED {matchedCount}
                        </Pill>
                        {scannedCount != null && (
                          <Pill tone="muted" variant="soft" withDot={false}>
                            SCANNED {scannedCount}
                          </Pill>
                        )}
                        <Pill tone="muted" variant="soft" withDot={false}>
                          SOURCE · {(sources.join(", ") || "NONE").toUpperCase()}
                        </Pill>
                      </span>
                    }
                  >
                    Results
                  </CardHeader>
                  <CardBody>
                    {rows.length === 0 ? (
                      <Empty
                        title="No matches with current filters"
                        body="Try a less restrictive DSL query or widen the universe."
                        action={
                          <button
                            type="button"
                            className="btn btn--accent"
                            onClick={() => {
                              setQuery(SAMPLES[0]);
                              setUniverse("SP500");
                              run();
                            }}
                          >
                            Reset & retry
                          </button>
                        }
                      />
                    ) : (
                      <DataGrid columns={cols} rows={rows} density="compact" />
                    )}
                  </CardBody>
                </Card>
              </>
            )}
          </div>
        </PaneBody>
        <PaneFooter>
          <span>provider · {(sources.join(", ") || "—")}</span>
          <span>elapsed · {elapsed != null ? elapsed.toFixed(0) : "—"} ms</span>
          <span>rows · {rows.length}/{limit}</span>
          <span>universe · {universe}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function NumericBar({ value, ratio }: { value: string; ratio: number }) {
  const pct = Math.max(0, Math.min(100, ratio * 100));
  return (
    <span className="most-numeric-bar">
      <span
        aria-hidden
        className="most-numeric-bar__track"
        style={{ ["--u-empty" as string]: `${100 - pct}%` }}
      />
      <span className="most-numeric-bar__label">{value}</span>
    </span>
  );
}

function FieldLabel({ children }: { children: ReactNode }) {
  return <span className="scan-field-label">{children}</span>;
}

function FilterChip({
  label,
  onRemove,
}: {
  label: string;
  onRemove?: () => void;
}) {
  return (
    <span style={filterChipStyle}>
      <span>{label}</span>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          style={filterChipCloseStyle}
          title="Remove filter"
          aria-label={`Remove filter ${label}`}
        >
          ×
        </button>
      )}
    </span>
  );
}

function normalizeRows(payload: unknown): Array<Record<string, unknown>> {
  if (Array.isArray(payload)) return payload.filter(isRecord);
  if (!isRecord(payload)) return [];
  const rows = payload.rows ?? payload.data ?? payload.items;
  return Array.isArray(rows) ? rows.filter(isRecord) : [];
}

/**
 * Static SP500 constituents lookup table. Wikipedia/S&P-derived snapshot
 * shipped in `ui/src/data/sp500.json`. When the user asks for the
 * `SP500` universe the screener now sends all ~500 tickers instead of
 * returning `null` (which fell through to a 5-stock hardcoded sample
 * — Bug #18). Source line + last-snapshot date live in the JSON.
 */
export const NAMED_UNIVERSES: Record<string, string[]> = {
  SP500: (sp500Data as { constituents: string[] }).constituents,
};

export function parseUniverse(value: string): string[] | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  // Named universes first (only "SP500" today; add NDX/DJIA/etc. by
  // dropping more JSON files into `ui/src/data/` and registering here).
  const named = NAMED_UNIVERSES[trimmed.toUpperCase()];
  if (named && named.length > 0) return [...named];
  // Otherwise parse a free-form ticker list (comma- or whitespace-delimited).
  const symbols = trimmed
    .split(/[\s,]+/)
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean);
  return symbols.length ? symbols : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const presetGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
  gap: 8,
};

const filterChipRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
  alignItems: "center",
};

const filterChipStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  height: 22,
  padding: "0 8px",
  background: "var(--surface-3)",
  border: "1px solid var(--border-subtle)",
  borderRadius: 11,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  letterSpacing: "0.06em",
  color: "var(--text-secondary)",
};

const filterChipCloseStyle: CSSProperties = {
  all: "unset",
  cursor: "default",
  width: 14,
  height: 14,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  borderRadius: "50%",
  color: "var(--text-mute)",
  fontSize: 12,
  lineHeight: 1,
};

const textareaStyle: CSSProperties = {
  width: "100%",
  resize: "vertical",
  background: "var(--surface-2)",
  color: "var(--text-primary)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
  padding: 8,
  outline: "none",
};

const sampleRowStyle: CSSProperties = {
  display: "flex",
  gap: 6,
  marginTop: 6,
  flexWrap: "wrap",
};

const kpiStripStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};
