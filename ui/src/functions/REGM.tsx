/**
 * REGM — Market Regime.
 *
 * Renders the backend's rule-based classification EXACTLY as reported:
 * the Regime / Trend / Vol / Curve cards mirror `payload.cards` verbatim,
 * and a supporting indicator table mirrors `payload.rows` (value + unit +
 * the rule that produced it). When the backend reports UNKNOWN / null /
 * "Cannot classify — no inputs available", the card renders an explicit
 * unknown state ("not reported — not guessed") — the pane never fills a
 * gap with its own classification. A provider_unavailable payload (live
 * benchmark series unreachable) surfaces the provider error verbatim.
 *
 * The payload's history/cluster fields (action=history) are intentionally
 * not rendered — this pane always requests the default action=current.
 */
import { type CSSProperties } from "react";
import {
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { defaultSymbolForFunction } from "@/lib/symbols";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface REGMCard {
  label?: string | null;
  value?: string | null;
}

interface REGMComponentRow {
  symbol?: string;
  component?: string | null;
  label?: string | null;
  value?: number | null;
  unit?: string | null;
  rule?: string | null;
  source_mode?: string | null;
}

interface REGMData {
  symbol?: string;
  status?: string;
  provider_error?: string;
  current?: {
    regime?: string | null;
    trend?: string | null;
    vol?: string | null;
    drawdown?: string | null;
    curve?: string | null;
    confidence?: number | null;
    data_state?: string | null;
  };
  data_state?: string;
  confidence?: number | null;
  rows?: REGMComponentRow[];
  cards?: REGMCard[];
  methodology?: string;
  source_mode?: string;
}

type DaysOption = 365 | 1095 | 1825;

const DAYS_OPTIONS: { value: DaysOption; label: string }[] = [
  { value: 365, label: "1Y" },
  { value: 1095, label: "3Y" },
  { value: 1825, label: "5Y" },
];

/** True when the backend explicitly declined to classify this component. */
function isUnknownValue(value: string | null | undefined): boolean {
  if (value == null) return true;
  const text = value.trim();
  if (text === "" || text === "—") return true;
  const lower = text.toLowerCase();
  return lower === "unknown" || lower.startsWith("cannot classify");
}

export function REGMPane({ code, symbol }: FunctionPaneProps) {
  const [days, setDays] = usePersistentOption<DaysOption>(
    "showme.regm.days",
    DAYS_OPTIONS.map((o) => o.value),
    1095,
  );

  const effectiveSymbol = symbol || defaultSymbolForFunction(code);
  const { state, data, error, refetch } = useFunction<REGMData>({
    code,
    symbol: effectiveSymbol || undefined,
    params: { days },
  });

  const payload = data?.data;
  const status = payload?.status ?? data?.status ?? "—";
  const cards = Array.isArray(payload?.cards) ? payload.cards : [];
  const rows = Array.isArray(payload?.rows) ? payload.rows : [];
  const dataState = payload?.data_state ?? payload?.current?.data_state;
  const confidence = payload?.confidence ?? payload?.current?.confidence ?? null;
  const warnings = data?.warnings ?? [];

  const body =
    state === "loading" || state === "idle" ? (
      <div className="u-grid-gap-8">
        <Skeleton height={64} />
        <Skeleton height={20} />
        <Skeleton height={120} />
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
        title="Regime unavailable"
        body={
          payload?.provider_error
            ? `${payload.provider_error} — nothing is fabricated while the benchmark provider is unreachable.`
            : "The live benchmark series is unavailable — no regime is guessed without it."
        }
        icon="!"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : (
      <div className="u-grid-gap-14">
        <section style={cardGridStyle} aria-label="REGM regime cards">
          {cards.length > 0 ? (
            cards.map((card, i) => (
              <RegimeCard
                key={`${card.label ?? "card"}-${i}`}
                label={card.label ?? "—"}
                value={card.value ?? null}
              />
            ))
          ) : (
            <span style={muteTextStyle}>
              backend returned no regime cards
            </span>
          )}
        </section>

        {(dataState && dataState !== "ok") || warnings.length > 0 ? (
          <section
            style={stateStripStyle}
            aria-label="REGM data-state notes"
          >
            {dataState && dataState !== "ok" ? (
              <Pill tone="warn" variant="soft" withDot={false}>
                data_state: {dataState}
              </Pill>
            ) : null}
            {warnings.map((w, i) => (
              <span key={i} style={muteTextStyle}>
                {w}
              </span>
            ))}
          </section>
        ) : null}

        {rows.length > 0 ? (
          <table style={tableStyle} aria-label="REGM indicator table">
            <thead>
              <tr>
                <th style={thStyle}>Component</th>
                <th style={thStyle}>Label</th>
                <th style={thStyle}>Value</th>
                <th style={thStyle}>Rule</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const unknown =
                  row.value == null || !Number.isFinite(row.value);
                return (
                  <tr key={`${row.component ?? "row"}-${i}`}>
                    <td style={tdStyle}>{row.component ?? "—"}</td>
                    <td style={tdStyle}>
                      {isUnknownValue(row.label) ? (
                        <Pill tone="warn" variant="soft" withDot={false}>
                          {row.label ?? "unknown"}
                        </Pill>
                      ) : (
                        (row.label ?? "—")
                      )}
                    </td>
                    <td style={{ ...tdStyle, fontFamily: "JetBrains Mono, monospace" }}>
                      {unknown
                        ? "—"
                        : `${(row.value as number).toFixed(2)}${row.unit ? ` ${row.unit}` : ""}`}
                    </td>
                    <td style={tdStyle}>{row.rule ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <span style={muteTextStyle}>no indicator rows returned</span>
        )}

        {payload?.methodology ? (
          <div style={methodologyStyle} aria-label="REGM methodology">
            {payload.methodology}
          </div>
        ) : null}
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Market Regime — ${payload?.symbol ?? effectiveSymbol ?? ""}`}
          subtitle={`trend · vol · drawdown · curve over ${days}d lookback`}
          trailing={
            <FunctionControlGroup>
              <SegmentedControl
                label="LOOKBACK"
                value={days}
                options={DAYS_OPTIONS}
                onChange={setDays}
                title="Benchmark history window"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Re-classify regime"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="sources" value={data?.sources?.join(", ") || "—"} />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="data_state" value={dataState ?? "—"} />
          <StatusDivider />
          <StatusSection
            label="confidence"
            value={
              confidence != null && Number.isFinite(confidence)
                ? confidence.toFixed(2)
                : "—"
            }
          />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="last" value={`${days}d`} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/**
 * One regime card: the value is rendered verbatim from the backend.
 * Unknown values (UNKNOWN / null / "Cannot classify …") get an explicit
 * warn state — never replaced with a guessed classification.
 */
function RegimeCard({ label, value }: { label: string; value: string | null }) {
  const unknown = isUnknownValue(value);
  return (
    <div style={cardStyle} aria-label={`REGM card ${label}`}>
      <div style={cardLabelStyle}>{label}</div>
      <div
        style={{
          ...cardValueStyle,
          color: unknown ? "var(--text-mute)" : "var(--text-primary)",
        }}
      >
        {unknown ? (value && value.trim() !== "" && value !== "—" ? value : "UNKNOWN") : value}
      </div>
      {unknown ? (
        <Pill tone="warn" variant="soft" withDot={false}>
          not reported — not guessed
        </Pill>
      ) : null}
    </div>
  );
}

const cardGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
  gap: 10,
};

const cardStyle: CSSProperties = {
  display: "grid",
  gap: 4,
  padding: "10px 12px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "var(--surface-1)",
  alignItems: "start",
};

const cardLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  letterSpacing: "0.06em",
  color: "var(--text-mute)",
  textTransform: "uppercase",
};

const cardValueStyle: CSSProperties = {
  fontSize: 14,
  fontWeight: 600,
  overflowWrap: "anywhere",
};

const stateStripStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  flexWrap: "wrap",
  border: "1px dashed var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "6px 10px",
};

const tableStyle: CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: 11,
};

const thStyle: CSSProperties = {
  textAlign: "left",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--text-mute)",
  borderBottom: "1px solid var(--border-subtle)",
  padding: "4px 8px",
};

const tdStyle: CSSProperties = {
  borderBottom: "1px solid var(--border-subtle)",
  padding: "5px 8px",
  color: "var(--text-primary)",
  overflowWrap: "anywhere",
};

const methodologyStyle: CSSProperties = {
  fontSize: 10,
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-mute)",
  border: "1px dashed var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "6px 10px",
};

const muteTextStyle: CSSProperties = {
  fontSize: 11,
  color: "var(--text-mute)",
};
