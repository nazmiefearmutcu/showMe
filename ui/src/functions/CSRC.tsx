/**
 * CSRC — Commodity Screener.
 *
 * Screen over the backend commodity reference universe (backend
 * screen/_funcs.py CSRCFunction). The pane composes a server-side DSL
 * filter from a persisted commodity-sector control, requests the live
 * quote overlay (`live: true`), and renders the payload's own metrics
 * table. Rows that the quote provider did not answer keep their
 * reference fields and carry an honest "reference" source pill — they
 * are never painted as live prices. Empty results surface the
 * backend's reason / next_actions guidance verbatim.
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
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import {
  formatCompactNumber,
  formatPercent,
  formatPrice,
} from "@/lib/format";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface CSRCRow {
  symbol?: string;
  name?: string;
  sector?: string;
  exchange?: string;
  contract_unit?: string;
  volume?: number;
  open_interest?: number;
  last?: number | null;
  change_pct?: number | null;
  quote_state?: string;
}

interface CSRCData {
  status?: string;
  reason?: string;
  query?: string;
  filter?: string;
  rows?: CSRCRow[];
  scanned?: number;
  matched?: number;
  next_actions?: string[];
}

const SECTOR_OPTIONS = [
  { value: "ALL", label: "ALL", title: "Sector ALL" },
  { value: "Energy", label: "ENERGY", title: "Sector Energy" },
  { value: "Metals", label: "METALS", title: "Sector Metals" },
  { value: "Agriculture", label: "AGRS", title: "Sector Agriculture" },
] as const;

const SORT_OPTIONS = [
  { value: "volume", label: "VOLUME", title: "Sort by volume" },
  { value: "open_interest", label: "OI", title: "Sort by open interest" },
  { value: "change_pct", label: "CHG%", title: "Sort by day change" },
] as const;

// The backend treats an empty `query` as "use my default" (which would
// silently restrict the screen to Energy), so the all-sectors filter is
// expressed as a permissive predicate instead — every reference row has
// a non-negative volume.
const MATCH_ALL_QUERY = "volume >= 0";
const LIMIT = 50;

export function CSRCPane({ code }: FunctionPaneProps) {
  const [sector, setSector] = usePersistentOption<string>(
    "showme.csrc.sector",
    SECTOR_OPTIONS.map((o) => o.value),
    "ALL",
  );
  const [sortKey, setSortKey] = usePersistentOption<string>(
    "showme.csrc.sort",
    SORT_OPTIONS.map((o) => o.value),
    "volume",
  );

  const query = useMemo(
    () => (sector === "ALL" ? MATCH_ALL_QUERY : `sector = "${sector}"`),
    [sector],
  );

  const { state, data, error, refetch } = useFunction<CSRCData>({
    code,
    params: { query, limit: LIMIT, live: true },
  });

  const payload = data?.data;
  const status = payload?.status ?? "—";

  const rows = useMemo(() => {
    const base = payload?.rows ?? [];
    const key = sortKey as keyof CSRCRow;
    return [...base].sort((a, b) => num(b[key]) - num(a[key]));
  }, [payload, sortKey]);

  const referenceCount = useMemo(
    () => rows.filter((row) => row.quote_state === "reference").length,
    [rows],
  );

  const isFilterError =
    status === "unsupported_predicate" || status === "input_error";

  const COLS: DataGridColumn<CSRCRow>[] = useMemo(
    () => [
      {
        key: "symbol",
        header: "Symbol",
        width: 96,
        render: (r) => <span style={monoStrongStyle}>{r.symbol ?? "—"}</span>,
      },
      {
        key: "name",
        header: "Contract",
        width: 160,
        render: (r) => (
          <span style={monoPrimaryStyle} title={r.contract_unit ?? undefined}>
            {r.name ?? "—"}
          </span>
        ),
      },
      {
        key: "sector",
        header: "Sector",
        width: 110,
        render: (r) =>
          r.sector ? (
            <Pill tone="accent" variant="soft" withDot={false}>
              {r.sector}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
      {
        key: "last",
        header: "Last",
        numeric: true,
        width: 100,
        render: (r) =>
          r.last == null ? (
            <span className="u-text-mute">—</span>
          ) : (
            <span style={monoStrongStyle}>{formatPrice(r.last)}</span>
          ),
      },
      {
        key: "change_pct",
        header: "Chg%",
        numeric: true,
        width: 90,
        render: (r) =>
          r.change_pct == null ? (
            <span className="u-text-mute">—</span>
          ) : (
            <span
              style={{
                ...monoStrongStyle,
                color:
                  r.change_pct >= 0 ? "var(--positive)" : "var(--negative)",
              }}
            >
              {formatPercent(r.change_pct, { signed: true })}
            </span>
          ),
      },
      {
        key: "volume",
        header: "Volume",
        numeric: true,
        width: 100,
        render: (r) => (
          <span style={monoMutedStyle}>{formatCompactNumber(r.volume)}</span>
        ),
      },
      {
        key: "open_interest",
        header: "Open int.",
        numeric: true,
        width: 100,
        render: (r) => (
          <span style={monoMutedStyle}>
            {formatCompactNumber(r.open_interest)}
          </span>
        ),
      },
      {
        key: "quote_state",
        header: "Source",
        width: 110,
        render: (r) =>
          r.quote_state ? (
            <Pill
              tone={r.quote_state === "live" ? "positive" : "muted"}
              variant="soft"
              withDot={false}
            >
              {r.quote_state}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
    ],
    [],
  );

  const body =
    state === "loading" || state === "idle" ? (
      <div className="u-grid-gap-8">
        <Skeleton height={28} />
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
    ) : isFilterError ? (
      <Empty
        title="Filter error"
        body={payload?.reason ?? "The active filter could not be applied."}
        icon="!"
        action={
          <button onClick={() => setSector("ALL")} className="btn">
            Reset filters
          </button>
        }
      />
    ) : rows.length === 0 ? (
      <Empty
        title="No rows matched your filters"
        body={
          payload?.reason ??
          payload?.next_actions?.[0] ??
          "Broaden the commodity sector filter and run the screen again."
        }
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : (
      <div className="u-grid-gap-14">
        <DataGrid
          columns={COLS}
          rows={rows}
          rowKey={(r, i) => `${r.symbol ?? ""}-${i}`}
          density="compact"
          ariaLabel="Commodity screener results"
        />
        <p style={noteStyle} aria-label="Result count note">
          {rows.length} of {payload?.matched ?? rows.length} matched
          {" · "}
          {payload?.scanned ?? "—"} scanned
          {" · "}
          query "{payload?.query ?? query}"
          {referenceCount > 0
            ? ` · ${referenceCount} reference row${referenceCount === 1 ? "" : "s"} (no live quote)`
            : ""}
        </p>
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Commodity Screener"
          subtitle={`${payload?.matched ?? 0} matched · ${payload?.scanned ?? 0} scanned`}
          trailing={
            <FunctionControlGroup>
              <SegmentedControl
                label="SECTOR"
                value={sector}
                options={SECTOR_OPTIONS}
                onChange={setSector}
              />
              <SegmentedControl
                label="SORT"
                value={sortKey}
                options={SORT_OPTIONS}
                onChange={setSortKey}
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Re-run commodity screen"
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
          <StatusSection label="matched" value={payload?.matched ?? 0} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="filter" value={query} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function num(value: unknown): number {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
}

const noteStyle: CSSProperties = {
  margin: 0,
  color: "var(--text-mute)",
  fontSize: 11,
  fontFamily: "JetBrains Mono, monospace",
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const monoPrimaryStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-primary)",
};

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
};
