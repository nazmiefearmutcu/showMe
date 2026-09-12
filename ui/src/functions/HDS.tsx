/**
 * HDS — Holders (institutional / insider ownership table).
 *
 * Header: reference/live pill + load-state pill + refresh. Body: KPI ribbon
 * (holders, top holder, institutional count, total % out) + a dense holder
 * table — holder, type, shares (with a share-tint bar scaled to the largest
 * holder), % of shares outstanding, reported/quarter stamp and a per-row
 * source pill.
 *
 * Data honesty: HDS has a live path (yfinance holder tables + local SEC 13F),
 * but when both providers are unavailable the backend falls back to labelled
 * public-reference rows. The pane detects those rows (source_mode containing
 * "reference" / status "reference_holders") and renders a prominent
 * "Reference data" badge + inline note instead of implying live 13F filings.
 */
import { useMemo, type CSSProperties } from "react";
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
import { defaultSymbolForFunction } from "@/lib/symbols";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface HDSRow {
  symbol?: string;
  holder?: string;
  holder_type?: string;
  shares?: number | null;
  pct_outstanding?: number | null;
  market_value?: number | null;
  date_reported?: string | null;
  quarter?: string | null;
  source_mode?: string;
}

interface HDSData {
  status?: string;
  reason?: string;
  rows?: HDSRow[];
  methodology?: string;
  field_dictionary?: Record<string, unknown>;
}

