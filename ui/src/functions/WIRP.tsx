/**
 * WIRP — World Interest Rate Probability.
 *
 * Bloomberg `WIRP<GO>` analogue: implied probabilities for the next 4-8
 * central-bank meetings split into cut / hold / hike scenarios. The Fed row
 * is built live and keyless (FRED target range + ^IRX-implied near-term
 * rate, or the CME FedWatch adapter when wired); ECB/BoE report
 * `provider_unavailable` rather than fabricated numbers. The header pill
 * classifies on the backend's actual `source_mode` values
 * (`live_fed_funds_futures` / `cme_fedwatch` / `live_fred_target_no_irx`),
 * so live data is never mislabelled as a reference table — and unknown
 * modes never over-claim live.
 */
import { useEffect, useMemo, type CSSProperties } from "react";
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
  Sparkline,
  StatCard,
  StatusDivider,
  StatusSection,
  Tabs,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { useUtcStamp } from "@/lib/useUtcStamp";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface WIRPRow {
  central_bank?: string;
  date?: string;
  cut_25bp?: number;
  hold?: number;
  hike_25bp?: number;
  implied_change_bp?: number;
  source_mode?: string;
}

interface WIRPCard {
  label?: string;
  value?: number | string | null;
}

interface WIRPAnchor {
  current_target_mid?: number | null;
  current_target_upper?: number | null;
  current_target_lower?: number | null;
  implied_near_term_rate?: number | null;
  implied_near_term_source?: string;
  effr?: number | null;
  as_of?: string | null;
  effr_as_of?: string | null;
}

interface WIRPPayload {
  central_bank?: string;
  rows?: WIRPRow[];
  surface?: unknown[];
  anchor?: WIRPAnchor;
  cards?: WIRPCard[];
  methodology?: string;
  field_dictionary?: Record<string, string>;
  source_mode?: string;
  data_mode?: string;
  status?: string;
}

interface AnchorEntry {
  key: string;
  label: string;
  value: string;
  title?: string;
}

/**
 * Meeting-to-meeting implied policy-rate path: a zero baseline (today's
 * anchor, no cumulative move yet) followed by the running sum of each
 * meeting's probability-weighted `implied_change_bp`. Meetings without a
 * finite implied move are skipped, not zeroed — a missing row must not
 * flatten a real path. No finite implied value anywhere → empty path.
 */
export function cumulativeBpPath(rows: WIRPRow[]): number[] {
  const path = [0];
  let acc = 0;
  let sawValue = false;
  for (const row of rows) {
    const bp = row.implied_change_bp;
    if (typeof bp !== "number" || !Number.isFinite(bp)) continue;
    acc += bp;
    path.push(acc);
    sawValue = true;
  }
  return sawValue ? path : [];
}

/**
 * Target-range anchor labels straight from the backend `anchor` object
 * (FRED target band / implied near-term rate). Values that did not arrive
 * are omitted rather than rendered as em-dash filler.
 */
export function anchorEntries(anchor: WIRPAnchor | undefined): AnchorEntry[] {
  if (!anchor) return [];
  const out: AnchorEntry[] = [];
  const { current_target_lower: lower, current_target_upper: upper } = anchor;
  if (
    typeof lower === "number" &&
    Number.isFinite(lower) &&
    typeof upper === "number" &&
    Number.isFinite(upper)
  ) {
    out.push({
      key: "target",
      label: "Target",
      value: `${lower.toFixed(2)}–${upper.toFixed(2)}%`,
    });
  }
  if (
    typeof anchor.current_target_mid === "number" &&
    Number.isFinite(anchor.current_target_mid)
  ) {
    out.push({
      key: "mid",
      label: "Mid",
      value: `${anchor.current_target_mid.toFixed(3)}%`,
    });
  }
  if (
    typeof anchor.implied_near_term_rate === "number" &&
    Number.isFinite(anchor.implied_near_term_rate)
  ) {
    out.push({
      key: "near",
      label: "Near-term",
      value: `${anchor.implied_near_term_rate.toFixed(3)}%`,
      title: anchor.implied_near_term_source,
    });
  }
  return out;
}

