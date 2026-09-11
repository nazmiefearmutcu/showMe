/**
 * FRH — Funding Rate Heatmap.
 *
 * Symbols × funding-rate grid over the perpetual-futures payload (Binance /
 * Bybit / OKX columns + cross-exchange average). Positive rates tint one way
 * (longs pay shorts), negative the other (shorts pay longs) via the shared
 * heat tokens; cells the backend could not fill (exchange returned nothing,
 * provider_count 0) render an honest "—", never a zero.
 *
 * Honesty: the backend's non-live path returns a synthetic sizing template
 * (sources=funding_rate_model, payload.live=false). That mode renders a
 * prominent "Model template" badge + inline "NOT live funding rates" note —
 * switching MODE to Live fetches real exchange data. The payload has no
 * funding-interval field, so no interval control is offered (the unit is
 * whatever the backend reports, per interval).
 */
import { useMemo, type CSSProperties } from "react";
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
  intensityToken,
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

interface FRHRow {
  symbol?: string;
  binance?: number | null;
  bybit?: number | null;
  okx?: number | null;
  avg?: number | null;
  rate?: number | null;
  interpretation?: string | null;
  provider_count?: number | null;
}

interface FRHData {
  surface?: FRHRow[];
  rows?: FRHRow[];
  exchanges?: string[];
  unit?: string;
  live?: boolean;
  methodology?: string;
}

type ModeOption = "template" | "live";

const MODE_OPTIONS: { value: ModeOption; label: string }[] = [
  { value: "template", label: "Template" },
  { value: "live", label: "Live" },
];

type LimitOption = 10 | 25 | 50 | 100;

const LIMIT_OPTIONS: LimitOption[] = [10, 25, 50, 100];

/** Floor for the tint scale so an all-zero grid still maps to step 0. */
const RANGE_FLOOR = 0.0005;

