/**
 * ECFC — Economic forecasts.
 *
 * IMF/OECD-style multi-indicator multi-year forecast table for a given country.
 * Header SegmentedControl picks the country; KPI ribbon renders the backend's
 * `cards` array; DataGrid lists every (indicator, year) row with units and
 * source-mode chips. Growth/inflation indicators show their value as a delta
 * chip so the table reads as "policy-relevant deltas" not raw numbers.
 */
import { useMemo, type CSSProperties, type ReactNode } from "react";
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
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

const COUNTRIES = [
  { value: "USA", label: "USA" },
  { value: "EUR", label: "EUR" },
  { value: "GBR", label: "GBR" },
  { value: "TUR", label: "TUR" },
  { value: "CHN", label: "CHN" },
  { value: "JPN", label: "JPN" },
  { value: "BRA", label: "BRA" },
  { value: "IND", label: "IND" },
] as const;
const COUNTRY_IDS = COUNTRIES.map((c) => c.value);

// Indicators whose `forecast_value` should be read as a signed delta (growth %).
const DELTA_INDICATORS = new Set(["NGDP_RPCH", "PCPIPCH"]);

interface EcfcRow {
  country?: string;
  indicator?: string;
  metric?: string;
  year?: number | string;
  forecast_value?: number | string | null;
  unit?: string;
  source_mode?: string;
}

interface EcfcCard {
  label?: string;
  value?: number | string | null;
}

interface EcfcPayload {
  country?: string;
  rows?: EcfcRow[];
  series?: EcfcRow[];
  cards?: EcfcCard[];
  methodology?: string;
  field_dictionary?: Record<string, string>;
  source_mode?: string;
}

export function ECFCPane({ code }: FunctionPaneProps) {
  const [country, setCountry] = usePersistentOption(
    "showme.ecfc.country",
    COUNTRY_IDS,
    "USA",
  );

  const { state, data, error, refetch } = useFunction<EcfcPayload>({
    code,
    params: { country },
  });

  const payload = data?.data ?? {};
  const rows = useMemo<EcfcRow[]>(
    () => normalizeRows(payload.rows ?? payload.series),
    [payload.rows, payload.series],
  );
  const cards = useMemo<EcfcCard[]>(
    () => (Array.isArray(payload.cards) ? payload.cards : []),
    [payload.cards],
  );
  const sourceMode = payload.source_mode ?? data?.sources?.[0] ?? "—";

  const indicatorCount = useMemo(() => {
    const set = new Set<string>();
    for (const row of rows) {
      if (row.indicator) set.add(String(row.indicator));
    }
    return set.size;
  }, [rows]);

  const yearCount = useMemo(() => {
    const set = new Set<number>();
    for (const row of rows) {
      const y = toYear(row.year);
      if (y != null) set.add(y);
    }
    return set.size;
  }, [rows]);

  const isLive = state === "ok";

  const COLS: DataGridColumn<EcfcRow>[] = useMemo(
    () => [
      {
        key: "metric",
        header: "Indicator",
        render: (row) => (
          <span style={metricCellStyle}>
            <span style={metricNameStyle}>{row.metric ?? row.indicator ?? "—"}</span>
            {row.indicator && (
              <span style={metricCodeStyle}>{row.indicator}</span>
            )}
          </span>
        ),
      },
      {
        key: "indicator",
        header: "Series",
        width: 132,
        render: (row) => (
          <Pill tone="muted" variant="soft" withDot={false}>
            {row.indicator ?? "—"}
          </Pill>
        ),
      },
      {
        key: "year",
        header: "Year",
        width: 72,
        numeric: true,
        render: (row) => (
          <span style={yearCellStyle}>{toYear(row.year) ?? "—"}</span>
        ),
      },
      {
        key: "forecast_value",
        header: "Forecast",
        width: 128,
        numeric: true,
        render: (row) => <ForecastCell row={row} />,
      },
      {
        key: "source_mode",
        header: "Source",
        width: 168,
        render: (row) => (
          <Pill
            tone={row.source_mode === "imf_oecd" ? "positive" : "muted"}
            variant="soft"
            withDot={false}
          >
            {row.source_mode ?? "—"}
          </Pill>
        ),
      },
    ],
    [],
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Economic forecasts"
          subtitle={`${country} · ${indicatorCount || rows.length} indicator${indicatorCount === 1 ? "" : "s"} · ${yearCount || 0} year${yearCount === 1 ? "" : "s"}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {indicatorCount} ind
              </Pill>
              <Pill
                tone={sourceMode === "imf_oecd" ? "positive" : "muted"}
                variant="soft"
                withDot={false}
              >
                {sourceMode}
              </Pill>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : state}
              </Pill>
              <SegmentedControl
                label="COUNTRY"
                value={country}
                options={COUNTRIES}
                onChange={setCountry}
              />
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh forecasts"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <div className="u-grid-gap-12">
              <Skeleton height={88} />
              <Skeleton height={240} />
            </div>
          ) : state === "error" ? (
            <Empty
              title="Forecast load failed"
              body={error?.message ?? "—"}
              icon="!"
              action={
                <button onClick={refetch} className="btn btn--accent">
                  Retry
                </button>
              }
            />
          ) : rows.length === 0 ? (
            <Empty
              title="No forecast rows"
              body={`No forecast data for ${country} in the current view.`}
              action={
                <button onClick={refetch} className="btn">
                  Refresh
                </button>
              }
            />
          ) : (
            <div className="u-grid-gap-14">
              <KPIRibbon cards={cards} country={country} />
              <DataGrid
                columns={COLS}
                rows={rows}
                rowKey={(row, i) =>
                  `${row.country ?? ""}-${row.indicator ?? ""}-${row.year ?? ""}-${i}`
                }
                density="compact"
              />
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || sourceMode}
          />
          <StatusDivider />
          <StatusSection label="country" value={country} tone="accent" />
          <StatusDivider />
          <StatusSection label="rows" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function KPIRibbon({
  cards,
  country,
}: {
  cards: EcfcCard[];
  country: string;
}) {
  if (cards.length === 0) {
    return (
      <section style={kpiGridStyle} aria-label="ECFC KPI ribbon">
        <StatCard
          label="Country"
          value={country}
          caption="NO CARDS RETURNED"
          tone="neutral"
        />
      </section>
    );
  }
  return (
    <section style={kpiGridStyle} aria-label="ECFC KPI ribbon">
      {cards.map((card, i) => {
        const n = numeric(card.value);
        const tone: "positive" | "negative" | "neutral" =
          n == null ? "neutral" : n >= 0 ? "positive" : "negative";
        return (
          <StatCard
            key={`${card.label ?? "card"}-${i}`}
            label={card.label ?? "—"}
            value={
              n == null
                ? card.value == null
                  ? "—"
                  : String(card.value)
                : `${n >= 0 ? "+" : ""}${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
            }
            caption={country}
            tone={tone}
          />
        );
      })}
    </section>
  );
}

