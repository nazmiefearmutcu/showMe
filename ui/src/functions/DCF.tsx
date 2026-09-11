/**
 * DCF — Discounted Cash Flow (two-stage FCFE valuation).
 *
 * Fully input-driven model desk: FCFE base ($M), shares ($M), high
 * growth %, terminal growth %, WACC % (all persisted under
 * `showme.dcf.*`) and a years segment drive the backend's two-stage
 * FCFE model. Headline cards put the model's fair value per share next
 * to a user-entered market mark (implied upside); the body shows the
 * discounted-cashflow table and the PV → equity-value bridge.
 *
 * Data honesty: this is a model, not a quote — when the backend reports
 * needs_input (e.g. no provider FCFE) or a model error (wacc ≤ terminal
 * growth) the pane surfaces that state verbatim instead of dressing up
 * the numbers.
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
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { defaultSymbolForFunction } from "@/lib/symbols";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import {
  usePersistentNumber,
  usePersistentOption,
} from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface DCFCashflowRow {
  year?: number;
  fcfe?: number;
  pv?: number;
  discount_factor?: number;
}

interface DCFBridgeRow {
  component?: string;
  value?: number;
}

interface DCFData {
  status?: string;
  error?: string;
  wacc?: number;
  g_high?: number;
  g_terminal?: number;
  years?: number;
  starting_fcfe?: number;
  pv_explicit?: number;
  terminal_value?: number;
  pv_terminal?: number;
  equity_value?: number;
  fair_value_per_share?: number | null;
  shares_outstanding?: number | null;
  rows?: DCFCashflowRow[];
  bridge?: DCFBridgeRow[];
  methodology?: string;
}

const YEARS_OPTIONS = [
  { value: 3, label: "3y" },
  { value: 5, label: "5y" },
  { value: 7, label: "7y" },
  { value: 10, label: "10y" },
] as const;
const YEARS_IDS = YEARS_OPTIONS.map((o) => o.value);

export function DCFPane({ code, symbol }: FunctionPaneProps) {
  const [fcfeM, setFcfeM] = usePersistentNumber("showme.dcf.fcfe", 10_000);
  const [sharesM, setSharesM] = usePersistentNumber("showme.dcf.shares", 15_000);
  const [growthPct, setGrowthPct] = usePersistentNumber("showme.dcf.growth", 10);
  const [termPct, setTermPct] = usePersistentNumber("showme.dcf.gterm", 2.5);
  const [waccPct, setWaccPct] = usePersistentNumber("showme.dcf.wacc", 8);
  const [markPct, setMarkPct] = usePersistentNumber("showme.dcf.price", 0);
  const [years, setYears] = usePersistentOption<number>(
    "showme.dcf.years",
    YEARS_IDS,
    5,
  );
  const effectiveSymbol =
    symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const { state, data, error, refetch } = useFunction<DCFData>({
    code,
    symbol: effectiveSymbol,
    params: {
      fcfe: fcfeM * 1e6,
      shares_outstanding: sharesM * 1e6,
      growth_high: round6(growthPct / 100),
      growth_terminal: round6(termPct / 100),
      wacc: round6(waccPct / 100),
      years,
    },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const cashflows = useMemo(() => payload?.rows ?? [], [payload]);
  const bridge = useMemo(() => payload?.bridge ?? [], [payload]);
  const status = payload?.status ?? "—";
  const modelError = payload?.error ?? null;
  const needsInput = status === "needs_input";

  const fairValue = payload?.fair_value_per_share ?? null;
  const mark = markPct > 0 ? markPct : null;
  const upsidePct =
    fairValue != null && mark != null && mark > 0
      ? (fairValue / mark - 1) * 100
      : null;

  const CF_COLS: DataGridColumn<DCFCashflowRow>[] = useMemo(
    () => [
      {
        key: "year",
        header: "Year",
        numeric: true,
        width: 84,
        render: (r) => (
          <span style={monoStrongStyle}>{r.year ?? "—"}</span>
        ),
      },
      {
        key: "fcfe",
        header: "FCFE",
        numeric: true,
        width: 124,
        render: (r) => (
          <span style={monoPrimaryStyle}>{fmtMoney(r.fcfe)}</span>
        ),
      },
      {
        key: "pv",
        header: "PV @ WACC",
        numeric: true,
        width: 124,
        render: (r) => (
          <span style={monoPrimaryStyle}>{fmtMoney(r.pv)}</span>
        ),
      },
      {
        key: "discount_factor",
        header: "DF",
        numeric: true,
        width: 104,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtFixed(r.discount_factor, 4)}</span>
        ),
      },
    ],
    [],
  );

  const BRIDGE_COLS: DataGridColumn<DCFBridgeRow>[] = useMemo(
    () => [
      {
        key: "component",
        header: "Component",
        width: 190,
        render: (r) => <span style={monoStrongStyle}>{r.component ?? "—"}</span>,
      },
      {
        key: "value",
        header: "Value",
        numeric: true,
        width: 150,
        render: (r) => <span style={monoPrimaryStyle}>{fmtMoney(r.value)}</span>,
      },
    ],
    [],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="DCF needs an equity ticker to value." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
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
  ) : cashflows.length === 0 ? (
    <Empty
      title={modelError ? "Model error" : "No model output"}
      body={
        modelError ??
        "The DCF engine returned no cashflow rows — check the inputs."
      }
      icon={modelError ? "!" : "∅"}
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={inputsRowStyle} aria-label="DCF model inputs">
        <NumField
          label="FCFE $M"
          ariaLabel="FCFE base in millions"
          value={fcfeM}
          onCommit={setFcfeM}
          step={500}
          min={0}
        />
        <NumField
          label="SHARES M"
          ariaLabel="Shares outstanding in millions"
          value={sharesM}
          onCommit={setSharesM}
          step={100}
          min={0}
        />
        <NumField
          label="GROWTH %"
          ariaLabel="High growth percent"
          value={growthPct}
          onCommit={setGrowthPct}
          step={0.5}
          min={-50}
        />
        <NumField
          label="TERM G %"
          ariaLabel="Terminal growth percent"
          value={termPct}
          onCommit={setTermPct}
          step={0.25}
          min={0}
        />
        <NumField
          label="WACC %"
          ariaLabel="WACC percent"
          value={waccPct}
          onCommit={setWaccPct}
          step={0.25}
          min={0}
        />
        <NumField
          label="MARK $"
          ariaLabel="Market price per share for comparison"
          value={markPct}
          onCommit={setMarkPct}
          step={1}
          min={0}
        />
      </section>
      {modelError ? (
        <div role="note" style={errorNoticeStyle}>
          <strong>Model error.</strong> {modelError} — adjust WACC or terminal
          growth; no valuation is shown.
        </div>
      ) : null}
      {needsInput && !modelError ? (
        <div role="note" style={noticeStyle}>
          <strong>Needs input.</strong> The backend marked this run
          needs_input (typically missing provider FCFE) — override FCFE or
          shares for a tradable model.
        </div>
      ) : null}
      <section style={kpiGridStyle} aria-label="DCF headline">
        <StatCard
          label="Fair value / share"
          value={fmtFixed(fairValue, 2)}
          caption={`EQUITY ${fmtMoney(payload?.equity_value)} · ${payload?.years ?? years}Y`}
          tone="neutral"
        />
        <StatCard
          label="Implied upside"
          value={
            upsidePct != null ? `${upsidePct >= 0 ? "+" : ""}${upsidePct.toFixed(1)}%` : "—"
          }
          caption={mark != null ? `VS MARK $${mark.toFixed(2)}` : "SET MARK $ TO COMPARE"}
          tone={upsidePct != null ? (upsidePct >= 0 ? "positive" : "negative") : "neutral"}
        />
        <StatCard
          label="PV explicit"
          value={fmtMoney(payload?.pv_explicit)}
          caption={`START FCFE ${fmtMoney(payload?.starting_fcfe)}`}
          tone="neutral"
        />
        <StatCard
          label="PV terminal"
          value={fmtMoney(payload?.pv_terminal)}
          caption={`G_HIGH ${fmtPct(payload?.g_high)} · G_TERM ${fmtPct(payload?.g_terminal)}`}
          tone="neutral"
        />
      </section>
      <div>
        <div style={gridTitleStyle}>discounted FCFE forecast</div>
        <DataGrid
          columns={CF_COLS}
          rows={cashflows}
          rowKey={(r, i) => `${r.year ?? "y"}-${i}`}
          density="compact"
          ariaLabel="DCF cashflow table"
        />
      </div>
      <div>
        <div style={gridTitleStyle}>value bridge</div>
        <DataGrid
          columns={BRIDGE_COLS}
          rows={bridge}
          rowKey={(r, i) => `${r.component ?? "c"}-${i}`}
          density="compact"
          ariaLabel="DCF value bridge"
        />
      </div>
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`DCF — ${effectiveSymbol ?? ""}`}
          subtitle={`two-stage FCFE · ${payload?.years ?? years}y @ WACC ${fmtPct(payload?.wacc ?? round6(waccPct / 100))}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                model
              </Pill>
              <SegmentedControl
                label="YEARS"
                value={years}
                options={YEARS_OPTIONS}
                onChange={setYears}
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Recompute DCF"
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
          <StatusSection label="shares" value={fmtCompact(payload?.shares_outstanding)} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="fcfe" value={`${fcfeM}M`} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── input field ───────────────────────────────────────────────────── */

