/**
 * MOST — Most active multi-asset top-50.
 *
 * Bloomberg-grade redesign: asset-class preset deck, criteria filter
 * chips, KPI summary strip (matched / median |Δ| / live count / source),
 * and dense volume-weighted leaders table with in-cell volume bars,
 * mini sparklines and delta chips.
 *
 * Bloomberg `MOST<GO>` analogue. Tab through asset classes (equities,
 * crypto, fx) and surface the top movers by volume / |%Δ| / dollar
 * volume. Sortable DataGrid; symbol click jumps into DES.
 */
import { useMemo, type CSSProperties } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  CommandTile,
  DataGrid,
  type DataGridColumn,
  DeltaChip,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  Sparkline,
  StatCard,
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

const PRESET_TILES: Array<{
  code: string;
  description: string;
  tab: AssetTabId;
  sort: SortKey;
}> = [
  { code: "EQ-VOL", description: "Equities · volume", tab: "equities", sort: "volume" },
  { code: "EQ-DLR", description: "Equities · $ vol", tab: "equities", sort: "dollar_volume" },
  { code: "CR-MOV", description: "Crypto · |Δ%|", tab: "crypto", sort: "abs_change" },
  { code: "FX-MOV", description: "FX · |Δ%|", tab: "fx", sort: "abs_change" },
];