function fmtRate(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${(value * 100).toFixed(4)}%`;
}

export function FRHPane({ code, symbol }: FunctionPaneProps) {
  const [mode, setMode] = usePersistentOption<ModeOption>(
    "showme.frh.mode",
    MODE_OPTIONS.map((o) => o.value),
    "template",
  );
  const [limit, setLimit] = usePersistentOption<LimitOption>(
    "showme.frh.limit",
    LIMIT_OPTIONS,
    25,
  );

  const { state, data, error, refetch } = useFunction<FRHData>({
    code,
    symbol: symbol || undefined,
    params: {
      limit,
      // Template mode must send the explicit reference flag: the backend's
      // default polarity treats an ABSENT live/reference param as live, so
      // omitting it silently fetched live exchange data under the Template
      // label. Live mode keeps the explicit live flag.
      ...(mode === "live" ? { live: true } : { reference: true }),
    },
  });

  const payload = data?.data;
  const status = data?.status ?? "—";
  const rows = useMemo<FRHRow[]>(
    () => (Array.isArray(payload?.rows) ? payload.rows : Array.isArray(payload?.surface) ? payload.surface : []),
    [payload],
  );
  const exchanges = useMemo<string[]>(() => {
    const list = payload?.exchanges;
    return Array.isArray(list) && list.length > 0 ? list : ["binance", "bybit", "okx"];
  }, [payload]);
  const isTemplate = payload?.live === false;

  const range = useMemo(() => {
    let maxAbs = 0;
    for (const row of rows) {
      for (const key of [...exchanges, "avg"]) {
        const value = row[key as keyof FRHRow];
        if (typeof value === "number" && Number.isFinite(value)) {
          maxAbs = Math.max(maxAbs, Math.abs(value));
        }
      }
    }
    return maxAbs > 0 ? maxAbs : RANGE_FLOOR;
  }, [rows, exchanges]);

  const body =
    state === "loading" || state === "idle" ? (
      <div className="u-grid-gap-8">
        <Skeleton height={22} />
        <Skeleton height={200} />
        <Skeleton height={20} width="70%" />
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
    ) : rows.length === 0 ? (
      <Empty
        title="No funding rows returned"
        body="No perpetual funding snapshot came back for this symbol set — nothing is fabricated while the exchanges are unreachable."
        icon="▦"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : (
      <div className="u-grid-gap-14">
        {isTemplate ? (
          <section style={templateNoteStyle} aria-label="FRH template warning">
            <Pill tone="warn" variant="filled" withDot={false}>
              Model template
            </Pill>
            <span style={templateTextStyle}>
              These rows are a backend sizing template (funding_rate_model),
              NOT live funding rates. Switch MODE to Live for real exchange
              data.
            </span>
          </section>
        ) : (
          <section style={legendStyle} aria-label="FRH legend">
            <span aria-hidden="true" style={swatchStyle} />
            <span style={legendTextStyle}>longs pay shorts</span>
            <span aria-hidden="true" style={{ ...swatchStyle, background: intensityToken(-RANGE_FLOOR, RANGE_FLOOR) }} />
            <span style={legendTextStyle}>shorts pay longs</span>
            <span style={legendTextStyle}>
              · cell values are {payload?.unit ?? "fraction per funding interval"}
            </span>
          </section>
        )}

        <div
          style={{
            ...gridStyle,
            gridTemplateColumns: `minmax(110px, 1.2fr) repeat(${exchanges.length + 1}, minmax(84px, 1fr)) minmax(120px, 1.2fr)`,
          }}
          role="table"
          aria-label="Funding rate heatmap"
        >
          <div style={rowGridStyle} role="row" aria-label="Funding rate columns">
            <HeaderCell text="Symbol" />
            {exchanges.map((ex) => (
              <HeaderCell key={ex} text={ex} />
            ))}
            <HeaderCell text="avg" />
            <HeaderCell text="signal" />
          </div>
          {rows.map((row) => {
            const sym = row.symbol ?? "—";
            return (
              <div
                key={sym}
                style={rowGridStyle}
                role="row"
                aria-label={`${sym} funding row`}
              >
                <div style={symbolStyle}>{sym}</div>
                {exchanges.map((ex) => {
                  const value = row[ex as keyof FRHRow];
                  return (
                    <RateCell
                      key={ex}
                      value={typeof value === "number" ? value : null}
                      range={range}
                      ariaLabel={`${sym} ${ex} funding ${typeof value === "number" ? fmtRate(value) : "missing"}`}
                    />
                  );
                })}
                <RateCell
                  value={typeof row.avg === "number" ? row.avg : null}
                  range={range}
                  ariaLabel={`${sym} avg funding ${typeof row.avg === "number" ? fmtRate(row.avg) : "missing"}`}
                />
                <div style={signalStyle}>{row.interpretation ?? "—"}</div>
              </div>
            );
          })}
        </div>

        {payload?.methodology ? (
          <div style={methodologyStyle} aria-label="FRH methodology">
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
          title="Funding Rate Heatmap"
          subtitle={`${rows.length} symbols · ${exchanges.join(" / ")}${isTemplate ? " · template" : " · live"}`}
          trailing={
            <FunctionControlGroup>
              <SegmentedControl
                label="MODE"
                value={mode}
                options={MODE_OPTIONS}
                onChange={setMode}
                title="Template vs live exchange funding"
              />
              <SegmentedControl
                label="SYMBOLS"
                value={limit}
                options={LIMIT_OPTIONS}
                onChange={setLimit}
                title="Symbol count"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Re-fetch funding snapshot"
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
          <StatusSection label="mode" value={isTemplate ? "template" : "live"} />
          <StatusDivider />
          <StatusSection label="symbols" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="last" value={limit} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function HeaderCell({ text }: { text: string }) {
  return (
    <div
      style={headerCellStyle}
      role="columnheader"
    >
      {text}
    </div>
  );
}

function RateCell({
  value,
  range,
  ariaLabel,
}: {
  value: number | null;
  range: number;
  ariaLabel: string;
}) {
  const finite = value != null && Number.isFinite(value);
  const ratio = finite ? Math.min(1, Math.abs(value) / range) : 0;
  return (
    <div
      role="cell"
      aria-label={ariaLabel}
      style={{
        ...cellStyle,
        background: finite ? intensityToken(value as number, range) : "transparent",
        color:
          ratio > 0.5 ? "var(--text-display)" : "var(--text-secondary)",
      }}
    >
      {finite ? fmtRate(value as number) : "—"}
    </div>
  );
}

const gridStyle: CSSProperties = {
  display: "grid",
  gap: 2,
  alignItems: "stretch",
};

const rowGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "subgrid",
  gridColumn: "1 / -1",
};

const headerCellStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--text-mute)",
  padding: "2px 6px",
  textAlign: "right",
};

const cellStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
  fontVariantNumeric: "tabular-nums",
  textAlign: "right",
  padding: "4px 6px",
  border: "1px solid var(--border-row)",
};

const symbolStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
  color: "var(--text-primary)",
  padding: "4px 6px",
  textAlign: "left",
  alignSelf: "center",
};

const signalStyle: CSSProperties = {
  fontSize: "var(--font-size-sm)",
  color: "var(--text-mute)",
  padding: "4px 6px",
  textAlign: "left",
  alignSelf: "center",
  overflowWrap: "anywhere",
};

const legendStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
};

const legendTextStyle: CSSProperties = {
  fontSize: "var(--font-size-sm)",
  color: "var(--text-mute)",
};

const swatchStyle: CSSProperties = {
  width: 14,
  height: 10,
  border: "1px solid var(--border-row)",
  background: intensityToken(RANGE_FLOOR, RANGE_FLOOR),
};

const templateNoteStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  flexWrap: "wrap",
  border: "1px dashed var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "6px 10px",
};

const templateTextStyle: CSSProperties = {
  fontSize: "var(--font-size-sm)",
  color: "var(--text-mute)",
};

const methodologyStyle: CSSProperties = {
  fontSize: "var(--font-size-2xs)",
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-mute)",
  border: "1px dashed var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "6px 10px",
};
