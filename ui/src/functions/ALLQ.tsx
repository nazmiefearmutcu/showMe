/**
 * ALLQ — Dealer Quotes (TRACE proxy).
 *
 * Indicative dealer-quote ladder anchored to a real reference price (US
 * Treasury FiscalData avg rate for sovereign aliases, yfinance otherwise).
 * Header: bond label + quote-width control (persisted `showme.allq.spread`)
 * + refresh. Body: best-bid / best-ask / inside-spread headline cards +
 * dealer table with spread tints (tightest quote highlighted green,
 * widest flagged).
 *
 * Data honesty: every row is an INDICATIVE composite, not an executable
 * dealer price — the pane says so inline with the anchor reference. When
 * the backend cannot reach a reference price it returns
 * provider_unavailable and the pane shows that state, never fabricated
 * quotes.
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
  buildGridCsv,
  downloadGridCsv,
  gridCsvFilename,
  type GridCsvColumn,
} from "@/design-system/grid-csv";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface ALLQRow {
  bond?: string;
  dealer?: string;
  bid?: number;
  ask?: number;
  mid?: number;
  size?: number;
  spread_points?: number;
  spread_bps_of_price?: number;
  quote_time?: string;
  reference?: string;
}

interface ALLQData {
  status?: string;
  rows?: ALLQRow[];
  spread_curve?: { dealer?: string; spread_bps_of_price?: number }[];
  summary?: {
    bond?: string;
    mid?: number;
    best_bid?: number;
    best_ask?: number;
    reference?: string;
    source_mode?: string;
  };
  next_actions?: string[];
  methodology?: string;
  field_dictionary?: Record<string, unknown>;
}

const SPREAD_OPTIONS = [
  { value: 10, label: "0.10", title: "WIDTH 0.10 pts" },
  { value: 18, label: "0.18", title: "WIDTH 0.18 pts" },
  { value: 25, label: "0.25", title: "WIDTH 0.25 pts" },
  { value: 36, label: "0.36", title: "WIDTH 0.36 pts" },
] as const;
const SPREAD_IDS = SPREAD_OPTIONS.map((o) => o.value);

export function ALLQPane({ code, symbol }: FunctionPaneProps) {
  const [spreadPts, setSpreadPts] = usePersistentOption<number>(
    "showme.allq.spread",
    SPREAD_IDS,
    18,
  );
  const effectiveSymbol =
    symbol || defaultSymbolForFunction(code, ["EQUITY", "BOND"]);
  const { state, data, error, refetch } = useFunction<ALLQData>({
    code,
    symbol: effectiveSymbol,
    params: { spread: spreadPts / 100 },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows: ALLQRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const summary = payload?.summary;
  const status = payload?.status ?? "—";

  const stats = useMemo(() => deriveStats(rows), [rows]);

  const COLS: DataGridColumn<ALLQRow>[] = useMemo(() => {
    const tightest = stats.minSpreadBps;
    const widest = stats.maxSpreadBps;
    return [
      {
        key: "dealer",
        header: "Dealer",
        width: 130,
        render: (r) => <span style={monoStrongStyle}>{r.dealer ?? "—"}</span>,
      },
      {
        key: "bid",
        header: "Bid",
        numeric: true,
        width: 104,
        render: (r) => (
          <span
            style={{
              ...monoPrimaryStyle,
              color:
                typeof r.bid === "number" && stats.bestBid != null && r.bid === stats.bestBid
                  ? "var(--positive)"
                  : undefined,
            }}
          >
            {fmtPrice(r.bid)}
          </span>
        ),
      },
      {
        key: "ask",
        header: "Ask",
        numeric: true,
        width: 104,
        render: (r) => (
          <span
            style={{
              ...monoPrimaryStyle,
              color:
                typeof r.ask === "number" && stats.bestAsk != null && r.ask === stats.bestAsk
                  ? "var(--positive)"
                  : undefined,
            }}
          >
            {fmtPrice(r.ask)}
          </span>
        ),
      },
      {
        key: "mid",
        header: "Mid",
        numeric: true,
        width: 104,
        render: (r) => <span style={monoMutedStyle}>{fmtPrice(r.mid)}</span>,
      },
      {
        key: "spread_bps_of_price",
        header: "Spread bps",
        numeric: true,
        width: 118,
        render: (r) => {
          const bps = r.spread_bps_of_price;
          const tone =
            typeof bps === "number" && bps === tightest
              ? "var(--positive)"
              : typeof bps === "number" && bps === widest && tightest !== widest
                ? "var(--negative)"
                : "var(--text-primary)";
          return (
            <span style={{ ...monoStrongStyle, color: tone }}>
              {fmtFixed(bps, 1)}
            </span>
          );
        },
      },
      {
        key: "size",
        header: "Size",
        numeric: true,
        width: 104,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtCompact(r.size)}</span>
        ),
      },
      {
        key: "quote_time",
        header: "Quote time",
        width: 108,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtTime(r.quote_time)}</span>
        ),
      },
    ];
  }, [stats]);

  // CSV export of the dealer ladder — RAW payload numbers (exporters should
  // not parse formatted "106.2081" strings back into floats).
  const csvColumns = useMemo<GridCsvColumn<ALLQRow>[]>(
    () => [
      { key: "dealer", header: "Dealer", value: (r) => r.dealer ?? "" },
      { key: "bond", header: "Bond", value: (r) => r.bond ?? "" },
      { key: "bid", header: "Bid", value: (r) => r.bid ?? "" },
      { key: "ask", header: "Ask", value: (r) => r.ask ?? "" },
      { key: "mid", header: "Mid", value: (r) => r.mid ?? "" },
      {
        key: "spread_bps_of_price",
        header: "Spread bps",
        value: (r) => r.spread_bps_of_price ?? "",
      },
      { key: "size", header: "Size", value: (r) => r.size ?? "" },
      {
        key: "quote_time",
        header: "Quote time",
        value: (r) => r.quote_time ?? "",
      },
      { key: "reference", header: "Reference", value: (r) => r.reference ?? "" },
    ],
    [],
  );

  const exportCsv = () => {
    const csv = buildGridCsv(csvColumns, rows);
    downloadGridCsv(
      gridCsvFilename(`allq-${summary?.bond ?? effectiveSymbol ?? "quotes"}`),
      csv,
    );
  };

  const unavailableReason =
    payload?.next_actions?.[0] ??
    data?.warnings?.[0] ??
    "Reference price source unreachable — no quotes are shown rather than fabricated ones.";

  const body = !effectiveSymbol ? (
    <Empty title="Pick a bond" body="ALLQ needs a bond alias to build the ladder." icon="⌖" />
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
      title="No dealer quotes"
      body={
        status === "provider_unavailable"
          ? unavailableReason
          : "The ladder came back empty for this bond."
      }
      icon="∅"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <div role="note" style={noticeStyle}>
        <strong>Indicative quotes.</strong> Composite ladder anchored to{" "}
        {summary?.reference ?? "a real reference price"} — NOT executable
        dealer prices.
      </div>
      <section style={kpiGridStyle} aria-label="ALLQ top of book">
        <StatCard
          label="Best bid"
          value={fmtPrice(stats.bestBid)}
          caption={stats.bestBidDealer ? `DEALER ${stats.bestBidDealer}` : "—"}
          tone="positive"
        />
        <StatCard
          label="Best ask"
          value={fmtPrice(stats.bestAsk)}
          caption={stats.bestAskDealer ? `DEALER ${stats.bestAskDealer}` : "—"}
          tone="positive"
        />
        <StatCard
          label="Inside spread"
          value={fmtFixed(stats.insideBps, 1)}
          caption="BPS OF MID"
          tone="neutral"
        />
        <StatCard
          label="Anchor mid"
          value={fmtPrice(summary?.mid ?? stats.insideMid)}
          caption={`${rows.length} COMPOSITES`}
          tone="neutral"
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(r, i) => `${r.dealer ?? "d"}-${i}`}
        density="compact"
        ariaLabel="ALLQ dealer quote ladder"
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Dealer Quotes — ${summary?.bond ?? effectiveSymbol ?? ""}`}
          subtitle={`${effectiveSymbol || "—"} · indicative TRACE proxy`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} quotes
              </Pill>
              <Pill
                tone={status === "ok" ? "positive" : "warn"}
                variant="soft"
                withDot={false}
              >
                indicative
              </Pill>
              <SegmentedControl
                label="WIDTH"
                value={spreadPts}
                options={SPREAD_OPTIONS}
                onChange={setSpreadPts}
              />
              <button
                type="button"
                className="btn"
                onClick={exportCsv}
                disabled={rows.length === 0}
                title="Download CSV"
                aria-label={`Download ${rows.length} dealer quotes as CSV`}
              >
                CSV
              </button>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh dealer ladder"
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
          <StatusSection label="quotes" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="width" value={`±${(spreadPts / 100).toFixed(2)}`} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── stats ─────────────────────────────────────────────────────────── */

