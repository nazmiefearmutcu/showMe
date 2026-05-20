import { useMemo, useState, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
  DeltaChip,
  Empty,
  HeatCell,
  intensityToken,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatusSection,
  StatusDivider,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { formatMissing, formatPrice } from "@/lib/format";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

type HeatmapMode = "live" | "model";
type HeatmapPeriod = "1D" | "MTD" | "QTD" | "YTD";

interface HeatmapRow {
  country?: string;
  sector?: string;
  etf?: string;
  symbol?: string;
  last?: number;
  change_pct?: number;
  period?: string;
  quote_type?: string;
}

const MODE_TABS: { id: HeatmapMode; label: string }[] = [
  { id: "live", label: "Live" },
  { id: "model", label: "Model" },
];

const PERIOD_TABS: { id: HeatmapPeriod; label: string }[] = [
  { id: "1D", label: "1D" },
  { id: "MTD", label: "MTD" },
  { id: "QTD", label: "QTD" },
  { id: "YTD", label: "YTD" },
];

export function MarketHeatmapPane({ code }: FunctionPaneProps) {
  const upperCode = code.toUpperCase();
  const isSector = upperCode === "SECT";
  const [mode, setMode] = useState<HeatmapMode>("live");
  const [period, setPeriod] = useState<HeatmapPeriod>("1D");

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: {
      live: mode === "live",
      live_screen: mode === "live",
      period: isSector ? period : undefined,
      quote_timeout: 4,
      screen_timeout: 5,
    },
  });

  const rows = useMemo(() => normalizeHeatmapRows(data?.data), [data]);
  const payloadStatus = payloadStatusLabel(data?.data, data?.metadata);
  const best = useMemo(
    () =>
      rows.reduce<HeatmapRow | null>(
        (acc, row) =>
          acc == null || numericChange(row) > numericChange(acc) ? row : acc,
        null,
      ),
    [rows],
  );
  const worst = useMemo(
    () =>
      rows.reduce<HeatmapRow | null>(
        (acc, row) =>
          acc == null || numericChange(row) < numericChange(acc) ? row : acc,
        null,
      ),
    [rows],
  );

  const columns = useMemo<DataGridColumn<HeatmapRow>[]>(
    () => [
      {
        key: "label",
        header: isSector ? "Sector" : "Country",
        render: (row) => (
          <strong className="u-text-primary">
            {labelForRow(row)}
          </strong>
        ),
      },
      {
        key: "etf",
        header: "ETF",
        width: 90,
        render: (row) => (
          <span className="mh-etf-symbol">
            {row.etf ?? row.symbol ?? "—"}
          </span>
        ),
      },
      {
        key: "last",
        header: "Last",
        numeric: true,
        width: 100,
        render: (row) => fmtNum(row.last),
      },
      {
        key: "change_pct",
        header: `${isSector ? period : "1D"} change`,
        numeric: true,
        width: 110,
        render: (row) =>
          row.change_pct != null ? (
            <DeltaChip value={row.change_pct} format="percent" fractionDigits={2} />
          ) : (
            "—"
          ),
      },
      {
        key: "quote_type",
        header: "Source",
        width: 90,
        render: (row) => (
          <Pill
            tone={
              String(row.quote_type ?? "").toLowerCase() === "live"
                ? "positive"
                : "warn"
            }
            withDot={false}
            variant="soft"
          >
            {row.quote_type ?? mode}
          </Pill>
        ),
      },
    ],
    [isSector, mode, period],
  );

  const totalUp = rows.filter((r) => numericChange(r) > 0).length;
  const totalDown = rows.filter((r) => numericChange(r) < 0).length;
  const breadthRatio = rows.length ? totalUp / rows.length : 0;

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={upperCode}
          title={isSector ? "Sector heatmap" : "World market heatmap"}
          subtitle={`${rows.length} ${isSector ? "sector" : "country"} row(s) · ${mode}`}
          trailing={
            <FunctionControlGroup>
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
              />
            </FunctionControlGroup>
          }
        />

        {/* Bloomberg-grade header toolbar */}
        <div style={headerToolbarStyle}>
          <div style={toolbarSegmentStyle}>
            <span style={toolbarLabelStyle}>SOURCE</span>
            <PillRow
              items={MODE_TABS}
              active={mode}
              onChange={(id) => setMode(id as HeatmapMode)}
              variant="filled"
            />
          </div>
          {isSector ? (
            <div style={toolbarSegmentStyle}>
              <span style={toolbarLabelStyle}>WINDOW</span>
              <PillRow
                items={PERIOD_TABS}
                active={period}
                onChange={(id) => setPeriod(id as HeatmapPeriod)}
                variant="filled"
              />
            </div>
          ) : null}
          <Pill tone="accent" variant="soft" withDot={false}>
            {isSector ? "S&P 11" : "Country ETFs"} ({rows.length})
          </Pill>
          <Pill
            tone={state === "ok" ? "positive" : state === "loading" ? "warn" : "muted"}
            variant="soft"
          >
            {state === "ok" ? "live" : state}
          </Pill>
          {data?.elapsed_ms != null && (
            <Pill tone="muted" variant="soft" withDot={false}>
              {data.elapsed_ms.toFixed(0)} ms
            </Pill>
          )}
        </div>

        <PaneBody className="u-p-0">
          <div className="u-p-14 u-grid-gap-12">
            {state === "loading" || state === "idle" ? (
              <Skeleton height={360} />
            ) : state === "error" ? (
              <Empty
                title="Function error"
                body={error?.message ?? "—"}
                icon="!"
              />
            ) : rows.length === 0 ? (
              <>
                {payloadStatus ? <StatusNotice notice={payloadStatus} /> : null}
                <Empty
                  title="No heatmap rows"
                  body="No country or sector ETF rows were returned."
                />
              </>
            ) : (
              <>
                {payloadStatus ? <StatusNotice notice={payloadStatus} /> : null}

                {/* Stat strip */}
                <div style={statStripStyle}>
                  <BreadthCard
                    label="Breadth"
                    up={totalUp}
                    down={totalDown}
                    ratio={breadthRatio}
                  />
                  <SuperlativeCard label="Best" row={best} tone="positive" />
                  <SuperlativeCard label="Worst" row={worst} tone="negative" />
                  <SimpleCard
                    label="Window"
                    value={isSector ? period : "1D"}
                    sub={mode}
                  />
                </div>

                {/* Main: heatmap grid (left) + legend rail (right) */}
                <div style={mainGridStyle}>
                  <div className="u-min-w-0">
                    <SectorHeatGrid rows={rows} isSector={isSector} />
                  </div>
                  <LegendRail rows={rows} />
                </div>

                <DataGrid
                  columns={columns}
                  rows={rows}
                  rowKey={(row, idx) => `${labelForRow(row)}-${idx}`}
                  density="compact"
                />
              </>
            )}
          </div>
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
            tone="muted"
          />
          <StatusSection
            label="sources"
            value={(data?.sources ?? []).join(", ") || "—"}
            tone="muted"
          />
          <StatusDivider />
          <StatusSection
            tone={data?.status === "ok" ? "positive" : "warn"}
            withDot
            label="status"
            value={data?.status ?? "ok"}
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function PillRow({
  items,
  active,
  onChange,
  variant = "filled",
}: {
  items: readonly { id: string; label: string }[];
  active: string;
  onChange: (id: string) => void;
  variant?: "filled" | "ghost";
}) {
  return (
    <div style={pillRowContainerStyle}>
      {items.map((it) => {
        const isActive = it.id === active;
        return (
          <button
            key={it.id}
            type="button"
            onClick={() => onChange(it.id)}
            style={{
              ...pillButtonStyle,
              background:
                isActive && variant === "filled"
                  ? "var(--accent)"
                  : isActive
                    ? "var(--accent-soft)"
                    : "transparent",
              color: isActive
                ? variant === "filled"
                  ? "var(--accent-on)"
                  : "var(--accent)"
                : "var(--text-secondary)",
              fontWeight: isActive ? 700 : 500,
            }}
          >
            {it.label}
          </button>
        );
      })}
    </div>
  );
}

