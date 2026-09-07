/**
 * LITM — Litigation Monitor (SEC 8-K litigation / governance item filter).
 *
 * Header: ITEM filter segmented control (all / monitored 8-K item codes
 * 1.03 / 1.04 / 3.03 / 5.02 / 5.03) + status pill + refresh. Body: KPI count
 * strip (matters in view, matters returned, 8-K events scanned, monitored
 * items) + a dense matters table — filing date, item-code pill, normalized
 * event type, severity tone pill and a source stamp (accession / document),
 * symbol-bound.
 *
 * Data honesty: the backend honestly reports "empty" when recent 8-K events
 * match none of the monitored litigation/governance items (the common case).
 * The pane renders that as an explicit "no matters" state with the scan
 * count — it never dresses a sentinel row up as a legal case. Severity is a
 * ShowMe review flag, not legal advice, and is labelled as such.
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

interface LITMRow {
  symbol?: string;
  event_type?: string | null;
  item_code?: string | null;
  filing_date?: string | null;
  severity?: string | null;
  source_mode?: string;
  accession?: string | null;
  document?: string | null;
}

interface LITMData {
  status?: string;
  reason?: string;
  rows?: LITMRow[];
  litigation_filings?: unknown[];
  kept_item_codes?: string[];
  all_8k_events?: number;
  methodology?: string;
}

const ITEM_CODES = ["1.03", "1.04", "3.03", "5.02", "5.03"] as const;
type ItemFilter = "all" | (typeof ITEM_CODES)[number];
const ITEM_OPTIONS = [
  { value: "all" as const, label: "ALL" },
  ...ITEM_CODES.map((c) => ({ value: c, label: c })),
];
const ITEM_IDS = ITEM_OPTIONS.map((o) => o.value);

function isSentinelRow(r: LITMRow): boolean {
  const t = r.event_type ?? "";
  return t === "no_litigation_event_found" || t === "provider_unavailable";
}

function severityTone(severity: string | null | undefined): "warn" | "muted" {
  const s = (severity ?? "").toLowerCase();
  return s === "review" || s === "unknown" ? "warn" : "muted";
}

export function LITMPane({ code, symbol }: FunctionPaneProps) {
  const [itemFilter, setItemFilter] = usePersistentOption<ItemFilter>(
    "showme.litm.item",
    ITEM_IDS,
    "all",
  );
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY"]);
  const { state, data, error, refetch } = useFunction<LITMData>({
    code,
    symbol: effectiveSymbol,
    params: { live: true },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows: LITMRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";
  const providerDown = state === "ok" && status === "provider_unavailable";

  // Defense-in-depth: the pane's disclaimer promises only monitored items, so
  // rows outside the monitored set (backend `kept_item_codes`, else the known
  // litigation/governance items) never render as matters.
  const monitoredCodes: readonly string[] = useMemo(
    () =>
      payload?.kept_item_codes?.length
        ? payload.kept_item_codes
        : (ITEM_CODES as readonly string[]),
    [payload],
  );
  const matters = useMemo(
    () =>
      rows.filter(
        (r) =>
          !isSentinelRow(r) &&
          r.item_code != null &&
          monitoredCodes.includes(r.item_code),
      ),
    [rows, monitoredCodes],
  );
  const honestEmpty = state === "ok" && !providerDown && matters.length === 0;

  const filtered = useMemo(
    () =>
      itemFilter === "all"
        ? matters
        : matters.filter((r) => r.item_code === itemFilter),
    [matters, itemFilter],
  );

  const latestFiling = useMemo(
    () =>
      matters
        .map((r) => (r.filing_date ?? "").slice(0, 10))
        .filter((d) => /^\d{4}-\d{2}-\d{2}/.test(d))
        .sort()
        .at(-1) ?? "—",
    [matters],
  );

  const COLS: DataGridColumn<LITMRow>[] = useMemo(
    () => [
      {
        key: "filing_date",
        header: "Filed",
        width: 116,
        render: (r) => (
          <span style={monoPrimaryStyle}>
            {(r.filing_date ?? "—").slice(0, 10)}
          </span>
        ),
      },
      {
        key: "item_code",
        header: "Item",
        width: 96,
        render: (r) =>
          r.item_code ? (
            <Pill tone="accent" variant="soft" withDot={false}>
              {`8-K ${r.item_code}`}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
      {
        key: "event_type",
        header: "Event",
        width: 260,
        render: (r) => (
          <span style={monoStrongStyle}>{r.event_type ?? "—"}</span>
        ),
      },
      {
        key: "severity",
        header: "Severity",
        width: 120,
        render: (r) =>
          r.severity ? (
            <Pill tone={severityTone(r.severity)} variant="soft" withDot={false}>
              {r.severity}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
      {
        key: "source",
        header: "Source",
        width: 320,
        render: (r) => {
          const parts: string[] = [];
          if (r.accession) parts.push(`acc ${r.accession}`);
          if (r.document) parts.push(r.document);
          return (
            <span style={notesStyle}>
              {r.source_mode ?? "—"}
              {parts.length ? ` · ${parts.join(" · ")}` : ""}
            </span>
          );
        },
      },
    ],
    [],
  );

  const emptyBody = providerDown
    ? payload?.reason ??
      "LITM needs SEC 8-K filing rows; the provider path was unavailable for this symbol."
    : `Scanned ${payload?.all_8k_events ?? rows.length} recent 8-K events${
        payload?.kept_item_codes?.length
          ? `; none matched the monitored litigation/governance items ${payload.kept_item_codes.join(", ")}.`
          : "; none matched the monitored litigation/governance items."
      }`;

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="LITM needs an equity ticker." icon="⌖" />
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
  ) : providerDown || honestEmpty ? (
    <Empty
      title={
        providerDown
          ? "Litigation monitor unavailable"
          : "No litigation 8-K items found"
      }
      body={emptyBody}
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : filtered.length === 0 ? (
    <Empty
      title="No matters match the current item filter"
      body="Set the ITEM control back to ALL to see every monitored matter returned for this symbol."
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="LITM KPI strip">
        <StatCard
          label="Matters in view"
          value={String(filtered.length)}
          caption={`${matters.length} RETURNED`}
          tone="neutral"
        />
        <StatCard
          label="8-K events scanned"
          value={String(payload?.all_8k_events ?? "—")}
          caption="RECENT FILINGS WINDOW"
          tone="neutral"
        />
        <StatCard
          label="Monitored items"
          value={String(payload?.kept_item_codes?.length ?? "—")}
          caption={payload?.kept_item_codes?.join(" / ") || "—"}
          tone="neutral"
        />
        <StatCard
          label="Latest matter filed"
          value={latestFiling}
          caption="SEC EDGAR"
          tone="neutral"
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={filtered}
        rowKey={(r, i) => `${r.accession ?? ""}-${r.item_code ?? ""}-${i}`}
        density="compact"
        ariaLabel="LITM litigation matters table"
      />
      <p style={disclaimerStyle} role="note">
        Severity is a ShowMe review flag, not legal advice. Only 8-K items
        {" "}{payload?.kept_item_codes?.join(", ") || "1.03 / 1.04 / 3.03 / 5.02 / 5.03"}{" "}
        are monitored.
      </p>
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Litigation Monitor — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${filtered.length} of ${matters.length} matters`}
          trailing={
            <FunctionControlGroup>
              <SegmentedControl
                label="ITEM"
                value={itemFilter}
                options={ITEM_OPTIONS}
                onChange={setItemFilter}
                title="Monitored 8-K item filter"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh litigation monitor"
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
          <StatusSection label="rows" value={`${filtered.length}/${matters.length}`} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="item" value={itemFilter} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
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

const notesStyle: CSSProperties = {
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-xs)",
};

const disclaimerStyle: CSSProperties = {
  margin: 0,
  color: "var(--text-mute)",
  fontSize: "var(--font-size-xs)",
  lineHeight: 1.45,
};
