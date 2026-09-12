/**
 * FORM4 — SEC Form 4 insider transactions.
 *
 * Symbol-bound pane over the live SEC EDGAR Form 4 feed. Body: monthly
 * filing-count histogram (inline SVG bars, chronological) + compact
 * insider-transaction table (insider, role, date, txn type, shares, price)
 * capped with a showing-note.
 *
 * Honesty: when the upstream XML parser is unavailable the rows degrade to
 * Form 4 filing metadata (insider/shares/price = "—") — the pane discloses
 * that inline instead of inventing numbers, and links out to the SEC primary
 * document only when an absolute URL is present in the payload.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
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
  StatusDivider,
  StatusSection,
} from "@/design-system";
import {
  formatCurrency,
  formatNumberFixed,
  formatSignedCurrency,
} from "@/lib/format";
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { defaultSymbolForFunction } from "@/lib/symbols";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface FORM4Row {
  filingDate?: string | null;
  date?: string | null;
  insider?: string | null;
  filer?: string | null;
  role?: string | null;
  transaction_type?: string | null;
  transaction?: string | null;
  side?: string | null;
  shares?: number | null;
  price?: number | null;
  value?: number | null;
  filing_url?: string | null;
  source_mode?: string | null;
}

interface FORM4Filing {
  filingDate?: string | null;
  reportDate?: string | null;
  accession?: string | null;
  url?: string | null;
}

interface FORM4Data {
  status?: string;
  data_mode?: string;
  symbol?: string;
  n?: number;
  rows?: FORM4Row[];
  filings?: FORM4Filing[];
  by_month?: { month: string; count: number }[];
  as_of?: string;
  filing_count?: number;
  methodology?: string;
  reason?: string;
  next_actions?: string[];
}

const MONTHS_OPTIONS = [
  { value: 3, label: "3m" },
  { value: 6, label: "6m" },
  { value: 12, label: "12m" },
  { value: 24, label: "24m" },
] as const;
const MONTHS_IDS = MONTHS_OPTIONS.map((o) => o.value);

const TABLE_CAP = 25;

/** Live adoption: visibility-paused 120s poll (campaign 2026-09-11). */
const REFRESH_MS = 120_000;