function NumField({
  label,
  ariaLabel,
  value,
  onCommit,
  step,
  min,
}: {
  label: string;
  ariaLabel: string;
  value: number;
  onCommit: (next: number) => void;
  step: number;
  min: number;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => {
    setDraft(String(value));
  }, [value]);
  return (
    <label style={fieldRowStyle}>
      <span style={fieldLabelStyle}>{label}</span>
      <input
        type="number"
        aria-label={ariaLabel}
        value={draft}
        step={step}
        min={min}
        onChange={(e) => {
          setDraft(e.target.value);
          const n = Number(e.target.value);
          if (e.target.value.trim() !== "" && Number.isFinite(n) && n >= min) {
            onCommit(n);
          }
        }}
        onBlur={() => setDraft(String(value))}
        style={numInputStyle}
      />
    </label>
  );
}

/* ── helpers ───────────────────────────────────────────────────────── */

function round6(v: number): number {
  return Math.round(v * 1e6) / 1e6;
}

function fmtMoney(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${v.toFixed(0)}`;
}

function fmtFixed(v: number | null | undefined, digits: number): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

function fmtCompact(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(0)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
  return String(v);
}

/* ── styles ────────────────────────────────────────────────────────── */

const inputsRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 12,
  alignItems: "flex-end",
};

const fieldRowStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 3,
};

const fieldLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  color: "var(--text-mute)",
  letterSpacing: "0.06em",
};

const numInputStyle: CSSProperties = {
  width: 84,
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: "var(--font-size-sm)",
  padding: "2px 4px",
  border: "1px solid var(--border-row)",
  borderRadius: 3,
  background: "var(--surface-1)",
  color: "var(--text-primary)",
};

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const gridTitleStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  letterSpacing: "0.05em",
  marginBottom: 6,
};

const noticeStyle: CSSProperties = {
  border: "1px solid var(--warn, var(--text-mute))",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: "var(--font-size-md)",
  color: "var(--text-primary)",
};

const errorNoticeStyle: CSSProperties = {
  border: "1px solid var(--negative, var(--text-mute))",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: "var(--font-size-md)",
  color: "var(--text-primary)",
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