function SectorHeatGrid({
  rows,
  isSector,
}: {
  rows: HeatmapRow[];
  isSector: boolean;
}) {
  const maxAbs = Math.max(...rows.map((row) => Math.abs(numericChange(row))), 1);
  return (
    <section style={heatGridStyle} aria-label="ETF performance heatmap">
      {rows.map((row, idx) => {
        const value = numericChange(row);
        const cellSize = sizeForValue(value, maxAbs);
        const tone =
          value === 0
            ? "neutral"
            : value > 0
              ? "positive"
              : "negative";
        return (
          <div
            key={`${labelForRow(row)}-${idx}`}
            style={{
              ...heatCellWrapStyle,
              gridColumn: `span ${cellSize}`,
              background: intensityToken(value, maxAbs),
              borderColor:
                tone === "positive"
                  ? "color-mix(in srgb, var(--positive) 32%, transparent)"
                  : tone === "negative"
                    ? "color-mix(in srgb, var(--negative) 32%, transparent)"
                    : "var(--border-subtle)",
            }}
            title={`${labelForRow(row)} · ${value.toFixed(2)}% (${isSector ? "sector" : "country"})`}
          >
            <div style={heatCellTopRowStyle}>
              <strong style={heatCellLabelStyle}>{labelForRow(row)}</strong>
              <span style={heatCellTickerStyle}>
                {row.etf ?? row.symbol ?? "—"}
              </span>
            </div>
            <div style={heatCellValueRowStyle}>
              <span
                style={{
                  ...heatCellValueStyle,
                  color: tone === "positive"
                    ? "var(--positive)"
                    : tone === "negative"
                      ? "var(--negative)"
                      : "var(--text-secondary)",
                }}
              >
                {value >= 0 ? "+" : ""}
                {value.toFixed(2)}%
              </span>
              <span style={heatCellLastStyle}>{fmtNum(row.last)}</span>
            </div>
          </div>
        );
      })}
    </section>
  );
}

