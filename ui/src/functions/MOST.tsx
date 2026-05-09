/**
 * MOST — Most active multi-asset top-50.
 *
 * Bloomberg `MOST<GO>` analogue. Tab through asset classes (equities,
 * crypto, fx) and surface the top movers by volume / |%Δ| / dollar
 * volume. Sortable DataGrid; symbol click jumps into DES.
 */
import { useMemo } from "react";
import {
  ChangeText,
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  Tabs,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { useWorkspace } from "@/lib/workspace";
import { navigate } from "@/lib/router";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  RowLimitControl,
} from "./function-controls";
import {
  ROW_LIMITS,
  type RowLimit,
  usePersistentOption,
} from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface MostRow {
  symbol?: string;
  ticker?: string;
  name?: string;
  asset_class?: string;
  exchange?: string;
  last?: number;
  prev_close?: number;
  price?: number;
  change?: number;
  change_pct?: number;
  changePercent?: number;
  volume?: number;
  dollar_volume?: number;
  market_cap?: number;
  quote_state?: string;
  activity_score?: number;
}

interface MostPayload {
  status?: string;
  rows: MostRow[];
  universe?: string[];
  universe_size?: number;
  asset_class_filter?: string;
  sort?: string;
  live?: boolean;
  as_of?: string;
  reason?: string | null;
  methodology?: string;
  field_dictionary?: Array<{ field?: string; meaning?: string }>;
}

const ASSET_TABS = [
  { id: "all", label: "All", asset_class: undefined },
  { id: "equities", label: "Equities", asset_class: "equities" },
  { id: "crypto", label: "Crypto", asset_class: "crypto" },
  { id: "fx", label: "FX", asset_class: "fx" },
] as const;
type AssetTabId = (typeof ASSET_TABS)[number]["id"];
const ASSET_TAB_IDS = ASSET_TABS.map((t) => t.id);

const SORT_TABS = [
  { id: "volume", label: "Volume" },
  { id: "abs_change", label: "|Δ%|" },
  { id: "dollar_volume", label: "$ Vol" },
] as const;
type SortKey = (typeof SORT_TABS)[number]["id"];
const SORT_IDS = SORT_TABS.map((t) => t.id);

