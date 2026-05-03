/**
 * GLCO — Global commodities mini-board.
 *
 * Bloomberg `GLCO<GO>` analogue: snapshot table over energy / metals
 * / agriculture / softs. Sortable by sector tab; row double-click
 * jumps into DES with the futures symbol.
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

interface CommodityRow {
  symbol?: string;
  ticker?: string;
  name?: string;
  sector?: string;
  category?: string;
  last?: number;
  price?: number;
  change?: number;
  change_pct?: number;
  changePercent?: number;
  unit?: string;
  contract_month?: string;
  open_interest?: number;
}

const SECTORS = [
  { id: "all", label: "All" },
  { id: "energy", label: "Energy" },
  { id: "metals", label: "Metals" },
  { id: "ags", label: "Ag" },
  { id: "softs", label: "Softs" },
] as const;
type SectorId = (typeof SECTORS)[number]["id"];
const SECTOR_IDS = SECTORS.map((s) => s.id);

const REFRESH_MS = 60_000;

export function GLCOPane({ code }: FunctionPaneProps) {
  const [sector, setSector] = usePersistentOption<SectorId>(
    "showme.glco-sector",
    SECTOR_IDS,
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
    params: { sector: sector === "all" ? undefined : sector, tick },
  });

  const rows = useMemo(() => {
    const all = normalizeRows(data?.data);
    if (sector === "all") return all;
    return all.filter((r) => matchesSector(r, sector));
  }, [data, sector]);

  const cols = useMemo<DataGridColumn<CommodityRow>[]>(
    () => [
      {
        key: "symbol",
        header: "Symbol",
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
        key: "sector",
        header: "Sector",
        width: 80,
        render: (r) => {
          const s = r.sector ?? r.category;
          return s ? (
            <Pill tone="muted" withDot={false}>
              {s}
            </Pill>
          ) : (
            "—"
          );
        },
      },
      {
        key: "last",
        header: "Last",
        numeric: true,
        width: 100,
        render: (r) => {
          const v = r.last ?? r.price;
          if (v == null) return "—";
          return (
            <span>
              {fmtNum(v)}
              {r.unit && (
                <span
                  style={{
                    marginLeft: 4,
                    color: "var(--text-mute)",
                    fontSize: 10,
                  }}
                >
                  {r.unit}
                </span>
              )}
            </span>
          );
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
        key: "contract_month",
        header: "Cont.",
        width: 80,
        render: (r) => r.contract_month ?? "—",
      },
      {
        key: "open_interest",
        header: "OI",
        numeric: true,
        width: 100,
        render: (r) => fmtCompact(r.open_interest),
      },
    ],
    [setFocusedTarget],
  );

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="Global commodities"
          subtitle={`${rows.length} contract(s) · ${sector} · refreshes every ${REFRESH_MS / 1000}s`}
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
            items={SECTORS.map((s) => ({ id: s.id, label: s.label }))}
            active={sector}
            onChange={(id) => setSector(id as SectorId)}
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
            <Empty title="No contracts" body={`No GLCO rows for ${sector}.`} />
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
          <span>sector · {sector}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function normalizeRows(payload: unknown): CommodityRow[] {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload as CommodityRow[];
  if (typeof payload === "object") {
    const o = payload as Record<string, unknown>;
    const items =
      o.contracts ?? o.commodities ?? o.rows ?? o.items ?? null;
    if (Array.isArray(items)) return items as CommodityRow[];
  }
  return [];
}

function matchesSector(r: CommodityRow, sector: string): boolean {
  const s = (r.sector ?? r.category ?? "").toLowerCase();
  if (sector === "ags") return s.includes("ag") || s.includes("grain");
  if (sector === "softs") return s.includes("soft");
  return s.includes(sector);
}

function fmtNum(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

function fmtCompact(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(2)}K`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
}
