/**
 * WACC — Weighted Average Cost of Capital.
 *
 * The sidecar derives WACC = (E/V × Re) + (D/V × Rd × (1 − T)) where
 * Re = rf + β × ERP. Inputs come from FRED (rf, Rd), yfinance (E, D,
 * country), the BetaFunction (β), and Damodaran (ERP). The panel:
 *   - Surfaces the headline WACC + a 5-row component table.
 *   - Renders the β / Rd sensitivity surface as a 3 × 3 heat grid so
 *     the user can read the WACC range at a glance.
 *   - Lists `warnings` and the resolved `sources` so the user can tell
 *     when the function fell back to FRED-default stubs.
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
import { useUtcStamp } from "@/lib/useUtcStamp";
import { defaultSymbolForFunction } from "@/lib/symbols";
import { maxOf, minOf } from "@/lib/maxOf";
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
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface WACCRow {
  component?: string;
  value?: number;
  formula?: string;
}

interface WACCSurfaceCell {
  bucket?: string;
  beta?: number;
  rd?: number;
  wacc?: number;
}

interface WACCPayload {
  status?: string;
  reason?: string;
  wacc?: number;
  re_capm?: number;
  rf?: number;
  beta?: number;
  erp?: number;
  rd?: number;
  tax_rate?: number;
  equity_weight?: number;
  debt_weight?: number;
  rows?: WACCRow[];
  surface?: WACCSurfaceCell[];
  methodology?: string;
  field_dictionary?: Record<string, string>;
  beta_source?: string;
  beta_window?: string | null;
  erp_source?: string;
  tax_source?: string;
  assumptions?: {
    market_premium?: number | null;
    beta_window?: string | null;
    beta_window_applied?: string | null;
    tax_rate_override?: number | null;
  };
  data_state?: string;
}

export function WACCPane({ code, symbol }: FunctionPaneProps) {
  // Bug #17 fix: do not hardcode "AAPL". Use the asset-class-aware default
  // so the recent-symbols history + WACC's EQUITY fallback decide the
  // symbol, mirroring every other equity pane.
  const resolvedSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY"]);

  // WACC#5: the assumptions the manifest declares. Rates are typed in percent
  // and sent as decimals; null means "not set", so the function resolves it.
  const [marketPremium, setMarketPremium] = useState<number | null>(null);
  const [betaWindow, setBetaWindow] = useState<string>("");
  const [betaInput, setBetaInput] = useState<number | null>(null);
  const [rf, setRf] = useState<number | null>(null);
  const [rd, setRd] = useState<number | null>(null);
  const [taxOverride, setTaxOverride] = useState<number | null>(null);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    symbol: resolvedSymbol,
    params: {
      market_premium: marketPremium ?? undefined,
      beta_window: betaWindow || undefined,
      beta: betaInput ?? undefined,
      rf: rf ?? undefined,
      rd: rd ?? undefined,
      tax_rate_override: taxOverride ?? undefined,
    },
  });

  const payload = useMemo<WACCPayload>(
    () =>
      data?.data && typeof data.data === "object" && !Array.isArray(data.data)
        ? (data.data as WACCPayload)
        : {},
    [data?.data],
  );

  const rows = useMemo<WACCRow[]>(
    () => (Array.isArray(payload.rows) ? payload.rows : []),
    [payload.rows],
  );

  const surface = useMemo<WACCSurfaceCell[]>(
    () => (Array.isArray(payload.surface) ? payload.surface : []),
    [payload.surface],
  );

  const utcStamp = useUtcStamp(data);
  const warnings = Array.isArray(data?.warnings) ? data?.warnings : [];
  const sources = Array.isArray(data?.sources) ? data?.sources : [];
  const fellBack = warnings.some((w) => /fred|damodaran|yfinance|beta/i.test(String(w)));
  // WACC#6: a labelled default or stale snapshot input makes the result partial.
  const partialInputs = payload.data_state === "partial";
  const syntheticBeta = payload.data_state === "synthetic_beta"
    || sources.some((s) => String(s).toLowerCase() === "synthetic_beta");

  const cols = useMemo<DataGridColumn<WACCRow>[]>(
    () => [
      {
        key: "component",
        header: "Component",
        width: 220,
        render: (r) => (
          <span style={componentCell}>
            {r.component ?? "—"}
          </span>
        ),
      },
      {
        key: "value",
        header: "Value",
        numeric: true,
        width: 140,
        render: (r) =>
          r.value == null ? "—" : (
            <span style={numCell}>
              {(r.value * 100).toFixed(2)}%
            </span>
          ),
      },
      {
        key: "formula",
        header: "Formula",
        render: (r) => (
          <span className="u-text-mute" style={{ fontSize: "var(--font-size-xs)" }}>
            {r.formula ?? "—"}
          </span>
        ),
      },
    ],
    [],
  );

  // CSV export of the component table — RAW decimals (0.0842, not "8.42%").
  const csvColumns = useMemo<GridCsvColumn<WACCRow>[]>(
    () => [
      { key: "component", header: "Component", value: (r) => r.component ?? "" },
      { key: "value", header: "Value", value: (r) => r.value ?? "" },
      { key: "formula", header: "Formula", value: (r) => r.formula ?? "" },
    ],
    [],
  );

  const exportCsv = () => {
    const csv = buildGridCsv(csvColumns, rows);
    downloadGridCsv(gridCsvFilename(`wacc-${resolvedSymbol}`), csv);
  };

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`WACC · ${resolvedSymbol}`}
          subtitle={`E ${pct(payload.equity_weight)} · D ${pct(payload.debt_weight)} · Tax ${pct(payload.tax_rate)}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {sources.length || 0} src
              </Pill>
              <Pill tone="accent" variant="soft" withDot={false}>{utcStamp} UTC</Pill>
              {syntheticBeta ? (
                <span data-testid="wacc-beta-pill" data-beta-state="synthetic">
                  <Pill tone="warn" variant="soft">synthetic β</Pill>
                </span>
              ) : payload.beta_source && payload.beta_source !== "user_input" ? (
                <span data-testid="wacc-beta-pill" data-beta-state="live">
                  <Pill tone="positive" variant="soft">
                    β {String(payload.beta_window ?? "").toLowerCase() || "live"}
                  </Pill>
                </span>
              ) : null}
              <Pill tone={partialInputs || fellBack ? "warn" : "positive"} variant="soft">
                {partialInputs
                  ? "partial inputs"
                  : payload.data_state === "user_input"
                    ? "user input"
                    : fellBack ? "fallback active" : "live"}
              </Pill>
              <button
                type="button"
                className="btn"
                onClick={exportCsv}
                disabled={rows.length === 0}
                title="Download CSV"
                aria-label={`Download ${rows.length} WACC components as CSV`}
              >
                CSV
              </button>
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <section style={inputGrid} aria-label="WACC assumptions">
            <OptionalNumberField
              label="ERP %"
              ariaLabel="Equity risk premium (ERP) %"
              value={marketPremium}
              scale={100}
              min={2}
              max={12}
              step={0.25}
              placeholder="Damodaran"
              onCommit={setMarketPremium}
            />
            <label style={inputField}>
              <span style={inputLabel}>Beta window</span>
              <select
                aria-label="Beta window"
                value={betaWindow}
                onChange={(e) => setBetaWindow(e.target.value)}
                style={inputControl}
              >
                <option value="">auto (5Y, 2Y, 1Y)</option>
                <option value="252d">252d (1Y)</option>
                <option value="504d">504d (2Y)</option>
              </select>
            </label>
            <OptionalNumberField
              label="β"
              ariaLabel="Beta (β)"
              value={betaInput}
              min={0}
              max={5}
              step={0.01}
              placeholder="BetaFunction"
              onCommit={setBetaInput}
            />
            <OptionalNumberField
              label="rf %"
              ariaLabel="Risk-free rate (rf) %"
              value={rf}
              scale={100}
              min={0}
              max={20}
              step={0.05}
              placeholder="FRED DGS10"
              onCommit={setRf}
            />
            <OptionalNumberField
              label="Rd %"
              ariaLabel="Pre-tax cost of debt (Rd) %"
              value={rd}
              scale={100}
              min={0}
              max={30}
              step={0.05}
              placeholder="issuer / FRED"
              onCommit={setRd}
            />
            <OptionalNumberField
              label="Tax override %"
              ariaLabel="Tax rate override %"
              value={taxOverride}
              scale={100}
              min={0}
              max={45}
              step={0.5}
              placeholder="issuer / statutory"
              onCommit={setTaxOverride}
            />
          </section>
          {state === "loading" || state === "idle" ? (
            <Skeleton height={300} />
          ) : state === "error" ? (
            <Empty title="Function error" body={error?.message ?? "—"} icon="!" />
          ) : payload.status === "not_applicable" ? (
            <Empty
              title="WACC not applicable"
              body={payload.reason ?? "WACC is not meaningful for this financial issuer; use the cost of equity."}
              icon="!"
            />
          ) : payload.status === "provider_unavailable" ? (
            <Empty
              title="WACC not available"
              body={payload.reason ?? "A required WACC input is unavailable from the providers, so no discount rate is reported."}
              icon="!"
            />
          ) : payload.wacc == null ? (
            <Empty title="No WACC payload" body={`The ${code} function returned no result.`} />
          ) : (
            <div className="u-grid-gap-14">
              {fellBack ? (
                <div style={warningBox}>
                  <strong className="u-text-warn">Provider fallback</strong>
                  <ul style={warningList}>
                    {warnings.slice(0, 4).map((w, i) => (
                      <li key={i} className="u-text-secondary">{String(w)}</li>
                    ))}
                  </ul>
                  <span className="u-text-mute" style={{ fontSize: "var(--font-size-xs)" }}>
                    Sidecar fell back to FRED/yfinance defaults — WACC is
                    deterministic but the inputs are not all live.
                  </span>
                </div>
              ) : null}
              <section style={kpiGrid} aria-label="WACC KPI ribbon">
                <StatCard
                  label="WACC"
                  value={pct(payload.wacc)}
                  caption={`Re ${pct(payload.re_capm)} · Rd ${pct(payload.rd)}`}
                  tone="neutral"
                />
                <StatCard
                  label="Cost of equity"
                  value={pct(payload.re_capm)}
                  caption={`rf ${pct(payload.rf)} · β ${beta(payload.beta)} · ERP ${pct(payload.erp)}`}
                  tone="positive"
                />
                <StatCard
                  label="Cost of debt (after-tax)"
                  value={afterTaxCostOfDebt(payload.rd, payload.tax_rate)}
                  caption={`Rd ${pct(payload.rd)} · Tax ${pct(payload.tax_rate)}`}
                  tone="negative"
                />
                <StatCard
                  label="Capital structure"
                  value={`E/D ${ratio(payload.equity_weight, payload.debt_weight)}`}
                  caption={`E ${pct(payload.equity_weight)} · D ${pct(payload.debt_weight)}`}
                  tone="neutral"
                />
              </section>
              <SensitivitySurface cells={surface} baseWacc={payload.wacc} />
              <DataGrid
                columns={cols}
                rows={rows}
                rowKey={(r, i) => `${r.component ?? "row"}-${i}`}
                density="compact"
              />
              {payload.methodology ? (
                <div style={methodologyBox}>
                  <strong className="u-text-secondary">Methodology</strong>
                  <span>{payload.methodology}</span>
                </div>
              ) : null}
              <div style={methodologyBox} aria-label="WACC assumptions applied">
                <strong className="u-text-secondary">Assumptions applied</strong>
                <span className="u-text-mute" style={{ fontSize: "var(--font-size-xs)" }}>
                  ERP {payload.erp_source ?? "—"} · β window {payload.beta_window ?? payload.assumptions?.beta_window_applied ?? "—"}
                  {" "}· tax {payload.tax_source ?? "—"}
                </span>
              </div>
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={sources.join(", ") || "—"} />
          <StatusDivider />
          <StatusSection label="symbol" value={resolvedSymbol} />
          <StatusDivider />
          <StatusSection label="rows" value={rows.length} />
          <StatusDivider />
          <StatusSection label="surface" value={surface.length} />
          <StatusDivider />
          <StatusSection label="elapsed" value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function SensitivitySurface({ cells, baseWacc }: { cells: WACCSurfaceCell[]; baseWacc?: number }) {
  if (!cells.length || baseWacc == null) return null;
  const valid = cells.filter((c) => typeof c.wacc === "number");
  if (!valid.length) return null;
  // UA-HIGH-12: stack-safe.
  const waccs = valid.map((c) => c.wacc ?? 0);
  const minWacc = minOf(waccs);
  const maxWacc = maxOf(waccs);
  const range = Math.max(0.0001, maxWacc - minWacc);
  return (
    <section style={surfaceWrap} aria-label="WACC sensitivity surface">
      <header style={surfaceHeader}>
        <strong className="u-text-display">β × Rd sensitivity</strong>
        <span className="u-text-mute" style={{ fontSize: "var(--font-size-xs)" }}>
          {valid.length} buckets · range {pct(minWacc)} → {pct(maxWacc)}
        </span>
      </header>
      <div style={surfaceGrid}>
        {valid.map((c, i) => {
          const normalised = ((c.wacc ?? 0) - minWacc) / range;
          const tone = (c.wacc ?? 0) >= baseWacc ? "var(--negative)" : "var(--positive)";
          const intensity = 0.2 + normalised * 0.6;
          return (
            <div
              key={i}
              style={{
                ...surfaceCell,
                background: `color-mix(in srgb, ${tone} ${(intensity * 100).toFixed(0)}%, var(--surface-2))`,
              }}
              title={c.bucket ?? ""}
            >
              <strong style={surfaceCellValue}>{pct(c.wacc)}</strong>
              <span style={surfaceCellLabel}>
                β {c.beta?.toFixed(2) ?? "—"} · Rd {pct(c.rd)}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/**
 * Optional assumption field. Commits on blur or Enter. An empty field clears
 * the override (null, so nothing is sent). A value is clamped to [min, max] in
 * display units and sent as value / scale (a percent field sends a decimal).
 */
