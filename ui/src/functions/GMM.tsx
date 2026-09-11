/**
 * GMM — Global Macro Matrix.
 *
 * Live cross-country macro-stress matrix from the keyless World Bank
 * open-data API (see backend/showme/engine/functions/macro/gmm.py).
 * One row per economy, one column per indicator (GDP growth, CPI
 * inflation, unemployment, debt/GDP) plus the backend's composite
 * macro-stress score. Cells carry an honest tone tint: hot inflation /
 * unemployment / debt shade negative, strong growth shades positive.
 * Each cell shows its own observation year — World Bank annual series
 * are lagged, so cells legitimately disagree on year. Missing cells
 * stay "—", never fabricated.
 */
import { useMemo, type CSSProperties } from "react";
import {
  Empty,
  intensityToken,
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

interface GMMCard {
  key?: string;
  label?: string;
  value?: string | number | null;
}

interface GMMRow {
  country?: string;
  country_code?: string;
  gdp_growth?: number | null;
  gdp_growth_year?: number | null;
  inflation?: number | null;
  inflation_year?: number | null;
  unemployment?: number | null;
  unemployment_year?: number | null;
  debt_gdp?: number | null;
  debt_gdp_year?: number | null;
  score?: number | null;
}

interface GMMData {
  status?: string;
  reason?: string;
  rows?: GMMRow[];
  cards?: GMMCard[];
  methodology?: string;
  next_actions?: string[];
  source_mode?: string;
}

type Universe = "ALL" | "G7" | "EM";

const UNIVERSE_OPTIONS = [
  { value: "ALL" as Universe, label: "ALL", title: "Universe: major economies" },
  { value: "G7" as Universe, label: "G7", title: "Universe: G7" },
  { value: "EM" as Universe, label: "EM", title: "Universe: EM majors" },
] as const;
const UNIVERSE_IDS = UNIVERSE_OPTIONS.map((o) => o.value);

// Country code lists sent as the `countries` param. ALL omits the param so
// the backend default (its curated major-economy set) stays the source of
// truth; G7/EM are subsets of codes the World Bank API resolves directly.
const UNIVERSE_COUNTRIES: Record<Exclude<Universe, "ALL">, string[]> = {
  G7: ["US", "GB", "FR", "DE", "IT", "JP", "CA"],
  EM: ["CN", "IN", "BR", "MX", "TR"],
};

export function GMMPane({ code }: FunctionPaneProps) {
  const [universe, setUniverse] = usePersistentOption<Universe>(
    "showme.gmm.universe",
    UNIVERSE_IDS,
    "ALL",
  );
  const params = useMemo<Record<string, unknown>>(() => {
    if (universe === "ALL") return {};
    return { countries: UNIVERSE_COUNTRIES[universe] };
  }, [universe]);
  const { state, data, error, refetch } = useFunction<GMMData>({ code, params });

  const payload = data?.data;
  const rows: GMMRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";
  const isOk = state === "ok" && status === "ok";

  const hottest = payload?.cards?.find((c) => c.key === "hottest_inflation");
  const fastest = payload?.cards?.find((c) => c.key === "fastest_growth");

  const body = state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={56} />
      <Skeleton height={20} />
      <Skeleton height={20} />
      <Skeleton height={20} width="80%" />
    </div>
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
  ) : status === "provider_unavailable" ? (
    <Empty
      title="World Bank unavailable"
      body={
        payload?.reason ??
        payload?.next_actions?.[0] ??
        "The World Bank fetch failed on this run."
      }
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : rows.length === 0 ? (
    <Empty
      title="No macro rows"
      body="The World Bank returned no observations for this universe."
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="GMM summary cards">
        <StatCard
          label="Economies"
          value={String(rows.length)}
          caption="WORLD BANK OPEN DATA"
          tone="neutral"
        />
        <StatCard
          label="Hottest CPI"
          value={cardValue(hottest)}
          caption="HIGHEST INFLATION"
          tone="negative"
        />
        <StatCard
          label="Fastest GDP"
          value={cardValue(fastest)}
          caption="HIGHEST GROWTH"
          tone="positive"
        />
        <StatCard
          label="Source"
          value="World Bank"
          caption="KEYLESS OPEN DATA"
          tone="neutral"
        />
      </section>
      <div style={tableScrollStyle}>
        <table className="gmm-matrix" style={tableStyle} aria-label="Global macro stress matrix">
          <thead>
            <tr>
              <th style={thStyle} scope="col">Economy</th>
              <th style={{ ...thStyle, ...thNumericStyle }} scope="col">Stress score</th>
              <th style={{ ...thStyle, ...thNumericStyle }} scope="col">GDP growth</th>
              <th style={{ ...thStyle, ...thNumericStyle }} scope="col">CPI inflation</th>
              <th style={{ ...thStyle, ...thNumericStyle }} scope="col">Unemployment</th>
              <th style={{ ...thStyle, ...thNumericStyle }} scope="col">Debt / GDP</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.country_code ?? row.country ?? ""}>
                <td style={tdCountryStyle}>
                  <span style={monoStrongStyle}>{row.country ?? "—"}</span>
                  <span style={ccStyle}>{row.country_code ?? ""}</span>
                </td>
                <MetricCell
                  metric="score"
                  value={row.score}
                  year={null}
                  format={(v) => v.toFixed(1)}
                />
                <MetricCell
                  metric="gdp_growth"
                  value={row.gdp_growth}
                  year={row.gdp_growth_year ?? null}
                  format={(v) => `${v.toFixed(1)}%`}
                  goodWhenPositive
                />
                <MetricCell
                  metric="inflation"
                  value={row.inflation}
                  year={row.inflation_year ?? null}
                  format={(v) => `${v.toFixed(1)}%`}
                />
                <MetricCell
                  metric="unemployment"
                  value={row.unemployment}
                  year={row.unemployment_year ?? null}
                  format={(v) => `${v.toFixed(1)}%`}
                />
                <MetricCell
                  metric="debt_gdp"
                  value={row.debt_gdp}
                  year={row.debt_gdp_year ?? null}
                  format={(v) => `${v.toFixed(0)}%`}
                />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p style={noteStyle} aria-label="Tone legend">
        <Pill tone="negative" variant="soft" withDot={false}>hot</Pill>
        <span> higher inflation, unemployment, debt, or stress score — </span>
        <Pill tone="positive" variant="soft" withDot={false}>strong</Pill>
        <span> faster growth. Each cell shows its own observation year; missing cells are left blank, never estimated.</span>
      </p>
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Global Macro Matrix"
          subtitle={`World Bank macro stress · ${rows.length} economies · ${universe}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={isOk ? "positive" : "warn"} variant="soft">
                {isOk ? "worldbank" : status}
              </Pill>
              <SegmentedControl
                label="UNIVERSE"
                title="Country universe"
                value={universe}
                options={UNIVERSE_OPTIONS}
                onChange={setUniverse}
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh macro matrix"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="economies" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="universe" value={universe} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/**
 * One matrix cell. Tone tint direction:
 *  - score / inflation / unemployment / debt: higher = more stressed (neg ramp);
 *  - gdp_growth: higher = healthier (pos ramp, negatives shade neg).
 * Ranges pick sensible pivot points so a typical major-economy value lands
 * mid-ramp and an extreme (TR 35% CPI) saturates.
 */
const CELL_RANGES: Record<string, number> = {
  score: 60,
  gdp_growth: 6,
  inflation: 12,
  unemployment: 14,
  debt_gdp: 240,
};

function MetricCell({
  metric,
  value,
  year,
  format,
  goodWhenPositive = false,
}: {
  metric: string;
  value: number | null | undefined;
  year: number | null;
  format: (v: number) => string;
  goodWhenPositive?: boolean;
}) {
  if (value == null || !Number.isFinite(value)) {
    return (
      <td style={tdCellStyle} aria-label="no World Bank observation">
        <span style={monoMutedStyle}>—</span>
      </td>
    );
  }
  const range = CELL_RANGES[metric] ?? 1;
  const signed = goodWhenPositive ? value : -value;
  const bg = intensityToken(signed, range);
  return (
    <td style={{ ...tdCellStyle, background: bg }}>
      <span style={monoPrimaryStyle}>{format(value)}</span>
      {year != null ? <span style={yearStyle}>{year}</span> : null}
    </td>
  );
}

function cardValue(card?: GMMCard): string {
  if (!card || card.value == null) return "—";
  return String(card.value);
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
  gap: 10,
};

const tableScrollStyle: CSSProperties = { overflowX: "auto" };

const tableStyle: CSSProperties = {
  borderCollapse: "collapse",
  width: "100%",
  fontSize: "var(--font-size-md)",
};

const thStyle: CSSProperties = {
  textAlign: "left",
  padding: "4px 8px",
  borderBottom: "1px solid var(--border-row)",
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  whiteSpace: "nowrap",
};

const thNumericStyle: CSSProperties = { textAlign: "right" };

const tdCellStyle: CSSProperties = {
  padding: "4px 8px",
  borderBottom: "1px solid var(--border-row)",
  textAlign: "right",
  whiteSpace: "nowrap",
};

const tdCountryStyle: CSSProperties = {
  padding: "4px 8px",
  borderBottom: "1px solid var(--border-row)",
  display: "flex",
  alignItems: "baseline",
  gap: 6,
  whiteSpace: "nowrap",
};

const ccStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  color: "var(--text-mute)",
};

const yearStyle: CSSProperties = {
  marginLeft: 6,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  color: "var(--text-mute)",
};

const noteStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
  margin: 0,
  color: "var(--text-mute)",
  fontSize: "var(--font-size-sm)",
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const monoPrimaryStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
};

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-mute)",
};
