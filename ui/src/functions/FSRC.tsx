/**
 * FSRC — Fund Screener.
 *
 * Screen over the backend fund/ETF reference universe (backend
 * screen/_funcs.py FSRCFunction). The pane composes a server-side DSL
 * filter from two persisted controls — fund category chips and a max
 * expense-ratio segmented control — and requests the live quote
 * overlay (`live: true`). Rows the quote provider did not answer keep
 * their reference fields behind an honest "reference" pill. Empty
 * results surface the backend's reason / next_actions guidance and a
 * one-click filter reset.
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
  formatCurrency,
  formatPercent,
  formatPrice,
} from "@/lib/format";
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

interface FSRCRow {
  symbol?: string;
  name?: string;
  issuer?: string;
  category?: string;
  aum_usd?: number;
  expenseRatio?: number;
  ytd_return_pct?: number;
  dividend_yield?: number;
  last?: number | null;
  change_pct?: number | null;
  quote_state?: string;
}

interface FSRCData {
  status?: string;
  reason?: string;
  query?: string;
  filter?: string;
  rows?: FSRCRow[];
  scanned?: number;
  matched?: number;
  next_actions?: string[];
}

// Canonical fund categories from the backend reference universe
// (showme_fund_reference_universe) — the chips compose a server-side
// `category = "…"` predicate, so the labels must match it verbatim.
const CATEGORIES = [
  "US Large Blend",
  "US Large Growth",
  "US Total Market",
  "US Small Blend",
  "Emerging Markets",
  "Commodity Precious Metals",
  "Long Government",
  "High Yield Bond",
] as const;

const MAX_EXPENSE_OPTIONS = [
  { value: "any", label: "ANY", title: "Expense ANY" },
  { value: "0.001", label: "≤0.10%", title: "Expense max 0.10%" },
  { value: "0.002", label: "≤0.20%", title: "Expense max 0.20%" },
  { value: "0.005", label: "≤0.50%", title: "Expense max 0.50%" },
] as const;

const SORT_OPTIONS = [
  { value: "aum_usd", label: "AUM", title: "Sort by AUM" },
  { value: "expenseRatio", label: "EXPENSE", title: "Sort by expense ratio" },
  { value: "ytd_return_pct", label: "YTD", title: "Sort by YTD return" },
] as const;

// The backend treats an empty `query` as "use my default" (which would
// silently apply its own aum/expense screen), so the unfiltered pane is
// expressed as a permissive predicate — every reference row has AUM ≥ 0.
const MATCH_ALL_QUERY = "aum_usd >= 0";
const LIMIT = 50;

export function FSRCPane({ code }: FunctionPaneProps) {
  const [category, setCategory] = usePersistentOption<string>(
    "showme.fsrc.category",
    ["ALL", ...CATEGORIES],
    "ALL",
  );
  const [maxExpense, setMaxExpense] = usePersistentOption<string>(
    "showme.fsrc.maxExpense",
    MAX_EXPENSE_OPTIONS.map((o) => o.value),
    "any",
  );
  const [sortKey, setSortKey] = usePersistentOption<string>(
    "showme.fsrc.sort",
    SORT_OPTIONS.map((o) => o.value),
    "aum_usd",
  );

  const query = useMemo(() => {
    const parts: string[] = [];
    if (category !== "ALL") parts.push(`category = "${category}"`);
    if (maxExpense !== "any") parts.push(`expenseRatio <= ${maxExpense}`);
    return parts.length ? parts.join(" AND ") : MATCH_ALL_QUERY;
  }, [category, maxExpense]);

  const { state, data, error, refetch } = useFunction<FSRCData>({
    code,
    params: { query, limit: LIMIT, live: true },
  });

  const payload = data?.data;
  const status = payload?.status ?? "—";

  const rows = useMemo(() => {
    const base = payload?.rows ?? [];
    const key = sortKey as keyof FSRCRow;
    return [...base].sort((a, b) => num(b[key]) - num(a[key]));
  }, [payload, sortKey]);

  const referenceCount = useMemo(
    () => rows.filter((row) => row.quote_state === "reference").length,
    [rows],
  );

  const isFilterError =
    status === "unsupported_predicate" || status === "input_error";

  function resetFilters() {
    setCategory("ALL");
    setMaxExpense("any");
  }

  // CSV export of the screener results — RAW payload numbers (expenseRatio
  // stays the 0.000945 fraction, not the formatted "0.09%" string).
  const csvColumns = useMemo<GridCsvColumn<FSRCRow>[]>(
    () => [
      { key: "symbol", header: "Symbol", value: (r) => r.symbol ?? "" },
      { key: "name", header: "Fund", value: (r) => r.name ?? "" },
      { key: "issuer", header: "Issuer", value: (r) => r.issuer ?? "" },
      { key: "category", header: "Category", value: (r) => r.category ?? "" },
      { key: "aum_usd", header: "AUM (USD)", value: (r) => r.aum_usd ?? "" },
      {
        key: "expenseRatio",
        header: "Expense ratio",
        value: (r) => r.expenseRatio ?? "",
      },
      {
        key: "ytd_return_pct",
        header: "YTD %",
        value: (r) => r.ytd_return_pct ?? "",
      },
      {
        key: "dividend_yield",
        header: "Dividend yield",
        value: (r) => r.dividend_yield ?? "",
      },
      { key: "last", header: "Last", value: (r) => r.last ?? "" },
      {
        key: "change_pct",
        header: "Change %",
        value: (r) => r.change_pct ?? "",
      },
      {
        key: "quote_state",
        header: "Source",
        value: (r) => r.quote_state ?? "",
      },
    ],
    [],
  );

  const exportCsv = () => {
    const csv = buildGridCsv(csvColumns, rows);
    downloadGridCsv(gridCsvFilename("fsrc-funds"), csv);
  };

  const COLS: DataGridColumn<FSRCRow>[] = useMemo(
    () => [
      {
        key: "symbol",
        header: "Symbol",
        width: 88,
        render: (r) => <span style={monoStrongStyle}>{r.symbol ?? "—"}</span>,
      },
      {
        key: "name",
        header: "Fund",
        width: 200,
        render: (r) => (
          <span style={monoPrimaryStyle} title={r.issuer ?? undefined}>
            {r.name ?? "—"}
          </span>
        ),
      },
      {
        key: "category",
        header: "Category",
        width: 170,
        render: (r) =>
          r.category ? (
            <Pill tone="accent" variant="soft" withDot={false}>
              {r.category}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
      {
        key: "aum_usd",
        header: "AUM",
        numeric: true,
        width: 96,
        render: (r) => (
          <span style={monoStrongStyle}>
            {formatCurrency(r.aum_usd, { compact: true })}
          </span>
        ),
      },
      {
        key: "expenseRatio",
        header: "Exp%",
        numeric: true,
        width: 84,
        render: (r) => (
          <span style={monoMutedStyle}>
            {formatPercent(r.expenseRatio, { fromFraction: true })}
          </span>
        ),
      },
      {
        key: "ytd_return_pct",
        header: "YTD%",
        numeric: true,
        width: 90,
        render: (r) =>
          r.ytd_return_pct == null ? (
            <span className="u-text-mute">—</span>
          ) : (
            <span
              style={{
                ...monoStrongStyle,
                color:
                  r.ytd_return_pct >= 0 ? "var(--positive)" : "var(--negative)",
              }}
            >
              {formatPercent(r.ytd_return_pct, { signed: true })}
            </span>
          ),
      },
      {
        key: "dividend_yield",
        header: "Div%",
        numeric: true,
        width: 84,
        render: (r) => (
          <span style={monoMutedStyle}>
            {formatPercent(r.dividend_yield, { fromFraction: true })}
          </span>
        ),
      },
      {
        key: "last",
        header: "Last",
        numeric: true,
        width: 92,
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
        key: "quote_state",
        header: "Source",
        width: 104,
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

  const chips =
    state === "ok" && !isFilterError ? (
      <div style={chipRowStyle} role="group" aria-label="Fund category filter">
        {["ALL", ...CATEGORIES].map((cat) => {
          const active = category === cat;
          return (
            <button
              key={cat}
              type="button"
              className={`fn-segmented__opt${active ? " fn-segmented__opt--active" : ""}`}
              aria-pressed={active}
              onClick={() => setCategory(cat)}
              title={`Category ${cat}`}
            >
              {cat}
            </button>
          );
        })}
      </div>
    ) : null;

  const results =
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
          <button onClick={resetFilters} className="btn">
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
          "Broaden the category or expense filter and run the screen again."
        }
        action={
          <button onClick={resetFilters} className="btn">
            Reset filters
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
          ariaLabel="Fund screener results"
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
          title="Fund Screener"
          subtitle={`${payload?.matched ?? 0} matched · ${payload?.scanned ?? 0} scanned`}
          trailing={
            <FunctionControlGroup>
              <SegmentedControl
                label="MAX EXP"
                value={maxExpense}
                options={MAX_EXPENSE_OPTIONS}
                onChange={setMaxExpense}
              />
              <SegmentedControl
                label="SORT"
                value={sortKey}
                options={SORT_OPTIONS}
                onChange={setSortKey}
              />
              <button
                type="button"
                className="btn"
                onClick={exportCsv}
                disabled={rows.length === 0}
                title="Download CSV"
                aria-label={`Download ${rows.length} fund rows as CSV`}
              >
                CSV
              </button>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Re-run fund screen"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <div className="u-grid-gap-14">
            {chips}
            {results}
          </div>
        </PaneBody>
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

const chipRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
};

const noteStyle: CSSProperties = {
  margin: 0,
  color: "var(--text-mute)",
  fontSize: "var(--font-size-sm)",
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