function OptionalNumberField({
  label,
  ariaLabel,
  value,
  scale = 1,
  min,
  max,
  step,
  placeholder,
  onCommit,
}: {
  label: string;
  ariaLabel: string;
  value: number | null;
  scale?: number;
  min: number;
  max: number;
  step: number;
  placeholder: string;
  onCommit: (next: number | null) => void;
}) {
  const shown = value == null ? "" : String(Number((value * scale).toFixed(6)));
  const [draft, setDraft] = useState(shown);
  const [lastShown, setLastShown] = useState(shown);
  if (shown !== lastShown) {
    // The committed value changed outside this field: resync the draft.
    setLastShown(shown);
    setDraft(shown);
  }
  const commit = () => {
    if (draft.trim() === "") {
      if (value !== null) onCommit(null);
      return;
    }
    const n = Number(draft);
    if (!Number.isFinite(n)) {
      setDraft(shown);
      return;
    }
    const clamped = Math.min(max, Math.max(min, n));
    const next = clamped / scale;
    if (value == null || Number((value * scale).toFixed(6)) !== clamped) {
      onCommit(next);
    } else {
      setDraft(shown);
    }
  };
  return (
    <label style={inputField}>
      <span style={inputLabel}>{label}</span>
      <input
        type="number"
        aria-label={ariaLabel}
        value={draft}
        min={min}
        max={max}
        step={step}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") setDraft(shown);
        }}
        style={inputControl}
      />
    </label>
  );
}

