/**
 * BTMM — central-bank policy-rate monitor.
 *
 * Dedicated native pane for the BIS CBPOL-backed policy-rate matrix. This is
 * intentionally not symbol-driven; it monitors country/rate environment.
 */
import { useMemo, useState } from "react";
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

interface BTMMRow {
  country_code?: string;
  bis_ref_area?: string;
  country?: string;
  central_bank?: string;
  currency?: string;
  region?: string;
  policy_rate?: number;
  as_of?: string;
  previous_rate?: number | null;
  previous_date?: string | null;
  change_bp?: number | null;
  last_move?: "hike" | "cut" | "hold" | string;
  trend_3m_bp?: number | null;
  history?: Array<{ date?: string; policy_rate?: number; country_code?: string }>;
  source?: string;
}

interface BTMMSummary {
  rows?: number;
  universe?: number;
  average_policy_rate?: number | null;
  max_policy_rate?: number | null;
  min_policy_rate?: number | null;
  hikes?: number;
  cuts?: number;
  holds?: number;
  largest_last_move?: BTMMRow | null;
}

interface BTMMPayload {
  country?: string;
  region?: string;
  rows: BTMMRow[];
  summary?: BTMMSummary;
}

const COUNTRIES = [
  { value: "ALL", label: "All" },
  { value: "US", label: "US" },
  { value: "EU", label: "EU" },
  { value: "GB", label: "UK" },
  { value: "JP", label: "JP" },
  { value: "TR", label: "TR" },
] as const;
type CountryId = (typeof COUNTRIES)[number]["value"];
const COUNTRY_IDS = COUNTRIES.map((c) => c.value) as CountryId[];

const REGIONS = [
  { value: "all", label: "All" },
  { value: "g10", label: "G10" },
  { value: "em", label: "EM" },
  { value: "americas", label: "Americas" },
  { value: "europe", label: "Europe" },
  { value: "asia_pacific", label: "APAC" },
  { value: "mea", label: "MEA" },
] as const;
type RegionId = (typeof REGIONS)[number]["value"];
const REGION_IDS = REGIONS.map((r) => r.value) as RegionId[];

const COLS: DataGridColumn<BTMMRow>[] = [
  {
    key: "country",
    header: "Country",
    width: 160,
    render: (row) => (
      <span>
        <strong style={{ color: "var(--accent)" }}>{row.country_code ?? "—"}</strong>
        <span style={{ color: "var(--text-secondary)" }}>
          {" "}
          {row.country ?? row.bis_ref_area ?? "—"}
        </span>
      </span>
    ),
  },
  {
    key: "central_bank",
    header: "Central bank",
    width: 230,
    render: (row) => row.central_bank ?? "—",
  },
  {
    key: "currency",
    header: "Ccy",
    width: 60,
    render: (row) => row.currency ?? "—",
  },
  {
    key: "policy_rate",
    header: "Rate",
    numeric: true,
    width: 90,
    render: (row) => fmtPct(row.policy_rate),
  },
  {
    key: "change_bp",
    header: "Last move",
    numeric: true,
    width: 112,
    render: (row) => (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        {movePill(row.last_move)}
        {row.change_bp == null ? "—" : <ChangeText value={row.change_bp} digits={0} />}
      </span>
    ),
  },
  {
    key: "trend_3m_bp",
    header: "3M bp",
    numeric: true,
    width: 84,
    render: (row) =>
      row.trend_3m_bp == null ? "—" : <ChangeText value={row.trend_3m_bp} digits={0} />,
  },
  {
    key: "as_of",
    header: "As of",
    width: 96,
    render: (row) => row.as_of ?? "—",
  },
  {
    key: "source",
    header: "Source",
    width: 100,
    render: (row) => row.source ?? "—",
  },
];

