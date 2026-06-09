/**
 * DEBT — Sovereign debt board.
 *
 * Bloomberg-terminal style macro overlay: horizontal bar ranking of
 * debt-to-GDP by country (severity-tinted), a local-currency-share column,
 * a sortable DataGrid, and KPI heroes for the highest / median / lowest
 * readings. The bundled baseline pins `portfolio_weight_pct = 0` and reports
 * `summary.portfolio_linked` so the macro table is never misread as real
 * portfolio exposure — surfaced honestly via the mode pill + footer.
 */
import { useMemo, type CSSProperties } from "react";
import {
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
  StatusDivider,
  StatusSection,
  Tabs,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { formatMissing, formatPercent } from "@/lib/format";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

/* ------------------------------------------------------------------ *
 * Payload contract — mirrors backend debt.py (consumed at data?.data).
 *   rows[]   : { country, debt_to_gdp, local_currency_share,
 *               portfolio_weight_pct, region?, name?, change?, history? }
 *   summary  : { countries, avg_debt_to_gdp, max?, median?, min?,
 *               max_country?, min_country?, portfolio_linked, as_of? }
 *   cards[]  : { key/label, value }
 *   data_mode / source_mode, methodology, warnings[], as_of
 * Every field is optional so a degraded payload still renders honestly.
 * ------------------------------------------------------------------ */
interface DebtRow {
  country?: string;
  name?: string;
  region?: string;
  debt_to_gdp?: number | null;
  local_currency_share?: number | null;
  local_ccy_share?: number | null;
  portfolio_weight_pct?: number | null;
  change?: number | null;
  change_pct?: number | null;
  history?: number[];
  trend?: number[];
  /** Observation vintage (World Bank year, e.g. "2023") — NOT the fetch date. */
  year?: string | number | null;
}

interface DebtSummary {
  countries?: number;
  count?: number;
  avg_debt_to_gdp?: number | null;
  max?: number | null;
  max_country?: string | null;
  median?: number | null;
  min?: number | null;
  min_country?: string | null;
  portfolio_linked?: boolean;
  as_of?: string;
}

interface DebtPayload {
  rows?: DebtRow[];
  summary?: DebtSummary;
  data_mode?: string;
  source_mode?: string;
  methodology?: string;
  warnings?: string[];
  as_of?: string;
}

const REGIONS = [
  { id: "all", label: "All" },
  { id: "americas", label: "Americas" },
  { id: "asia", label: "Asia" },
  { id: "europe", label: "Europe" },
  { id: "oceania", label: "Oceania" },
] as const;
type RegionId = (typeof REGIONS)[number]["id"];
const REGION_IDS = REGIONS.map((r) => r.id);

const REFRESH_MS = 120_000;
const DATA_MODE_LIVE = "live";

export function DEBTPane({ code, symbol }: FunctionPaneProps) {
  const [region, setRegion] = usePersistentOption<RegionId>(
    "showme.debt-region",
    REGION_IDS,
    "all",
  );
  const [showTrend, setShowTrend] = usePersistentOption<"on" | "off">(
    "showme.debt-trend",
    ["on", "off"],
    "on",
  );
  // Visibility-aware poll — macro data refreshes slowly.
  const tick = useVisibilityTick(REFRESH_MS);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    symbol,
    params: { tick },
  });

  const payload = useMemo<DebtPayload>(
    () => (isRecord(data?.data) ? (data?.data as DebtPayload) : {}),
    [data?.data],
  );

  const allRows = useMemo<DebtRow[]>(
    () => (Array.isArray(payload.rows) ? payload.rows : []),
    [payload.rows],
  );
  const summary = payload.summary ?? {};

  const rows = useMemo(
    () =>
      region === "all"
        ? allRows
        : allRows.filter((r) => matchesRegion(r, region)),
    [allRows, region],
  );

  // Bars scale against the GLOBAL max so cross-region comparison stays honest.
  const scaleMax = useMemo(() => {
    const vals = allRows
      .map((r) => numeric(r.debt_to_gdp))
      .filter((v): v is number => v != null);
    return vals.length ? Math.max(...vals) : 100;
  }, [allRows]);

  const barRanking = useMemo(
    () =>
      [...rows].sort(
        (a, b) => (numeric(b.debt_to_gdp) ?? 0) - (numeric(a.debt_to_gdp) ?? 0),
      ),
    [rows],
  );

  // KPI heroes — fall back to derived stats when summary omits them.
  const kpi = useMemo(() => deriveKpi(allRows, summary), [allRows, summary]);

  const dataMode = payload.source_mode ?? payload.data_mode ?? "modeled";
  const isLive = dataMode === DATA_MODE_LIVE;
  const portfolioLinked = summary.portfolio_linked === true;
  const warnings = Array.isArray(payload.warnings) ? payload.warnings : [];
  const methodology =
    typeof payload.methodology === "string" ? payload.methodology : "";
  const sources =
    data?.sources?.join(", ") || String(payload.source_mode ?? dataMode);
  const asOf = payload.as_of ?? summary.as_of ?? "—";
  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 16), [tick]);

  const cols = useMemo<DataGridColumn<DebtRow>[]>(() => {
    const base: DataGridColumn<DebtRow>[] = [
      {
        key: "country",
        header: "Country",
        sortable: true,
        width: 150,
        render: (r) => (
          <div style={countryCellStyle}>
            <span style={isoStyle}>{r.country ?? "—"}</span>
            {r.name ? <span style={countryNameStyle}>{r.name}</span> : null}
          </div>
        ),
      },
      {
        key: "debt_to_gdp",
        header: "Debt / GDP",
        numeric: true,
        sortable: true,
        width: 120,
        render: (r) => {
          const v = numeric(r.debt_to_gdp);
          if (v == null) return <span style={mutedNum}>—</span>;
          return (
            <span style={{ ...primaryNum, color: debtColor(v) }}>
              {fmtPct(v)}
            </span>
          );
        },
      },
      {
        key: "local_currency_share",
        header: (
          <span style={refHeaderStyle}>
            Local ccy
            <span
              style={refBadgeStyle}
              role="img"
              aria-label="Yayınlanmış referans (canlı seri değil)"
              title="Yayınlanmış referans — canlı World Bank serisi değil"
            >
              referans
            </span>
          </span>
        ),
        numeric: true,
        sortable: true,
        width: 150,
        render: (r) => <LocalCcyBar value={localShare(r)} />,
      },
      {
        key: "year",
        header: "Veri yılı",
        numeric: true,
        sortable: true,
        width: 80,
        render: (r) => {
          const y = vintageYear(r);
          if (!y) return <span style={mutedNum}>{formatMissing}</span>;
          return <span style={mutedNum}>{y}</span>;
        },
      },
      {
        key: "portfolio_weight_pct",
        header: "Portfolio wt",
        numeric: true,
        sortable: true,
        width: 110,
        render: (r) => {
          const v = numeric(r.portfolio_weight_pct);
          // Honest missing-vs-real-zero: a null/absent weight is unknown
          // (em-dash), a real 0 is the baseline "no portfolio link" reading.
          if (v == null) {
            return (
              <span style={mutedNum} data-testid={`debt-portfolio-${r.country ?? r.name ?? "row"}`}>
                {formatMissing}
              </span>
            );
          }
          if (v === 0) {
            return (
              <span style={mutedNum} data-testid={`debt-portfolio-${r.country ?? r.name ?? "row"}`}>
                {fmtPct(0, 2)}
              </span>
            );
          }
          return (
            <span style={primaryNum} data-testid={`debt-portfolio-${r.country ?? r.name ?? "row"}`}>
              {fmtPct(v, 2)}
            </span>
          );
        },
      },
      {
        key: "change",
        header: "5Y Δ",
        numeric: true,
        sortable: true,
        width: 96,
        render: (r) => {
          const v = numeric(r.change ?? r.change_pct);
          if (v == null) return <span style={mutedNum}>—</span>;
          return <DeltaChip value={v} format="raw" fractionDigits={1} />;
        },
      },
    ];
    if (showTrend === "on") {
      base.push({
        key: "trend",
        header: "Trend",
        width: 92,
        render: (r) => {
          const series = trendForRow(r);
          if (series.length < 2) return <span style={mutedNum}>—</span>;
          const dir =
            series[series.length - 1] >= series[0] ? "negative" : "positive";
          return (
            <span className="u-inline-flex">
              <Sparkline values={series} width={72} height={20} tone={dir} />
            </span>
          );
        },
      });
    }
    return base;
  }, [showTrend]);

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Sovereign debt board"
          subtitle={`${rows.length} economies · ${region} · poll ${REFRESH_MS / 1000}s · ${dataMode}`}
          trailing={
            <FunctionControlGroup>
              <label style={toggleStyle}>
                <input
                  type="checkbox"
                  checked={showTrend === "on"}
                  onChange={(e) => setShowTrend(e.target.checked ? "on" : "off")}
                />
                Trend
              </label>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} ctry
              </Pill>
              <Pill tone="accent" variant="soft" withDot={false}>
                {utcStamp} UTC
              </Pill>
              <Pill
                tone={portfolioLinked ? "positive" : "muted"}
                variant="soft"
              >
                {portfolioLinked ? "portfolio linked" : "macro only"}
              </Pill>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : dataMode}
              </Pill>
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                busy={state === "loading" || state === "refreshing"}
                onClick={refetch}
              />
            </FunctionControlGroup>
          }
        />
        <div style={tabBarStyle}>
          <Tabs
            variant="segmented"
            ariaLabel="Bölge filtresi"
            items={REGIONS.map((r) => ({ id: r.id, label: r.label }))}
            active={region}
            onChange={(id) => setRegion(id as RegionId)}
          />
        </div>
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            // SCOPED live region: the pane polls, so only the loading / error /
            // empty transition may be aria-live — the steady-state board must
            // NOT be (else SRs re-announce the whole table every poll).
            <div role="status" aria-live="polite" aria-busy={state === "loading"}>
              <Skeleton height={320} />
            </div>
          ) : state === "error" ? (
            <div role="status" aria-live="polite">
              <Empty
                title="Function error"
                body={error?.message ?? "—"}
                icon="!"
              />
            </div>
          ) : allRows.length === 0 ? (
            <div role="status" aria-live="polite">
              <Empty
                title="No sovereign data"
                body="The debt provider returned no country rows."
              />
            </div>
          ) : (
            <div className="u-grid-gap-14">
              {/* PORTFOLIO honesty: when no portfolio is wired this board is a
                  macro overlay, NOT the operator's holdings. Make it
                  unmistakable so a row's "0.00%" weight is never misread. */}
              {!portfolioLinked ? (
                <section
                  data-testid="debt-portfolio-note"
                  style={macroNoteStyle}
                >
                  <strong className="u-text-secondary">Sadece makro</strong>
                  <span className="u-text-mute">
                    Portföy bağlı değil — bu tablo ülke bazında makro borç
                    görünümüdür, gerçek pozisyonlarınız değildir. Portföy ağırlığı
                    her satırda 0&apos;a sabitlenmiştir.
                  </span>
                </section>
              ) : null}

              {warnings.length ? (
                <section style={noticeStyle}>
                  <strong className="u-text-warn">Provider warnings</strong>
                  <ul style={warningListStyle}>
                    {warnings.slice(0, 3).map((w, i) => (
                      <li key={i} className="u-text-secondary">
                        {String(w)}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              <section style={kpiGridStyle} aria-label="DEBT KPI ribbon">
                <StatCard
                  label="Highest debt/GDP"
                  value={fmtPct(kpi.max)}
                  caption={kpi.maxCountry ?? "—"}
                  tone="negative"
                />
                <StatCard
                  label="Median"
                  value={fmtPct(kpi.median)}
                  caption={`${kpi.count} economies`}
                  tone="neutral"
                />
                <StatCard
                  label="Lowest debt/GDP"
                  value={fmtPct(kpi.min)}
                  caption={kpi.minCountry ?? "—"}
                  tone="positive"
                />
                <StatCard
                  label="Avg local ccy"
                  value={fmtPct(kpi.avgLocalShare, 0)}
                  caption="share issued in local ccy"
                  tone="neutral"
                />
              </section>

              {barRanking.length === 0 ? (
                <Empty
                  title="No matches"
                  body={`No economies in ${region}.`}
                />
              ) : (
                <section style={boardStyle} aria-label="Debt-to-GDP ranking">
                  <div style={legendRowStyle}>
                    <LegendDot
                      color="var(--positive)"
                      label="< 60%"
                      ariaLabel="Düşük borç/GSYİH: %60 altı"
                    />
                    <LegendDot
                      color="var(--accent)"
                      label="60–100%"
                      ariaLabel="Orta borç/GSYİH: %60–100"
                    />
                    <LegendDot
                      color="var(--negative)"
                      label="> 100%"
                      ariaLabel="Yüksek borç/GSYİH: %100 üstü"
                    />
                    <span style={legendScaleStyle}>
                      scaled to {scaleMax.toFixed(0)}%
                    </span>
                  </div>
                  <div style={barWrapStyle}>
                    {barRanking.map((r) => (
                      <DebtBar
                        key={r.country ?? r.name}
                        row={r}
                        scaleMax={scaleMax}
                      />
                    ))}
                  </div>
                </section>
              )}

              <DataGrid
                columns={cols}
                rows={rows}
                rowKey={(r, i) => `${r.country ?? r.name ?? "row"}-${i}`}
                density="compact"
                ariaLabel="Ülke bazında devlet borcu"
              />

              <p style={refFootnoteStyle}>
                <strong>Local ccy</strong> sütunu yayınlanmış bir{" "}
                <em>referans</em>tır, canlı World Bank serisi değildir.{" "}
                <strong>Veri yılı</strong> gözlem vintage&apos;ini gösterir —{" "}
                <code>as of</code> ise getirme zamanıdır.
              </p>

              {methodology ? (
                <section style={methodPanelStyle}>
                  <div style={metaLabelStyle}>Methodology</div>
                  <p style={methodTextStyle}>{methodology}</p>
                </section>
              ) : null}
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={sources} />
          <StatusDivider />
          <StatusSection
            label="mode"
            value={dataMode}
            tone={isLive ? "positive" : "neutral"}
          />
          <StatusDivider />
          <StatusSection label="as of" value={asOf} />
          <StatusDivider />
          <StatusSection label="rows" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="region" value={region} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/** Horizontal ranked bar: country label, severity-tinted fill, value + 5Y Δ. */
function DebtBar({ row, scaleMax }: { row: DebtRow; scaleMax: number }) {
  const v = numeric(row.debt_to_gdp) ?? 0;
  const pct = scaleMax > 0 ? Math.min(100, (v / scaleMax) * 100) : 0;
  const color = debtColor(v);
  const change = numeric(row.change ?? row.change_pct);
  const label = row.country ?? row.name ?? "—";
  const hasValue = numeric(row.debt_to_gdp) != null;
  // Bars convey magnitude via width + severity color only — expose the reading
  // to assistive tech so it is not a color/width-only datum. Lead with the ISO
  // code (plus the long name when present) so the value is unambiguous.
  const accName = row.name ? `${label} ${row.name}` : label;
  const ariaLabel = `${accName}: borç/GSYİH ${
    hasValue ? fmtPct(v) : formatMissing
  }${change != null ? `, 5Y Δ ${fmtPct(change)}` : ""}`;
  return (
    <div style={barRowStyle} role="img" aria-label={ariaLabel}>
      <div style={barLabelStyle} title={row.name ?? label}>
        {label}
      </div>
      <div style={barTrackStyle} aria-hidden>
        <div
          style={{
            ...barFillStyle,
            width: `${Math.max(2, pct)}%`,
            background: `linear-gradient(90deg, color-mix(in srgb, ${color} 55%, transparent), ${color})`,
          }}
        />
      </div>
      <div style={barValueStyle}>
        <span style={{ color, fontWeight: 700 }}>{fmtPct(v)}</span>
        {change != null ? (
          <span className="u-inline-flex">
            <DeltaChip value={change} format="raw" fractionDigits={1} />
          </span>
        ) : null}
      </div>
    </div>
  );
}

/** Inline mini-bar for the local-currency issuance share column. */
function LocalCcyBar({ value }: { value: number | null }) {
  if (value == null) return <span style={mutedNum}>—</span>;
  const pct = Math.max(0, Math.min(100, value));
  return (
    <span style={ccyWrapStyle}>
      <span style={ccyTrackStyle} aria-hidden>
        <span style={{ ...ccyFillStyle, width: `${pct}%` }} />
      </span>
      <span style={{ ...mutedNum, minWidth: 38, textAlign: "right" }}>
        {fmtPct(value, 0)}
      </span>
    </span>
  );
}

function LegendDot({
  color,
  label,
  ariaLabel,
}: {
  color: string;
  label: string;
  ariaLabel: string;
}) {
  // Severity is encoded by swatch color — expose its meaning to AT so the
  // legend is not a color-only key.
  return (
    <span style={legendDotStyle} role="img" aria-label={ariaLabel}>
      <span aria-hidden style={{ ...legendSwatchStyle, background: color }} />
      {label}
    </span>
  );
}

/* ------------------------------------------------------------------ *
 * Derivations + helpers
 * ------------------------------------------------------------------ */
interface DebtKpi {
  count: number;
  max: number | null;
  maxCountry: string | null;
  min: number | null;
  minCountry: string | null;
  median: number | null;
  avgLocalShare: number | null;
}

function deriveKpi(rows: DebtRow[], summary: DebtSummary): DebtKpi {
  const count = summary.countries ?? summary.count ?? rows.length;
  let max = numeric(summary.max);
  let min = numeric(summary.min);
  let maxCountry = summary.max_country ?? null;
  let minCountry = summary.min_country ?? null;
  let median = numeric(summary.median);

  const pairs = rows
    .map((r) => ({
      country: r.country ?? r.name ?? "—",
      v: numeric(r.debt_to_gdp),
    }))
    .filter((p): p is { country: string; v: number } => p.v != null);

  if (pairs.length) {
    if (max == null) {
      const top = pairs.reduce((a, b) => (b.v > a.v ? b : a));
      max = top.v;
      maxCountry = maxCountry ?? top.country;
    }
    if (min == null) {
      const bot = pairs.reduce((a, b) => (b.v < a.v ? b : a));
      min = bot.v;
      minCountry = minCountry ?? bot.country;
    }
    if (median == null) {
      const sorted = pairs.map((p) => p.v).sort((a, b) => a - b);
      const mid = Math.floor(sorted.length / 2);
      median =
        sorted.length % 2 === 0
          ? (sorted[mid - 1] + sorted[mid]) / 2
          : sorted[mid];
    }
  }

  const shares = rows
    .map((r) => localShare(r))
    .filter((v): v is number => v != null);
  const avgLocalShare = shares.length
    ? shares.reduce((a, b) => a + b, 0) / shares.length
    : null;

  return { count, max, maxCountry, min, minCountry, median, avgLocalShare };
}

function localShare(r: DebtRow): number | null {
  return numeric(r.local_currency_share ?? r.local_ccy_share);
}

/** Observation vintage (World Bank year) as a clean string, or "" if absent. */
function vintageYear(r: DebtRow): string {
  const y = r.year;
  if (y == null) return "";
  const s = String(y).trim();
  return s && s.toLowerCase() !== "nan" ? s : "";
}

function matchesRegion(r: DebtRow, region: RegionId): boolean {
  return (r.region ?? "").toLowerCase().includes(region);
}

/** Severity color ramp keyed to the debt-to-GDP reading. */
function debtColor(v: number): string {
  if (v >= 100) return "var(--negative)";
  if (v >= 60) return "var(--accent)";
  return "var(--positive)";
}

function trendForRow(r: DebtRow): number[] {
  if (Array.isArray(r.history) && r.history.length >= 2) return r.history.slice(-12);
  if (Array.isArray(r.trend) && r.trend.length >= 2) return r.trend.slice(-12);
  return [];
}

/**
 * Percent formatter delegating to the shared `format.ts`. The backend already
 * emits debt_to_gdp / local_currency_share / portfolio_weight_pct IN PERCENT
 * (0–100), so `fromFraction` stays false (the default) — multiplying would
 * render "12567%". Absent values fall back to the shared em-dash sentinel.
 */
function fmtPct(v: number | null | undefined, digits = 1): string {
  return formatPercent(v, { digits });
}

function numeric(v: unknown): number | null {
  if (v == null) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/* ------------------------------------------------------------------ *
 * Local styles (CSSProperties objects, theme-token driven).
 * ------------------------------------------------------------------ */
const tabBarStyle: CSSProperties = {
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 10,
};

const boardStyle: CSSProperties = {
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-2)",
  padding: 12,
  display: "grid",
  gap: 8,
};

const legendRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 16,
  fontSize: 11,
  color: "var(--text-secondary)",
};

const legendDotStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
};

const legendSwatchStyle: CSSProperties = {
  width: 9,
  height: 9,
  borderRadius: 2,
  display: "inline-block",
};

const legendScaleStyle: CSSProperties = {
  marginLeft: "auto",
  color: "var(--text-mute)",
  fontSize: 10,
  letterSpacing: "0.04em",
};

const barWrapStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 5,
};

const barRowStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "128px minmax(0, 1fr) 132px",
  alignItems: "center",
  gap: 10,
};

const barLabelStyle: CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: "var(--text-display)",
  fontFamily: "JetBrains Mono, monospace",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const barTrackStyle: CSSProperties = {
  height: 14,
  borderRadius: 3,
  background: "var(--surface-3)",
  overflow: "hidden",
  position: "relative",
};

const barFillStyle: CSSProperties = {
  height: "100%",
  borderRadius: 3,
  transition: "width var(--motion-base)",
};

const barValueStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "flex-end",
  gap: 8,
  fontVariantNumeric: "tabular-nums",
  fontSize: 12,
  fontFamily: "JetBrains Mono, monospace",
};

const countryCellStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  lineHeight: 1.15,
};

const isoStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontWeight: 600,
  color: "var(--text-display)",
};

const countryNameStyle: CSSProperties = {
  fontSize: 10,
  color: "var(--text-secondary)",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
  maxWidth: 130,
};

const primaryNum: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontWeight: 600,
  color: "var(--text-display)",
};

const mutedNum: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
  fontSize: 11,
};

const ccyWrapStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "flex-end",
  gap: 6,
  width: "100%",
};

const ccyTrackStyle: CSSProperties = {
  width: 56,
  height: 6,
  borderRadius: 999,
  background: "var(--surface-3)",
  overflow: "hidden",
};

const ccyFillStyle: CSSProperties = {
  height: "100%",
  borderRadius: 999,
  background: "var(--accent)",
  display: "block",
};

const toggleStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  fontSize: 11,
  color: "var(--text-secondary)",
};

const noticeStyle: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 30%, transparent)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
  display: "grid",
  gap: 4,
};

const warningListStyle: CSSProperties = {
  margin: 0,
  paddingLeft: 18,
  fontSize: "var(--font-size-xs)",
};

const macroNoteStyle: CSSProperties = {
  border: "1px solid var(--border-card)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
  display: "grid",
  gap: 3,
  fontSize: 12,
};

const refHeaderStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
};

const refBadgeStyle: CSSProperties = {
  fontSize: 9,
  fontWeight: 700,
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  padding: "1px 5px",
  borderRadius: 999,
  border: "1px solid color-mix(in srgb, var(--accent) 35%, transparent)",
  color: "var(--accent)",
  background: "color-mix(in srgb, var(--accent) 12%, transparent)",
};

const refFootnoteStyle: CSSProperties = {
  margin: 0,
  color: "var(--text-mute)",
  fontSize: 11,
  lineHeight: 1.5,
};

const methodPanelStyle: CSSProperties = {
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  padding: 12,
  background: "var(--surface-2)",
};

const metaLabelStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  marginBottom: 6,
};

const methodTextStyle: CSSProperties = {
  margin: 0,
  color: "var(--text-secondary)",
  lineHeight: 1.5,
  fontSize: 12,
};