export function MOSTPane({ code }: FunctionPaneProps) {
  const [tab, setTab] = usePersistentOption<AssetTabId>(
    "showme.most-asset-tab",
    ASSET_TAB_IDS,
    "all",
  );
  const [sort, setSort] = usePersistentOption<SortKey>(
    "showme.most-sort",
    SORT_IDS,
    "volume",
  );
  const [limit, setLimit] = usePersistentOption<RowLimit>(
    "showme.most-limit",
    ROW_LIMITS,
    50,
  );
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);
  const assetClass = useMemo(
    () => ASSET_TABS.find((t) => t.id === tab)!.asset_class,
    [tab],
  );
  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: { asset_class: assetClass, limit, sort, live_screen: true },
  });

  const payload = useMemo(() => normalizePayload(data?.data), [data]);
  const rows = useMemo(() => {
    const base = payload?.rows ?? [];
    return [...base]
      .sort((a, b) => sortVal(b, sort) - sortVal(a, sort))
      .slice(0, limit);
  }, [payload, sort, limit]);
  const sourceLabel = data?.sources?.length ? data.sources.join(" + ") : "—";
  const warnings = data?.warnings ?? [];

  const cols = useMemo<DataGridColumn<MostRow>[]>(
    () => [
      {
        key: "symbol",
        header: "Symbol",
        width: 110,
        render: (r) => {
          const sym = r.symbol ?? r.ticker ?? "";
          return (
            <button
              type="button"
              onClick={() => {
                setFocusedTarget("DES", sym);
                navigate(`/symbol/${sym}/DES`);
              }}
              style={{
                background: "transparent",
                border: "none",
                color: "var(--accent)",
                cursor: "default",
                font: "inherit",
                padding: 0,
                fontWeight: 600,
              }}
            >
              {sym || "—"}
            </button>
          );
        },
      },
      {
        key: "name",
        header: "Name",
        render: (r) => (
          <span style={{ color: "var(--text-secondary)" }}>
            {r.name ?? r.exchange ?? "—"}
          </span>
        ),
      },
      {
        key: "asset_class",
        header: "Class",
        width: 80,
        render: (r) =>
          r.asset_class ? (
            <Pill tone="muted" withDot={false}>
              {r.asset_class}
            </Pill>
          ) : (
            "—"
        ),
      },
      {
        key: "exchange",
        header: "Venue",
        width: 100,
        render: (r) => (
          <span style={{ color: "var(--text-secondary)" }}>
            {r.exchange ?? "—"}
          </span>
        ),
      },
      {
        key: "last",
        header: "Last",
        numeric: true,
        width: 100,
        render: (r) => fmtPrice(r.last ?? r.price),
      },
      {
        key: "change_pct",
        header: "Δ %",
        numeric: true,
        width: 90,
        render: (r) => {
          const v = r.change_pct ?? r.changePercent;
          return v != null ? <ChangeText value={v} digits={2} suffix="%" /> : "—";
        },
      },
      {
        key: "volume",
        header: "Vol",
        numeric: true,
        width: 100,
        render: (r) => fmtCompact(r.volume),
      },
      {
        key: "dollar_volume",
        header: "$ Vol",
        numeric: true,
        width: 100,
        render: (r) => fmtCompact(r.dollar_volume ?? estimateDollar(r)),
      },
      {
        key: "quote_state",
        header: "State",
        width: 90,
        render: (r) => (
          <Pill tone={r.quote_state === "live" ? "positive" : "muted"} withDot={false}>
            {r.quote_state ?? (payload?.live ? "live" : "reference")}
          </Pill>
        ),
      },
    ],
    [payload?.live, setFocusedTarget],
  );

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="Most active"
          subtitle={`${rows.length} row(s) · ${payload?.asset_class_filter ?? assetClass ?? "all"} · sorted by ${sort}`}
          trailing={
            <FunctionControlGroup>
              <RowLimitControl
                value={limit}
                onChange={(next) => setLimit(next as RowLimit)}
                disabled={state === "loading"}
              />
              <Tabs
                variant="segmented"
                items={SORT_TABS.map((s) => ({ id: s.id, label: s.label }))}
                active={sort}
                onChange={(id) => setSort(id as SortKey)}
              />
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <div
          style={{
            padding: "8px 14px",
            borderBottom: "1px solid var(--border-subtle)",
            background: "var(--bg-elev-2)",
          }}
        >
          <Tabs
            variant="segmented"
            items={ASSET_TABS.map((t) => ({ id: t.id, label: t.label }))}
            active={tab}
            onChange={(id) => setTab(id as AssetTabId)}
          />
        </div>
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <Skeleton height={320} />
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
              title="No movers"
              body={payload?.reason ?? `No ${tab} payload right now.`}
            />
          ) : (
            <>
              <MostSummary
                payload={payload}
                sourceLabel={sourceLabel}
                warnings={warnings}
              />
              <ActivityBars rows={rows} sort={sort} />
              <DataGrid
                columns={cols}
                rows={rows}
                rowKey={(r, i) => `${r.symbol ?? r.ticker ?? ""}-${i}`}
                density="compact"
                onRowDoubleClick={(r) => {
                  const sym = r.symbol ?? r.ticker;
                  if (!sym) return;
                  setFocusedTarget("DES", sym);
                  navigate(`/symbol/${sym}/DES`);
                }}
              />
            </>
          )}
        </PaneBody>
        <PaneFooter>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span>asset · {assetClass ?? "all"}</span>
          <span>rows · {rows.length}/{limit}</span>
          <span>source · {sourceLabel}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function normalizePayload(payload: unknown): MostPayload | null {
  if (!payload) return null;
  if (Array.isArray(payload)) return { rows: payload as MostRow[] };
  if (typeof payload === "object") {
    const o = payload as Record<string, unknown>;
    const items = o.items ?? o.rows ?? o.movers ?? o.most_active ?? null;
    if (Array.isArray(items)) {
      return {
        ...o,
        rows: items as MostRow[],
      } as MostPayload;
    }
  }
  return null;
}