export function BTMMPane({ code }: FunctionPaneProps) {
  const [country, setCountry] = usePersistentOption<CountryId>(
    "showme.btmm-country",
    COUNTRY_IDS,
    "ALL",
  );
  const [region, setRegion] = usePersistentOption<RegionId>(
    "showme.btmm-region",
    REGION_IDS,
    "all",
  );

  const { state, data, error, refetch } = useFunction<BTMMPayload>({
    code,
    params: { country, region, limit: 80 },
  });
  const payload = useMemo(() => normalizePayload(data?.data), [data]);
  const rawRows = payload.rows;
  const [search, setSearch] = useState("");
  const rows = useMemo(() => filterRows(rawRows, search), [rawRows, search]);
  const summary = payload.summary;
  const largestMove = summary?.largest_last_move;
  const chartRow = rows[0] ?? rawRows[0];

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="Central-bank monitor"
          subtitle={`${rows.length}/${summary?.universe ?? rows.length} rate rows · ${country} · ${regionLabel(region)}`}
          help={<BTMMHelp />}
          trailing={
            <FunctionControlGroup>
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh policy-rate matrix"
              />
            </FunctionControlGroup>
          }
        />
        <div
          style={{
            display: "grid",
            gap: 8,
            padding: "8px 14px",
            borderBottom: "1px solid var(--border-subtle)",
            background: "var(--bg-elev-2)",
          }}
        >
          <FunctionControlGroup>
            <label
              style={{
                display: "grid",
                gap: 3,
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 10,
                color: "var(--text-mute)",
                textTransform: "uppercase",
              }}
            >
              Search
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="country, bank, ccy"
                style={{
                  minWidth: 180,
                  background: "var(--bg-elev-1)",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--text-primary)",
                  padding: "6px 8px",
                  font: "inherit",
                  textTransform: "none",
                }}
              />
            </label>
            <SegmentedControl
              label="COUNTRY"
              value={country}
              options={COUNTRIES}
              onChange={(next) => {
                setCountry(next);
                if (next !== "ALL") setRegion("all");
              }}
              disabled={state === "loading"}
            />
            <SegmentedControl
              label="REGION"
              value={region}
              options={REGIONS}
              onChange={(next) => {
                setRegion(next);
                if (next !== "all") setCountry("ALL");
              }}
              disabled={state === "loading"}
            />
          </FunctionControlGroup>
        </div>
        <PaneBody
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 12,
            minHeight: 0,
          }}
        >
          {state === "loading" || state === "idle" ? (
            <Skeleton height={340} />
          ) : state === "error" ? (
            <Empty
              title="BTMM failed"
              body={error?.message ?? "Policy-rate data could not be loaded."}
              icon="!"
              action={
                <button onClick={refetch} className="btn">
                  Retry
                </button>
              }
            />
          ) : rows.length === 0 ? (
            <Empty
              title="No matching central banks"
              body="Change the country or region filter."
            />
          ) : (
            <>
              <SummaryBand summary={summary} largestMove={largestMove} />
              <PolicyRateHistory row={chartRow} />
              <DataGrid
                columns={COLS}
                rows={rows}
                rowKey={(row, index) => `${row.country_code ?? row.bis_ref_area ?? "row"}-${index}`}
                density="compact"
              />
              {data?.warnings?.length ? (
                <div
                  style={{
                    border: "1px solid rgba(255,122,0,0.32)",
                    borderRadius: "var(--radius-sm)",
                    padding: 10,
                    color: "var(--warn)",
                    background: "rgba(255,122,0,0.06)",
                    fontFamily: "JetBrains Mono, monospace",
                    fontSize: 11,
                  }}
                >
                  {data.warnings.join(" | ")}
                </div>
              ) : null}
            </>
          )}
        </PaneBody>
        <PaneFooter>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span>sources · {data?.sources?.join(", ") || "—"}</span>
          <span>filter · {country}/{region}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function SummaryBand({
  summary,
  largestMove,
}: {
  summary?: BTMMSummary;
  largestMove?: BTMMRow | null;
}) {
  const cells = [
    ["Avg rate", fmtPct(summary?.average_policy_rate)],
    ["High", fmtPct(summary?.max_policy_rate)],
    ["Low", fmtPct(summary?.min_policy_rate)],
    ["Hikes", String(summary?.hikes ?? 0)],
    ["Cuts", String(summary?.cuts ?? 0)],
    [
      "Largest move",
      largestMove
        ? `${largestMove.country_code ?? "—"} ${fmtBp(largestMove.change_bp)}`
        : "—",
    ],
  ];
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-md)",
        overflow: "hidden",
        background: "rgba(0,0,0,0.16)",
      }}
    >
      {cells.map(([label, value]) => (
        <div
          key={label}
          style={{
            minWidth: 0,
            padding: "8px 10px",
            borderRight: "1px solid rgba(255,255,255,0.055)",
          }}
        >
          <div
            style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 10,
              color: "var(--text-mute)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            {label}
          </div>
          <div
            style={{
              marginTop: 4,
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 15,
              color: "var(--text-primary)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {value}
          </div>
        </div>
      ))}
    </div>
  );
}

