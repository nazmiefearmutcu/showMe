/**
 * SRSK — Sovereign Risk.
 *
 * Ranked cross-country sovereign-risk table from keyless World Bank
 * fundamentals (backend composes a 0-100 macro risk score, a CDS-proxy
 * spread and a Hull 1Y default probability). Header: universe segmented
 * control (Core 4 / Wide 12, persisted) + status pill + refresh.
 * Body: KPI ribbon (highest-risk sovereign, ranked count, recovery,
 * as-of) + table ranked worst-first with risk-band tone tints. The table
 * is capped at the 10 riskiest rows with an honest showing-note; any
 * country whose World Bank legs all failed is kept, unranked, at the
 * bottom with its fallback caveat.
 */
import { useMemo, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
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
import { formatNumberFixed } from "@/lib/format";
import { useFunction } from "@/lib/useFunction";
import {
  buildGridCsv,
  downloadGridCsv,
  gridCsvFilename,
  type GridCsvColumn,
} from "@/design-system/grid-csv";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface SRSKRow {
  country?: string;
  debt_to_gdp?: number | null;
  reserves_months?: number | null;
  current_account_gdp?: number | null;
  inflation_pct?: number | null;
  risk_score?: number | null;
  proxy_spread_pct?: number | null;
  pd_1y_pct?: number | null;
  recovery?: number | null;
  source_mode?: string;
  as_of?: string | null;
  note?: string | null;
  legs_present?: number | null;
  legs_total?: number | null;
}

interface SRSKCards {
  highest_pd_country?: string | null;
  highest_pd?: number | null;
  recovery?: number | null;
  data_mode?: string;
  as_of?: string | null;
}

interface SRSKData {
  status?: string;
  reason?: string;
  rows?: SRSKRow[];
  cards?: SRSKCards;
  data_mode?: string;
  summary?: {
    countries?: number;
    recovery?: number;
    formula?: string;
    worldbank_countries?: number;
    unscored_countries?: number;
    highest_risk_country?: string | null;
  };
  methodology?: string;
  field_dictionary?: Record<string, unknown>;
}

const CORE_UNIVERSE = ["TR", "US", "DE", "JP"] as const;
const WIDE_UNIVERSE = [
  "US",
  "DE",
  "JP",
  "GB",
  "FR",
  "IT",
  "ES",
  "TR",
  "BR",
  "MX",
  "IN",
  "CN",
] as const;

const UNIVERSE_OPTIONS = [
  { value: "core", label: "Core 4", title: "Universe Core 4" },
  { value: "wide", label: "Wide 12", title: "Universe Wide 12" },
] as const;

type UniverseId = (typeof UNIVERSE_OPTIONS)[number]["value"];
const UNIVERSE_IDS = UNIVERSE_OPTIONS.map((o) => o.value);

const MAX_SHOWN = 10;

export function SRSKPane({ code }: FunctionPaneProps) {
  const [universe, setUniverse] = usePersistentOption<UniverseId>(
    "showme.srsk.universe",
    UNIVERSE_IDS,
    "core",
  );
  const countries = universe === "wide" ? WIDE_UNIVERSE : CORE_UNIVERSE;
  const { state, data, error, refetch } = useFunction<SRSKData>({
    code,
    params: { countries: [...countries] },
  });

  const payload = data?.data;
  const warnings = data?.warnings ?? [];
  const ranked = useMemo(() => rankRows(payload?.rows ?? []), [payload]);
  const shown = ranked.slice(0, MAX_SHOWN);
  const isLive = state === "ok" && payload?.data_mode === "live_official";

  const stats = useMemo(
    () => deriveStats(ranked, payload?.cards),
    [ranked, payload],
  );

  // CSV export reaches the FULL ranked set (the table caps at MAX_SHOWN,
  // the file does not) — ranks are applied to every scored row.
  const csvColumns = useMemo<GridCsvColumn<RankedRow>[]>(
    () => [
      {
        key: "rank",
        header: "Rank",
        value: (r) => r.__rank ?? "",
      },
      { key: "country", header: "Country", value: (r) => r.country ?? "" },
      { key: "risk_score", header: "Risk score", value: (r) => r.risk_score ?? "" },
      {
        key: "proxy_spread_pct",
        header: "CDS-proxy %",
        value: (r) => r.proxy_spread_pct ?? "",
      },
      { key: "pd_1y_pct", header: "1Y PD %", value: (r) => r.pd_1y_pct ?? "" },
      {
        key: "debt_to_gdp",
        header: "Debt/GDP %",
        value: (r) => r.debt_to_gdp ?? "",
      },
      {
        key: "reserves_months",
        header: "Reserves months",
        value: (r) => r.reserves_months ?? "",
      },
      {
        key: "current_account_gdp",
        header: "CA %GDP",
        value: (r) => r.current_account_gdp ?? "",
      },
      {
        key: "inflation_pct",
        header: "CPI %",
        value: (r) => r.inflation_pct ?? "",
      },
      { key: "recovery", header: "Recovery", value: (r) => r.recovery ?? "" },
      { key: "as_of", header: "As of", value: (r) => r.as_of ?? "" },
      {
        key: "source_mode",
        header: "Source",
        value: (r) => r.source_mode ?? "",
      },
      { key: "note", header: "Note", value: (r) => r.note ?? "" },
      { key: "legs", header: "Legs", value: (r) => legsLabel(r) ?? "" },
    ],
    [],
  );

  const exportCsv = () => {
    const csv = buildGridCsv(csvColumns, withRanks(ranked));
    downloadGridCsv(gridCsvFilename(`srsk-${universe}`), csv);
  };

  const COLS: DataGridColumn<RankedRow>[] = useMemo(
    () => [
      {
        key: "rank",
        header: "#",
        width: 44,
        render: (r) => (
          <span style={monoMutedStyle}>
            {r.risk_score == null || isPartial(r) ? "—" : String(r.__rank ?? "")}
          </span>
        ),
      },
      {
        key: "country",
        header: "Country",
        width: 96,
        render: (r) => (
          <span style={monoStrongStyle} title={r.note ?? undefined}>
            {r.country ?? "—"}
          </span>
        ),
      },
      {
        key: "risk_score",
        header: "Score 0-100",
        numeric: true,
        width: 118,
        render: (r) => (
          <span
            style={{
              ...monoStrongStyle,
              color: scoreColor(r.risk_score),
            }}
          >
            {fmtNum(r.risk_score, 1)}
          </span>
        ),
      },
      {
        key: "proxy_spread_pct",
        header: "CDS-proxy %",
        numeric: true,
        width: 122,
        render: (r) => (
          <span style={monoPrimaryStyle}>{fmtNum(r.proxy_spread_pct, 2)}</span>
        ),
      },
      {
        key: "pd_1y_pct",
        header: "1Y PD %",
        numeric: true,
        width: 104,
        render: (r) => (
          <span
            style={{
              ...monoStrongStyle,
              color: pdColor(r.pd_1y_pct),
            }}
          >
            {fmtNum(r.pd_1y_pct, 2)}
          </span>
        ),
      },
      {
        key: "debt_to_gdp",
        header: "Debt/GDP %",
        numeric: true,
        width: 118,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtNum(r.debt_to_gdp, 1)}</span>
        ),
      },
      {
        key: "reserves_months",
        header: "Reserves mo",
        numeric: true,
        width: 116,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtNum(r.reserves_months, 2)}</span>
        ),
      },
      {
        key: "current_account_gdp",
        header: "CA %GDP",
        numeric: true,
        width: 104,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtNum(r.current_account_gdp, 2)}</span>
        ),
      },
      {
        key: "inflation_pct",
        header: "CPI %",
        numeric: true,
        width: 92,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtNum(r.inflation_pct, 2)}</span>
        ),
      },
      {
        key: "as_of",
        header: "As of",
        width: 84,
        render: (r) => (
          <span style={monoMutedStyle}>{r.as_of ?? "—"}</span>
        ),
      },
      {
        key: "legs",
        header: "Legs",
        width: 64,
        render: (r) => {
          const label = legsLabel(r);
          if (label == null) return <span className="u-text-mute">—</span>;
          return (
            <span
              style={{
                ...monoMutedStyle,
                color: isPartial(r) ? "var(--warning, var(--text-mute))" : monoMutedStyle.color,
              }}
              title={isPartial(r) ? "Partial composite: fewer than all macro legs returned data" : undefined}
            >
              {label}
            </span>
          );
        },
      },
      {
        key: "source_mode",
        header: "Source",
        width: 180,
        render: (r) =>
          r.source_mode ? (
            <span style={unscoredCellStyle}>
              <Pill
                tone={
                  r.source_mode === "worldbank" ||
                  r.source_mode.startsWith("fred")
                    ? "accent"
                    : "muted"
                }
                variant="soft"
                withDot={false}
              >
                {r.source_mode}
              </Pill>
              {typeof r.risk_score !== "number" && r.note ? (
                <span style={unscoredNoteStyle}>{r.note}</span>
              ) : null}
            </span>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
    ],
    [],
  );

  const warningBanner =
    warnings.length > 0 ? (
      <div role="status" style={warningStyle} aria-label="Data quality warning">
        {warnings.join(" · ")}
      </div>
    ) : null;

  const body =
    state === "loading" || state === "idle" ? (
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
    ) : ranked.length === 0 ? (
      <div className="u-grid-gap-14">
        {warningBanner}
        <Empty
          title={
            payload?.status === "provider_unavailable"
              ? "Sovereign data unavailable"
              : "No sovereign rows returned"
          }
          body={
            payload?.reason ??
            "World Bank returned no fundamentals and no FRED key is configured."
          }
          icon="∅"
          action={
            <button onClick={refetch} className="btn">
              Retry
            </button>
          }
        />
      </div>
    ) : (
      <div className="u-grid-gap-14">
        {warningBanner}
        <section style={kpiGridStyle} aria-label="SRSK KPI ribbon">
          <StatCard
            label="Highest risk"
            value={stats.worstCountry ?? "—"}
            caption={`1Y PD ${fmtNum(stats.worstPd, 2)}%`}
            tone="negative"
          />
          <StatCard
            label="Ranked countries"
            value={String(stats.rankedCount)}
            caption={`${stats.totalCount} requested · ${stats.unscoredCount} unscored${
              stats.partialCount > 0 ? ` · ${stats.partialCount} partial legs` : ""
            }`}
            tone="neutral"
          />
          <StatCard
            label="Recovery"
            value={stats.recovery != null ? `${Math.round(stats.recovery * 100)}%` : "—"}
            caption="HULL PD ASSUMPTION"
            tone="neutral"
          />
          <StatCard
            label="Data as of"
            value={stats.asOf ?? "—"}
            caption={payload?.data_mode ?? "—"}
            tone={isLive ? "positive" : "neutral"}
          />
        </section>
        {ranked.length > shown.length ? (
          <div role="note" style={capNoteStyle}>
            Showing the {shown.length} riskiest of {ranked.length} countries
            (ranked worst-first) — the table is capped at {MAX_SHOWN} rows.
          </div>
        ) : null}
        <DataGrid
          columns={COLS}
          rows={withRanks(shown)}
          rowKey={(r, i) => `${r.country ?? "unranked"}-${i}`}
          density="compact"
          ariaLabel="SRSK ranked sovereign risk table"
        />
        <div style={methodologyStyle}>{payload?.summary?.formula ?? ""}</div>
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Sovereign Risk"
          subtitle={`${payload?.data_mode ?? "—"} · ${ranked.length} countries`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live worldbank" : payload?.data_mode ?? "—"}
              </Pill>
              <SegmentedControl
                label="UNIVERSE"
                value={universe}
                options={UNIVERSE_OPTIONS}
                onChange={setUniverse}
              />
              <button
                type="button"
                className="btn"
                onClick={exportCsv}
                disabled={ranked.length === 0}
                title="Download CSV"
                aria-label={`Download ${ranked.length} sovereign rows as CSV`}
              >
                CSV
              </button>
              <LoadStatePill state={state} status={payload?.status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh sovereign risk"
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
          <StatusSection label="status" value={payload?.status ?? "—"} />
          <StatusDivider />
          <StatusSection label="ranked" value={ranked.length} />
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

/* ── helpers ───────────────────────────────────────────────────────── */

interface RankedRow extends SRSKRow {
  __rank?: number;
}

/** A composite built from fewer than all macro legs is not comparable with a full one. */
function isPartial(r: SRSKRow): boolean {
  return (
    typeof r.legs_present === "number" &&
    typeof r.legs_total === "number" &&
    r.legs_present < r.legs_total
  );
}

function legsLabel(r: SRSKRow): string | null {
  if (typeof r.legs_present !== "number" || typeof r.legs_total !== "number") return null;
  return `${r.legs_present}/${r.legs_total}`;
}

/**
 * Worst-first by risk_score among full-coverage rows, then partial-coverage
 * rows (shown, never ranked against full ones), then rows without a score.
 */
function rankRows(rows: SRSKRow[]): RankedRow[] {
  const byScoreDesc = (a: SRSKRow, b: SRSKRow) =>
    (b.risk_score ?? 0) - (a.risk_score ?? 0);
  const scored = rows.filter((r) => typeof r.risk_score === "number");
  const full = scored.filter((r) => !isPartial(r)).sort(byScoreDesc);
  const partial = scored.filter((r) => isPartial(r)).sort(byScoreDesc);
  const unscored = rows.filter((r) => typeof r.risk_score !== "number");
  return [...full, ...partial, ...unscored];
}

function withRanks(rows: RankedRow[]): RankedRow[] {
  let rank = 0;
  return rows.map((r) =>
    typeof r.risk_score === "number" && !isPartial(r) ? { ...r, __rank: ++rank } : r,
  );
}

function deriveStats(rows: RankedRow[], cards?: SRSKCards) {
  // The backend's card is the highest PD, which can differ from the top
  // composite score once FRED spreads refine PD; prefer it over the table order.
  const worst = rows.find((r) => typeof r.risk_score === "number" && !isPartial(r));
  return {
    worstCountry: cards?.highest_pd_country ?? worst?.country ?? null,
    worstPd: cards?.highest_pd ?? worst?.pd_1y_pct ?? null,
    rankedCount: rows.filter((r) => typeof r.risk_score === "number" && !isPartial(r)).length,
    totalCount: rows.length,
    // Rows with no risk score stay unranked, even when a FRED differential prices them.
    unscoredCount: rows.filter((r) => typeof r.risk_score !== "number").length,
    // Partial composites (fewer than all four legs) are shown but not ranked.
    partialCount: rows.filter((r) => typeof r.risk_score === "number" && isPartial(r)).length,
    recovery: cards?.recovery ?? rows[0]?.recovery ?? null,
    asOf: cards?.as_of ?? rows.find((r) => r.as_of)?.as_of ?? null,
  };
}

/** Risk-band tint: hot sovereigns red, calm ones green, middle neutral. */
function scoreColor(score: number | null | undefined): string {
  if (score == null || !Number.isFinite(score)) return "var(--text-mute)";
  if (score >= 65) return "var(--negative)";
  if (score < 40) return "var(--positive)";
  return "var(--text-primary)";
}

function pdColor(pd: number | null | undefined): string {
  if (pd == null || !Number.isFinite(pd)) return "var(--text-mute)";
  if (pd >= 10) return "var(--negative)";
  if (pd < 2) return "var(--positive)";
  return "var(--text-primary)";
}

function fmtNum(v: unknown, digits: number): string {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  return formatNumberFixed(n, digits);
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const capNoteStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  letterSpacing: "0.04em",
};

const methodologyStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
};

const warningStyle: CSSProperties = {
  border: "1px solid var(--warning, var(--text-mute))",
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-sm)",
  padding: "6px 8px",
  fontFamily: "JetBrains Mono, monospace",
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
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
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
};

const unscoredCellStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "flex-start",
  gap: 4,
};

// The visible reason an unscored country has no spread or PD.
const unscoredNoteStyle: CSSProperties = {
  ...monoMutedStyle,
  fontSize: "var(--font-size-2xs)",
  whiteSpace: "normal",
};
