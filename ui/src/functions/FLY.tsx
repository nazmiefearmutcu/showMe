/**
 * FLY — Flight tracking (OpenSky ADS-B state vectors).
 *
 * Header: callsign + country inputs (applied on Enter / Apply) + limit
 * segmented control + status + refresh. Body: honesty note (positions
 * are ADS-B snapshots; route origin/destination is NOT inferred) + a
 * status table: callsign, country, altitude, speed, heading,
 * ground/airborne pill, last contact (UTC).
 *
 * Honesty: the backend only returns aircraft when `live_flight=true` AND
 * OpenSky answers; the pane always sends the flag and renders the
 * provider_unavailable payload's reason as an explicit empty state —
 * no sample aircraft are ever invented. Applied filters show as pills so
 * an empty board is always attributable to a filter or an outage.
 */
import { useMemo, useState, type CSSProperties } from "react";
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
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface FLYRow {
  icao24?: string;
  callsign?: string;
  origin_country?: string;
  last_contact_utc?: string;
  lon?: number | null;
  lat?: number | null;
  altitude_ft?: number | null;
  speed_kt?: number | null;
  heading?: number | null;
  vertical_rate_mps?: number | null;
  on_ground?: boolean;
  source_mode?: string;
}

interface FLYData {
  status?: string;
  reason?: string;
  callsign?: string | null;
  country?: string | null;
  rows?: FLYRow[];
  methodology?: string;
}

const DEFAULT_LIMIT = 25;
const LIMIT_OPTIONS = [
  { value: 10, label: "10" },
  { value: 25, label: "25" },
  { value: 50, label: "50" },
] as const;
const LIMIT_IDS = LIMIT_OPTIONS.map((o) => o.value);

export function FLYPane({ code }: FunctionPaneProps) {
  // Draft vs applied inputs: useFunction refetches on param change, so a
  // keystroke-level binding would fire one OpenSky request per character.
  const [callsignDraft, setCallsignDraft] = useState("");
  const [countryDraft, setCountryDraft] = useState("");
  const [applied, setApplied] = useState({ callsign: "", country: "" });
  const [limit, setLimit] = usePersistentOption<number>(
    "showme.fly.limit",
    LIMIT_IDS,
    DEFAULT_LIMIT,
  );

  const { state, data, error, refetch } = useFunction<FLYData>({
    code,
    params: {
      // live_flight is the backend's explicit opt-in for the keyless
      // OpenSky feed — without it the function refuses to run.
      live_flight: true,
      callsign: applied.callsign || undefined,
      country: applied.country || undefined,
      limit,
    },
  });

  const payload = data?.data;
  const rows: FLYRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";

  const airborne = rows.filter((r) => !r.on_ground).length;
  const lastContact =
    rows.map((r) => r.last_contact_utc ?? "").sort().at(-1) ?? "—";

  const applyInputs = () =>
    setApplied({
      callsign: callsignDraft.trim().toUpperCase(),
      country: countryDraft.trim(),
    });

  const COLS: DataGridColumn<FLYRow>[] = useMemo(
    () => [
      {
        key: "callsign",
        header: "Callsign",
        width: 116,
        render: (r) => (
          <span style={monoStrongStyle}>{r.callsign ?? r.icao24 ?? "—"}</span>
        ),
      },
      {
        key: "origin_country",
        header: "Country",
        width: 140,
        render: (r) => (
          <span style={monoPrimaryStyle}>{r.origin_country ?? "—"}</span>
        ),
      },
      {
        key: "altitude_ft",
        header: "Alt (ft)",
        numeric: true,
        width: 104,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtInt(r.altitude_ft)}</span>
        ),
      },
      {
        key: "speed_kt",
        header: "Speed (kt)",
        numeric: true,
        width: 110,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtInt(r.speed_kt)}</span>
        ),
      },
      {
        key: "heading",
        header: "Heading",
        numeric: true,
        width: 100,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtHeading(r.heading)}</span>
        ),
      },
      {
        key: "on_ground",
        header: "State",
        width: 110,
        render: (r) => (
          <Pill
            tone={r.on_ground ? "warn" : "positive"}
            variant="soft"
            withDot={false}
          >
            {r.on_ground ? "on ground" : "airborne"}
          </Pill>
        ),
      },
      {
        key: "last_contact_utc",
        header: "Last contact (UTC)",
        width: 180,
        render: (r) => (
          <span style={monoMutedStyle}>{r.last_contact_utc ?? "—"}</span>
        ),
      },
    ],
    [],
  );

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
    ) : status === "provider_unavailable" || rows.length === 0 ? (
      <div className="u-grid-gap-14">
        <div role="status" style={noteStyle} aria-label="Tracking coverage note">
          Live OpenSky ADS-B snapshots only. No aircraft are shown when the
          feed is unavailable — sample or historical traffic is never
          substituted.
        </div>
        <Empty
          title="No live aircraft"
          body={
            payload?.reason ??
            "OpenSky returned no aircraft for the current filters."
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
        <div role="status" style={noteStyle} aria-label="Tracking coverage note">
          Live OpenSky ADS-B snapshots. Positions are last reported states —
          route origin/destination is not inferred without a flight-plan
          provider.
        </div>
        <section style={kpiGridStyle} aria-label="FLY KPI ribbon">
          <StatCard
            label="Aircraft"
            value={String(rows.length)}
            caption={`${airborne} AIRBORNE · ${rows.length - airborne} GROUND`}
            tone="neutral"
          />
          <StatCard
            label="Callsign filter"
            value={applied.callsign || "ALL"}
            caption={applied.country ? `COUNTRY "${applied.country}"` : "NO COUNTRY FILTER"}
            tone="neutral"
          />
          <StatCard
            label="Last contact"
            value={fmtTime(lastContact)}
            caption="UTC"
            tone="neutral"
          />
        </section>
        <DataGrid
          columns={COLS}
          rows={rows}
          rowKey={(r, i) => `${r.icao24 ?? r.callsign ?? "ac"}-${i}`}
          density="compact"
          ariaLabel="FLY aircraft table"
        />
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Flight Tracking"
          subtitle={`${rows.length} aircraft · OpenSky live_flight`}
          trailing={
            <FunctionControlGroup>
              <input
                type="search"
                aria-label="Callsign filter"
                value={callsignDraft}
                onChange={(e) => setCallsignDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") applyInputs();
                }}
                placeholder="callsign e.g. THY"
                style={inputStyle}
              />
              <input
                type="search"
                aria-label="Country filter"
                value={countryDraft}
                onChange={(e) => setCountryDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") applyInputs();
                }}
                placeholder="origin country"
                style={inputStyle}
              />
              <button
                type="button"
                className="btn"
                onClick={applyInputs}
                title="Apply callsign + country filters"
              >
                Apply
              </button>
              <SegmentedControl
                label="LIMIT"
                value={limit}
                options={LIMIT_OPTIONS}
                onChange={setLimit}
                title="Aircraft limit"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh live traffic"
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
          <StatusSection label="aircraft" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="limit" value={limit} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── helpers ───────────────────────────────────────────────────────── */

function fmtInt(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return Math.round(v).toLocaleString("en-US");
}

function fmtHeading(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${Math.round(v)}°`;
}

function fmtTime(iso: string): string {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 19) || "—";
}

/* ── styles ────────────────────────────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const noteStyle: CSSProperties = {
  border: "1px solid var(--border, var(--text-mute))",
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

const inputStyle: CSSProperties = {
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-md)",
  height: 24,
  padding: "0 6px",
  width: 150,
};
