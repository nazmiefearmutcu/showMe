/**
 * ICX — Index Constituents.
 *
 * Bloomberg ``ICX<GO>`` analogue over the backend curated index-member
 * tables (backend screen/icx.py). The pane is addressed by an index
 * CODE — the ``symbol`` prop when it maps to one of the eight supported
 * codes, otherwise a persisted selector — and renders the member table
 * with a best-effort live quote snapshot. Prices are left as dashes
 * when the quote provider does not answer; they are never fabricated.
 *
 * Honesty note: the payload carries no index weights, so rows are
 * sorted by day change (or alphabetically / curated order) and the tint
 * bars visualize change_pct magnitude — not weights.
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
  Skeleton,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { formatPercent, formatPrice } from "@/lib/format";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface ICXRow {
  symbol?: string;
  company?: string;
  index?: string;
  last?: number | null;
  change_pct?: number | null;
}

interface ICXData {
  status?: string;
  index?: string;
  constituents?: number;
  rows?: ICXRow[];
  methodology?: string;
  note?: string;
  available_indexes?: string[];
  next_actions?: string[];
  summary?: { index?: string; constituent_count?: number; source?: string };
}

// The eight curated index codes supported by the backend
// (ICXFunction._INDEX_CONSTITUENTS), region-grouped for the selector.
const INDEX_CODES = [
  "SPX",
  "NDX",
  "DJIA",
  "DAX",
  "CAC",
  "FTSE",
  "STOXX",
  "BIST",
] as const;

const INDEX_OPTIONS = INDEX_CODES.map((value) => ({
  value,
  title: `Index ${value}`,
}));

const SORT_OPTIONS = [
  { value: "change", label: "CHG%", title: "Sort by day change" },
  { value: "az", label: "A-Z", title: "Sort by ticker" },
  { value: "curated", label: "LISTED", title: "Curated index order" },
] as const;

const BAR_MAX_WIDTH = 44;

export function ICXPane({ code, symbol }: FunctionPaneProps) {
  const [persistedIndex, setIndex] = usePersistentOption<string>(
    "showme.icx.index",
    INDEX_CODES,
    "SPX",
  );
  const [sortKey, setSortKey] = usePersistentOption<string>(
    "showme.icx.sort",
    SORT_OPTIONS.map((o) => o.value),
    "change",
  );

  // The index CODE is ICX's symbol-ish param: honour a symbol prop that
  // maps to a supported code, else fall back to the persisted selector.
  const propIndex =
    symbol && (INDEX_CODES as readonly string[]).includes(symbol.toUpperCase())
      ? symbol.toUpperCase()
      : null;
  const effectiveIndex = propIndex ?? persistedIndex;

  const { state, data, error, refetch } = useFunction<ICXData>({
    code,
    params: { index: effectiveIndex },
  });

  const payload = data?.data;
  const status = payload?.status ?? "—";

  const rows = useMemo(() => {
    const base = [...(payload?.rows ?? [])];
    if (sortKey === "az") {
      base.sort((a, b) => (a.symbol ?? "").localeCompare(b.symbol ?? ""));
    } else if (sortKey === "change") {
      base.sort((a, b) => num(b.change_pct) - num(a.change_pct));
    }
    return base;
  }, [payload, sortKey]);

  const missingQuotes = useMemo(
    () => rows.filter((row) => row.last == null).length,
    [rows],
  );

  const maxAbsChange = useMemo(
    () => rows.reduce((max, row) => Math.max(max, Math.abs(num(row.change_pct))), 0),
    [rows],
  );

  const unknownIndex = status === "empty" && rows.length === 0;

  const COLS: DataGridColumn<ICXRow>[] = useMemo(
    () => [
      {
        key: "symbol",
        header: "Symbol",
        width: 104,
        render: (r) => <span style={monoStrongStyle}>{r.symbol ?? "—"}</span>,
      },
      {
        key: "company",
        header: "Company",
        render: (r) => (
          <span style={monoPrimaryStyle}>{r.company ?? "—"}</span>
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
        width: 160,
        render: (r) => <ChangeBar row={r} maxAbs={maxAbsChange} />,
      },
    ],
    [maxAbsChange],
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
    ) : unknownIndex ? (
      <Empty
        title="Unknown index code"
        body={
          [
            payload?.note ??
              payload?.next_actions?.[0] ??
              "Pick a supported index code from the selector.",
            payload?.available_indexes?.length
              ? `Supported codes: ${payload.available_indexes.join(", ")}.`
              : null,
          ]
            .filter((part): part is string => typeof part === "string")
            .join(" ")
        }
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : rows.length === 0 ? (
      <Empty
        title="No constituents returned"
        body="The backend returned no members for this index."
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
          ariaLabel="Index constituents"
        />
        <p style={noteStyle} aria-label="Result count note">
          {rows.length} constituents · index {payload?.index ?? effectiveIndex}
          {" · "}
          {missingQuotes === 0
            ? "quotes live"
            : missingQuotes === rows.length
              ? "live quote snapshot unavailable — showing constituents without prices"
              : `${missingQuotes} without live quote`}
          {" · "}tint bars show day change magnitude (payload carries no
          weights)
        </p>
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Index Constituents"
          subtitle={`${payload?.constituents ?? 0} constituents · ${payload?.index ?? effectiveIndex}`}
          trailing={
            <FunctionControlGroup>
              <SegmentedControl
                label="INDEX"
                value={effectiveIndex}
                options={INDEX_OPTIONS}
                onChange={setIndex}
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
                title="Re-fetch constituents"
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
          <StatusSection
            label="constituents"
            value={payload?.constituents ?? 0}
          />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="index" value={effectiveIndex} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function ChangeBar({ row, maxAbs }: { row: ICXRow; maxAbs: number }) {
  const value = row.change_pct;
  if (value == null || !Number.isFinite(value)) {
    return <span className="u-text-mute">—</span>;
  }
  const positive = value >= 0;
  // Deterministic bar: magnitude relative to the largest absolute move
  // on screen, capped at the full track width.
  const pct = maxAbs > 0 ? Math.min(100, (Math.abs(value) / maxAbs) * 100) : 0;
  return (
    <span style={changeCellStyle}>
      <span
        style={{
          ...monoStrongStyle,
          color: positive ? "var(--positive)" : "var(--negative)",
        }}
      >
        {formatPercent(value, { signed: true })}
      </span>
      <span
        aria-hidden="true"
        style={trackStyle}
        data-testid={`chg-track-${row.symbol ?? ""}`}
      >
        <span
          style={{
            ...fillStyle,
            width: `${pct}%`,
            background: positive ? "var(--positive)" : "var(--negative)",
          }}
        />
      </span>
    </span>
  );
}

function num(value: unknown): number {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
}

const changeCellStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  justifyContent: "flex-end",
  width: "100%",
};

const trackStyle: CSSProperties = {
  position: "relative",
  width: BAR_MAX_WIDTH,
  height: 4,
  borderRadius: 2,
  background: "var(--surface-2)",
  overflow: "hidden",
  flexShrink: 0,
};

const fillStyle: CSSProperties = {
  position: "absolute",
  top: 0,
  bottom: 0,
  left: 0,
  borderRadius: 2,
};

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