function numOrNull(v: unknown): number | null {
  if (v == null) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

/** One month of signed insider flow, derived from the real row payload. */
export interface MonthlyNetBucket {
  month: string;
  count: number;
  /** Sum of buy-side notionals (USD), or null when the month is unresolved. */
  buy: number | null;
  /** Sum of sell-side notionals (USD, positive magnitude). */
  sell: number | null;
  /** buy − sell; null when unresolved (never a partial sum). */
  net: number | null;
  /** True only when every buy/sell row in the month carried a notional. */
  resolved: boolean;
  /** Buy/sell rows whose notional could not be derived (metadata-only). */
  missing: number;
}

const MONTH_KEY_RE = /^\d{4}-\d{2}$/;

function rowMonth(row: FORM4Row): string | null {
  const raw = String(row.filingDate ?? row.date ?? "").trim();
  const key = raw.slice(0, 7);
  return MONTH_KEY_RE.test(key) ? key : null;
}

/** buy → +1, sell → −1; grants/option exercises/metadata carry no buy-sell flow. */
function rowDirection(row: FORM4Row): number {
  const type = String(row.transaction_type ?? "").trim().toLowerCase();
  if (type === "buy") return 1;
  if (type === "sell") return -1;
  const side = String(row.side ?? "").trim().toLowerCase();
  if (side === "buy") return 1;
  if (side === "sell") return -1;
  return 0;
}

/** Reported USD value first, else shares × price; null when neither is real. */
function rowNotional(row: FORM4Row): number | null {
  const value = numOrNull(row.value);
  if (value != null) return value;
  const shares = numOrNull(row.shares);
  const price = numOrNull(row.price);
  return shares != null && price != null ? shares * price : null;
}

/**
 * Net insider flow per month: buys − sells in USD, computed from the filing
 * rows the pane already renders. A month is resolved only when EVERY buy/sell
 * row in it carries a computable notional — a partial sum would understate
 * the flow, so unresolved months stay null and render as an em-dash.
 */
export function monthlyNetBuckets(
  byMonth: { month: string; count: number }[],
  rows: FORM4Row[],
): MonthlyNetBucket[] {
  const totals = new Map<
    string,
    { buy: number; sell: number; missing: number }
  >();
  for (const row of rows) {
    const month = rowMonth(row);
    if (!month) continue;
    const direction = rowDirection(row);
    if (direction === 0) continue;
    const acc = totals.get(month) ?? { buy: 0, sell: 0, missing: 0 };
    const notional = rowNotional(row);
    if (notional == null) {
      acc.missing += 1;
    } else if (direction > 0) {
      acc.buy += Math.abs(notional);
    } else {
      acc.sell += Math.abs(notional);
    }
    totals.set(month, acc);
  }
  return byMonth.map((bucket) => {
    const acc = totals.get(bucket.month);
    if (!acc || acc.missing > 0) {
      return {
        month: bucket.month,
        count: bucket.count,
        buy: null,
        sell: null,
        net: null,
        resolved: false,
        missing: acc?.missing ?? 0,
      };
    }
    return {
      month: bucket.month,
      count: bucket.count,
      buy: acc.buy,
      sell: acc.sell,
      net: acc.buy - acc.sell,
      resolved: true,
      missing: 0,
    };
  });
}

/**
 * The wire emits `by_month` newest-first; take the most recent `cap` months
 * and flip to oldest-left chronological order for both monthly strips.
 */
export function recentChronological<T extends { month: string }>(
  months: T[],
  cap = 12,
): T[] {
  return [...months]
    .sort((a, b) => (a.month < b.month ? 1 : a.month > b.month ? -1 : 0))
    .slice(0, cap)
    .reverse();
}

export function FORM4Pane({ code, symbol }: FunctionPaneProps) {
  const [months, setMonths] = usePersistentOption<number>(
    "showme.form4.months",
    MONTHS_IDS,
    6,
  );
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY"]);
  const { state, data, error, refetch } = useFunction<FORM4Data>({
    code,
    symbol: effectiveSymbol,
    params: { months },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows: FORM4Row[] = useMemo(() => payload?.rows ?? [], [payload]);

  // Live adoption (campaign 2026-09-11): visibility-paused 120s refetch.
  // The tick only drives `refetch()`; keeping it out of `params` is what
  // prevents a fresh fetch key (and skeleton flash) on every poll (UA-HIGH-16).
  const tick = useVisibilityTick(REFRESH_MS);
  useEffect(() => {
    if (tick === 0) return; // initial mount is useFunction's own load
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tick is the trigger
  }, [tick]);

  // New-filings-since-last-poll badge. Honest by construction: the count is
  // only compared within the SAME (symbol, window) request, so a WINDOW change
  // re-baselines instead of masquerading as fresh filings. The first payload
  // is always a baseline (no badge).
  const countKey = `${effectiveSymbol}|${months}`;
  const countRef = useRef<{ key: string; count: number | null }>({
    key: "",
    count: null,
  });
  const [newSinceLastPoll, setNewSinceLastPoll] = useState(0);
  useEffect(() => {
    const count = numOrNull(
      payload?.filing_count ?? payload?.n ?? rows.length,
    );
    if (count == null) return;
    const prev = countRef.current;
    if (prev.key !== countKey || prev.count == null) {
      countRef.current = { key: countKey, count };
      setNewSinceLastPoll(0);
      return;
    }
    countRef.current = { key: countKey, count };
    setNewSinceLastPoll(count > prev.count ? count - prev.count : 0);
  }, [payload, rows.length, countKey]);
  const filings: FORM4Filing[] = useMemo(
    () => payload?.filings ?? [],
    [payload],
  );
  const byMonth = useMemo(() => payload?.by_month ?? [], [payload]);
  // OPP (audit A3): buys − sells in USD per month, computed from the same
  // rows the grid renders — no invented split of the count histogram.
  const netBuckets = useMemo(
    () => monthlyNetBuckets(byMonth, rows),
    [byMonth, rows],
  );
  const status = payload?.status ?? "—";
  const dataMode = payload?.data_mode ?? status;

  // Absolute SEC primary-document URL for row i (payload may carry a
  // relative stub like "xslF345X06/form4.xml" — never render that as a link).
  const absoluteUrls = useMemo(
    () =>
      rows.map((r, i) => {
        for (const candidate of [r.filing_url, filings[i]?.url]) {
          const raw = typeof candidate === "string" ? candidate.trim() : "";
          if (raw.startsWith("http://") || raw.startsWith("https://")) {
            return raw;
          }
        }
        return null;
      }),
    [rows, filings],
  );

  const shown = rows.slice(0, TABLE_CAP);
  const allMetadataOnly =
    rows.length > 0 &&
    rows.every((r) => (r.source_mode ?? "").includes("filing_metadata"));

  const COLS: DataGridColumn<FORM4Row>[] = useMemo(
    () => [
      {
        key: "date",
        header: "Date",
        width: 110,
        // Built-in sorter reads `sortValue` first; the row carries the date
        // under `filingDate` (or the legacy `date` alias).
        sortValue: (r) => r.filingDate ?? r.date ?? null,
        render: (r) => (
          <span style={monoPrimaryStyle}>
            {String(r.filingDate ?? r.date ?? "—").slice(0, 10)}
          </span>
        ),
      },
      {
        key: "insider",
        header: "Insider",
        width: 200,
        render: (r) => (
          <span style={r.insider || r.filer ? monoStrongStyle : monoMutedStyle}>
            {r.insider || r.filer || "—"}
          </span>
        ),
      },
      {
        key: "role",
        header: "Role",
        width: 170,
        render: (r) =>
          r.role ? (
            <span style={monoMutedStyle}>{r.role}</span>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
      {
        key: "transaction_type",
        header: "Type",
        width: 110,
        render: (r) => {
          const t = (r.transaction_type ?? "").trim();
          if (t) {
            return (
              <Pill
                tone={
                  t === "buy"
                    ? "positive"
                    : t === "sell"
                      ? "negative"
                      : "muted"
                }
                variant="soft"
                withDot={false}
              >
                {t}
              </Pill>
            );
          }
          const desc = (r.transaction ?? "").trim();
          return (
            <span className="u-text-mute" title={desc || undefined}>
              {desc && desc !== "Form 4 filing document" ? desc : "—"}
            </span>
          );
        },
      },
      {
        key: "shares",
        header: "Shares",
        numeric: true,
        width: 110,
        render: (r) => (
          <span style={monoStrongStyle}>{fmtNum(r.shares, 0)}</span>
        ),
      },
      {
        key: "price",
        header: "Price",
        numeric: true,
        width: 100,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtNum(r.price, 2)}</span>
        ),
      },
      {
        key: "filing",
        header: "Form",
        width: 76,
        render: (_r, i) => {
          const url = absoluteUrls[i];
          return url ? (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn--ghost fn-refresh-btn--labeled"
              title="Open SEC primary document"
              aria-label="Open SEC primary document"
            >
              SEC ↗
            </a>
          ) : (
            <span className="u-text-mute">—</span>
          );
        },
      },
    ],
    [absoluteUrls],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="FORM4 needs an equity ticker." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={72} />
      <Skeleton height={20} />
      <Skeleton height={20} />
      <Skeleton height={20} width="85%" />
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
      title="No Form 4 filings returned"
      body={
        payload?.next_actions?.[0] ??
        payload?.reason ??
        `No insider filings for ${effectiveSymbol} in the last ${months} months.`
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {newSinceLastPoll > 0 && (
        <div
          role="status"
          aria-live="polite"
          data-testid="form4-new-filings"
          style={noteStyle}
        >
          <Pill tone="accent" variant="soft" withDot={false}>
            {`+${newSinceLastPoll} new filing${newSinceLastPoll === 1 ? "" : "s"} since last poll`}
          </Pill>
        </div>
      )}
      <section aria-label="FORM4 monthly filing histogram">
        <MonthlyHistogram byMonth={byMonth} />
      </section>
      {netBuckets.length > 0 && (
        <section aria-label="FORM4 monthly net insider flow">
          <MonthlyNetFlow buckets={netBuckets} />
        </section>
      )}
      {allMetadataOnly && (
        <Pill tone="warn" variant="soft" withDot={false}>
          Filing metadata only — the upstream parser returned no per-trade
          shares or prices, not a fabricated table.
        </Pill>
      )}
      <DataGrid
        columns={COLS}
        rows={shown}
        rowKey={(r, i) => `${r.filingDate ?? ""}-${r.insider ?? ""}-${i}`}
        density="compact"
        ariaLabel="FORM4 insider transactions"
        // Audit A3 FORM4 M: primary filings grid gets the kit's built-in
        // sorter (newest first) + keyboard cell navigation/clipboard copy.
        defaultSortKey="date"
        defaultSortDir="descending"
        keyboardNavigable
      />
      {rows.length > shown.length && (
        <span className="u-text-mute" style={noteStyle}>
          Showing {shown.length} of {rows.length} filings (table capped).
        </span>
      )}
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Insider Transactions — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${rows.length} filings · as of ${
            (payload?.as_of ?? "").slice(0, 10) || "—"
          }`}
          trailing={
            <FunctionControlGroup>
              <Pill
                tone={
                  dataMode === "live_official"
                    ? "positive"
                    : dataMode === "delayed_reference"
                      ? "warn"
                      : "muted"
                }
                variant="soft"
              >
                {dataMode}
              </Pill>
              <SegmentedControl
                label="WINDOW"
                value={months}
                options={MONTHS_OPTIONS}
                onChange={setMonths}
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh Form 4 feed"
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
          <StatusSection label="filings" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="window" value={`${months}m`} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/**
 * Monthly filing-count histogram — inline SVG bars, chronological
 * (oldest left → newest right), capped at the most recent 12 buckets.
 * The wire order is newest-first; `recentChronological` keeps the newest
 * 12 (the old `slice(-12)` dropped them when >12 months were returned).
 */
function MonthlyHistogram({
  byMonth,
}: {
  byMonth: { month: string; count: number }[];
}) {
  const buckets = recentChronological(byMonth);
  if (!buckets.length) {
    return (
      <span className="u-text-mute">No monthly filing counts returned.</span>
    );
  }
  const max = buckets.reduce((m, b) => Math.max(m, b.count), 0) || 1;
  const slot = 44;
  const barW = 26;
  const height = 84;
  const width = buckets.length * slot;
  return (
    <div>
      <svg
        role="img"
        aria-label={`Filings per month, ${buckets[0].month} to ${
          buckets[buckets.length - 1].month
        }, peak ${max}`}
        width={width}
        height={height + 22}
        style={{ maxWidth: "100%" }}
      >
        {buckets.map((b, i) => {
          const h = Math.max(2, (b.count / max) * height);
          const x = i * slot + (slot - barW) / 2;
          return (
            <g key={b.month}>
              <title>{`${b.month}: ${b.count} filings`}</title>
              <rect
                x={x}
                y={height - h}
                width={barW}
                height={h}
                rx={2}
                fill="var(--accent)"
              />
              <text
                x={x + barW / 2}
                y={height + 14}
                textAnchor="middle"
                fontSize={9}
                fill="var(--text-mute)"
                style={{ fontFamily: "JetBrains Mono, monospace" }}
              >
                {b.month.slice(2)}
              </text>
              <text
                x={x + barW / 2}
                y={height - h - 3}
                textAnchor="middle"
                fontSize={9}
                fill="var(--text-secondary)"
                style={{ fontFamily: "JetBrains Mono, monospace" }}
              >
                {b.count}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/**
 * OPP (audit A3): net insider flow table — MONTH × (BUY, SELL, NET) with a
 * signed mini-bar in the NET column (positive right of the zero line, negative
 * left). Unresolved months render an em-dash and no bar; the row title spells
 * out why (metadata-only filings have no parsed shares × price).
 */
function MonthlyNetFlow({ buckets }: { buckets: MonthlyNetBucket[] }) {
  const shown = recentChronological(buckets);
  const maxAbs = shown.reduce(
    (m, b) => (b.net != null ? Math.max(m, Math.abs(b.net)) : m),
    0,
  );
  return (
    <div>
      <div style={netHeadStyle}>
        <span style={netTitleStyle}>NET INSIDER FLOW</span>
        <span style={netMetaStyle}>
          buys − sells, USD · — = transaction values not parsed
        </span>
      </div>
      <table style={netTableStyle}>
        <thead>
          <tr>
            <th scope="col" style={netThLeftStyle}>
              Month
            </th>
            <th scope="col" style={netThRightStyle}>
              Buy
            </th>
            <th scope="col" style={netThRightStyle}>
              Sell
            </th>
            <th scope="col" style={netThRightStyle}>
              Net
            </th>
          </tr>
        </thead>
        <tbody>
          {shown.map((b) => {
            const net = b.net;
            const unresolved = net == null;
            const tone =
              net == null
                ? "var(--text-mute)"
                : net > 0
                  ? "var(--positive)"
                  : net < 0
                    ? "var(--negative)"
                    : "var(--text-secondary)";
            const barPct =
              net != null && maxAbs > 0
                ? Math.max(1, (Math.abs(net) / maxAbs) * 100)
                : 0;
            const title = unresolved
              ? `Net not computable for ${b.month} — ${
                  b.missing > 0
                    ? `${b.missing} buy/sell filing(s) without parsed shares × price`
                    : "no parsed buy/sell rows"
                }`
              : `${b.month}: buy ${formatCurrency(b.buy, CURRENCY_OPTS)}, sell ${formatCurrency(b.sell, CURRENCY_OPTS)}, net ${formatSignedCurrency(b.net, CURRENCY_OPTS)}`;
            return (
              <tr
                key={b.month}
                data-testid="form4-net-row"
                data-net={unresolved ? "na" : String(b.net)}
                title={title}
              >
                <th scope="row" style={netMonthStyle}>
                  {b.month}
                </th>
                <td style={netMoneyStyle}>{fmtMoney(b.buy)}</td>
                <td style={netMoneyStyle}>{fmtMoney(b.sell)}</td>
                <td style={netCellStyle}>
                  <span
                    data-testid="form4-net-value"
                    style={{ ...netValueStyle, color: tone }}
                  >
                    {fmtSignedMoney(b.net)}
                  </span>
                  {net != null && (
                    <span style={netBarWrapStyle} aria-hidden="true">
                      <span style={netBarZeroStyle} />
                      <span
                        data-testid="form4-net-bar"
                        style={{
                          position: "absolute",
                          top: 2,
                          bottom: 2,
                          left: net >= 0 ? "50%" : undefined,
                          right: net < 0 ? "50%" : undefined,
                          width: `${barPct / 2}%`,
                          background:
                            net >= 0 ? "var(--positive)" : "var(--negative)",
                          borderRadius: 1,
                        }}
                      />
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Compact USD for the monthly net table (missing values → em-dash). */
const CURRENCY_OPTS = { compact: true, fractionDigits: 1 } as const;

function fmtMoney(v: number | null): string {
  return formatCurrency(v, CURRENCY_OPTS);
}

function fmtSignedMoney(v: number | null): string {
  return formatSignedCurrency(v, CURRENCY_OPTS);
}

function fmtNum(v: unknown, digits: number): string {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return formatNumberFixed(n, digits);
}

const noteStyle: CSSProperties = { fontSize: "var(--font-size-sm)" };
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

const netHeadStyle: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  gap: 8,
  marginBottom: 4,
};
const netTitleStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  letterSpacing: "0.08em",
  color: "var(--text-secondary)",
};
const netMetaStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
};
const netTableStyle: CSSProperties = {
  borderCollapse: "collapse",
  width: "100%",
  maxWidth: 560,
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: "var(--font-size-sm)",
};
const netThBaseStyle: CSSProperties = {
  fontWeight: 500,
  fontSize: "var(--font-size-2xs)",
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--text-mute)",
  borderBottom: "1px solid var(--border-subtle)",
  padding: "2px 6px",
};
const netThLeftStyle: CSSProperties = {
  ...netThBaseStyle,
  textAlign: "left",
};
const netThRightStyle: CSSProperties = {
  ...netThBaseStyle,
  textAlign: "right",
  width: 76,
};
const netMonthStyle: CSSProperties = {
  ...monoPrimaryStyle,
  fontWeight: 400,
  textAlign: "left",
  padding: "2px 6px",
  color: "var(--text-mute)",
};
const netMoneyStyle: CSSProperties = {
  ...monoPrimaryStyle,
  textAlign: "right",
  padding: "2px 6px",
};
const netCellStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "flex-end",
  gap: 6,
  padding: "2px 6px",
};
const netValueStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontWeight: 600,
  minWidth: 52,
  textAlign: "right",
};
const netBarWrapStyle: CSSProperties = {
  position: "relative",
  display: "inline-block",
  width: 64,
  height: 10,
  flex: "0 0 auto",
};
const netBarZeroStyle: CSSProperties = {
  position: "absolute",
  left: "50%",
  top: 0,
  bottom: 0,
  width: 1,
  background: "var(--border-subtle)",
};