function MostSummary({
  payload,
  sourceLabel,
  warnings,
}: {
  payload: MostPayload | null;
  sourceLabel: string;
  warnings: string[];
}) {
  const asOf = payload?.as_of ? new Date(payload.as_of).toLocaleTimeString() : "—";
  const fields = payload?.field_dictionary?.slice(0, 4) ?? [];
  return (
    <div
      style={{
        display: "grid",
        gap: 8,
        padding: "12px 0 14px",
        borderBottom: "1px solid var(--border-subtle)",
        marginBottom: 12,
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
          gap: 8,
        }}
      >
        <SummaryMetric label="source" value={sourceLabel.toUpperCase()} />
        <SummaryMetric label="status" value={(payload?.status ?? "ok").toUpperCase()} />
        <SummaryMetric label="universe" value={String(payload?.universe_size ?? "—")} />
        <SummaryMetric label="as of" value={asOf} />
      </div>
      {payload?.methodology ? (
        <div style={{ color: "var(--text-secondary)", fontSize: 12, lineHeight: 1.45 }}>
          {payload.methodology}
        </div>
      ) : null}
      {fields.length ? (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {fields.map((field) => (
            <Pill key={field.field ?? field.meaning} tone="muted" withDot={false}>
              {field.field}: {field.meaning}
            </Pill>
          ))}
        </div>
      ) : null}
      {warnings.length ? (
        <div style={{ color: "var(--negative)", fontSize: 12 }}>
          {warnings.join(" · ")}
        </div>
      ) : null}
    </div>
  );
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        border: "1px solid var(--border-subtle)",
        borderRadius: 6,
        padding: "8px 10px",
        minWidth: 0,
      }}
    >
      <div style={{ color: "var(--text-muted)", fontSize: 10, textTransform: "uppercase" }}>
        {label}
      </div>
      <div
        style={{
          color: "var(--text-primary)",
          fontSize: 12,
          fontWeight: 700,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

function ActivityBars({ rows, sort }: { rows: MostRow[]; sort: SortKey }) {
  const visible = rows.slice(0, 8);
  const max = Math.max(1, ...visible.map((row) => Math.abs(sortVal(row, sort))));
  return (
    <div
      style={{
        display: "grid",
        gap: 6,
        marginBottom: 14,
      }}
    >
      {visible.map((row) => {
        const symbol = row.symbol ?? row.ticker ?? "—";
        const value = Math.abs(sortVal(row, sort));
        const pct = Math.max(3, Math.min(100, (value / max) * 100));
        const change = row.change_pct ?? row.changePercent;
        return (
          <div
            key={symbol}
            style={{
              display: "grid",
              gridTemplateColumns: "92px minmax(0, 1fr) 90px",
              alignItems: "center",
              gap: 10,
              fontSize: 12,
            }}
          >
            <span style={{ fontWeight: 700, color: "var(--accent)" }}>{symbol}</span>
            <div
              style={{
                height: 10,
                background: "var(--bg-elev-2)",
                border: "1px solid var(--border-subtle)",
                borderRadius: 6,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${pct}%`,
                  height: "100%",
                  background: change != null && change < 0 ? "var(--negative)" : "var(--positive)",
                }}
              />
            </div>
            <span style={{ textAlign: "right", color: "var(--text-secondary)" }}>
              {formatSortValue(row, sort)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function sortVal(r: MostRow, key: SortKey): number {
  if (key === "volume") return Number(r.volume ?? 0);
  if (key === "abs_change")
    return Math.abs(Number(r.change_pct ?? r.changePercent ?? 0));
  if (key === "dollar_volume")
    return Number(r.dollar_volume ?? estimateDollar(r));
  return 0;
}

function formatSortValue(r: MostRow, key: SortKey): string {
  if (key === "abs_change") {
    const v = Math.abs(Number(r.change_pct ?? r.changePercent ?? 0));
    return `${v.toFixed(2)}%`;
  }
  if (key === "dollar_volume") return fmtCompact(r.dollar_volume ?? estimateDollar(r));
  return fmtCompact(r.volume);
}

function estimateDollar(r: MostRow): number {
  const p = r.last ?? r.price;
  if (p == null || r.volume == null) return 0;
  return p * r.volume;
}

function fmtPrice(v: number | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

function fmtCompact(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e12) return `${(v / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(2)}K`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
}
