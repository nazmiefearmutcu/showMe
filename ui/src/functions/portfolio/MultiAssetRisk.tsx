/**
 * MARS — Multi-Asset Risk (specialized portfolio pane, wave-2 lane L8).
 *
 * Factor-risk screen for `portfolio/_more.py` MARSFunction: annualized alpha,
 * R², annualized vol, VaR/ETL (positive-loss fields), the six factor-loading
 * bars and the loading table with per-factor meanings. The backend regresses
 * on live ETF factor proxies by default; MODEL opts into the labelled
 * template series (`reference=true`) and disclosed proxy shortfalls ride the
 * warnings strip.
 */
import { useMemo, useState } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "../function-controls";
import type { FunctionPaneProps } from "../registry-types";
import {
  asRows,
  DataQualityBadge,
  emptyCopy,
  fmtNum,
  fmtPct,
  MetricStrip,
  num,
  PaneGate,
  PortfolioEmpty,
  SectionHead,
  sortByField,
  str,
  toneClass,
  WarningStrip,
  type Row,
} from "./shared";

/**
 * Factor contribution waterfall input, derived from the real `rows[]` fields
 * (regression betas). Order is by |loading| descending — `abs_loading` when
 * the backend supplies it, else |loading| — and the sign is kept so the bar
 * can honestly say whether the portfolio moves with (+) or against (−) the
 * factor.
 */
export interface WaterfallFactor {
  factor: string;
  loading: number;
  absLoading: number;
  meaning?: string;
}

export function deriveFactorWaterfall(rows: Row[]): WaterfallFactor[] {
  return rows
    .map((row): WaterfallFactor | null => {
      const loading = num(row.loading);
      const factor = str(row.factor);
      if (loading == null || factor == null) return null;
      const absRaw = num(row.abs_loading);
      return {
        factor,
        loading,
        absLoading: absRaw != null ? Math.abs(absRaw) : Math.abs(loading),
        meaning: str(row.meaning) ?? undefined,
      };
    })
    .filter((entry): entry is WaterfallFactor => entry != null)
    .sort((a, b) => b.absLoading - a.absLoading);
}

interface MarsPayload {
  status?: string;
  reason?: string;
  alpha_daily?: number | null;
  alpha_annualized?: number | null;
  factor_loadings?: Record<string, number>;
  rows?: Row[];
  r_squared?: number | null;
  annualized_volatility?: number | null;
  var_95_daily_loss?: number | null;
  etl_95_daily_loss?: number | null;
  samples?: number;
  summary?: Row;
  methodology?: string;
  [key: string]: unknown;
}

const LOADING_COLUMNS: DataGridColumn<Row>[] = [
  {
    key: "factor",
    header: "Factor",
    width: 92,
    render: (row) => <span className="portfolio-analytics-num">{str(row.factor) ?? "—"}</span>,
  },
  {
    key: "loading",
    header: "Loading",
    width: 96,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className={`portfolio-analytics-num ${toneClass(typeof row.loading === "number" ? row.loading : null) ?? ""}`}>
        {typeof row.loading === "number" ? row.loading.toFixed(4) : "—"}
      </span>
    ),
  },
  {
    key: "abs_loading",
    header: "|Loading|",
    width: 90,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className="portfolio-analytics-num">
        {typeof row.abs_loading === "number" ? row.abs_loading.toFixed(4) : "—"}
      </span>
    ),
  },
  {
    key: "meaning",
    header: "Meaning",
    width: 260,
    render: (row) => str(row.meaning) ?? "—",
  },
];