function pct(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

/** Beta to two decimals, or "—" when the backend did not return one (UI-11). */
function beta(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(2);
}

/**
 * After-tax cost of debt = rd × (1 − tax). Returns "—" unless BOTH rd and the
 * tax rate are present: a defaulted 0% tax would silently overstate the cost
 * and a defaulted rd would show 0.00% (UI-11).
 */
function afterTaxCostOfDebt(
  rd: number | undefined | null,
  tax: number | undefined | null,
): string {
  if (rd == null || tax == null || !Number.isFinite(rd) || !Number.isFinite(tax)) return "—";
  return pct(rd * (1 - tax));
}

function ratio(a: number | undefined | null, b: number | undefined | null): string {
  if (a == null || b == null || !Number.isFinite(a) || !Number.isFinite(b) || b === 0) return "—";
  return (a / b).toFixed(2);
}

const componentCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-display)",
  fontWeight: 600,
};

const numCell: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 700,
};

const kpiGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
  gap: 10,
};

const warningBox: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 30%, transparent)",
  background: "var(--warn-soft)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
};

const warningList: CSSProperties = {
  margin: 0,
  paddingLeft: 18,
  fontSize: "var(--font-size-xs)",
};

const surfaceWrap: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: 12,
  display: "grid",
  gap: 10,
};

const surfaceHeader: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  justifyContent: "space-between",
};

const surfaceGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
  gap: 6,
};

const surfaceCell: CSSProperties = {
  borderRadius: "var(--radius-sm)",
  padding: "10px 12px",
  border: "1px solid var(--border-subtle)",
  display: "grid",
  gap: 4,
  textAlign: "center",
};

const surfaceCellValue: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-md)",
  color: "var(--text-display)",
  fontWeight: 700,
};

const surfaceCellLabel: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  color: "var(--text-mute)",
};

const inputGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
  gap: 8,
  padding: "8px 0",
};

const inputField: CSSProperties = {
  display: "grid",
  gap: 4,
  minWidth: 0,
};

const inputLabel: CSSProperties = {
  fontSize: "var(--font-size-xs)",
  color: "var(--text-mute)",
};

const inputControl: CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  padding: "4px 6px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  fontVariantNumeric: "tabular-nums",
};

const methodologyBox: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "10px 12px",
  display: "grid",
  gap: 6,
};
