import { useMemo, useState, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
  DeltaChip,
  Empty,
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
import { formatMissing, formatPercent, formatPrice } from "@/lib/format";
import { maxAbsOf } from "@/lib/maxOf";
import { navigate } from "@/lib/router";
import { useWorkspace } from "@/lib/workspace";
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
  change_pct_period?: string;
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
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);

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
  // The user-requested change window (the WINDOW selector for SECT; MAP is
  // always intraday). `requestedPeriod` is what the user asked for; the backend
  // tells us what it actually DELIVERED via `change_pct_period` (e.g. "1D" in
  // live mode regardless of the request). We label every change value with the
  // DELIVERED period so an MTD request can't masquerade as MTD data.
  const requestedPeriod = isSector ? period : "1D";
  const deliveredPeriod = deliveredPeriodOf(data?.data, rows, requestedPeriod);
  const periodMismatch = isSector && deliveredPeriod !== requestedPeriod;
  const warnings = extractWarnings(data);
  // P-honesty: model/fallback detection — synthetic rows must not read as real
  // market sentiment. True when metadata flags degraded/fallback OR every row
  // is quote_type "model".
  const isModel = useMemo(
    () => isModelData(rows, data?.data, data?.metadata),
    [rows, data],
  );
  const asOf = useMemo(() => extractAsOf(data), [data]);

  const onPick = (sym?: string) => {
    if (!sym) return;
    setFocusedTarget("DES", sym);
    navigate(`/symbol/${sym}/DES`);
  };
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
        header: `${deliveredPeriod} change`,
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
    [isSector, mode, deliveredPeriod],
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
            tone={
              isModel
                ? "warn"
                : state === "ok"
                  ? "positive"
                  : state === "loading"
                    ? "warn"
                    : "muted"
            }
            variant="soft"
          >
            {isModel ? "model" : state === "ok" ? "live" : state}
          </Pill>
          <Pill tone="muted" variant="soft" withDot={false}>
            {asOf ? `${asOf} UTC` : "—"}
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
              <div aria-busy="true" aria-live="polite">
                <Skeleton height={360} />
              </div>
            ) : state === "error" ? (
              <div role="status">
                <Empty
                  title="Function error"
                  body={error?.message ?? "—"}
                  icon="!"
                />
              </div>
            ) : rows.length === 0 ? (
              <>
                {isModel ? <ModelDataBadge /> : null}
                {periodMismatch ? (
                  <PeriodMismatchNotice
                    requested={requestedPeriod}
                    delivered={deliveredPeriod}
                    warnings={warnings}
                  />
                ) : null}
                {payloadStatus ? <StatusNotice notice={payloadStatus} /> : null}
                <Empty
                  title="No heatmap rows"
                  body="No country or sector ETF rows were returned."
                />
              </>
            ) : (
              <>
                {isModel ? <ModelDataBadge /> : null}
                {periodMismatch ? (
                  <PeriodMismatchNotice
                    requested={requestedPeriod}
                    delivered={deliveredPeriod}
                    warnings={warnings}
                  />
                ) : null}
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
                    value={deliveredPeriod}
                    sub={mode}
                  />
                </div>

                {/* Main: heatmap grid (left) + legend rail (right) */}
                <div style={mainGridStyle}>
                  <div className="u-min-w-0">
                    <SectorHeatGrid
                      rows={rows}
                      isSector={isSector}
                      deliveredPeriod={deliveredPeriod}
                      isModel={isModel}
                      onPick={onPick}
                    />
                  </div>
                  <LegendRail
                    rows={rows}
                    deliveredPeriod={deliveredPeriod}
                    isModel={isModel}
                    onPick={onPick}
                  />
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
            aria-pressed={isActive}
            onClick={() => onChange(it.id)}
            className="mh-pill-button"
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
  deliveredPeriod,
  isModel,
  onPick,
}: {
  rows: HeatmapRow[];
  isSector: boolean;
  deliveredPeriod: string;
  isModel: boolean;
  onPick: (sym?: string) => void;
}) {
  // UA-HIGH-12: stack-safe.
  const maxAbs = maxAbsOf(rows.map(numericChange), 1);
  return (
    <div className="u-grid-gap-6">
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
          const sym = row.etf ?? row.symbol;
          const synthetic =
            isModel ||
            String(row.quote_type ?? "").toLowerCase() === "model";
          // DI1: ratio-driven contrast (mirror HeatCell) — high-intensity
          // tiles use the bright display color so green/red text stays legible
          // on a saturated same-tone background; low-intensity uses secondary.
          const fg = textColorForCell(value, maxAbs);
          const pct = formatPercent(value, { digits: 2, signed: true });
          return (
            <button
              key={`${labelForRow(row)}-${idx}`}
              type="button"
              className="mh-heat-cell"
              onClick={() => onPick(sym)}
              disabled={!sym}
              aria-label={`${labelForRow(row)} (${sym ?? "—"}) ${pct} ${deliveredPeriod}${synthetic ? " (model)" : ""}`}
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
              title={`${labelForRow(row)} · ${pct} ${deliveredPeriod} (${isSector ? "sector" : "country"})`}
            >
              <div style={heatCellTopRowStyle}>
                <strong style={{ ...heatCellLabelStyle, color: fg }}>
                  {labelForRow(row)}
                </strong>
                <span style={heatCellTickerStyle}>{sym ?? "—"}</span>
              </div>
              <div style={heatCellValueRowStyle}>
                <span style={{ ...heatCellValueStyle, color: fg }}>{pct}</span>
                <span style={heatCellLastStyle}>{fmtNum(row.last)}</span>
              </div>
            </button>
          );
        })}
      </section>
      <p style={sizingNoteStyle} data-testid="map-sizing-note">
        Kutu boyutu = % değişim büyüklüğü (piyasa değeri DEĞİL).
      </p>
    </div>
  );
}