const BANKS = [
  { id: "FED", label: "Fed" },
  { id: "ECB", label: "ECB" },
  { id: "BOE", label: "BOE" },
] as const;
type BankId = (typeof BANKS)[number]["id"];
const BANK_IDS = BANKS.map((b) => b.id);

const REFRESH_MS = 60_000;

export function WIRPPane({ code }: FunctionPaneProps) {
  const [bank, setBank] = usePersistentOption<BankId>(
    "showme.wirp-bank",
    BANK_IDS,
    "FED",
  );
  // Bundle D / PERF-04. Visibility-aware poll.
  const tick = useVisibilityTick(REFRESH_MS);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: { central_bank: bank, meetings: 6 },
  });
  // F4 fix (A6-WIRP-M): poll on the visibility tick without touching the
  // fetch params — a changing param key makes useFunction treat every poll
  // as a fresh load (skeleton flash + cleared data). Canonical GLCO pattern.
  useEffect(() => {
    if (tick === 0) return;
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tick is the trigger
  }, [tick]);

  const payload = useMemo<WIRPPayload>(
    () =>
      data?.data && typeof data.data === "object" && !Array.isArray(data.data)
        ? (data.data as WIRPPayload)
        : {},
    [data?.data],
  );

  const rows = useMemo<WIRPRow[]>(
    () => (Array.isArray(payload.rows) ? payload.rows : []),
    [payload.rows],
  );

  // F4 fix (A6-WIRP-H): the live backend emits top-level `source_mode` values
  // such as `live_fed_funds_futures` / `cme_fedwatch` / `live_fred_target_no_irx`.
  // Comparing against the literal "live" mislabelled every live row as a
  // reference table. Only the explicit live modes earn the live pill —
  // anything else (reference table, provider outage, unknown drift) stays
  // honestly labelled reference.
  const LIVE_SOURCE_MODES = new Set([
    "live_fed_funds_futures",
    "cme_fedwatch",
    "live_fred_target_no_irx",
  ]);
  const sourceMode = payload.source_mode ?? rows[0]?.source_mode ?? "unknown";
  const status = typeof payload.status === "string" ? payload.status : "";
  const isReferenceTable =
    !LIVE_SOURCE_MODES.has(sourceMode) || status === "provider_unavailable";
  const warningsList = Array.isArray(data?.warnings) ? data?.warnings : [];

  const utcStamp = useUtcStamp(tick);

  const cols = useMemo<DataGridColumn<WIRPRow>[]>(
    () => [
      {
        key: "date",
        header: "Meeting",
        width: 120,
        render: (r) => <span style={dateCell}>{r.date ?? "—"}</span>,
      },
      {
        key: "cut",
        header: "Cut 25bp",
        numeric: true,
        width: 110,
        render: (r) =>
          r.cut_25bp == null ? "—" : (
            <ProbBar value={r.cut_25bp} tone="var(--negative)" />
          ),
      },
      {
        key: "hold",
        header: "Hold",
        numeric: true,
        width: 110,
        render: (r) =>
          r.hold == null ? "—" : <ProbBar value={r.hold} tone="var(--accent)" />,
      },
      {
        key: "hike",
        header: "Hike 25bp",
        numeric: true,
        width: 110,
        render: (r) =>
          r.hike_25bp == null ? "—" : (
            <ProbBar value={r.hike_25bp} tone="var(--positive)" />
          ),
      },
      {
        key: "implied",
        header: "Implied Δ",
        numeric: true,
        width: 110,
        render: (r) => {
          if (r.implied_change_bp == null) return "—";
          const bp = r.implied_change_bp;
          const tone = bp >= 0 ? "var(--positive)" : "var(--negative)";
          return (
            <span style={{ ...impliedCell, color: tone }}>
              {bp >= 0 ? "+" : ""}
              {bp.toFixed(1)} bp
            </span>
          );
        },
      },
    ],
    [],
  );

  const cards = Array.isArray(payload.cards) ? payload.cards : [];
  const totalImplied = rows.reduce(
    (acc, r) => acc + (typeof r.implied_change_bp === "number" ? r.implied_change_bp : 0),
    0,
  );
  // Secondary visual (campaign C1): cumulative implied path from the real
  // per-meeting `implied_change_bp` series + the backend `anchor` band.
  const path = cumulativeBpPath(rows);
  const anchors = anchorEntries(payload.anchor);
  const pathReady = path.length >= 2;

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Rate probabilities"
          subtitle={`${bank} · ${rows.length} meetings · poll ${REFRESH_MS / 1000}s · ${sourceMode}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>{rows.length} mtg</Pill>
              <Pill tone="accent" variant="soft" withDot={false}>{utcStamp} UTC</Pill>
              <span data-testid="wirp-mode-pill">
                <Pill
                  tone={isReferenceTable ? "warn" : "positive"}
                  variant="soft"
                >
                  {isReferenceTable ? "reference table" : "live"}
                </Pill>
              </span>
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <div style={tabBarStyle}>
          <Tabs
            variant="segmented"
            items={BANKS.map((b) => ({ id: b.id, label: b.label }))}
            active={bank}
            onChange={(id) => setBank(id as BankId)}
          />
        </div>
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <Skeleton height={300} />
          ) : state === "error" ? (
            <Empty title="Function error" body={error?.message ?? "—"} icon="!" />
          ) : rows.length === 0 ? (
            <Empty title="No meetings" body={`No WIRP rows for ${bank}.`} />
          ) : (
            <div className="u-grid-gap-14">
              {isReferenceTable ? (
                <div style={noticeStyle}>
                  <strong className="u-text-warn">Reference probability table</strong>
                  <span className="u-text-secondary">
                    Rows are labelled `{sourceMode}` — no live futures-implied
                    probability source (CME FedWatch / SOFR / OIS) is
                    contributing right now. Treat values as labelled
                    references, not live tape data.
                  </span>
                </div>
              ) : null}
              {warningsList.length ? (
                <div style={warningBox}>
                  <strong className="u-text-warn">Provider warnings</strong>
                  <ul style={warningList}>
                    {warningsList.slice(0, 3).map((w, i) => (
                      <li key={i} className="u-text-secondary">
                        {String(w)}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <section style={kpiGrid} aria-label="WIRP KPI ribbon">
                {cards.length
                  ? cards.slice(0, 3).map((card, i) => (
                      <StatCard
                        key={i}
                        label={card.label ?? `Card ${i + 1}`}
                        value={
                          card.value == null
                            ? "—"
                            : typeof card.value === "number"
                              ? card.value.toString()
                              : String(card.value)
                        }
                        caption={`AS OF ${utcStamp} UTC`}
                        tone="neutral"
                      />
                    ))
                  : null}
                <StatCard
                  label="Cumulative implied Δ"
                  value={`${totalImplied >= 0 ? "+" : ""}${totalImplied.toFixed(1)} bp`}
                  caption={`${rows.length} meetings · ${bank}`}
                  tone={totalImplied >= 0 ? "positive" : "negative"}
                />
              </section>
              {pathReady || anchors.length ? (
                <section style={pathPanelStyle} aria-label="WIRP implied path">
                  <div style={pathMetaStyle}>
                    <span style={pathTitleStyle}>Implied path</span>
                    <span className="u-text-mute" style={pathCaptionStyle}>
                      Σ implied Δ from the {bank} anchor · {rows.length} meetings
                    </span>
                    {anchors.map((a) => (
                      <span key={a.key} style={anchorChipStyle} title={a.title}>
                        <span style={anchorLabelStyle}>{a.label}</span>
                        <span style={anchorValueStyle}>{a.value}</span>
                      </span>
                    ))}
                  </div>
                  {pathReady ? (
                    <Sparkline
                      values={path}
                      width={200}
                      height={40}
                      tone={path[path.length - 1] >= 0 ? "positive" : "negative"}
                      ariaLabel="Cumulative implied policy-rate path"
                    />
                  ) : (
                    <span className="u-text-mute" style={pathCaptionStyle}>
                      No per-meeting implied series returned.
                    </span>
                  )}
                </section>
              ) : null}
              <DataGrid
                columns={cols}
                rows={rows}
                rowKey={(r, i) => `${r.date ?? "row"}-${i}`}
                density="compact"
                ariaLabel="WIRP meeting probabilities"
              />
              {payload.methodology ? (
                <div style={methodologyBox}>
                  <strong className="u-text-secondary">Methodology</strong>
                  <span>{payload.methodology}</span>
                </div>
              ) : null}
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={data?.sources?.join(", ") || sourceMode} />
          <StatusDivider />
          <StatusSection label="poll" value={`${REFRESH_MS / 1000}s`} />
          <StatusDivider />
          <StatusSection label="meetings" value={rows.length} />
          <StatusDivider />
          <StatusSection label="elapsed" value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`} />
          <StatusDivider />
          <StatusSection label="bank" value={bank} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function ProbBar({ value, tone }: { value: number; tone: string }) {
  const pct = Math.max(0, Math.min(100, value * 100));
  const intensity = 0.25 + Math.min(value, 1) * 0.55;
  return (
    <span style={probWrap}>
      <span style={probTrack} aria-hidden>
        <span
          style={{
            ...probFill,
            width: `${pct}%`,
            background: `color-mix(in srgb, ${tone} ${(intensity * 100).toFixed(0)}%, transparent)`,
          }}
        />
      </span>
      <span style={{ ...probLabel, color: tone }}>{pct.toFixed(0)}%</span>
    </span>
  );
}