function LegendRail({ rows }: { rows: HeatmapRow[] }) {
  const sorted = [...rows].sort(
    (a, b) => numericChange(b) - numericChange(a),
  );
  const top5 = sorted.slice(0, 5);
  const bottom5 = sorted.slice(-5).reverse();

  return (
    <aside style={legendRailStyle}>
      <RailSection title="Heat scale">
        <div className="u-grid-gap-6">
          <div style={gradientBarStyle} aria-hidden>
            {Array.from({ length: 41 }).map((_, idx) => {
              const value = -1 + (idx / 40) * 2;
              return (
                <div
                  key={idx}
                  style={{
                    flex: 1,
                    background: intensityToken(value),
                  }}
                />
              );
            })}
          </div>
          <div style={gradientLegendTicksStyle}>
            <span>−10%</span>
            <span>−5%</span>
            <span>0</span>
            <span>+5%</span>
            <span>+10%</span>
          </div>
        </div>
      </RailSection>
      <RailSection title="Top movers">
        <div className="u-grid-gap-4">
          {top5.map((row, idx) => (
            <RankRow key={`top-${idx}`} row={row} tone="positive" />
          ))}
        </div>
      </RailSection>
      <RailSection title="Worst movers">
        <div className="u-grid-gap-4">
          {bottom5.map((row, idx) => (
            <RankRow key={`bot-${idx}`} row={row} tone="negative" />
          ))}
        </div>
      </RailSection>
    </aside>
  );
}

function RankRow({ row, tone }: { row: HeatmapRow; tone: "positive" | "negative" }) {
  const value = numericChange(row);
  return (
    <div style={rankRowStyle}>
      <HeatCell value={value} range={5} size={22} fractionDigits={1} />
      <div style={rankColumnStyle}>
        <span style={rankLabelStyle}>{labelForRow(row)}</span>
        <span style={rankTickerStyle}>{row.etf ?? row.symbol ?? "—"}</span>
      </div>
      <span
        style={{
          ...rankValueStyle,
          color: tone === "positive" ? "var(--positive)" : "var(--negative)",
        }}
      >
        {value >= 0 ? "+" : ""}
        {value.toFixed(2)}%
      </span>
    </div>
  );
}

