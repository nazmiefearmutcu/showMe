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
  price?: number;
  change?: number;
  change_pct?: number;
  changePercent?: number;
  volume?: number;
  dollar_volume?: number;
  market_cap?: number;
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
    params: { asset_class: assetClass, limit },
  });

  const rows = useMemo(() => {
    const base = normalizeRows(data?.data);
    return [...base]
      .sort((a, b) => sortVal(b, sort) - sortVal(a, sort))
      .slice(0, limit);
  }, [data, sort, limit]);

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
    ],
    [setFocusedTarget],
  );

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="Most active"
          subtitle={`${rows.length} row(s) · sorted by ${sort}`}
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
            <Empty title="No movers" body={`No ${tab} payload right now.`} />
          ) : (
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
          )}
        </PaneBody>
        <PaneFooter>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span>asset · {assetClass ?? "all"}</span>
          <span>rows · {rows.length}/{limit}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function normalizeRows(payload: unknown): MostRow[] {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload as MostRow[];
  if (typeof payload === "object") {
    const o = payload as Record<string, unknown>;
    const items = o.items ?? o.rows ?? o.movers ?? o.most_active ?? null;
    if (Array.isArray(items)) return items as MostRow[];
  }
  return [];
}

function sortVal(r: MostRow, key: SortKey): number {
  if (key === "volume") return Number(r.volume ?? 0);
  if (key === "abs_change")
    return Math.abs(Number(r.change_pct ?? r.changePercent ?? 0));
  if (key === "dollar_volume")
    return Number(r.dollar_volume ?? estimateDollar(r));
  return 0;
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
