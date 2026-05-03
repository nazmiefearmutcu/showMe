/**
 * WEI — World equity indices.
 *
 * Bloomberg `WEI<GO>` analogue: live (or 30 s polled) snapshot table
 * for ~60 indices grouped by region. Cells render last / change / Δ% /
 * intraday range and refresh on tick.
 */
import { useEffect, useMemo, useState } from "react";
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
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface WEIRow {
  symbol?: string;
  ticker?: string;
  name?: string;
  region?: string;
  last?: number;
  price?: number;
  change?: number;
  change_pct?: number;
  changePercent?: number;
  open?: number;
  high?: number;
  low?: number;
  prev_close?: number;
  ts?: string;
  market_state?: string;
}

const REGIONS = [
  { id: "all", label: "All" },
  { id: "americas", label: "Americas" },
  { id: "europe", label: "Europe" },
  { id: "asia", label: "Asia" },
  { id: "mea", label: "MEA" },
] as const;
type RegionId = (typeof REGIONS)[number]["id"];
const REGION_IDS = REGIONS.map((r) => r.id);

const REFRESH_MS = 30_000;

export function WEIPane({ code }: FunctionPaneProps) {
  const [region, setRegion] = usePersistentOption<RegionId>(
    "showme.wei-region",
    REGION_IDS,
    "all",
  );
  const [tick, setTick] = useState(0);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: { region: region === "all" ? undefined : region, tick },
  });

  const rows = useMemo(() => {
    const all = normalizeRows(data?.data);
    if (region === "all") return all;
    return all.filter(
      (r) => (r.region ?? "").toLowerCase() === region.toLowerCase(),
    );
  }, [data, region]);

  const cols = useMemo<DataGridColumn<WEIRow>[]>(
    () => [
      {
        key: "symbol",
        header: "Index",
        width: 90,
        render: (r) => {
          const sym = r.symbol ?? r.ticker ?? "";
          return (
            <button
              type="button"
              onClick={() => {
                if (!sym) return;
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
            {r.name ?? "—"}
          </span>
        ),
      },
      {
        key: "region",
        header: "Region",
        width: 90,
        render: (r) =>
          r.region ? (
            <Pill tone="muted" withDot={false}>
              {r.region}
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
        render: (r) => fmtNum(r.last ?? r.price),
      },
      {
        key: "change",
        header: "Δ",
        numeric: true,
        width: 90,
        render: (r) => {
          const v =
            r.change ??
            ((r.last ?? r.price ?? 0) - (r.prev_close ?? r.last ?? r.price ?? 0));
          return v != null ? <ChangeText value={v} digits={2} /> : "—";
        },
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
        key: "range",
        header: "Day range",
        width: 130,
        render: (r) => {
          if (r.low == null || r.high == null) return "—";
          return (
            <span style={{ fontVariantNumeric: "tabular-nums" }}>
              {fmtNum(r.low)} – {fmtNum(r.high)}
            </span>
          );
        },
      },
      {
        key: "market_state",
        header: "State",
        width: 80,
        render: (r) =>
          r.market_state ? (
            <Pill
              tone={
                r.market_state.toLowerCase() === "regular"
                  ? "positive"
                  : r.market_state.toLowerCase() === "closed"
                    ? "muted"
                    : "warn"
              }
              withDot={false}
            >
              {r.market_state}
            </Pill>
          ) : (
            "—"
          ),
      },
    ],
    [setFocusedTarget],
  );

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="World indices"
          subtitle={`${rows.length} row(s) · refreshes every ${REFRESH_MS / 1000}s`}
          trailing={
            <FunctionControlGroup>
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
            items={REGIONS.map((r) => ({ id: r.id, label: r.label }))}
            active={region}
            onChange={(id) => setRegion(id as RegionId)}
          />
        </div>
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <Skeleton height={300} />
          ) : state === "error" ? (
            <Empty
              title="Function error"
              body={error?.message ?? "—"}
              icon="!"
            />
          ) : rows.length === 0 ? (
            <Empty title="No quotes" body={`No WEI rows for ${region}.`} />
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
          <span>region · {region}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function normalizeRows(payload: unknown): WEIRow[] {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload as WEIRow[];
  if (typeof payload === "object") {
    const o = payload as Record<string, unknown>;
    const items = o.items ?? o.rows ?? o.indices ?? null;
    if (Array.isArray(items)) return items as WEIRow[];
  }
  return [];
}

function fmtNum(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}
