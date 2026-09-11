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
import { formatNumberFixed } from "@/lib/format";
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
  const byMonth = payload?.by_month ?? [];
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
 */
function MonthlyHistogram({
  byMonth,
}: {
  byMonth: { month: string; count: number }[];
}) {
  const buckets = byMonth.slice(-12);
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
