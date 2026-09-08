/**
 * EVTS — Corporate Events Calendar.
 *
 * yfinance-gated dated corporate events (calendar entries, earnings dates,
 * actions, dividends, splits) per equity. Header: provider control
 * (persisted under `showme.evts.provider`) + status pill + refresh. Body:
 * events table (date, type chip, event, value) newest first. When the
 * calendar provider returns nothing the pane renders the backend's honest
 * reason — events are never invented.
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
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface EVTSRow {
  date?: string | null;
  event?: string;
  value?: string | number | (string | number)[] | null;
  source_section?: string;
  symbol?: string;
}

interface EVTSData {
  status?: string;
  reason?: string;
  rows?: EVTSRow[];
  symbol?: string;
  event_count?: number;
  next_actions?: string[];
}

type ProviderValue = "yfinance" | "off";
const PROVIDER_OPTIONS = [
  { value: "yfinance" as ProviderValue, label: "yfinance" },
  { value: "off" as ProviderValue, label: "off" },
] as const;
const PROVIDER_IDS = PROVIDER_OPTIONS.map((o) => o.value);

function chipTone(section: string | undefined): "accent" | "positive" | "warn" | "muted" {
  switch ((section ?? "").toLowerCase()) {
    case "earnings": return "accent";
    case "dividends": return "positive";
    case "action": return "warn";
    default: return "muted";
  }
}

export function EVTSPane({ code, symbol }: FunctionPaneProps) {
  const [provider, setProvider] = usePersistentOption<ProviderValue>(
    "showme.evts.provider",
    PROVIDER_IDS,
    "yfinance",
  );
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const { state, data, error, refetch } = useFunction<EVTSData>({
    code,
    symbol: effectiveSymbol,
    params: { live_events: provider === "yfinance" },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";
  const unavailable = status === "provider_unavailable";

  const COLS: DataGridColumn<EVTSRow>[] = useMemo(
    () => [
      {
        key: "date",
        header: "Date",
        width: 130,
        render: (r) => (
          <span style={monoPrimaryStyle}>{fmtDate(r.date)}</span>
        ),
      },
      {
        key: "type",
        header: "Type",
        width: 110,
        render: (r) => (
          <Pill tone={chipTone(r.source_section)} variant="soft" withDot={false}>
            {r.source_section ?? "event"}
          </Pill>
        ),
      },
      {
        key: "event",
        header: "Event",
        width: 240,
        render: (r) => <span style={titleStyle}>{r.event ?? "—"}</span>,
      },
      {
        key: "value",
        header: "Value",
        numeric: true,
        width: 200,
        render: (r) => <span style={monoMutedStyle}>{fmtValue(r.value)}</span>,
      },
    ],
    [],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="EVTS needs an equity / ETF ticker." icon="⌖" />
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
  ) : unavailable ? (
    <Empty
      title="Events provider unavailable"
      body={payload?.reason ?? "The corporate-events provider returned nothing — no events are fabricated."}
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : rows.length === 0 ? (
    <Empty
      title="No corporate events returned"
      body={`The ${provider} events provider returned no dated events for ${effectiveSymbol}.`}
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="EVTS summary">
        <StatCard
          label="Events"
          value={String(payload?.event_count ?? rows.length)}
          caption={`PROVIDER ${provider.toUpperCase()} · NEWEST FIRST`}
          tone="neutral"
        />
        <StatCard
          label="Earnings rows"
          value={String(rows.filter((r) => r.source_section === "earnings").length)}
          caption="REPORT / ESTIMATE DATES"
          tone="neutral"
        />
        <StatCard
          label="Dividends + splits"
          value={String(
            rows.filter((r) => r.source_section === "dividends" || r.source_section === "splits").length,
          )}
          caption="DISTRIBUTION EVENTS"
          tone="neutral"
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(r, i) => `${r.date ?? ""}-${r.event ?? ""}-${i}`}
        density="compact"
        ariaLabel="EVTS corporate events"
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Corporate Events — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${rows.length} events · ${provider}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} rows
              </Pill>
              <SegmentedControl
                label="PROVIDER"
                value={provider}
                options={PROVIDER_OPTIONS}
                onChange={setProvider}
                title="Corporate events provider"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh corporate events"
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
          <StatusSection label="events" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="provider" value={provider} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function fmtDate(v: string | null | undefined): string {
  const s = String(v ?? "").trim();
  if (!s) return "—";
  return s.slice(0, 10);
}

function fmtValue(v: EVTSRow["value"]): string {
  if (v == null) return "—";
  if (Array.isArray(v)) return v.map((item) => fmtValue(item)).join(" / ");
  if (typeof v === "number" && Number.isFinite(v)) {
    return v.toLocaleString("en-US", { maximumFractionDigits: 4 });
  }
  const s = String(v).trim();
  return s || "—";
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
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

const titleStyle: CSSProperties = {
  fontSize: 12,
  color: "var(--text-primary)",
};
