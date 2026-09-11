/**
 * HFS — Holder Search (13F reverse lookup).
 *
 * Search box takes an issuer ticker / company / CUSIP (defaults to the bound
 * symbol) and lists the filers that held it last quarter — shares, notional,
 * % outstanding, quarter — with recent searches persisted under
 * `showme.hfs.recent`.
 *
 * Data honesty: the backend reads the LOCAL SEC 13F DuckDB store. When the
 * store is empty the rows are labelled public-reference holders
 * (source_mode "reference_13f_public") and `next_actions` explains how to
 * backfill. The pane renders a prominent "Reference data" badge for those
 * rows and an honest "no local 13F match" state for provider_unavailable
 * payloads instead of implying live filings.
 */
import {
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type FormEvent,
} from "react";
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

interface HFSRow {
  filer?: string;
  issuer?: string;
  cusip?: string;
  shares?: number | null;
  market_value?: number | null;
  pct_outstanding?: number | null;
  quarter?: string | null;
  source_mode?: string;
}

interface HFSData {
  status?: string;
  rows?: HFSRow[];
  issuer?: string;
  quarter?: string;
  methodology?: string;
  next_actions?: string[];
  field_dictionary?: Record<string, unknown>;
}

const RECENT_KEY = "showme.hfs.recent";
const RECENT_MAX = 5;

function readRecents(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
      .map((item) => item.trim().toUpperCase())
      .slice(0, RECENT_MAX);
  } catch {
    return [];
  }
}

function writeRecents(values: string[]): string[] {
  const next = values.slice(0, RECENT_MAX);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable — recents just do not persist */
  }
  return next;
}

export function HFSPane({ code, symbol }: FunctionPaneProps) {
  const [input, setInput] = useState(() => (symbol || "").trim());
  const [lookup, setLookup] = useState(() => (symbol || "").trim());
  const [recents, setRecents] = useState<string[]>(readRecents);

  // Follow the terminal symbol when it changes; the search box overrides it.
  useEffect(() => {
    const s = (symbol || "").trim();
    if (s) {
      setInput(s);
      setLookup(s);
    }
  }, [symbol]);

  const { state, data, error, refetch } = useFunction<HFSData>({
    code,
    params: { issuer: lookup, live: true },
    enabled: lookup.length > 0,
  });

  const payload = data?.data;
  const rows: HFSRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";

  const unavailable = useMemo(
    () =>
      state === "ok" &&
      (status === "provider_unavailable" ||
        (rows.length > 0 &&
          rows.every((r) => r.source_mode === "holder_search_unavailable"))),
    [state, status, rows],
  );

  const isReference = useMemo(() => {
    if (unavailable || !rows.length) return false;
    const withMode = rows.filter((r) => !!r.source_mode);
    if (!withMode.length) return false;
    return withMode.every((r) => (r.source_mode ?? "").includes("reference"));
  }, [rows, unavailable]);
  const isLive = state === "ok" && status === "ok" && !isReference && !unavailable;

  // Persist the lookup once a result resolves OK (dedupe, most recent first).
  useEffect(() => {
    if (state !== "ok" || unavailable) return;
    const value = lookup.trim().toUpperCase();
    if (!value) return;
    setRecents((prev) => {
      const next = [value, ...prev.filter((item) => item !== value)].slice(0, RECENT_MAX);
      return writeRecents(next);
    });
  }, [state, unavailable, lookup]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const next = input.trim().toUpperCase();
    if (!next) return;
    setLookup(next);
  }

  function lookupFromRecent(value: string) {
    setInput(value);
    setLookup(value);
  }

  const stats = useMemo(() => deriveStats(rows), [rows]);
  const quarter = payload?.quarter ?? "—";

  const COLS: DataGridColumn<HFSRow>[] = useMemo(
    () => [
      {
        key: "filer",
        header: "Filer",
        width: 240,
        render: (r) => <span style={monoStrongStyle}>{r.filer ?? "—"}</span>,
      },
      {
        key: "issuer",
        header: "Issuer",
        width: 104,
        render: (r) => (
          <span style={monoPrimaryStyle}>{r.issuer ?? payload?.issuer ?? "—"}</span>
        ),
      },
      {
        key: "shares",
        header: "Shares",
        numeric: true,
        width: 132,
        render: (r) => (
          <span style={monoStrongStyle}>{fmtCompact(r.shares)}</span>
        ),
      },
      {
        key: "market_value",
        header: "Notional",
        numeric: true,
        width: 124,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtCompact(r.market_value)}</span>
        ),
      },
      {
        key: "pct_outstanding",
        header: "% out",
        numeric: true,
        width: 88,
        render: (r) => (
          <span style={monoStrongStyle}>{fmtPctOut(r.pct_outstanding)}</span>
        ),
      },
      {
        key: "quarter",
        header: "Quarter",
        width: 172,
        render: (r) => (
          <span style={monoMutedStyle}>
            {(r.quarter ?? payload?.quarter ?? "—").slice(0, 32)}
          </span>
        ),
      },
      {
        key: "source_mode",
        header: "Source",
        width: 196,
        render: (r) =>
          r.source_mode ? (
            <Pill
              tone={
                (r.source_mode ?? "").includes("reference") ||
                (r.source_mode ?? "").includes("unavailable")
                  ? "warn"
                  : "accent"
              }
              variant="soft"
              withDot={false}
            >
              {r.source_mode}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
    ],
    [payload?.issuer, payload?.quarter],
  );

  const resultBody = !lookup ? (
    <Empty
      title="Issuer required"
      body="Enter a ticker (AAPL), company name, or CUSIP to run the 13F reverse lookup."
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
  ) : unavailable || rows.length === 0 ? (
    <Empty
      title="No local 13F match"
      body={
        payload?.next_actions?.join(" ") ??
        "The local SEC 13F store returned no filers for this issuer. Run scripts/ingest_13f.py to backfill it."
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {isReference ? (
        <div role="status" aria-label="Reference data notice" style={referenceBannerStyle}>
          <Pill tone="warn" variant="soft">
            Reference data
          </Pill>
          <span style={referenceNoteStyle}>
            These rows are labelled public-reference holders, NOT live 13F
            filings. Backfill the local store (scripts/ingest_13f.py) for
            real filer positions.
          </span>
        </div>
      ) : null}
      <section style={kpiGridStyle} aria-label="HFS KPI ribbon">
        <StatCard
          label="Filers"
          value={String(rows.length)}
          caption={`ISSUER ${payload?.issuer ?? lookup}`}
          tone="neutral"
        />
        <StatCard
          label="Top filer"
          value={stats.topFiler ?? "—"}
          caption={fmtCompact(stats.topShares)}
          tone="neutral"
        />
        <StatCard
          label="Total shares"
          value={fmtCompact(stats.totalShares)}
          caption={`${quarter} QUARTER`}
          tone="neutral"
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(r, i) => `${r.filer ?? ""}-${i}`}
        density="compact"
        ariaLabel="HFS filer table"
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Holder Search — ${lookup || "—"}`}
          subtitle={`13F reverse lookup · ${rows.length} filers · ${quarter}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} filers
              </Pill>
              <Pill
                tone={isLive ? "positive" : isReference ? "warn" : "muted"}
                variant="soft"
                withDot={false}
              >
                {isLive ? "live" : isReference ? "reference" : status}
              </Pill>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!lookup}
                title="Refresh 13F lookup"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <form onSubmit={submit} style={searchFormStyle} aria-label="Issuer search">
            <label htmlFor="hfs-issuer-input" style={searchLabelStyle}>
              ISSUER
            </label>
            <input
              id="hfs-issuer-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ticker / company / CUSIP"
              spellCheck={false}
              autoComplete="off"
              style={searchInputStyle}
            />
            <button type="submit" className="btn" disabled={!input.trim()}>
              Search
            </button>
          </form>
          {recents.length > 0 ? (
            <div style={recentsRowStyle} aria-label="Recent searches">
              <span style={searchLabelStyle}>RECENT</span>
              {recents.map((item) => (
                <button
                  key={item}
                  type="button"
                  className="btn btn--ghost"
                  style={recentChipStyle}
                  onClick={() => lookupFromRecent(item)}
                  title={`Search ${item}`}
                >
                  {item}
                </button>
              ))}
            </div>
          ) : null}
          {resultBody}
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="issuer" value={payload?.issuer ?? (lookup || "—")} tone="accent" />
          <StatusDivider />
          <StatusSection label="rows" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