export function MultiAssetRiskPane({ code }: FunctionPaneProps) {
  const [symbolsInput, setSymbolsInput] = useState("SPY,TLT,GLD,BTCUSDT");
  const [reference, setReference] = useState(false);

  const symbols = useMemo(
    () =>
      symbolsInput
        .split(/[,\s]+/)
        .map((entry) => entry.trim().toUpperCase())
        .filter(Boolean),
    [symbolsInput],
  );
  const params = useMemo(
    () => ({ symbols: symbols.join(","), reference }),
    [symbols, reference],
  );
  const { state, data, error, refetch } = useFunction<MarsPayload>({ code, params });
  const payload = data?.data;

  const rows = useMemo(() => sortByField(asRows(payload?.rows), "loading"), [payload]);
  const waterfall = useMemo(() => deriveFactorWaterfall(asRows(payload?.rows)), [payload]);
  const warnings = data?.warnings ?? [];
  const status = str(payload?.status) ?? data?.status ?? "ok";
  const isEmpty = !payload || rows.length === 0;

  const alpha = typeof payload?.alpha_annualized === "number" ? payload.alpha_annualized : null;
  const proxiesLoaded = Array.isArray(data?.metadata?.factor_proxies_loaded)
    ? (data?.metadata?.factor_proxies_loaded as unknown[]).filter(
        (entry): entry is string => typeof entry === "string",
      )
    : [];

  const badge = (
    <DataQualityBadge
      payload={payload as Row | undefined}
      metadata={data?.metadata}
      sources={data?.sources}
    />
  );
  const empty = emptyCopy(payload as Row | undefined);

  const body = (
    <PaneGate state={state} error={error} refetch={refetch}>
      {isEmpty ? (
        <PortfolioEmpty badge={badge} title={empty.title} body={empty.body} />
      ) : (
        <div className="portfolio-analytics-view">
          {badge}
          <section className="portfolio-analytics-summary">
            <div className="portfolio-analytics-summary__hero">
              <span className="portfolio-analytics-label">Alpha (annualized)</span>
              <strong className={toneClass(alpha)}>
                {fmtPct(alpha, { fromFraction: true, signed: true })}
              </strong>
              <span>
                {rows.length} factor(s) · {payload?.samples ?? "—"} overlapping observations
              </span>
            </div>
            <MetricStrip
              metrics={[
                {
                  key: "r2",
                  label: "R²",
                  value: fmtPct(payload?.r_squared, { fromFraction: true }),
                },
                {
                  key: "vol",
                  label: "Vol (ann.)",
                  value: fmtPct(payload?.annualized_volatility, { fromFraction: true }),
                },
                {
                  key: "var",
                  label: "VaR 95 (1d loss)",
                  value: fmtPct(payload?.var_95_daily_loss, { fromFraction: true }),
                  tone: toneClass(typeof payload?.var_95_daily_loss === "number" ? -payload.var_95_daily_loss : null),
                },
                {
                  key: "etl",
                  label: "ETL 95 (1d loss)",
                  value: fmtPct(payload?.etl_95_daily_loss, { fromFraction: true }),
                  tone: toneClass(typeof payload?.etl_95_daily_loss === "number" ? -payload.etl_95_daily_loss : null),
                },
                {
                  key: "alpha_daily",
                  label: "Alpha (daily)",
                  value: fmtNum(payload?.alpha_daily, 5),
                  tone: toneClass(typeof payload?.alpha_daily === "number" ? payload.alpha_daily : null),
                },
                {
                  key: "samples",
                  label: "Samples",
                  value: typeof payload?.samples === "number" ? String(payload.samples) : "—",
                },
              ]}
            />
          </section>

          {proxiesLoaded.length ? (
            <div className="u-flex u-flex-wrap u-gap-3" aria-label="Factor proxies loaded">
              <span className="portfolio-analytics-label">Factor proxies loaded</span>
              {proxiesLoaded.map((proxy) => (
                <Pill key={proxy} tone="muted" variant="soft" withDot={false}>
                  {proxy}
                </Pill>
              ))}
            </div>
          ) : null}

          <WarningStrip warnings={warnings} />

          <div className="portfolio-analytics-grid">
            <section className="portfolio-table-panel">
              <SectionHead title="Factor loadings" meta="regression beta against ETF proxies" />
              <DataGrid
                columns={LOADING_COLUMNS}
                rows={rows}
                rowKey={(row, idx) => `${String(row.factor ?? idx)}-${idx}`}
                density="compact"
                ariaLabel="MARS factor loading table"
              />
            </section>

            <aside className="portfolio-analytics-rail">
              <section className="portfolio-visual-panel">
                <SectionHead title="Factor contribution" meta="signed beta · sorted by |loading|" />
                <FactorWaterfall factors={waterfall} />
              </section>

              {payload?.methodology ? (
                <section className="portfolio-method-panel">
                  <h3>Method</h3>
                  <p>{payload.methodology}</p>
                </section>
              ) : null}
            </aside>
          </div>
        </div>
      )}
    </PaneGate>
  );

  return (
    <div className="portfolio-analytics-host">
      <Pane>
        <PaneHeader
          code={code.toUpperCase()}
          title="Multi-Asset Risk"
          subtitle="Factor loadings, VaR, and residual risk"
          trailing={
            <FunctionControlGroup>
              <label className="portfolio-control-field portfolio-control-field--wide" htmlFor={`mars-${code}-universe`}>
                <span>Universe</span>
                <input
                  id={`mars-${code}-universe`}
                  value={symbolsInput}
                  onChange={(event) => setSymbolsInput(event.target.value.toUpperCase())}
                  spellCheck={false}
                />
              </label>
              <button
                type="button"
                className={`btn btn--ghost portfolio-analytics-live${reference ? "" : " portfolio-analytics-live--on"}`}
                onClick={() => setReference((value) => !value)}
                aria-pressed={!reference}
                title="Toggle live ETF factor proxies vs the labelled template series"
              >
                {reference ? "MODEL" : "LIVE"}
              </button>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                busy={state === "refreshing" || state === "loading"}
                onClick={refetch}
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody className="portfolio-analytics-body">{body}</PaneBody>
        <PaneFooter>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span>sources · {data?.sources?.join(", ") || "—"}</span>
          <span>factors · {rows.length}</span>
          {warnings.length ? <span>{warnings.length} warn</span> : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

function FactorWaterfall({ factors }: { factors: WaterfallFactor[] }) {
  if (!factors.length) {
    return <span className="portfolio-analytics-muted">No factor loadings returned.</span>;
  }
  const max = Math.max(...factors.map((factor) => factor.absLoading), 1e-9);
  return (
    <div data-testid="mars-waterfall">
      <div className="portfolio-ladder u-mt-4" aria-label="Factor contribution waterfall" role="list">
        {factors.map((factor) => {
          const negative = factor.loading < 0;
          const width = Math.min(50, (factor.absLoading / max) * 50);
          return (
            <div
              className="portfolio-ladder__row"
              key={factor.factor}
              role="listitem"
              data-factor={factor.factor}
              data-direction={negative ? "neg" : "pos"}
              title={`${factor.meaning ?? factor.factor} — ${
                negative
                  ? "negative loading: portfolio moves against the factor"
                  : "positive loading: portfolio moves with the factor"
              }`}
            >
              <span>{factor.factor}</span>
              <div className="portfolio-ladder__track" style={{ position: "relative" }}>
                <span
                  aria-hidden="true"
                  style={{
                    position: "absolute",
                    left: "50%",
                    top: 0,
                    bottom: 0,
                    width: 1,
                    background: "var(--border-subtle)",
                  }}
                />
                <i
                  className={
                    negative
                      ? "portfolio-ladder__bar portfolio-ladder__bar--neg"
                      : "portfolio-ladder__bar"
                  }
                  style={{
                    position: "absolute",
                    top: 0,
                    height: "100%",
                    width: `${width}%`,
                    ...(negative ? { right: "50%", left: "auto" } : { left: "50%" }),
                  }}
                />
              </div>
              <strong className={toneClass(factor.loading)}>
                {`${factor.loading >= 0 ? "+" : ""}${factor.loading.toFixed(4)}`}
              </strong>
            </div>
          );
        })}
      </div>
      <p className="portfolio-analytics-muted" style={{ margin: "6px 0 0" }}>
        signed regression beta · positive = moves with the factor, negative = hedges it
      </p>
    </div>
  );
}

export default MultiAssetRiskPane;
