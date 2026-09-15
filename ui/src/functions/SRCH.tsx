/**
 * SRCH — Bond Screener.
 *
 * Screen over the backend bond reference universe (backend
 * screen/_funcs.py SRCHFunction, the EQS-pattern DSL filter). The pane
 * composes a server-side predicate from three persisted controls —
 * bond-type chips, a minimum-yield floor and a maximum-duration cap —
 * and renders the payload's own curve metrics. This universe is
 * reference-grade fixture data (no live quotes), so the pane labels it
 * honestly instead of implying a live bond feed. Empty results surface
 * the backend's reason / next_actions guidance and a filter reset.
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
import { formatNumber, formatPercent } from "@/lib/format";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface SRCHRow {
  symbol?: string;
  issuer?: string;
  type?: string;
  country?: string;
  currency?: string;
  maturity?: string;
  tenor_years?: number;
  yield?: number;
  duration?: number;
  rating?: string;
  // Live-path honesty labels (backend screen/_funcs.py SRCHFunction):
  // live = refreshed from a keyless provider this cycle; unavailable = a
  // configured live tenor no provider answered (curated value shown);
  // reference = curated-only row (legacy payloads omit the field).
  quote_type?: "live" | "reference" | "unavailable";
  yield_state?: "live" | "reference";
  yield_source?: string | null;
  yield_as_of?: string;
  yield_cadence?: string;
}

interface SRCHData {
  status?: string;
  reason?: string;
  query?: string;
  filter?: string;
  rows?: SRCHRow[];
  scanned?: number;
  matched?: number;
  next_actions?: string[];
}

type QuoteType = "live" | "reference" | "unavailable";

function quoteTypeOf(row: SRCHRow): QuoteType {
  if (row.quote_type === "live" || row.quote_type === "unavailable") {
    return row.quote_type;
  }
  return "reference";
}

// Canonical bond types from the backend reference universe
// (showme_bond_reference_universe) — the chips compose a server-side
// `type = "…"` predicate, so the labels must match it verbatim.
// Session-17: the universe grew from 8 curve points to the full US nominal
// curve + TIPS + DE/FR/IT/ES/GB/JP 2Y & 10Y, so the new instrument types are
// chip-selectable too.
const BOND_TYPES = [
  "Bill",
  "Note",
  "Bond",
  "TIPS",
  "Bund",
  "Gilt",
  "JGB",
  "OAT",
  "BTP",
  "Bono",
] as const;

const MIN_YIELD_OPTIONS = [
  { value: "any", label: "ANY", title: "Min yield ANY" },
  { value: "3", label: "≥3%", title: "Min yield 3%" },
  { value: "4", label: "≥4%", title: "Min yield 4%" },
  { value: "5", label: "≥5%", title: "Min yield 5%" },
] as const;

const MAX_DURATION_OPTIONS = [
  { value: "any", label: "ANY", title: "Max duration ANY" },
  { value: "5", label: "≤5y", title: "Max duration 5y" },
  { value: "10", label: "≤10y", title: "Max duration 10y" },
] as const;

const SORT_OPTIONS = [
  { value: "tenor_years", label: "TENOR", title: "Sort by tenor" },
  { value: "yield", label: "YIELD", title: "Sort by yield" },
  { value: "duration", label: "DURATION", title: "Sort by duration" },
] as const;

// The backend treats an empty `query` as "use my default" (which would
// silently apply its own yield/duration screen), so the unfiltered pane
// is expressed as a permissive predicate — every reference row has a
// non-negative yield.
const MATCH_ALL_QUERY = "yield >= 0";
const LIMIT = 50;

export function SRCHPane({ code }: FunctionPaneProps) {
  const [bondType, setBondType] = usePersistentOption<string>(
    "showme.srch.type",
    ["ALL", ...BOND_TYPES],
    "ALL",
  );
  const [minYield, setMinYield] = usePersistentOption<string>(
    "showme.srch.minYield",
    MIN_YIELD_OPTIONS.map((o) => o.value),
    "any",
  );
  const [maxDuration, setMaxDuration] = usePersistentOption<string>(
    "showme.srch.maxDuration",
    MAX_DURATION_OPTIONS.map((o) => o.value),
    "any",
  );
  const [sortKey, setSortKey] = usePersistentOption<string>(
    "showme.srch.sort",
    SORT_OPTIONS.map((o) => o.value),
    "tenor_years",
  );

  const query = useMemo(() => {
    const parts: string[] = [];
    if (bondType !== "ALL") parts.push(`type = "${bondType}"`);
    if (minYield !== "any") parts.push(`yield >= ${minYield}`);
    if (maxDuration !== "any") parts.push(`duration <= ${maxDuration}`);
    return parts.length ? parts.join(" AND ") : MATCH_ALL_QUERY;
  }, [bondType, minYield, maxDuration]);

  const { state, data, error, refetch } = useFunction<SRCHData>({
    code,
    params: { query, limit: LIMIT },
  });

  const payload = data?.data;
  const status = payload?.status ?? "—";

  const rows = useMemo(() => {
    const base = payload?.rows ?? [];
    const key = sortKey as keyof SRCHRow;
    return [...base].sort((a, b) => num(b[key]) - num(a[key]));
  }, [payload, sortKey]);

  // Per-row coverage: live rows were refreshed by a keyless provider this
  // cycle; unavailable rows are configured live tenors no provider answered
  // (their curated reference value is still shown); reference rows are
  // curated-only. Drives the header chip, the per-row source pill and the
  // honesty note — no whole-table downgrade when coverage is partial.
  const coverage = useMemo(() => {
    const base = payload?.rows ?? [];
    const liveSources = new Set<string>();
    let live = 0;
    let unavailable = 0;
    for (const row of base) {
      const kind = quoteTypeOf(row);
      if (kind === "live") {
        live += 1;
        if (row.yield_source) liveSources.add(row.yield_source);
      } else if (kind === "unavailable") {
        unavailable += 1;
      }
    }
    return { live, unavailable, total: base.length, liveSources: [...liveSources] };
  }, [payload]);

  const isFilterError =
    status === "unsupported_predicate" || status === "input_error";

  const coverageNote = useMemo(() => {
    if (!coverage.total || coverage.live === 0) {
      return "reference bond universe (no live quotes)";
    }
    const via = coverage.liveSources.length
      ? ` via ${coverage.liveSources.join(", ")}`
      : "";
    return coverage.unavailable > 0
      ? `live yields ${coverage.live}/${coverage.total}${via} · ${coverage.unavailable} tenor(s) show curated reference values`
      : `live yields${via}`;
  }, [coverage]);

  const coveragePill =
    coverage.total === 0 ? null : coverage.live > 0 ? (
      <span data-testid="srch-coverage-pill">
        {coverage.unavailable > 0 ? (
          <Pill tone="warn" variant="soft" withDot={false}>
            PARTIAL {coverage.live}/{coverage.total} LIVE
          </Pill>
        ) : (
          <Pill tone="positive" variant="soft" withDot={false}>
            LIVE {coverage.live}
          </Pill>
        )}
      </span>
    ) : (
      <span data-testid="srch-coverage-pill">
        <Pill tone="muted" variant="soft" withDot={false}>
          REFERENCE
        </Pill>
      </span>
    );

  function resetFilters() {
    setBondType("ALL");
    setMinYield("any");
    setMaxDuration("any");
  }

  const COLS: DataGridColumn<SRCHRow>[] = useMemo(
    () => [
      {
        key: "symbol",
        header: "Symbol",
        width: 96,
        render: (r) => <span style={monoStrongStyle}>{r.symbol ?? "—"}</span>,
      },
      {
        key: "issuer",
        header: "Issuer",
        width: 150,
        render: (r) => (
          <span style={monoPrimaryStyle} title={r.country ?? undefined}>
            {r.issuer ?? "—"}
          </span>
        ),
      },
      {
        key: "type",
        header: "Type",
        width: 84,
        render: (r) =>
          r.type ? (
            <Pill tone="accent" variant="soft" withDot={false}>
              {r.type}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
      {
        key: "maturity",
        header: "Maturity",
        width: 92,
        render: (r) => <span style={monoMutedStyle}>{r.maturity ?? "—"}</span>,
      },
      {
        key: "yield",
        header: "Yield",
        numeric: true,
        width: 96,
        render: (r) => (
          <span style={monoStrongStyle}>
            {formatPercent(r.yield ?? null)}
          </span>
        ),
      },
      {
        key: "quote_type",
        header: "Source",
        width: 96,
        render: (r) => <QuoteSourceCell row={r} />,
      },
      {
        key: "duration",
        header: "Duration",
        numeric: true,
        width: 96,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtYears(r.duration)}</span>
        ),
      },
      {
        key: "tenor_years",
        header: "Tenor",
        numeric: true,
        width: 84,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtYears(r.tenor_years)}</span>
        ),
      },
      {
        key: "rating",
        header: "Rating",
        width: 84,
        render: (r) =>
          r.rating ? (
            <Pill tone="muted" variant="soft" withDot={false}>
              {r.rating}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
      {
        key: "currency",
        header: "Ccy",
        width: 64,
        render: (r) => (
          <span style={monoMutedStyle}>{r.currency ?? "—"}</span>
        ),
      },
    ],
    [],
  );

  const chips =
    state === "ok" && !isFilterError ? (
      <div style={chipRowStyle} role="group" aria-label="Bond type filter">
        {["ALL", ...BOND_TYPES].map((t) => {
          const active = bondType === t;
          return (
            <button
              key={t}
              type="button"
              className={`fn-segmented__opt${active ? " fn-segmented__opt--active" : ""}`}
              aria-pressed={active}
              onClick={() => setBondType(t)}
              title={`Bond type ${t}`}
            >
              {t}
            </button>
          );
        })}
      </div>
    ) : null;

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
          "Broaden the type, yield, or duration filter and run the screen again."
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
          ariaLabel="Bond screener results"
        />
        <p style={noteStyle} aria-label="Result count note">
          {rows.length} of {payload?.matched ?? rows.length} matched
          {" · "}
          {payload?.scanned ?? "—"} scanned
          {" · "}
          {coverageNote}
          {" · "}
          query "{payload?.query ?? query}"
        </p>
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Bond Screener"
          subtitle={`${payload?.matched ?? 0} matched · ${payload?.scanned ?? 0} scanned`}
          trailing={
            <FunctionControlGroup>
              {coveragePill}
              <SegmentedControl
                label="MIN YLD"
                value={minYield}
                options={MIN_YIELD_OPTIONS}
                onChange={setMinYield}
              />
              <SegmentedControl
                label="MAX DUR"
                value={maxDuration}
                options={MAX_DURATION_OPTIONS}
                onChange={setMaxDuration}
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
                title="Re-run bond screen"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <div className="u-grid-gap-14">
            {chips}
            {body}
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
          <StatusSection
            label="live yields"
            value={
              coverage.total
                ? `${coverage.live}/${coverage.total}`
                : "—"
            }
            tone={coverage.live ? "positive" : "muted"}
          />
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

/**
 * Per-row source pill. `LIVE` marks a yield refreshed by a keyless provider
 * this cycle (tooltip carries provider + observation date); `N/A` marks a
 * configured live tenor no provider answered — its curated reference value
 * is still displayed; `REF` marks curated-only rows (legacy payloads).
 */
function QuoteSourceCell({ row }: { row: SRCHRow }) {
  const kind = quoteTypeOf(row);
  const testId = `srch-quote-${row.symbol ?? "row"}`;
  if (kind === "live") {
    const source = row.yield_source ?? "provider";
    const asOf = row.yield_as_of ? `, as of ${row.yield_as_of}` : "";
    return (
      <span title={`live ${source}${asOf}`} data-testid={testId}>
        <Pill tone="positive" variant="soft" withDot={false}>
          LIVE
        </Pill>
      </span>
    );
  }
  if (kind === "unavailable") {
    return (
      <span
        title="no live provider answered for this tenor this cycle — curated reference value shown"
        data-testid={testId}
      >
        <Pill tone="warn" variant="soft" withDot={false}>
          N/A
        </Pill>
      </span>
    );
  }
  return (
    <span title="curated reference value" data-testid={testId}>
      <Pill tone="muted" variant="soft" withDot={false}>
        REF
      </Pill>
    </span>
  );
}

function fmtYears(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${formatNumber(value, 1)}y`;
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