function BreadthCard({
  label,
  up,
  down,
  ratio,
}: {
  label: string;
  up: number;
  down: number;
  ratio: number;
}) {
  return (
    <div style={statCardStyle}>
      <span style={statLabelStyle}>{label}</span>
      <div style={breadthBarStyle}>
        <div
          className="mh-breadth-fill"
          style={{ ["--u-pct" as string]: `${ratio * 100}%` }}
        />
      </div>
      <div style={breadthRowStyle}>
        <span className="u-text-positive">▲ {up}</span>
        <span className="u-text-mute">·</span>
        <span className="u-text-negative">▼ {down}</span>
      </div>
    </div>
  );
}

function SuperlativeCard({
  label,
  row,
  tone,
}: {
  label: string;
  row: HeatmapRow | null;
  tone: "positive" | "negative";
}) {
  if (!row) {
    return (
      <div style={statCardStyle}>
        <span style={statLabelStyle}>{label}</span>
        <strong style={statValueStyle}>—</strong>
      </div>
    );
  }
  const value = numericChange(row);
  return (
    <div
      style={{
        ...statCardStyle,
        borderLeft: `3px solid ${
          tone === "positive" ? "var(--positive)" : "var(--negative)"
        }`,
      }}
    >
      <span style={statLabelStyle}>{label}</span>
      <strong style={statValueStyle}>{labelForRow(row)}</strong>
      <span style={statSubStyle}>
        <DeltaChip value={value} format="percent" fractionDigits={2} />
        <span className="scan-divider">
          {row.etf ?? row.symbol ?? ""}
        </span>
      </span>
    </div>
  );
}

function SimpleCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div style={statCardStyle}>
      <span style={statLabelStyle}>{label}</span>
      <strong style={statValueStyle}>{value}</strong>
      {sub && <span style={statSubStyle}>{sub.toUpperCase()}</span>}
    </div>
  );
}

function RailSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section style={railSectionStyle}>
      <div style={railSectionTitleStyle}>{title}</div>
      {children}
    </section>
  );
}

function StatusNotice({
  notice,
}: {
  notice: { title: string; body: string };
}) {
  return (
    <section style={noticeBoxStyle}>
      <strong>{notice.title}</strong>
      <span>{notice.body}</span>
    </section>
  );
}

// ----- helpers -----

function normalizeHeatmapRows(payload: unknown): HeatmapRow[] {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload as HeatmapRow[];
  if (typeof payload !== "object") return [];
  const rows = (payload as Record<string, unknown>).rows;
  return Array.isArray(rows) ? (rows as HeatmapRow[]) : [];
}

function payloadStatusLabel(
  payload: unknown,
  metadata: Record<string, unknown> | undefined,
): { title: string; body: string } | null {
  if (!payload || typeof payload !== "object") return null;
  const record = payload as Record<string, unknown>;
  const status = String(record.status ?? "").toLowerCase();
  const degraded = Boolean(metadata?.fallback || metadata?.degraded);
  const reason = String(record.reason ?? "");
  if (!status && !degraded && !reason) return null;
  const providerErrors = Array.isArray(metadata?.provider_errors)
    ? metadata.provider_errors.map(String).slice(0, 2).join(" · ")
    : "";
  return {
    title:
      status === "provider_unavailable"
        ? "Provider unavailable"
        : status || "Degraded snapshot",
    body: [reason, providerErrors].filter(Boolean).join(" "),
  };
}

function labelForRow(row: HeatmapRow): string {
  return row.sector ?? row.country ?? row.symbol ?? row.etf ?? "—";
}

function numericChange(row: HeatmapRow): number {
  return typeof row.change_pct === "number" && Number.isFinite(row.change_pct)
    ? row.change_pct
    : 0;
}

function fmtNum(value: number | undefined | null): string {
  // Adaptive precision via the shared formatter — keeps sub-dollar prices
  // (FX, sat-denominated crypto) from collapsing to "0.00". Returns the
  // shared em-dash sentinel for missing values.
  if (value == null || !Number.isFinite(value)) return formatMissing;
  return formatPrice(value);
}