interface HFSStats {
  topFiler: string | null;
  topShares: number | null;
  totalShares: number | null;
}

function deriveStats(rows: HFSRow[]): HFSStats {
  if (!rows.length) {
    return { topFiler: null, topShares: null, totalShares: null };
  }
  const sorted = [...rows].sort(
    (a, b) => (finite(b.shares) ?? 0) - (finite(a.shares) ?? 0),
  );
  const shareVals = rows
    .map((r) => finite(r.shares))
    .filter((v): v is number => v != null);
  return {
    topFiler: sorted[0]?.filer ?? null,
    topShares: finite(sorted[0]?.shares),
    totalShares: shareVals.length ? shareVals.reduce((a, v) => a + v, 0) : null,
  };
}

/** Normalize a % outstanding figure: 13F reference rows report fractions. */
function normalizePct(v: unknown): number | null {
  const n = finite(v);
  if (n == null) return null;
  return Math.abs(n) <= 1.5 ? n * 100 : n;
}

function fmtPctOut(v: unknown): string {
  const n = normalizePct(v);
  return n == null ? "—" : `${n.toFixed(2)}%`;
}

function fmtCompact(v: unknown): string {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  const a = Math.abs(n);
  if (a >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function finite(v: unknown): number | null {
  if (v == null) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const referenceBannerStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  padding: "8px 10px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--warn-soft)",
  background: "var(--warn-soft)",
};

const referenceNoteStyle: CSSProperties = {
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-xs)",
  lineHeight: 1.45,
};

const searchFormStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const searchLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  color: "var(--text-mute)",
  letterSpacing: "0.06em",
  whiteSpace: "nowrap",
};

const searchInputStyle: CSSProperties = {
  flex: "0 1 280px",
  minWidth: 160,
  padding: "6px 10px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
};

const recentsRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
};

const recentChipStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
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
