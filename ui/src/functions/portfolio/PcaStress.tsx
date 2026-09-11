/**
 * PCAS — PCA Factor Stress (specialized portfolio pane, wave-2 lane L8).
 *
 * Purpose-built screen for `portfolio/pcas.py`: explained-variance profile
 * (PC1..PC5), the k-σ shock P&L headline, top component loadings, and the
 * per-asset shocked return / P&L table. `live_prices` selects real yfinance
 * return history; MODEL opts into the labelled template returns (the shared
 * data-quality badge discloses it).
 */
import { useMemo, useState } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "../function-controls";
import type { FunctionPaneProps } from "../registry-types";
import {
  asRows,
  BarRow,
  DataQualityBadge,
  emptyCopy,
  fmtMoney,
  fmtNum,
  fmtPct,
  MetricStrip,
  PaneGate,
  PortfolioEmpty,
  SectionHead,
  ShareBarRow,
  str,
  toneClass,
  WarningStrip,
  type Row,
} from "./shared";

interface PcasPayload {
  status?: string;
  reason?: string;
  pc_index?: number;
  k_sigma?: number;
  explained_variance_ratio?: number[];
  factor_shock_magnitude?: number;
  portfolio_return_pct?: number | null;
  portfolio_pnl_dollar?: number | null;
  total_notional?: number;
  top_loadings?: Row[];
  asset_returns?: Row[];
  rows?: Row[];
  loadings?: Row[];
  samples?: number;
  methodology?: string;
  [key: string]: unknown;
}

const ASSET_COLUMNS: DataGridColumn<Row>[] = [
  {
    key: "symbol",
    header: "Symbol",
    width: 108,
    render: (row) => <span className="portfolio-analytics-num">{str(row.symbol) ?? "—"}</span>,
  },
  {
    key: "weight_pct",
    header: "Weight",
    width: 84,
    align: "right",
    numeric: true,
    render: (row) => <span className="portfolio-analytics-num">{fmtPct(row.weight_pct)}</span>,
  },
  {
    key: "shock_return_pct",
    header: "Shock Ret",
    width: 92,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className={`portfolio-analytics-num ${toneClass(typeof row.shock_return_pct === "number" ? row.shock_return_pct : null) ?? ""}`}>
        {fmtPct(row.shock_return_pct, { signed: true })}
      </span>
    ),
  },
  {
    key: "pnl",
    header: "P&L",
    width: 118,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className={`portfolio-analytics-num ${toneClass(typeof row.pnl === "number" ? row.pnl : null) ?? ""}`}>
        {fmtMoney(row.pnl)}
      </span>
    ),
  },
];

const LOADING_COLUMNS: DataGridColumn<Row>[] = [
  {
    key: "symbol",
    header: "Symbol",
    width: 108,
    render: (row) => <span className="portfolio-analytics-num">{str(row.symbol) ?? "—"}</span>,
  },
  {
    key: "loading",
    header: "Loading",
    width: 92,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className={`portfolio-analytics-num ${toneClass(typeof row.loading === "number" ? row.loading : null) ?? ""}`}>
        {typeof row.loading === "number" ? row.loading.toFixed(4) : "—"}
      </span>
    ),
  },
];

