/**
 * FLY — Flight tracking (OpenSky ADS-B state vectors).
 *
 * Header: callsign + country inputs (applied on Enter / Apply) + limit
 * segmented control + alerts settings + status + refresh. Body: honesty
 * note (positions are ADS-B snapshots; route origin/destination is NOT
 * inferred) + a status table: callsign, country, altitude, speed, heading,
 * ground/airborne pill, last contact (UTC) + the in-pane alert history.
 *
 * Honesty: the backend only returns aircraft when `live_flight=true` AND
 * OpenSky answers; the pane always sends the flag and renders the
 * provider_unavailable payload's reason as an explicit empty state —
 * no sample aircraft are ever invented. Applied filters show as pills so
 * an empty board is always attributable to a filter or an outage.
 *
 * Alerts (2026-09-16): client-side rules evaluated on every poll against
 * the current rows — erratic flight path, crash risk (steep/low descent),
 * stale ADS-B contact. Rules never fire on missing fields; see
 * `fly-alerts.ts` for the per-rule data requirements. Fired alerts land in
 * the app toast host AND the pane's alert-history list; dedupe/cooldown is
 * per callsign+rule. The pane auto-refreshes every 60 s while visible (the
 * OpenSky public quota is 4000 requests/day, well above 1/min).
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
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
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { toast } from "@/lib/toast";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";
import {
  DEFAULT_FLY_ALERT_CONFIG,
  emptyFlyAlertMemory,
  evaluateFlyAlerts,
  loadFlyAlertConfig,
  normalizeFlyAlertConfig,
  saveFlyAlertConfig,
  type FlyAlert,
  type FlyAlertConfig,
  type FlyAlertMemory,
  type FlyContactRow,
} from "./fly-alerts";

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
// The backend clamps `limit` to [1, 100] — offer the full honest range so
// the segmented control genuinely drives the row cap end-to-end.
const LIMIT_OPTIONS = [
  { value: 10, label: "10" },
  { value: 25, label: "25" },
  { value: 50, label: "50" },
  { value: 100, label: "100", title: "LIMIT 100 (OpenSky backend cap)" },
] as const;
const LIMIT_IDS = LIMIT_OPTIONS.map((o) => o.value);
/** Visibility-paused auto-refresh. OpenSky public quota: 4000 req/day. */
const REFRESH_MS = 60_000;
const ALERT_HISTORY_MAX = 50;
const ALERT_HISTORY_SHOWN = 10;
const TOASTS_PER_POLL = 3;

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

  // Alert settings + per-session state. Config persists under
  // `showme.fly.alerts`; memory/history are session-scoped.
  const [alertConfig, setAlertConfig] = useState<FlyAlertConfig>(() => loadFlyAlertConfig());
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [alertHistory, setAlertHistory] = useState<FlyAlert[]>([]);
  const alertMemoryRef = useRef<FlyAlertMemory>(emptyFlyAlertMemory());
  const alertConfigRef = useRef(alertConfig);
  const alertsWrapRef = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    alertConfigRef.current = alertConfig;
  }, [alertConfig]);

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

  // Visibility-paused 60 s refresh so the alert rules see fresh polls. The
  // tick only triggers `refetch()`; it never enters `params` (useFunction
  // fingerprints params into the fetch key — UA-HIGH-16).
  const tick = useVisibilityTick(REFRESH_MS);
  useEffect(() => {
    if (tick === 0) return; // initial mount is useFunction's own load
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tick is the trigger
  }, [tick]);

  // Evaluate rules once per poll. Deps are payload+state only: toggling a
  // rule must not re-run an unchanged snapshot through the deltas (the
  // config is read through a ref for the same reason).
  useEffect(() => {
    if (state !== "ok") return;
    const { alerts, memory } = evaluateFlyAlerts(
      alertMemoryRef.current,
      rows as FlyContactRow[],
      alertConfigRef.current,
      Date.now(),
    );
    alertMemoryRef.current = memory;
    if (alerts.length === 0) return;
    setAlertHistory((prev) => [...alerts].reverse().concat(prev).slice(0, ALERT_HISTORY_MAX));
    for (const alert of alerts.slice(0, TOASTS_PER_POLL)) {
      toast.warn(alert.callsign, `${alert.label} — ${alert.detail}`);
    }
    if (alerts.length > TOASTS_PER_POLL) {
      toast.warn(
        `+${alerts.length - TOASTS_PER_POLL} more FLY alerts`,
        "See the pane alert history for details.",
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- rows derives from payload
  }, [payload, state]);

  // Close the settings popover on an outside press.
  useEffect(() => {
    if (!alertsOpen) return;
    const onDown = (event: MouseEvent) => {
      const node = alertsWrapRef.current;
      if (node && !node.contains(event.target as Node)) setAlertsOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [alertsOpen]);

  const updateAlertConfig = (next: FlyAlertConfig) => {
    const normalized = normalizeFlyAlertConfig(next);
    setAlertConfig(normalized);
    saveFlyAlertConfig(normalized);
  };

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

  const alertHistoryBlock =
    alertHistory.length > 0 ? (
      <section
        style={alertHistoryStyle}
        aria-label="FLY alert history"
        data-testid="fly-alert-history"
      >
        <div style={alertHistoryHeadStyle}>
          <span style={noteLabelStyle}>
            ALERT HISTORY · latest {Math.min(alertHistory.length, ALERT_HISTORY_SHOWN)}
            {alertHistory.length > ALERT_HISTORY_SHOWN
              ? ` of ${alertHistory.length}`
              : ""}
          </span>
          <button
            type="button"
            className="btn"
            onClick={() => setAlertHistory([])}
            title="Clear FLY alert history"
          >
            Clear
          </button>
        </div>
        {alertHistory.slice(0, ALERT_HISTORY_SHOWN).map((alert) => (
          <div key={alert.id} style={alertRowStyle}>
            <span style={monoMutedStyle}>{fmtClock(alert.ts)}</span>
            <span style={monoStrongStyle}>{alert.callsign}</span>
            <span style={alertLabelStyle}>{alert.label}</span>
            <span style={monoMutedStyle}>{alert.detail}</span>
          </div>
        ))}
      </section>
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
                title="Aircraft limit (backend cap 100)"
              />
              <span ref={alertsWrapRef} style={alertsWrapStyle}>
                <button
                  type="button"
                  className="btn"
                  aria-haspopup="dialog"
                  aria-expanded={alertsOpen}
                  aria-label="FLY alerts"
                  onClick={() => setAlertsOpen((open) => !open)}
                  title="FLY alert rules: erratic path · crash risk · stale contact"
                >
                  Alerts{alertHistory.length > 0 ? ` · ${alertHistory.length}` : ""}
                </button>
                {alertsOpen && (
                  <FlyAlertsPopover
                    config={alertConfig}
                    onChange={updateAlertConfig}
                    onClose={() => setAlertsOpen(false)}
                  />
                )}
              </span>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh live traffic"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}{alertHistoryBlock}</PaneBody>
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
          <StatusDivider />
          <StatusSection
            label="alerts"
            value={alertHistory.length}
            tone={alertHistory.length > 0 ? "warn" : undefined}
          />
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

function fmtClock(ts: number): string {
  if (!Number.isFinite(ts)) return "—";
  return new Date(ts).toISOString().slice(11, 19);
}

/* ── alert settings popover ────────────────────────────────────────── */

/**
 * Compact per-rule settings: enable toggle + thresholds, persisted by the
 * parent on every change. Every threshold shows its unit and every rule
 * states the fields it needs — a rule with missing data stays silent
 * (see `fly-alerts.ts`).
 */
function FlyAlertsPopover({
  config,
  onChange,
  onClose,
}: {
  config: FlyAlertConfig;
  onChange: (next: FlyAlertConfig) => void;
  onClose: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-label="FLY alert settings"
      data-testid="fly-alerts-popover"
      style={popoverStyle}
      onKeyDown={(event) => {
        if (event.key === "Escape") onClose();
      }}
    >
      <div style={popoverTitleStyle}>FLY ALERTS</div>

      <div style={ruleBlockStyle}>
        <ToggleRow
          label="Erratic flight path"
          checked={config.erratic.enabled}
          onToggle={(checked) =>
            onChange({ ...config, erratic: { ...config.erratic, enabled: checked } })
          }
        />
        <ThresholdInput
          label="heading change ≥"
          inputLabel="Erratic heading threshold (deg)"
          value={config.erratic.headingDeg}
          min={5}
          max={180}
          step={5}
          unit="°"
          onCommit={(v) =>
            onChange({ ...config, erratic: { ...config.erratic, headingDeg: v } })
          }
        />
        <span style={ruleHintStyle}>
          Needs heading on two consecutive polls (a two-step zig-zag of half
          the threshold also counts).
        </span>
      </div>

      <div style={ruleBlockStyle}>
        <ToggleRow
          label="Crash risk"
          checked={config.crash.enabled}
          onToggle={(checked) =>
            onChange({ ...config, crash: { ...config.crash, enabled: checked } })
          }
        />
        <ThresholdInput
          label="steep descent ≤ −"
          inputLabel="Crash vertical rate threshold (ft/min)"
          value={config.crash.verticalFpm}
          min={200}
          max={10000}
          step={100}
          unit="ft/min"
          onCommit={(v) =>
            onChange({ ...config, crash: { ...config.crash, verticalFpm: v } })
          }
        />
        <ThresholdInput
          label="or below"
          inputLabel="Crash low altitude threshold (ft)"
          value={config.crash.lowAltFt}
          min={100}
          max={30000}
          step={100}
          unit="ft (descending)"
          onCommit={(v) =>
            onChange({ ...config, crash: { ...config.crash, lowAltFt: v } })
          }
        />
        <span style={ruleHintStyle}>
          Needs vertical rate (converted from m/s); the low-altitude form
          additionally needs altitude. on-ground aircraft are excluded.
        </span>
      </div>

      <div style={ruleBlockStyle}>
        <ToggleRow
          label="Stale contact"
          checked={config.stale.enabled}
          onToggle={(checked) =>
            onChange({ ...config, stale: { ...config.stale, enabled: checked } })
          }
        />
        <ThresholdInput
          label="no ADS-B contact ≥"
          inputLabel="Stale contact threshold (minutes)"
          value={config.stale.minutes}
          min={1}
          max={720}
          step={1}
          unit="min"
          onCommit={(v) =>
            onChange({ ...config, stale: { ...config.stale, minutes: v } })
          }
        />
        <span style={ruleHintStyle}>
          Needs last_contact_utc and a prior poll of the same callsign. Data
          staleness only — FLY has no flight-schedule provider.
        </span>
      </div>

      <div style={popoverFootRowStyle}>
        <span style={popoverFootStyle}>
          Rules run on every poll (60 s while the pane is visible). One fire
          per aircraft+rule per 5 min cooldown. Missing fields never fire.
        </span>
        <button
          type="button"
          className="btn"
          onClick={() => onChange(DEFAULT_FLY_ALERT_CONFIG)}
          title="Restore FLY alert defaults (60° / −2,500 ft/min / 2,000 ft / 10 min)"
        >
          Reset defaults
        </button>
      </div>
    </div>
  );
}

function ToggleRow({
  label,
  checked,
  onToggle,
}: {
  label: string;
  checked: boolean;
  onToggle: (checked: boolean) => void;
}) {
  return (
    <label style={toggleRowStyle}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onToggle(event.target.checked)}
      />
      <span style={ruleNameStyle}>{label}</span>
    </label>
  );
}

function ThresholdInput({
  label,
  inputLabel,
  value,
  min,
  max,
  step,
  unit,
  onCommit,
}: {
  label: string;
  inputLabel: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  onCommit: (value: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => {
    setDraft(String(value));
  }, [value]);
  const commit = () => {
    const parsed = Number(draft);
    if (draft.trim() !== "" && Number.isFinite(parsed)) onCommit(parsed);
    else setDraft(String(value));
  };
  return (
    <label style={thresholdRowStyle}>
      <span style={thresholdLabelStyle}>{label}</span>
      <input
        type="number"
        aria-label={inputLabel}
        min={min}
        max={max}
        step={step}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit();
        }}
        style={numInputStyle}
      />
      <span style={thresholdUnitStyle}>{unit}</span>
    </label>
  );
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

/* ── alert history ─────────────────────────────────────────────────── */

const alertHistoryStyle: CSSProperties = {
  marginTop: 12,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "var(--surface-2)",
  padding: "8px 10px",
  display: "grid",
  gap: 4,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
};

const alertHistoryHeadStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const noteLabelStyle: CSSProperties = {
  color: "var(--text-mute)",
  letterSpacing: "0.04em",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
};

const alertRowStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "62px 84px minmax(180px, auto) 1fr",
  alignItems: "baseline",
  gap: 8,
  color: "var(--text-primary)",
};

const alertLabelStyle: CSSProperties = {
  color: "var(--warn)",
  fontFamily: "JetBrains Mono, monospace",
};

/* ── alerts control + popover ──────────────────────────────────────── */

const alertsWrapStyle: CSSProperties = {
  position: "relative",
  display: "inline-flex",
  alignItems: "center",
};

const popoverStyle: CSSProperties = {
  position: "absolute",
  top: "calc(100% + 6px)",
  right: 0,
  zIndex: 60,
  width: 336,
  maxHeight: 360,
  overflowY: "auto",
  display: "grid",
  gap: 8,
  padding: "10px 12px",
  border: "1px solid var(--border-card, var(--border-subtle))",
  borderRadius: "var(--radius-sm)",
  background: "var(--surface-2)",
  boxShadow: "var(--shadow-elev-2, var(--shadow-elev-1))",
  color: "var(--text-primary)",
  textAlign: "left",
  cursor: "default",
};

const popoverTitleStyle: CSSProperties = {
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  letterSpacing: "0.08em",
};

const ruleBlockStyle: CSSProperties = {
  display: "grid",
  gap: 4,
  padding: "6px 8px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "var(--bg-elev-2, var(--surface-2))",
};

const toggleRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  cursor: "pointer",
};

const ruleNameStyle: CSSProperties = {
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
  fontWeight: 600,
};

const ruleHintStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: "var(--font-size-xs)",
  lineHeight: 1.4,
};

const thresholdRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
};

const thresholdLabelStyle: CSSProperties = {
  color: "var(--text-secondary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  minWidth: 122,
};

const thresholdUnitStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
};

const numInputStyle: CSSProperties = {
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-md)",
  height: 22,
  padding: "0 4px",
  width: 76,
};

const popoverFootStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: "var(--font-size-xs)",
  lineHeight: 1.4,
};

const popoverFootRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};