export function HDSPane({ code, symbol }: FunctionPaneProps) {
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const { state, data, error, refetch } = useFunction<HDSData>({
    code,
    symbol: effectiveSymbol,
    params: { live: true },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows: HDSRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";

  const isReference = useMemo(() => {
    if (status === "reference_holders") return true;
    if (!rows.length) return false;
    const withMode = rows.filter((r) => !!r.source_mode);
    if (!withMode.length) return false;
    return withMode.every((r) => (r.source_mode ?? "").includes("reference"));
  }, [rows, status]);
  const isLive = state === "ok" && status === "ok" && !isReference;

  const stats = useMemo(() => deriveStats(rows), [rows]);
  const asOf = stats.asOf;

  const maxShares = useMemo(
    () =>
      rows.reduce(
        (acc, r) => Math.max(acc, finite(r.shares) ?? 0),
        0,
      ),
    [rows],
  );

  const COLS: DataGridColumn<HDSRow>[] = useMemo(
    () => [
      {
        key: "holder",
        header: "Holder",
        width: 240,
        render: (r) => (
          <span style={monoStrongStyle}>{r.holder ?? "—"}</span>
        ),
      },
      {
        key: "holder_type",
        header: "Type",
        width: 148,
        render: (r) =>
          r.holder_type ? (
            <Pill tone="muted" variant="soft" withDot={false}>
              {r.holder_type}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
      {
        key: "shares",
        header: "Shares",
        numeric: true,
        width: 188,
        render: (r) => {
          const shares = finite(r.shares);
          return (
            <span style={cellBarWrapStyle}>
              <span style={cellBarTextStackStyle}>
                <span style={monoStrongStyle}>{fmtCompact(shares)}</span>
                {shares != null && maxShares > 0 ? (
                  <span
                    style={barTrackStyle}
                    role="presentation"
                    aria-hidden="true"
                  >
                    <span
                      style={{
                        ...barFillStyle,
                        width: `${Math.max(2, (shares / maxShares) * 100)}%`,
                      }}
                    />
                  </span>
                ) : null}
              </span>
            </span>
          );
        },
      },
      {
        key: "pct_outstanding",
        header: "% out",
        numeric: true,
        width: 92,
        render: (r) => (
          <span style={monoStrongStyle}>{fmtPctOut(r.pct_outstanding)}</span>
        ),
      },
      {
        key: "reported",
        header: "Reported",
        width: 148,
        render: (r) => (
          <span style={monoMutedStyle}>
            {fmtReported(r.date_reported, r.quarter)}
          </span>
        ),
      },
      {
        key: "source_mode",
        header: "Source",
        width: 200,
        render: (r) =>
          r.source_mode ? (
            <Pill
              tone={
                (r.source_mode ?? "").includes("reference")
                  ? "warn"
                  : (r.source_mode ?? "").includes("13f")
                    ? "accent"
                    : "muted"
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
    [maxShares],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="HDS needs an equity / ETF ticker." icon="⌖" />
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
  ) : rows.length === 0 ? (
    <Empty
      title="No holder rows returned"
      body={
        payload?.reason ??
        "No institutional or 13F holder rows were returned for this symbol."
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
        <div
          role="status"
          aria-label="Reference data notice"
          style={referenceBannerStyle}
        >
          <Pill tone="warn" variant="soft">
            Reference data
          </Pill>
          <span style={referenceNoteStyle}>
            These are labelled public-reference holder rows, NOT live 13F
            filings. Backfill the local 13F store (scripts/ingest_13f.py) or
            retry when the live provider recovers.
          </span>
        </div>
      ) : null}
      <section style={kpiGridStyle} aria-label="HDS KPI ribbon">
        <StatCard
          label="Holders"
          value={String(rows.length)}
          caption={`AS OF ${asOf}`}
          tone="neutral"
        />
        <StatCard
          label="Top holder"
          value={stats.topHolder ?? "—"}
          caption={fmtCompact(stats.topShares)}
          tone="neutral"
        />
        <StatCard
          label="Institutions"
          value={String(stats.institutions)}
          caption="13F / INSTITUTIONAL ROWS"
          tone="neutral"
        />
        <StatCard
          label="Total % out"
          value={fmtPctOut(stats.totalPct)}
          caption="SUM OF ROWS"
          tone="neutral"
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(r, i) => `${r.holder ?? ""}-${i}`}
        density="compact"
        ariaLabel="HDS holder table"
        // Lane B4: largest holders first — matches the "Top holder" KPI and
        // the concentration read; null shares sink to the bottom.
        defaultSortKey="shares"
        defaultSortDir="descending"
        keyboardNavigable
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Holders — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${rows.length} holders · as of ${asOf}`}
          trailing={
            <FunctionControlGroup>
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
                disabled={!effectiveSymbol}
                title="Refresh holders"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "—"}
          />
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
          <StatusSection label="as of" value={asOf} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

interface HDSStats {
  topHolder: string | null;
  topShares: number | null;
  institutions: number;
  totalPct: number | null;
  asOf: string;
}

function deriveStats(rows: HDSRow[]): HDSStats {
  if (!rows.length) {
    return { topHolder: null, topShares: null, institutions: 0, totalPct: null, asOf: "—" };
  }
  const sorted = [...rows].sort(
    (a, b) => (finite(b.shares) ?? 0) - (finite(a.shares) ?? 0),
  );
  const institutions = rows.filter((r) =>
    (r.holder_type ?? "").includes("institutional"),
  ).length;
  const pctVals = rows
    .map((r) => normalizePct(r.pct_outstanding))
    .filter((v): v is number => v != null);
  const totalPct = pctVals.length ? pctVals.reduce((a, v) => a + v, 0) : null;
  const dated = rows
    .map((r) => (r.date_reported ?? "").slice(0, 10))
    .filter((d) => /^\d{4}-\d{2}-\d{2}/.test(d))
    .sort()
    .at(-1);
  const quarter = rows.map((r) => r.quarter ?? "").find((q) => !!q);
  return {
    topHolder: sorted[0]?.holder ?? null,
    topShares: finite(sorted[0]?.shares),
    institutions,
    totalPct,
    asOf: dated ?? (quarter ? String(quarter).slice(0, 32) : "—"),
  };
}

/** Normalize a % outstanding figure: yfinance reports fractions (0.087). */
function normalizePct(v: unknown): number | null {
  const n = finite(v);
  if (n == null) return null;
  return Math.abs(n) <= 1.5 ? n * 100 : n;
}

function fmtPctOut(v: unknown): string {
  const n = normalizePct(v);
  return n == null ? "—" : `${n.toFixed(2)}%`;
}

function fmtReported(
  dateReported: string | null | undefined,
  quarter: string | null | undefined,
): string {
  const d = (dateReported ?? "").slice(0, 10);
  if (/^\d{4}-\d{2}-\d{2}/.test(d)) return d;
  if (quarter) return String(quarter).slice(0, 32);
  return "—";
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

const cellBarWrapStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  width: "100%",
};

const cellBarTextStackStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
  flex: 1,
  minWidth: 0,
};

const barTrackStyle: CSSProperties = {
  display: "block",
  height: 3,
  borderRadius: 2,
  background: "var(--surface-3)",
  overflow: "hidden",
};

const barFillStyle: CSSProperties = {
  display: "block",
  height: "100%",
  background: "var(--accent)",
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