function ForecastCell({ row }: { row: EcfcRow }): ReactNode {
  const n = numeric(row.forecast_value);
  if (n == null) {
    return <span style={primaryNumStyle}>—</span>;
  }
  if (row.indicator && DELTA_INDICATORS.has(row.indicator)) {
    return (
      <span style={deltaCellStyle}>
        <DeltaChip value={n} format="raw" fractionDigits={2} />
        {row.unit && <span style={unitStyle}>{row.unit}</span>}
      </span>
    );
  }
  return (
    <span style={primaryNumStyle}>
      {n.toLocaleString(undefined, { maximumFractionDigits: 2 })}
      {row.unit ? <span style={unitStyle}> {row.unit}</span> : null}
    </span>
  );
}

function normalizeRows(payload: unknown): EcfcRow[] {
  if (Array.isArray(payload)) {
    return payload.filter((item): item is EcfcRow => typeof item === "object" && item !== null);
  }
  return [];
}

function toYear(value: number | string | undefined): number | null {
  if (value == null) return null;
  if (typeof value === "number" && Number.isFinite(value)) return Math.trunc(value);
  const n = Number(String(value).slice(0, 4));
  return Number.isFinite(n) ? n : null;
}

function numeric(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string") {
    const n = Number(value.replace(/[%,]/g, ""));
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 10,
};

const metricCellStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
  minWidth: 0,
};

const metricNameStyle: CSSProperties = {
  color: "var(--text-primary)",
  fontWeight: 500,
};

const metricCodeStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-mute)",
  letterSpacing: "0.04em",
};

const yearCellStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
  fontWeight: 500,
};

const primaryNumStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
  display: "inline-flex",
  alignItems: "baseline",
  gap: 4,
};

const deltaCellStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
};

const unitStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-mute)",
};
