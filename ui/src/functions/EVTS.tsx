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
import { useMemo, useState, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { PaneState } from "@/design-system/PaneState";
import {
  buildGridCsv,
  downloadGridCsv,
  gridCsvFilename,
  type GridCsvColumn,
} from "@/design-system/grid-csv";
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
  const [section, setSection] = useState("ALL");
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const { state, data, error, refetch } = useFunction<EVTSData>({
    code,
    symbol: effectiveSymbol,
    params: { reference: provider !== "yfinance" },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";
  const unavailable = status === "provider_unavailable";

  const sections = useMemo(() => {
    const set = new Set<string>();
    for (const row of rows) {
      if (row.source_section) set.add(row.source_section);
    }
    return ["ALL", ...Array.from(set).sort()];
  }, [rows]);

  const visible = useMemo(
    () => (section === "ALL" ? rows : rows.filter((r) => r.source_section === section)),
    [rows, section],
  );

  const COLS: DataGridColumn<EVTSRow>[] = useMemo(
    () => [
      {
        key: "date",
        header: "Date",
        width: 130,
        sortable: true,
        sortValue: (r) => r.date ?? "",
        render: (r) => (
          <span style={monoPrimaryStyle}>{fmtDate(r.date)}</span>
        ),
      },
      {
        key: "type",
        header: "Type",
        width: 110,
        sortable: true,
        sortValue: (r) => r.source_section ?? "",
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
        sortable: true,
        sortValue: (r) => r.event ?? "",
        render: (r) => <span style={titleStyle}>{r.event ?? "—"}</span>,
      },
      {
        key: "value",
        header: "Value",
        numeric: true,
        width: 200,
        sortable: true,
        sortValue: (r) => sortableValue(r.value),
        render: (r) => <span style={monoMutedStyle}>{fmtValue(r.value)}</span>,
      },
    ],
    [],
  );

  const csvColumns = useMemo<GridCsvColumn<EVTSRow>[]>(
    () => [
      { key: "date", header: "Date", value: (r) => fmtDate(r.date) },
      { key: "type", header: "Type", value: (r) => r.source_section ?? "" },
      { key: "event", header: "Event", value: (r) => r.event ?? "" },
      {
        key: "value",
        header: "Value",
        value: (r) => (Array.isArray(r.value) ? r.value.join(" / ") : r.value),
      },
    ],
    [],
  );

  const exportCsv = () => {
    const csv = buildGridCsv(csvColumns, visible);
    downloadGridCsv(gridCsvFilename(`evts-${effectiveSymbol || "events"}`), csv);
  };

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="EVTS needs an equity / ETF ticker." icon="⌖" />
  ) : (
    <PaneState
      state={state}
      error={error}
      empty={unavailable || rows.length === 0}
      emptyTitle={
        unavailable ? "Events provider unavailable" : "No corporate events returned"
      }
      emptyBody={
        unavailable
          ? (payload?.reason ??
            "The corporate-events provider returned nothing — no events are fabricated.")
          : `The ${provider} events provider returned no dated events for ${effectiveSymbol}.`
      }
      emptyIcon={unavailable ? "!" : "∅"}
      onRetry={refetch}
    >
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
        <div style={chipRowStyle} role="group" aria-label="Event type filter">
          {sections.map((sec) => {
            const active = section === sec;
            return (
              <button
                key={sec}
                type="button"
                className={`fn-segmented__opt${active ? " fn-segmented__opt--active" : ""}`}
                aria-pressed={active}
                onClick={() => setSection(sec)}
                title={`Filter event type ${sec}`}
              >
                {sec}
              </button>
            );
          })}
        </div>
        <DataGrid
          columns={COLS}
          rows={visible}
          rowKey={(r, i) => `${r.date ?? ""}-${r.event ?? ""}-${i}`}
          density="compact"
          ariaLabel="EVTS corporate events"
          defaultSortKey="date"
          defaultSortDir="descending"
          empty="No events match this type filter"
        />
      </div>
    </PaneState>
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
                {visible.length}/{rows.length} rows
              </Pill>
              <button
                type="button"
                className="btn"
                onClick={exportCsv}
                disabled={visible.length === 0}
                title="Download CSV"
                aria-label={`Download ${visible.length} events as CSV`}
              >
                CSV
              </button>
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

/** Sort accessor for the mixed value payload (numbers first, else text). */
function sortableValue(v: EVTSRow["value"]): string | number {
  if (v == null) return "";
  if (Array.isArray(v)) return v.length > 0 ? sortableValue(v[0]) : "";
  if (typeof v === "number") return Number.isFinite(v) ? v : "";
  const s = String(v).trim();
  if (!s) return "";
  const n = Number(s);
  return Number.isFinite(n) ? n : s;
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const chipRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
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
  fontSize: "var(--font-size-md)",
  color: "var(--text-primary)",
};