function LegendRail({
  rows,
  deliveredPeriod,
  isModel,
  onPick,
}: {
  rows: HeatmapRow[];
  deliveredPeriod: string;
  isModel: boolean;
  onPick: (sym?: string) => void;
}) {
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
            <RankRow
              key={`top-${idx}`}
              row={row}
              tone="positive"
              deliveredPeriod={deliveredPeriod}
              isModel={isModel}
              onPick={onPick}
            />
          ))}
        </div>
      </RailSection>
      <RailSection title="Worst movers">
        <div className="u-grid-gap-4">
          {bottom5.map((row, idx) => (
            <RankRow
              key={`bot-${idx}`}
              row={row}
              tone="negative"
              deliveredPeriod={deliveredPeriod}
              isModel={isModel}
              onPick={onPick}
            />
          ))}
        </div>
      </RailSection>
    </aside>
  );
}

function RankRow({
  row,
  tone,
  deliveredPeriod,
  isModel,
  onPick,
}: {
  row: HeatmapRow;
  tone: "positive" | "negative";
  deliveredPeriod: string;
  isModel: boolean;
  onPick: (sym?: string) => void;
}) {
  const value = numericChange(row);
  const sym = row.etf ?? row.symbol;
  const synthetic =
    isModel || String(row.quote_type ?? "").toLowerCase() === "model";
  const pct = formatPercent(value, { digits: 2, signed: true });
  // DI1: ratio-driven contrast — the mover value uses the bright display
  // color for big moves (legible against any row tint) and the tone color
  // for small ones.
  const fg = textColorForCell(value, 5);
  return (
    <button
      type="button"
      className="mh-rank-row"
      style={rankRowStyle}
      onClick={() => onPick(sym)}
      disabled={!sym}
      aria-label={`${labelForRow(row)} (${sym ?? "—"}) ${pct} ${deliveredPeriod}${synthetic ? " (model)" : ""}`}
    >
      {/* Heat swatch — a plain element (NOT design-system HeatCell, which is a
          <button>) so we don't nest interactive controls inside this row
          button. */}
      <span
        aria-hidden
        style={{
          width: 22,
          height: 22,
          flexShrink: 0,
          borderRadius: 4,
          background: intensityToken(value, 5),
          border: "1px solid var(--border-row)",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 9,
          fontFamily: "JetBrains Mono, monospace",
          fontVariantNumeric: "tabular-nums",
          color: textColorForCell(value, 5),
        }}
      >
        {value.toFixed(1)}
      </span>
      <div style={rankColumnStyle}>
        <span style={rankLabelStyle}>{labelForRow(row)}</span>
        <span style={rankTickerStyle}>{sym ?? "—"}</span>
      </div>
      <span
        style={{
          ...rankValueStyle,
          color:
            fg === "var(--text-display)"
              ? "var(--text-display)"
              : tone === "positive"
                ? "var(--positive)"
                : "var(--negative)",
        }}
      >
        {pct}
      </span>
    </button>
  );
}

/** Prominent "MODEL data — not live" badge (mirrors WEI's ModelDataBadge). */
function ModelDataBadge() {
  return (
    <div
      className="wei-model-badge"
      role="status"
      data-testid="map-model-badge"
      aria-label="Model veri — canlı piyasa değil"
    >
      <span className="wei-model-badge__dot" aria-hidden />
      <strong>MODEL VERİ — canlı piyasa değil</strong>
      <span className="u-text-secondary">
        Bu kutular deterministik bir ETF modeli, canlı piyasa kotasyonu değil.
      </span>
    </div>
  );
}