function PolicyRateHistory({ row }: { row?: BTMMRow }) {
  const points = (row?.history ?? []).filter(
    (point) => typeof point.policy_rate === "number" && point.date,
  );
  if (points.length < 2) return null;
  const values = points.map((point) => Number(point.policy_rate));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const width = 680;
  const height = 118;
  const path = points
    .map((point, index) => {
      const x = (index / Math.max(1, points.length - 1)) * width;
      const y = height - ((Number(point.policy_rate) - min) / span) * (height - 18) - 9;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const latest = points[points.length - 1];
  return (
    <div
      style={{
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-md)",
        background: "rgba(0,0,0,0.12)",
        padding: 10,
        display: "grid",
        gap: 8,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 12,
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 11,
          color: "var(--text-secondary)",
        }}
      >
        <span>{row?.country_code ?? "—"} policy-rate history</span>
        <span>{latest?.date} · {fmtPct(latest?.policy_rate)}</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ width: "100%", height }}>
        <line x1="0" y1={height - 9} x2={width} y2={height - 9} stroke="rgba(255,255,255,0.12)" />
        <line x1="0" y1="9" x2={width} y2="9" stroke="rgba(255,255,255,0.08)" />
        <path d={path} fill="none" stroke="var(--accent)" strokeWidth="2.2" vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  );
}

function filterRows(rows: BTMMRow[], search: string): BTMMRow[] {
  const needle = search.trim().toLowerCase();
  if (!needle) return rows;
  return rows.filter((row) =>
    [
      row.country_code,
      row.bis_ref_area,
      row.country,
      row.central_bank,
      row.currency,
      row.region,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(needle),
  );
}

function BTMMHelp() {
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <strong style={{ color: "var(--accent)", fontFamily: "JetBrains Mono, monospace" }}>
        BTMM · Central-bank monitor
      </strong>
      <span style={{ color: "var(--text-secondary)" }}>
        Country buttons isolate one policy-rate series. Region buttons switch to a
        central-bank universe such as G10, EM, Europe, Americas, APAC, or MEA.
      </span>
      <span style={{ color: "var(--text-secondary)" }}>
        Rate is the latest BIS CBPOL daily value. Last move compares the latest
        rate with the previous different rate; 3M bp compares with the value
        roughly 90 calendar days earlier.
      </span>
      <span style={{ color: "var(--text-mute)" }}>
        Use Refresh to re-query the backend. The backend caches BIS data for six
        hours and shows a warning if it has to fall back.
      </span>
    </div>
  );
}

function normalizePayload(payload: BTMMPayload | unknown): BTMMPayload {
  if (payload && typeof payload === "object") {
    const obj = payload as Record<string, unknown>;
    const rows = Array.isArray(obj.rows) ? (obj.rows as BTMMRow[]) : [];
    return {
      country: typeof obj.country === "string" ? obj.country : undefined,
      region: typeof obj.region === "string" ? obj.region : undefined,
      rows,
      summary:
        obj.summary && typeof obj.summary === "object"
          ? (obj.summary as BTMMSummary)
          : undefined,
    };
  }
  return { rows: [] };
}

function fmtPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  })}%`;
}

function fmtBp(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(0)}bp`;
}

function movePill(move: BTMMRow["last_move"]) {
  const normalized = String(move ?? "hold").toLowerCase();
  const tone =
    normalized === "hike"
      ? "negative"
      : normalized === "cut"
        ? "positive"
        : "muted";
  return (
    <Pill tone={tone} withDot={false}>
      {normalized}
    </Pill>
  );
}

function regionLabel(region: RegionId): string {
  return REGIONS.find((item) => item.value === region)?.label ?? region;
}