// Determine grid span (column span 1..3) based on relative magnitude.
function sizeForValue(value: number, maxAbs: number): number {
  const ratio = maxAbs ? Math.abs(value) / maxAbs : 0;
  if (ratio > 0.66) return 3;
  if (ratio > 0.33) return 2;
  return 1;
}

// ----- styles -----

const headerToolbarStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-1)",
  flexWrap: "wrap",
};

const toolbarSegmentStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
};

const toolbarLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const pillRowContainerStyle: CSSProperties = {
  display: "inline-flex",
  gap: 2,
  padding: 2,
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
};

const pillButtonStyle: CSSProperties = {
  border: "none",
  padding: "3px 10px",
  borderRadius: "var(--radius-sm)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  cursor: "default",
  letterSpacing: "0.04em",
  transition: "background var(--motion-fast), color var(--motion-fast)",
};

const statStripStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 8,
};

const statCardStyle: CSSProperties = {
  display: "grid",
  gap: 4,
  padding: "10px 12px",
  background: "var(--surface-2)",
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  minWidth: 0,
};

const statLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const statValueStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 14,
  fontWeight: 600,
  color: "var(--text-display)",
  fontVariantNumeric: "tabular-nums",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const statSubStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-mute)",
  letterSpacing: "0.06em",
  display: "flex",
  alignItems: "center",
};

const breadthBarStyle: CSSProperties = {
  height: 6,
  background: "var(--surface-3)",
  borderRadius: 4,
  overflow: "hidden",
};

const breadthRowStyle: CSSProperties = {
  display: "flex",
  gap: 6,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  fontWeight: 600,
};

const mainGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1fr) 240px",
  gap: 12,
};

const heatGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(6, 1fr)",
  gap: 6,
  minHeight: 180,
};

const heatCellWrapStyle: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  padding: "10px 12px",
  display: "grid",
  gap: 6,
  alignContent: "space-between",
  minHeight: 76,
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
};

const heatCellTopRowStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "baseline",
  gap: 8,
};

const heatCellLabelStyle: CSSProperties = {
  fontSize: 11,
  color: "var(--text-display)",
  letterSpacing: "0.02em",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const heatCellTickerStyle: CSSProperties = {
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.06em",
};

const heatCellValueRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  justifyContent: "space-between",
  gap: 8,
};

const heatCellValueStyle: CSSProperties = {
  fontSize: 16,
  fontWeight: 700,
};

const heatCellLastStyle: CSSProperties = {
  fontSize: 10,
  color: "var(--text-secondary)",
};

const legendRailStyle: CSSProperties = {
  display: "grid",
  alignContent: "start",
  gap: 10,
  width: 240,
  minWidth: 0,
};

const railSectionStyle: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-1)",
  borderRadius: "var(--radius-md)",
  padding: "10px 12px",
};

const railSectionTitleStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.1em",
  textTransform: "uppercase",
  marginBottom: 8,
};

const gradientBarStyle: CSSProperties = {
  display: "flex",
  height: 14,
  borderRadius: 4,
  overflow: "hidden",
  border: "1px solid var(--border-subtle)",
};

const gradientLegendTicksStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.04em",
};

const rankRowStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "auto minmax(0, 1fr) auto",
  alignItems: "center",
  gap: 8,
  padding: "4px 0",
  borderBottom: "1px solid var(--border-row)",
};

const rankColumnStyle: CSSProperties = {
  display: "grid",
  gap: 1,
  minWidth: 0,
};

const rankLabelStyle: CSSProperties = {
  fontSize: 11,
  color: "var(--text-primary)",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const rankTickerStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.06em",
};

const rankValueStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  fontWeight: 600,
  fontVariantNumeric: "tabular-nums",
};

const noticeBoxStyle: CSSProperties = {
  border: "1px solid var(--warn)",
  background: "var(--warn-soft)",
  color: "var(--text-secondary)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
};