interface ALLQStats {
  bestBid: number | null;
  bestBidDealer: string | null;
  bestAsk: number | null;
  bestAskDealer: string | null;
  insideBps: number | null;
  insideMid: number | null;
  minSpreadBps: number | null;
  maxSpreadBps: number | null;
}

function deriveStats(rows: ALLQRow[]): ALLQStats {
  let bestBid: ALLQRow | null = null;
  let bestAsk: ALLQRow | null = null;
  let minSpread: ALLQRow | null = null;
  let maxSpread: ALLQRow | null = null;
  for (const r of rows) {
    if (typeof r.bid === "number" && (bestBid?.bid ?? -Infinity) < r.bid) bestBid = r;
    if (typeof r.ask === "number" && (bestAsk?.ask ?? Infinity) > r.ask) bestAsk = r;
    if (
      typeof r.spread_bps_of_price === "number" &&
      (minSpread?.spread_bps_of_price ?? Infinity) > r.spread_bps_of_price
    ) {
      minSpread = r;
    }
    if (
      typeof r.spread_bps_of_price === "number" &&
      (maxSpread?.spread_bps_of_price ?? -Infinity) < r.spread_bps_of_price
    ) {
      maxSpread = r;
    }
  }
  let insideBps: number | null = null;
  let insideMid: number | null = null;
  if (
    bestBid?.bid != null &&
    bestAsk?.ask != null &&
    bestAsk.ask >= bestBid.bid
  ) {
    insideMid = (bestBid.bid + bestAsk.ask) / 2;
    const spread = bestAsk.ask - bestBid.bid;
    insideBps = insideMid > 0 ? (spread / insideMid) * 10_000 : null;
  }
  return {
    bestBid: bestBid?.bid ?? null,
    bestBidDealer: bestBid?.dealer ?? null,
    bestAsk: bestAsk?.ask ?? null,
    bestAskDealer: bestAsk?.dealer ?? null,
    insideBps,
    insideMid,
    minSpreadBps: minSpread?.spread_bps_of_price ?? null,
    maxSpreadBps: maxSpread?.spread_bps_of_price ?? null,
  };
}

/* ── formatting ────────────────────────────────────────────────────── */

function fmtPrice(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(4);
}

function fmtFixed(v: number | null | undefined, digits: number): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

function fmtCompact(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
  return String(v);
}

function fmtTime(iso: string | undefined): string {
  if (!iso || iso.length < 19) return "—";
  return iso.slice(11, 19) + "Z";
}

/* ── styles ────────────────────────────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const noticeStyle: CSSProperties = {
  border: "1px solid var(--warn, var(--text-mute))",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: "var(--font-size-md)",
  color: "var(--text-primary)",
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