/**
 * SECT live mode delivers only intraday (1D) changes even when the user picks
 * MTD/QTD/YTD. This notice discloses the delivered vs. requested period and
 * surfaces any backend `warnings`, so an MTD request can't read as MTD data.
 */
function PeriodMismatchNotice({
  requested,
  delivered,
  warnings,
}: {
  requested: string;
  delivered: string;
  warnings: string[];
}) {
  return (
    <div
      className="wei-model-badge"
      role="status"
      data-testid="map-period-notice"
      aria-label="Period mismatch"
    >
      <span className="wei-model-badge__dot" aria-hidden />
      <strong>
        Canlı modda yalnız günlük ({delivered}) değişim var
      </strong>
      <span className="u-text-secondary">
        Seçilen {requested} için geçmiş veri gerekir; gösterilen değerler{" "}
        {delivered} değişimidir.
      </span>
      {warnings.map((w, i) => (
        <span key={i} className="u-text-secondary">
          {w}
        </span>
      ))}
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
  // A healthy "ok"/"live" status on a clean payload is NOT a notice — emitting
  // a warning box for it is UI noise (and a honesty regression: it implies a
  // problem when there is none). Only genuinely degraded/fallback/error/model
  // statuses (or any non-empty reason / degraded metadata) produce a notice.
  const healthy = !status || status === "ok" || status === "live";
  if (healthy && !degraded && !reason) return null;
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

/**
 * The period the backend ACTUALLY delivered for the change values. SECT live
 * mode stamps `change_pct_period` ("1D") even when the user asked for
 * MTD/QTD/YTD; we prefer that, fall back to the per-row `period`, then to the
 * requested period. This is the label we put on every change value so a
 * mismatch can't masquerade as the requested window.
 */
function deliveredPeriodOf(
  payload: unknown,
  rows: HeatmapRow[],
  requested: string,
): string {
  if (payload && typeof payload === "object") {
    const cp = (payload as Record<string, unknown>).change_pct_period;
    if (typeof cp === "string" && cp) return cp;
  }
  const rowPeriod = rows.find(
    (r) => typeof r.change_pct_period === "string" && r.change_pct_period,
  )?.change_pct_period;
  if (rowPeriod) return rowPeriod;
  return requested;
}

/** Top-level FunctionResult `warnings` (string[]); empty if absent. */
function extractWarnings(envelope: unknown): string[] {
  if (!envelope || typeof envelope !== "object") return [];
  const w = (envelope as Record<string, unknown>).warnings;
  if (!Array.isArray(w)) return [];
  return w.filter((x): x is string => typeof x === "string" && x.length > 0);
}

/** Server data-freshness (`fetched_at`) as an HH:MM UTC stamp, if present. */
function extractAsOf(envelope: unknown): string | undefined {
  if (!envelope || typeof envelope !== "object") return undefined;
  const raw = (envelope as Record<string, unknown>).fetched_at;
  if (typeof raw !== "string" || !raw) return undefined;
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return undefined;
  return d.toISOString().slice(11, 16);
}

/**
 * Detect model / fallback data: synthetic rows must not read as real market
 * sentiment. True when metadata flags degraded/fallback, the payload status is
 * model/provider_unavailable, or every row is explicitly quote_type "model".
 */
function isModelData(
  rows: HeatmapRow[],
  payload: unknown,
  metadata: Record<string, unknown> | undefined,
): boolean {
  if (metadata?.degraded === true || metadata?.fallback === true) return true;
  const o = (payload && typeof payload === "object" ? payload : {}) as Record<
    string,
    unknown
  >;
  const status = String(o.status ?? "").toLowerCase();
  if (status === "model" || status === "provider_unavailable") return true;
  if (
    rows.length &&
    rows.every((r) => String(r.quote_type ?? "").toLowerCase() === "model")
  ) {
    return true;
  }
  return false;
}

/**
 * DI1: ratio-driven foreground contrast (mirror design-system/HeatCell).
 * On a high-intensity tile the same-tone green/red text loses contrast, so we
 * switch to the bright `--text-display`; low-intensity tiles use a readable
 * secondary tone.
 */
function textColorForCell(value: number, range: number): string {
  const ratio = range ? Math.min(1, Math.abs(value) / range) : 0;
  return ratio > 0.5 ? "var(--text-display)" : "var(--text-secondary)";
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
  cursor: "pointer",
  letterSpacing: "0.04em",
  transition: "background var(--motion-fast), color var(--motion-fast)",
};

const sizingNoteStyle: CSSProperties = {
  margin: 0,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.04em",
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