export function PcaStressPane({ code }: FunctionPaneProps) {
  const [pcIndex, setPcIndex] = useState<0 | 1 | 2>(0);
  const [kSigma, setKSigma] = useState<2 | 3 | 4>(3);
  const [livePrices, setLivePrices] = useState(true);

  const params = useMemo(
    () => ({
      pc_index: pcIndex,
      k_sigma: kSigma,
      live: true,
      live_prices: livePrices,
      include_legacy: true,
    }),
    [pcIndex, kSigma, livePrices],
  );
  const { state, data, error, refetch } = useFunction<PcasPayload>({ code, params });
  const payload = data?.data;

  const assetRows = useMemo(() => asRows(payload?.asset_returns ?? payload?.rows), [payload]);
  const loadings = useMemo(() => {
    const fromTop = asRows(payload?.top_loadings);
    return fromTop.length ? fromTop : asRows(payload?.loadings);
  }, [payload]);
  const variance = useMemo(
    () =>
      Array.isArray(payload?.explained_variance_ratio)
        ? payload.explained_variance_ratio.filter(
            (value): value is number => typeof value === "number" && Number.isFinite(value),
          )
        : [],
    [payload],
  );

  const warnings = data?.warnings ?? [];
  const status = str(payload?.status) ?? data?.status ?? "ok";
  const isEmpty = !payload || (assetRows.length === 0 && loadings.length === 0 && variance.length === 0);

  const loadingMax = useMemo(
    () => Math.max(...loadings.map((row) => Math.abs(typeof row.loading === "number" ? row.loading : 0)), 1e-9),
    [loadings],
  );
  const varianceMax = useMemo(() => Math.max(...variance, 1e-9), [variance]);
  const pcLabel = `PC${(typeof payload?.pc_index === "number" ? payload.pc_index : pcIndex) + 1}`;
  const kLabel = `${fmtNum(payload?.k_sigma ?? kSigma, 1)}σ`;
  const pnl = typeof payload?.portfolio_pnl_dollar === "number" ? payload.portfolio_pnl_dollar : null;

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
              <span className="portfolio-analytics-label">
                {pcLabel} · {kLabel} shock · P&L
              </span>
              <strong className={toneClass(pnl)}>{fmtMoney(pnl)}</strong>
              <span>
                portfolio return {fmtPct(payload?.portfolio_return_pct, { signed: true })} on{" "}
                {fmtMoney(payload?.total_notional)} notional
              </span>
            </div>
            <MetricStrip
              metrics={[
                {
                  key: "return_pct",
                  label: "Portfolio Return",
                  value: fmtPct(payload?.portfolio_return_pct, { signed: true }),
                  tone: toneClass(typeof payload?.portfolio_return_pct === "number" ? payload.portfolio_return_pct : null),
                },
                {
                  key: "shock",
                  label: "Factor Shock",
                  value: fmtNum(payload?.factor_shock_magnitude, 4),
                  title: "Magnitude of the applied principal-component shock",
                },
                {
                  key: "notional",
                  label: "Total Notional",
                  value: fmtMoney(payload?.total_notional),
                },
                {
                  key: "samples",
                  label: "Return Samples",
                  value: typeof payload?.samples === "number" ? String(payload.samples) : "—",
                },
                {
                  key: "pc",
                  label: "Component",
                  value: pcLabel,
                  title: `pc_index ${payload?.pc_index ?? pcIndex}`,
                },
                {
                  key: "k",
                  label: "Shock Size",
                  value: kLabel,
                },
              ]}
            />
          </section>

          <WarningStrip warnings={warnings} />

          <div className="portfolio-analytics-grid">
            <section className="portfolio-table-panel">
              <SectionHead title="Asset shock projection" meta={`${assetRows.length} asset(s) · weight × shocked return`} />
              <DataGrid
                columns={ASSET_COLUMNS}
                rows={assetRows}
                rowKey={(row, idx) => `${String(row.symbol ?? idx)}-${idx}`}
                density="compact"
                ariaLabel="PCAS asset shock table"
              />
            </section>

            <aside className="portfolio-analytics-rail">
              <section className="portfolio-visual-panel">
                <SectionHead title="Explained variance" meta="first five components" />
                {variance.length ? (
                  <div className="portfolio-ladder u-mt-4">
                    {variance.map((ratio, index) => (
                      <ShareBarRow
                        key={`pcv-${index}`}
                        label={`PC${index + 1}`}
                        value={ratio}
                        max={varianceMax}
                        text={fmtPct(ratio, { fromFraction: true })}
                      />
                    ))}
                  </div>
                ) : (
                  <span className="portfolio-analytics-muted">No variance profile returned.</span>
                )}
              </section>

              <section className="portfolio-visual-panel">
                <SectionHead title="Top loadings" meta={pcLabel} />
                {loadings.length ? (
                  <div className="portfolio-ladder u-mt-4">
                    {loadings.slice(0, 8).map((row, index) => {
                      const loading = typeof row.loading === "number" ? row.loading : 0;
                      return (
                        <BarRow
                          key={`${String(row.symbol ?? index)}-ld`}
                          label={str(row.symbol) ?? "—"}
                          value={loading}
                          max={loadingMax}
                          text={loading.toFixed(4)}
                        />
                      );
                    })}
                  </div>
                ) : (
                  <span className="portfolio-analytics-muted">No loadings returned.</span>
                )}
                {loadings.length ? (
                  <div className="u-mt-6">
                    <DataGrid
                      columns={LOADING_COLUMNS}
                      rows={loadings}
                      rowKey={(row, idx) => `ld-${String(row.symbol ?? idx)}-${idx}`}
                      density="compact"
                      ariaLabel="PCAS loading table"
                    />
                  </div>
                ) : null}
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
          title="PCA Stress"
          subtitle="Principal-component shock and P&L projection"
          trailing={
            <FunctionControlGroup>
              <SegmentedControl
                label="PC"
                value={pcIndex}
                options={[
                  { value: 0, label: "PC1" },
                  { value: 1, label: "PC2" },
                  { value: 2, label: "PC3" },
                ]}
                onChange={setPcIndex}
              />
              <SegmentedControl
                label="SHOCK"
                value={kSigma}
                options={[
                  { value: 2, label: "2σ" },
                  { value: 3, label: "3σ" },
                  { value: 4, label: "4σ" },
                ]}
                onChange={setKSigma}
              />
              <button
                type="button"
                className={`btn btn--ghost portfolio-analytics-live${livePrices ? " portfolio-analytics-live--on" : ""}`}
                onClick={() => setLivePrices((value) => !value)}
                aria-pressed={livePrices}
                title="Toggle live yfinance returns vs the labelled template returns"
              >
                {livePrices ? "LIVE" : "MODEL"}
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
          <span>assets · {assetRows.length}</span>
          {warnings.length ? <span>{warnings.length} warn</span> : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

export default PcaStressPane;
