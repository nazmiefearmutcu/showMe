/**
 * DVD — dividends (Awareness-backed).
 *
 * Data: `upcoming` declared dividends from awareness `/calendar/corporate`
 * (type dividend) and `history` from yfinance live history, plus a `summary`
 * block (annualised amount, last amount and ex-date, frequency guess).
 *
 * Honesty: the fabricated template default is gone. An empty payload renders
 * "No dividends" and never a made-up schedule. Unknown values show "—".
 */
import { useMemo, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
  DeltaChip,
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
import { formatMissing } from "@/lib/format";
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";
import { AwarenessUnavailable } from "./awareness/AwarenessUnavailable";
import { ProviderHealthStrip } from "./awareness/ProviderHealthStrip";
import type { AwarenessMeta } from "./awareness/types";
import type { ProvenanceSource } from "./awareness/ProvenanceButton";
import { ProvenanceButton } from "./awareness/ProvenanceButton";

export interface DivRow {
  ex_date?: string | null;
  date?: string | null;
  record_date?: string | null;
  pay_date?: string | null;
  amount?: number | null;
  currency?: string | null;
  source?: string | null;
  sources?: ProvenanceSource[] | null;
  fields?: Record<string, unknown> | null;
}

interface DvdSummary {
  annual_amount?: number | null;
  last_amount?: number | null;
  last_ex_date?: string | null;
  frequency_guess?: string | null;
}

interface DvdPayload {
  status?: string;
  reason?: string | null;
  upcoming?: DivRow[];
  history?: DivRow[];
  summary?: DvdSummary;
  meta?: AwarenessMeta;
  next_actions?: string[];
}

export function DVDPane({ code, symbol }: FunctionPaneProps) {
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const { state, data, error, refetch } = useFunction<DvdPayload>({
    code,
    symbol: effectiveSymbol,
    params: { history: true },
    enabled: !!effectiveSymbol,
  });

  const payload: DvdPayload = data?.data ?? {};
  const status = payload.status ?? "—";
  const unavailable = status === "provider_unavailable";
  const meta: AwarenessMeta = payload.meta ?? {};
  const upcoming = useMemo(
    () => sortRows(payload.upcoming ?? [], "asc"),
    [payload.upcoming],
  );
  const history = useMemo(() => sortRows(payload.history ?? [], "desc"), [payload.history]);
  const summary: DvdSummary = payload.summary ?? {};
  const currency = history[0]?.currency ?? upcoming[0]?.currency ?? null;
  const lastAmount = summary.last_amount ?? divAmount(history[0]);
  const empty = upcoming.length === 0 && history.length === 0;

  const COLS: DataGridColumn<DivRow>[] = useMemo(
    () => [
      {
        key: "ex",
        header: "Ex-date",
        width: 116,
        render: (r) => <span style={monoPrimaryStyle}>{fmtDay(divDate(r))}</span>,
      },
      {
        key: "record",
        header: "Record",
        width: 116,
        render: (r) => (
          <span style={monoMutedStyle}>
            {fmtDay(r.record_date ?? r.fields?.record_date)}
          </span>
        ),
      },
      {
        key: "pay",
        header: "Pay",
        width: 116,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtDay(r.pay_date ?? r.fields?.pay_date)}</span>
        ),
      },
      {
        key: "amount",
        header: "Amount",
        numeric: true,
        width: 112,
        render: (r) => (
          <span style={monoStrongStyle}>{fmtAmount(divAmount(r), r.currency)}</span>
        ),
      },
      {
        key: "source",
        header: "Source",
        render: (r) => (
          <span className="aw-cal__meta">
            <span style={monoMutedStyle}>
              {r.source ??
                ((r.sources ?? []).map((s) => s.provider).join(", ") || formatMissing)}
            </span>
            <ProvenanceButton
              sources={r.sources}
              subject={`dividend ${fmtDay(divDate(r))}`}
            />
          </span>
        ),
      },
    ],
    [],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="DVD needs an equity or ETF ticker." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={56} />
      <Skeleton height={20} />
      <Skeleton height={20} width="80%" />
    </div>
  ) : state === "error" ? (
    <Empty
      title="Function error"
      body={error?.message ?? formatMissing}
      icon="!"
      action={
        <button type="button" onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : unavailable ? (
    <AwarenessUnavailable
      reason={payload.reason ?? null}
      onRetry={refetch}
      subject="dividend data"
    />
  ) : empty ? (
    <Empty
      title="No dividends returned"
      body={`No declared or historical dividends for ${effectiveSymbol}. Nothing is estimated.`}
      action={
        <button type="button" onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="DVD summary">
        <StatCard
          label="Last dividend"
          value={fmtAmount(lastAmount, currency)}
          caption={summary.last_ex_date ? `EX ${fmtDay(summary.last_ex_date)}` : "—"}
          tone="neutral"
        />
        <StatCard
          label="Annualised"
          value={fmtAmount(summary.annual_amount ?? null, currency)}
          caption="FROM DECLARED RATE"
          tone="neutral"
        />
        <StatCard
          label="Frequency"
          value={summary.frequency_guess ?? formatMissing}
          caption="ESTIMATED FROM HISTORY"
          tone="neutral"
        />
        <StatCard
          label="Upcoming"
          value={String(upcoming.length)}
          caption="DECLARED"
          tone="neutral"
        />
      </section>
      {upcoming.length > 0 ? (
        <section aria-label="Upcoming dividends" className="u-grid-gap-8">
          <h3 style={sectionTitleStyle}>Upcoming</h3>
          <DataGrid
            columns={COLS}
            rows={upcoming}
            rowKey={(r, i) => `u-${divDate(r) ?? ""}-${i}`}
            density="compact"
            ariaLabel="Upcoming dividend rows"
          />
        </section>
      ) : null}
      {history.length > 0 ? (
        <section aria-label="Dividend history" className="u-grid-gap-8">
          <h3 style={sectionTitleStyle}>History</h3>
          <DataGrid
            columns={COLS}
            rows={history}
            rowKey={(r, i) => `h-${divDate(r) ?? ""}-${i}`}
            density="compact"
            ariaLabel="Dividend history rows"
          />
        </section>
      ) : null}
      {history.length >= 2 ? <ChangeNote history={history} /> : null}
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Dividends — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${upcoming.length} upcoming · ${history.length} history`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {history.length} history
              </Pill>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh dividends"
              />
            </FunctionControlGroup>
          }
        />
        <ProviderHealthStrip
          providers={meta.providers}
          feedHealth={meta.feed_health}
          generatedAt={meta.generated_at}
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="sources" value={data?.sources?.join(", ") || "awareness"} />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="rows" value={upcoming.length + history.length} />
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

/** Year-over-year change of the latest dividend vs the one about a year earlier. */
function ChangeNote({ history }: { history: DivRow[] }) {
  const latest = divAmount(history[0]);
  const prev = divAmount(history[1]);
  if (latest == null || prev == null || prev === 0) return null;
  const pct = ((latest - prev) / Math.abs(prev)) * 100;
  return (
    <p style={noteStyle} aria-label="Change versus the previous dividend">
      Latest vs previous: <DeltaChip value={pct} format="percent" fractionDigits={2} />
    </p>
  );
}

function divDate(r: DivRow): string | null {
  return r.ex_date ?? r.date ?? (r.fields?.ex_date as string | undefined) ?? null;
}

function divAmount(r: DivRow | undefined): number | null {
  if (!r) return null;
  const raw = r.amount ?? (r.fields?.amount as number | undefined) ?? null;
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

function sortRows(rows: DivRow[], dir: "asc" | "desc"): DivRow[] {
  const copy = [...rows];
  copy.sort((a, b) => {
    const da = divDate(a) ?? "";
    const db = divDate(b) ?? "";
    return dir === "asc" ? da.localeCompare(db) : db.localeCompare(da);
  });
  return copy;
}

function fmtDay(v: unknown): string {
  if (v == null) return formatMissing;
  const s = String(v).trim();
  return s ? s.slice(0, 10) : formatMissing;
}

function fmtAmount(v: number | null | undefined, currency?: string | null): string {
  if (v == null || !Number.isFinite(v)) return formatMissing;
  const prefix = currency && currency !== "USD" ? `${currency} ` : "$";
  return `${prefix}${v.toLocaleString("en-US", { maximumFractionDigits: 4 })}`;
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const sectionTitleStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--font-display)",
  fontSize: "var(--font-size-md)",
  fontWeight: 600,
  color: "var(--text-display)",
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

const noteStyle: CSSProperties = {
  margin: 0,
  fontSize: "var(--font-size-sm)",
  color: "var(--text-mute)",
};
