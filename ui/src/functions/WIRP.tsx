/**
 * WIRP — World Interest Rate Probability.
 *
 * Bloomberg `WIRP<GO>` analogue: implied probabilities for the next 4-8
 * central-bank meetings split into cut / hold / hike scenarios. The
 * sidecar currently returns a labelled `reference_rate_probability_table`
 * source mode and a `live futures-implied probability adapter is not
 * configured` warning — the pane exposes that warning prominently so the
 * user never confuses it with a live FedWatch feed.
 */
import { useEffect, useMemo, useState, type CSSProperties } from "react";
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
  Tabs,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
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

interface WIRPPayload {
  central_bank?: string;
  rows?: WIRPRow[];
  surface?: unknown[];
  cards?: WIRPCard[];
  methodology?: string;
  field_dictionary?: Record<string, string>;
  source_mode?: string;
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
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: { central_bank: bank, meetings: 6, tick },
  });

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

  const sourceMode =
    payload.source_mode ?? rows[0]?.source_mode ?? "reference_rate_probability_table";
  const isReferenceTable = sourceMode !== "live";
  const warningsList = Array.isArray(data?.warnings) ? data?.warnings : [];

  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 16), [tick]);

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
              <Pill
                tone={isReferenceTable ? "warn" : "positive"}
                variant="soft"
              >
                {isReferenceTable ? "reference table" : "live"}
              </Pill>
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
                    Rows are labelled `reference_rate_probability_table` — the live
                    futures-implied probability adapter (CME FedWatch / SOFR / OIS)
                    is not configured. Treat values as labelled references, not
                    live tape data.
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
              <DataGrid
                columns={cols}
                rows={rows}
                rowKey={(r, i) => `${r.date ?? "row"}-${i}`}
                density="compact"
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
