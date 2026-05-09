import { useMemo, useState, type CSSProperties } from "react";
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

const MODE_TABS = [
  { id: "live", label: "Live" },
  { id: "model", label: "Model" },
] as const;

const PERIOD_TABS = [
  { id: "1D", label: "1D" },
  { id: "MTD", label: "MTD" },
  { id: "QTD", label: "QTD" },
  { id: "YTD", label: "YTD" },
] as const;

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
  const best = useMemo(() => rows.reduce<HeatmapRow | null>(
    (acc, row) => (acc == null || numericChange(row) > numericChange(acc) ? row : acc),
    null,
  ), [rows]);
  const worst = useMemo(() => rows.reduce<HeatmapRow | null>(
    (acc, row) => (acc == null || numericChange(row) < numericChange(acc) ? row : acc),
    null,
  ), [rows]);

  const columns = useMemo<DataGridColumn<HeatmapRow>[]>(
    () => [
      {
        key: "label",
        header: isSector ? "Sector" : "Country",
        render: (row) => (
          <strong style={{ color: "var(--text-primary)" }}>
            {labelForRow(row)}
          </strong>
        ),
      },
      {
        key: "etf",
        header: "ETF",
        width: 90,
        render: (row) => (
          <span style={{ color: "var(--accent)", fontWeight: 700 }}>
            {row.etf ?? row.symbol ?? "-"}
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
            <ChangeText value={row.change_pct} digits={2} suffix="%" />
          ) : (
            "-"
          ),
      },
      {
        key: "quote_type",
        header: "Source",
        width: 90,
        render: (row) => (
          <Pill
            tone={String(row.quote_type ?? "").toLowerCase() === "live" ? "positive" : "warn"}
            withDot={false}
          >
            {row.quote_type ?? mode}
          </Pill>
        ),
      },
    ],
    [isSector, mode, period],
  );

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={upperCode}
          title={isSector ? "Sector heatmap" : "World market heatmap"}
          subtitle={`${rows.length} ${isSector ? "sector" : "country"} row(s) · ${mode}`}
          trailing={
            <FunctionControlGroup>
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <div style={toolbar}>
          <Tabs
            variant="segmented"
            items={MODE_TABS.map((item) => ({ id: item.id, label: item.label }))}
            active={mode}
            onChange={(id) => setMode(id as HeatmapMode)}
          />
          {isSector ? (
            <Tabs
              variant="segmented"
              items={PERIOD_TABS.map((item) => ({ id: item.id, label: item.label }))}
              active={period}
              onChange={(id) => setPeriod(id as HeatmapPeriod)}
            />
          ) : null}
        </div>
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <Skeleton height={360} />
          ) : state === "error" ? (
            <Empty title="Function error" body={error?.message ?? "-"} icon="!" />
          ) : rows.length === 0 ? (
            <>
              {payloadStatus ? <StatusNotice notice={payloadStatus} /> : null}
              <Empty title="No heatmap rows" body="No country or sector ETF rows were returned." />
            </>
          ) : (
            <div style={bodyStack}>
              {payloadStatus ? <StatusNotice notice={payloadStatus} /> : null}
              <div style={metricRow}>
                <HeatMetric label="best" row={best} />
                <HeatMetric label="worst" row={worst} />
                <div style={metricBox}>
                  <span style={metaLabel}>period</span>
                  <strong>{isSector ? period : "1D"}</strong>
                </div>
              </div>
              <HeatmapGrid rows={rows} />
              <DataGrid
                columns={columns}
                rows={rows}
                rowKey={(row, idx) => `${labelForRow(row)}-${idx}`}
                density="compact"
              />
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "-"} ms</span>
          <span>sources · {(data?.sources ?? []).join(", ") || "-"}</span>
          <span>status · {data?.status ?? "ok"}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function normalizeHeatmapRows(payload: unknown): HeatmapRow[] {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload as HeatmapRow[];
  if (typeof payload !== "object") return [];
  const rows = (payload as Record<string, unknown>).rows;
  return Array.isArray(rows) ? rows as HeatmapRow[] : [];
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
    title: status === "provider_unavailable" ? "Provider unavailable" : status || "Degraded snapshot",
    body: [reason, providerErrors].filter(Boolean).join(" "),
  };
}

function StatusNotice({ notice }: { notice: { title: string; body: string } }) {
  return (
    <section style={noticeBox}>
      <strong>{notice.title}</strong>
      <span>{notice.body}</span>
    </section>
  );
}

function HeatmapGrid({ rows }: { rows: HeatmapRow[] }) {
  const maxAbs = Math.max(...rows.map((row) => Math.abs(numericChange(row))), 1);
  return (
    <section style={heatGrid} aria-label="ETF performance heatmap">
      {rows.map((row, idx) => {
        const value = numericChange(row);
        const alpha = 0.24 + Math.min(Math.abs(value) / maxAbs, 1) * 0.54;
        const background = value >= 0
          ? `rgba(0,209,131,${alpha})`
          : `rgba(255,59,88,${alpha})`;
        return (
          <div key={`${labelForRow(row)}-${idx}`} style={{ ...heatCell, background }}>
            <strong>{labelForRow(row)}</strong>
            <span>{row.etf ?? row.symbol ?? "-"}</span>
            <b>{value.toFixed(2)}%</b>
          </div>
        );
      })}
    </section>
  );
}

function HeatMetric({ label, row }: { label: string; row: HeatmapRow | null }) {
  return (
    <div style={metricBox}>
      <span style={metaLabel}>{label}</span>
      <strong>{row ? labelForRow(row) : "-"}</strong>
      <small>{row?.change_pct != null ? `${row.change_pct.toFixed(2)}%` : "-"}</small>
    </div>
  );
}

function labelForRow(row: HeatmapRow): string {
  return row.sector ?? row.country ?? row.symbol ?? row.etf ?? "-";
}

function numericChange(row: HeatmapRow): number {
  return typeof row.change_pct === "number" && Number.isFinite(row.change_pct) ? row.change_pct : 0;
}

function fmtNum(value: number | undefined): string {
  if (value == null || !Number.isFinite(value)) return "-";
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

const toolbar: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 10,
  flexWrap: "wrap",
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--bg-elev-2)",
};

const bodyStack: CSSProperties = {
  display: "grid",
  gap: 12,
};

const noticeBox: CSSProperties = {
  border: "1px solid rgba(255,181,71,0.35)",
  background: "rgba(255,181,71,0.08)",
  color: "var(--text-secondary)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
};

const metricRow: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
  gap: 8,
};

const metricBox: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
  display: "grid",
  gap: 3,
  color: "var(--text-primary)",
  minHeight: 54,
};

const metaLabel: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: 10,
  letterSpacing: 0,
  textTransform: "uppercase",
};

const heatGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(92px, 1fr))",
  gap: 6,
  minHeight: 130,
};

const heatCell: CSSProperties = {
  border: "1px solid rgba(255,255,255,0.08)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 9px",
  minHeight: 64,
  display: "grid",
  gap: 3,
  alignContent: "center",
  color: "var(--text-primary)",
  fontVariantNumeric: "tabular-nums",
};