const tabBarStyle: CSSProperties = {
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const dateCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-display)",
  fontWeight: 600,
};

const impliedCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontWeight: 700,
};

const probWrap: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  width: "100%",
};

const probTrack: CSSProperties = {
  position: "relative",
  flex: "1 1 auto",
  height: 8,
  background: "var(--surface-3)",
  borderRadius: 999,
  overflow: "hidden",
};

const probFill: CSSProperties = {
  position: "absolute",
  top: 0,
  left: 0,
  height: "100%",
  borderRadius: 999,
};

const probLabel: CSSProperties = {
  flex: "0 0 auto",
  width: 40,
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: "var(--font-size-xs)",
  fontWeight: 600,
  textAlign: "right",
};

const kpiGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
  gap: 10,
};

const noticeStyle: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  background: "var(--warn-soft)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
};

const warningBox: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 30%, transparent)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
  display: "grid",
  gap: 4,
};

const warningList: CSSProperties = {
  margin: 0,
  paddingLeft: 18,
  fontSize: "var(--font-size-xs)",
};

const methodologyBox: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "10px 12px",
  display: "grid",
  gap: 6,
};

const pathPanelStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  flexWrap: "wrap",
  gap: 14,
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
};

const pathMetaStyle: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  flexWrap: "wrap",
  gap: "4px 12px",
  minWidth: 0,
};

const pathTitleStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  fontWeight: 700,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--text-display)",
};

const pathCaptionStyle: CSSProperties = {
  fontSize: "var(--font-size-xs)",
};

const anchorChipStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "baseline",
  gap: 5,
};

const anchorLabelStyle: CSSProperties = {
  fontSize: "var(--font-size-2xs)",
  textTransform: "uppercase",
  letterSpacing: "0.05em",
  color: "var(--text-mute)",
};

const anchorValueStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: "var(--font-size-xs)",
  fontWeight: 600,
  color: "var(--text-primary)",
};