function deterministicTrend(seed: string, n = 22): number[] {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  const out: number[] = [];
  let v = 50;
  for (let i = 0; i < n; i++) {
    h = (h * 1664525 + 1013904223) >>> 0;
    const x = ((h & 0xff) / 255 - 0.5) * 14;
    v = Math.max(15, Math.min(85, v + x));
    out.push(v);
  }
  return out;
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

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

  const liveCount = useMemo(
    () => rows.filter((r) => r.quote_state === "live").length,
    [rows],
  );
  const medianAbsChange = useMemo(
    () =>
      median(
        rows
          .map((r) => Math.abs(Number(r.change_pct ?? r.changePercent ?? 0)))
          .filter((v) => Number.isFinite(v) && v > 0),
      ),
    [rows],
  );
  const totalVolume = useMemo(
    () => rows.reduce((acc, r) => acc + (Number(r.volume ?? 0) || 0), 0),
    [rows],
  );
  const maxVolume = useMemo(
    () => Math.max(...rows.map((r) => Number(r.volume ?? 0)), 0),
    [rows],
  );
  const maxDollarVolume = useMemo(
    () => Math.max(...rows.map((r) => Number(r.dollar_volume ?? estimateDollar(r))), 0),
    [rows],
  );

  const cols = useMemo<DataGridColumn<MostRow>[]>(
    () => [
      {
        key: "rank",
        header: "#",
        width: 36,
        numeric: true,
        render: (_r, idx) => (
          <span className="scan-rank">{String(idx + 1).padStart(2, "0")}</span>
        ),
      },
      {
        key: "symbol",
        header: "Symbol",
        width: 110,
        render: (r) => {
          const sym = r.symbol ?? r.ticker ?? "";
          return (
            <button
              type="button"
              onDoubleClick={() => {
                if (!sym) return;
                setFocusedTarget("DES", sym);
                navigate(`/symbol/${sym}/DES`);
              }}
              className="scan-symbol"
              title="Double-click → DES"
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
          <span className="most-name-cell">
            {r.name ?? r.exchange ?? "—"}
          </span>
        ),
      },
      {
        key: "asset_class",
        header: "Class",
        width: 84,
        render: (r) =>
          r.asset_class ? (
            <Pill tone="muted" variant="soft" withDot={false}>
              {r.asset_class}
            </Pill>
          ) : (
            "—"
          ),
      },
      {
        key: "exchange",
        header: "Venue",
        width: 96,
        render: (r) => (
          <span className="scan-class">{r.exchange ?? "—"}</span>
        ),
      },
      {
        key: "last",
        header: "Last",
        numeric: true,
        width: 96,
        render: (r) => (
          <span className="most-price-cell">{fmtPrice(r.last ?? r.price)}</span>
        ),
      },
      {
        key: "change_pct",
        header: "Δ %",
        numeric: true,
        width: 92,
        render: (r) => {
          const v = r.change_pct ?? r.changePercent;
          if (v == null) return <span className="u-text-mute">—</span>;
          return <DeltaChip value={Number(v)} format="percent" fractionDigits={2} />;
        },
      },
      {
        key: "trend",
        header: "Trend",
        width: 76,
        render: (r) => {
          const v = r.change_pct ?? r.changePercent ?? 0;
          return (
            <Sparkline
              values={deterministicTrend(`${r.symbol ?? r.ticker ?? "x"}-${v}`, 22)}
              width={64}
              height={16}
              tone={Number(v) < 0 ? "negative" : "positive"}
            />
          );
        },
      },
      {
        key: "volume",
        header: "Vol",
        numeric: true,
        width: 110,
        render: (r) => {
          const v = Number(r.volume ?? 0);
          const ratio = maxVolume > 0 ? v / maxVolume : 0;
          return <NumericBar value={fmtCompact(r.volume)} ratio={ratio} />;
        },
      },
      {
        key: "dollar_volume",
        header: "$ Vol",
        numeric: true,
        width: 110,
        render: (r) => {
          const v = Number(r.dollar_volume ?? estimateDollar(r));
          const ratio = maxDollarVolume > 0 ? v / maxDollarVolume : 0;
          return (
            <NumericBar
              value={fmtCompact(r.dollar_volume ?? estimateDollar(r))}
              ratio={ratio}
            />
          );
        },
      },
      {
        key: "quote_state",
        header: "State",
        width: 90,
        render: (r) => (
          <Pill
            tone={r.quote_state === "live" ? "positive" : "muted"}
            variant="soft"
            withDot={r.quote_state === "live"}
          >
            {r.quote_state ?? (payload?.live ? "live" : "reference")}
          </Pill>
        ),
      },
    ],
    [payload?.live, setFocusedTarget, maxVolume, maxDollarVolume],
  );

  const activeFilters: Array<{ id: string; label: string; onRemove?: () => void }> = [
    { id: "asset", label: `ASSET · ${tab.toUpperCase()}` },
    { id: "sort", label: `SORT · ${sortLabel(sort)}` },
    { id: "limit", label: `LIMIT · ${limit}` },
    { id: "screen", label: "LIVE SCREEN" },
  ];

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Most active"
          subtitle={`${rows.length} row(s) · ${payload?.asset_class_filter ?? assetClass ?? "all"} · sorted by ${sort}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="accent" variant="soft" withDot={false}>
                MATCHED {rows.length} / {payload?.universe_size ?? "—"}
              </Pill>
              <Pill
                tone={liveCount > 0 ? "positive" : "muted"}
                variant="soft"
                withDot={liveCount > 0}
              >
                {liveCount > 0 ? `LIVE ${liveCount}` : "REFERENCE"}
              </Pill>
              <Pill tone="muted" variant="soft" withDot={false}>
                BY {sortLabel(sort)} ↓
              </Pill>
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
        <div className="most-tab-strip">
          <Tabs
            variant="segmented"
            items={ASSET_TABS.map((t) => ({ id: t.id, label: t.label }))}
            active={tab}
            onChange={(id) => setTab(id as AssetTabId)}
          />
        </div>
        <PaneBody>
          <div className="u-flex u-flex-col u-gap-14">
            <Card variant="elev-2">
              <CardHeader
                trailing={
                  <Pill tone="muted" variant="soft" withDot={false}>
                    {PRESET_TILES.length} PRESETS
                  </Pill>
                }
              >
                Saved screens
              </CardHeader>
              <CardBody>
                <div style={presetGridStyle}>
                  {PRESET_TILES.map((p) => (
                    <CommandTile
                      key={p.code}
                      code={p.code}
                      description={p.description}
                      active={tab === p.tab && sort === p.sort}
                      onClick={() => {
                        setTab(p.tab);
                        setSort(p.sort);
                      }}
                    />
                  ))}
                </div>
              </CardBody>
            </Card>

            <Card>
              <CardHeader
                trailing={
                  <span className="u-inline-flex u-gap-6 u-items-center btn btn--ghost u-btn-mini btn--accent">
                    <button
                      type="button"
                      
                      onClick={() => {
                        setTab("all");
                        setSort("volume");
                        setLimit(50);
                      }}
                      
                    >
                      Reset
                    </button>
                    <button
                      type="button"
                      
                      onClick={refetch}
                      
                    >
                      Apply
                    </button>
                  </span>
                }
              >
                Filter rail
              </CardHeader>
              <CardBody>
                <div style={filterChipRowStyle}>
                  {activeFilters.map((f) => (
                    <FilterChip key={f.id} label={f.label} onRemove={f.onRemove} />
                  ))}
                </div>
              </CardBody>
            </Card>

            {state === "loading" || state === "idle" ? (
              <Card>
                <CardBody>
                  <Skeleton height={320} />
                </CardBody>
              </Card>
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
                title="No matches with current filters"
                body={payload?.reason ?? `No ${tab} payload right now.`}
                action={
                  <button
                    type="button"
                    className="btn btn--accent"
                    onClick={() => {
                      setTab("all");
                      setSort("volume");
                      refetch();
                    }}
                  >
                    Reset & retry
                  </button>
                }
              />
            ) : (
              <>
                <div style={kpiStripStyle}>
                  <StatCard
                    label="Active"
                    value={String(rows.length)}
                    caption={`OF ${payload?.universe_size ?? "—"} UNIVERSE`}
                    trend={deterministicTrend(`a-${rows.length}-${tab}`)}
                    tone="neutral"
                  />
                  <StatCard
                    label="Median |Δ%|"
                    value={medianAbsChange != null ? `${medianAbsChange.toFixed(2)}%` : "—"}
                    caption={`SORTED BY ${sortLabel(sort)}`}
                    trend={deterministicTrend(`d-${medianAbsChange ?? 0}-${sort}`)}
                    tone={
                      medianAbsChange == null
                        ? "neutral"
                        : medianAbsChange > 2
                          ? "positive"
                          : "neutral"
                    }
                  />
                  <StatCard
                    label="Volume sum"
                    value={fmtCompact(totalVolume)}
                    caption={`LIVE ${liveCount}/${rows.length}`}
                    trend={deterministicTrend(`v-${totalVolume}-${liveCount}`)}
                    tone="neutral"
                  />
                  <StatCard
                    label="Source"
                    value={sourceLabel.toUpperCase()}
                    caption={`AS OF ${payload?.as_of ? new Date(payload.as_of).toLocaleTimeString() : "—"}`}
                    trend={deterministicTrend(`s-${sourceLabel}-${rows.length}`)}
                    tone="neutral"
                  />
                </div>

                <MostMethodology payload={payload} warnings={warnings} />

                <Card>
                  <CardHeader
                    trailing={
                      <span className="u-inline-flex u-gap-6 u-flex-wrap">
                        <Pill tone="positive" variant="soft" withDot={false}>
                          {rows.length} LEADERS
                        </Pill>
                        <Pill tone="muted" variant="soft" withDot={false}>
                          {payload?.asset_class_filter ?? assetClass ?? "ALL"}
                        </Pill>
                        <Pill tone="muted" variant="soft" withDot={false}>
                          BY {sortLabel(sort)}
                        </Pill>
                      </span>
                    }
                  >
                    Volume-weighted leaders
                  </CardHeader>
                  <CardBody>
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
                  </CardBody>
                </Card>
              </>
            )}
          </div>
        </PaneBody>
        <PaneFooter>
          <span>provider · {sourceLabel}</span>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span>asset · {assetClass ?? "all"}</span>
          <span>rows · {rows.length}/{limit}</span>
          <span>sort · {sort}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function NumericBar({ value, ratio }: { value: string; ratio: number }) {
  const pct = Math.max(0, Math.min(100, ratio * 100));
  return (
    <span className="most-numeric-bar">
      <span
        aria-hidden
        className="most-numeric-bar__track"
        style={{ ["--u-empty" as string]: `${100 - pct}%` }}
      />
      <span className="most-numeric-bar__label">{value}</span>
    </span>
  );
}

function FilterChip({
  label,
  onRemove,
}: {
  label: string;
  onRemove?: () => void;
}) {
  return (
    <span style={filterChipStyle}>
      <span>{label}</span>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          style={filterChipCloseStyle}
          title="Remove filter"
          aria-label={`Remove filter ${label}`}
        >
          ×
        </button>
      )}
    </span>
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

function MostMethodology({
  payload,
  warnings,
}: {
  payload: MostPayload | null;
  warnings: string[];
}) {
  const fields = payload?.field_dictionary?.slice(0, 4) ?? [];
  if (!payload?.methodology && !fields.length && !warnings.length) return null;
  return (
    <Card>
      <CardHeader>Methodology & dictionary</CardHeader>
      <CardBody>
        <div className="u-grid-gap-8">
          {payload?.methodology ? (
            <div className="most-methodology">{payload.methodology}</div>
          ) : null}
          {fields.length ? (
            <div className="u-flex u-gap-6 u-flex-wrap">
              {fields.map((field) => (
                <Pill
                  key={field.field ?? field.meaning}
                  tone="muted"
                  variant="soft"
                  withDot={false}
                >
                  {field.field}: {field.meaning}
                </Pill>
              ))}
            </div>
          ) : null}
          {warnings.length ? (
            <div className="most-warnings">{warnings.join(" · ")}</div>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}

function ActivityBars({ rows, sort }: { rows: MostRow[]; sort: SortKey }) {
  const visible = rows.slice(0, 8);
  const max = Math.max(1, ...visible.map((row) => Math.abs(sortVal(row, sort))));
  return (
    <div className="most-bars">
      {visible.map((row) => {
        const symbol = row.symbol ?? row.ticker ?? "—";
        const value = Math.abs(sortVal(row, sort));
        const pct = Math.max(3, Math.min(100, (value / max) * 100));
        const change = row.change_pct ?? row.changePercent;
        const negative = change != null && change < 0;
        return (
          <div key={symbol} className="most-bars__row">
            <span className="most-bars__symbol">{symbol}</span>
            <div className="most-bars__track">
              <div
                className={`most-bars__fill${negative ? " most-bars__fill--neg" : ""}`}
                style={{ ["--u-pct" as string]: `${pct}%` }}
              />
            </div>
            <span className="most-bars__value">{formatSortValue(row, sort)}</span>
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

function sortLabel(key: SortKey): string {
  if (key === "volume") return "VOLUME";
  if (key === "abs_change") return "|Δ%|";
  return "$ VOL";
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

const presetGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
  gap: 8,
};

const filterChipRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
  alignItems: "center",
};

const filterChipStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  height: 22,
  padding: "0 8px",
  background: "var(--surface-3)",
  border: "1px solid var(--border-subtle)",
  borderRadius: 11,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  letterSpacing: "0.06em",
  color: "var(--text-secondary)",
};

const filterChipCloseStyle: CSSProperties = {
  all: "unset",
  cursor: "default",
  width: 14,
  height: 14,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  borderRadius: "50%",
  color: "var(--text-mute)",
  fontSize: 12,
  lineHeight: 1,
};

const kpiStripStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};
