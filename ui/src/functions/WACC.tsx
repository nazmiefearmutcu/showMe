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
import { useFunction } from "@/lib/useFunction";
import { defaultSymbolForFunction } from "@/lib/symbols";
import { maxOf, minOf } from "@/lib/maxOf";
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
  data_state?: string;
}

export function WACCPane({ code, symbol }: FunctionPaneProps) {
  // Bug #17 fix: do not hardcode "AAPL". Use the asset-class-aware default
  // so the recent-symbols history + WACC's EQUITY fallback decide the
  // symbol, mirroring every other equity pane.
  const resolvedSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY"]);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    symbol: resolvedSymbol,
    params: {},
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

  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 16), [data]);
  const warnings = Array.isArray(data?.warnings) ? data?.warnings : [];
  const sources = Array.isArray(data?.sources) ? data?.sources : [];
  const fellBack = warnings.some((w) => /fred|damodaran|yfinance|beta/i.test(String(w)));
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
              <Pill tone={fellBack ? "warn" : "positive"} variant="soft">
                {fellBack ? "fallback active" : "live"}
              </Pill>
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <Skeleton height={300} />
          ) : state === "error" ? (
            <Empty title="Function error" body={error?.message ?? "—"} icon="!" />
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
                  caption={`rf ${pct(payload.rf)} · β ${(payload.beta ?? 0).toFixed(2)} · ERP ${pct(payload.erp)}`}
                  tone="positive"
                />
                <StatCard
                  label="Cost of debt (after-tax)"
                  value={pct(((payload.rd ?? 0) * (1 - (payload.tax_rate ?? 0))))}
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

function pct(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(2)}%`;
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

const methodologyBox: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "10px 12px",
  display: "grid",
  gap: 6,
};
