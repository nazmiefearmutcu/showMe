/**
 * ACCT — Account Overview (specialized portfolio pane, wave-2 lane L8).
 *
 * Replaces the generic PortfolioAnalytics matrix with the exposure view the
 * backend actually returns: per-account roll-up (`accounts[]` + `rows[]`) and
 * cross-account exposure (`cross.by_asset_class` / `cross.by_symbol`).
 * No new endpoint, no derived fabrication — every figure maps to a payload
 * field documented in wave2-targets §3 (`portfolio/acct.py`).
 */
import { useEffect, useMemo } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import { navigate } from "@/lib/router";
import { formatCurrency, formatMissing, formatNumber, formatPrice } from "@/lib/format";
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "../function-controls";
import type { FunctionPaneProps } from "../registry-types";
import {
  asRecord,
  asRows,
  DataQualityBadge,
  emptyCopy,
  fmtMoney,
  MetricStrip,
  numLoose,
  PaneGate,
  PortfolioEmpty,
  SectionHead,
  ShareBarRow,
  str,
  toneClass,
  WarningStrip,
  type Row,
} from "./shared";

interface AcctPayload {
  status?: string;
  reason?: string;
  accounts?: Row[];
  rows?: Row[];
  cross?: Row;
  summary?: Row;
  methodology?: string;
  field_dictionary?: Record<string, string>;
  [key: string]: unknown;
}

const ACCOUNT_COLUMNS: DataGridColumn<Row>[] = [
  {
    key: "account",
    header: "Account",
    width: 120,
    render: (row) => <span className="portfolio-analytics-num">{str(row.account) ?? formatMissing}</span>,
  },
  {
    key: "positions",
    header: "Positions",
    width: 78,
    align: "right",
    numeric: true,
    render: (row) => (typeof row.positions === "number" ? formatNumber(row.positions) : formatMissing),
  },
  {
    key: "market_value",
    header: "Market Value",
    width: 120,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className="portfolio-analytics-num">{fmtMoney(row.market_value)}</span>
    ),
  },
  {
    key: "unrealized_pnl",
    header: "Unrealized P&L",
    width: 118,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className={`portfolio-analytics-num ${toneClass(typeof row.unrealized_pnl === "number" ? row.unrealized_pnl : null) ?? ""}`}>
        {fmtMoney(row.unrealized_pnl)}
      </span>
    ),
  },
  {
    key: "top_asset_class",
    header: "Top Class",
    width: 100,
    render: (row) => str(row.top_asset_class) ?? formatMissing,
  },
];

const POSITION_COLUMNS: DataGridColumn<Row>[] = [
  {
    key: "account",
    header: "Account",
    width: 96,
    render: (row) => <span className="portfolio-analytics-num">{str(row.account) ?? formatMissing}</span>,
  },
  {
    key: "symbol",
    header: "Symbol",
    width: 110,
    render: (row) => {
      const symbol = str(row.symbol);
      if (!symbol) return formatMissing;
      return (
        <button
          type="button"
          className="u-symbol-link"
          onClick={() => navigate(`/symbol/${symbol}/DES`)}
        >
          {symbol}
        </button>
      );
    },
  },
  {
    key: "asset_class",
    header: "Class",
    width: 86,
    render: (row) => str(row.asset_class) ?? formatMissing,
  },
  {
    key: "quantity",
    header: "Qty",
    width: 92,
    align: "right",
    numeric: true,
    render: (row) =>
      typeof row.quantity === "number" ? formatNumber(row.quantity, 4) : formatMissing,
  },
  {
    key: "avg_cost",
    header: "Avg Cost",
    width: 92,
    align: "right",
    numeric: true,
    render: (row) =>
      typeof row.avg_cost === "number" ? formatPrice(row.avg_cost) : formatMissing,
  },
  {
    key: "last",
    header: "Last",
    width: 92,
    align: "right",
    numeric: true,
    render: (row) =>
      typeof row.last === "number" ? formatPrice(row.last) : formatMissing,
  },
  {
    key: "market_value",
    header: "Market Value",
    width: 118,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className="portfolio-analytics-num">{fmtMoney(row.market_value)}</span>
    ),
  },
  {
    key: "unrealized_pnl",
    header: "Unrealized P&L",
    width: 118,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className={`portfolio-analytics-num ${toneClass(typeof row.unrealized_pnl === "number" ? row.unrealized_pnl : null) ?? ""}`}>
        {fmtMoney(row.unrealized_pnl)}
      </span>
    ),
  },
];

export function AccountOverviewPane({ code }: FunctionPaneProps) {
  const { state, data, error, refetch } = useFunction<AcctPayload>({ code });
  // Live adoption (campaign 2026-09-11): marks roll server-side only, so the
  // account table used to go stale until a manual Refresh. Visibility-paused
  // 60s refetch; the tick drives `refetch()` only — never a param, or the
  // fetch key would change every cycle and wipe the table to a skeleton.
  const tick = useVisibilityTick(60_000);
  useEffect(() => {
    if (tick === 0) return; // initial mount is useFunction's own load
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tick is the trigger
  }, [tick]);
  const payload = data?.data;
  const accounts = useMemo(() => asRows(payload?.accounts), [payload]);
  const accountRows = useMemo(() => asRows(payload?.rows), [payload]);
  const cross = useMemo(() => asRecord(payload?.cross), [payload]);
  const summary = useMemo(() => asRecord(payload?.summary), [payload]);

  const positions = useMemo<Row[]>(
    () =>
      accounts.flatMap((slot) =>
        asRows(slot.positions).map((position) => ({
          account: slot.account,
          ...position,
          quantity: numLoose(position.quantity),
          avg_cost: numLoose(position.avg_cost),
          last: numLoose(position.last),
          market_value: numLoose(position.market_value),
          unrealized_pnl: numLoose(position.unrealized_pnl),
        })),
      ),
    [accounts],
  );

  const byAssetClass = useMemo(() => {
    const source = asRecord(cross?.by_asset_class);
    if (!source) return [] as Array<{ label: string; value: number }>;
    return Object.entries(source)
      .map(([label, value]) => ({
        label,
        value: typeof value === "number" && Number.isFinite(value) ? value : 0,
      }))
      .sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
  }, [cross]);

  const bySymbol = useMemo(() => {
    const source = asRecord(cross?.by_symbol);
    if (!source) return [] as Array<{ label: string; value: number }>;
    return Object.entries(source)
      .map(([label, value]) => ({
        label,
        value: typeof value === "number" && Number.isFinite(value) ? value : 0,
      }))
      .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
      .slice(0, 10);
  }, [cross]);

  const totalMv = useMemo(() => {
    const direct = typeof cross?.total_mv === "number" ? cross.total_mv : null;
    if (direct != null) return direct;
    const fromSummary = typeof summary?.total_market_value === "number" ? summary.total_market_value : null;
    if (fromSummary != null) return fromSummary;
    return null;
  }, [cross, summary]);

  const totalUnrealized = useMemo(() => {
    let total = 0;
    let seen = false;
    for (const account of accounts) {
      if (typeof account.total_unrealized_pnl === "number") {
        total += account.total_unrealized_pnl;
        seen = true;
      }
    }
    return seen ? total : null;
  }, [accounts]);

  const status = str(payload?.status);
  const warnings = data?.warnings ?? [];
  const isEmpty =
    !payload ||
    status === "ready_no_positions" ||
    status === "empty" ||
    status === "empty_portfolio" ||
    (accounts.length === 0 && accountRows.length === 0 && positions.length === 0);

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
        <PortfolioEmpty
          badge={badge}
          title={empty.title}
          body={empty.body}
          action={
            <div className="u-flex u-gap-8">
              <button type="button" className="btn btn--accent" onClick={() => navigate("/fn/CONN")}>
                Connect Broker
              </button>
              <button type="button" className="btn" onClick={() => navigate("/fn/PORT_WHATIF")}>
                Open What-If
              </button>
            </div>
          }
        />
      ) : (
        <div className="portfolio-analytics-view">
          {badge}
          <section className="portfolio-analytics-summary">
            <div className="portfolio-analytics-summary__hero">
              <span className="portfolio-analytics-label">Total market value</span>
              <strong>{totalMv == null ? formatMissing : formatCurrency(totalMv)}</strong>
              <span>
                {accounts.length} account(s) · {positions.length} position(s)
              </span>
            </div>
            <MetricStrip
              metrics={[
                {
                  key: "accounts",
                  label: "Accounts",
                  value: typeof summary?.accounts === "number" ? formatNumber(summary.accounts) : formatNumber(accounts.length),
                },
                {
                  key: "positions",
                  label: "Positions",
                  value: typeof summary?.positions === "number" ? formatNumber(summary.positions) : formatNumber(positions.length),
                },
                {
                  key: "unrealized",
                  label: "Unrealized P&L",
                  value: fmtMoney(totalUnrealized),
                  tone: toneClass(totalUnrealized),
                },
                {
                  key: "top_class",
                  label: "Top Class",
                  value: byAssetClass[0]?.label ?? formatMissing,
                },
                {
                  key: "top_symbol",
                  label: "Top Symbol",
                  value: bySymbol[0]?.label ?? formatMissing,
                },
              ]}
            />
          </section>

          <WarningStrip warnings={warnings} />

          <div className="portfolio-analytics-grid">
            <div className="u-flex-col u-gap-5">
              <section className="portfolio-table-panel">
                <SectionHead title="Accounts" meta={`${accountRows.length} account(s)`} />
                <DataGrid
                  columns={ACCOUNT_COLUMNS}
                  rows={accountRows}
                  rowKey={(row, idx) => `${String(row.account ?? "acct")}-${idx}`}
                  density="compact"
                  ariaLabel="ACCT account roll-up"
                />
              </section>

              {positions.length ? (
                <section className="portfolio-table-panel">
                  <SectionHead title="Positions" meta={`${positions.length} row(s)`} />
                  <DataGrid
                    columns={POSITION_COLUMNS}
                    rows={positions}
                    rowKey={(row, idx) => `${String(row.account ?? "")}-${String(row.symbol ?? idx)}-${idx}`}
                    density="compact"
                    ariaLabel="ACCT position detail"
                  />
                </section>
              ) : null}
            </div>

            <aside className="portfolio-analytics-rail">
              <section className="portfolio-visual-panel">
                <SectionHead title="Asset-class exposure" meta="cross-account" />
                {byAssetClass.length ? (
                  <div className="portfolio-ladder u-mt-4">
                    {byAssetClass.map((entry) => (
                      <ShareBarRow
                        key={entry.label}
                        label={entry.label}
                        value={Math.abs(entry.value)}
                        max={Math.abs(byAssetClass[0]?.value ?? 1)}
                        text={fmtMoney(entry.value, true)}
                      />
                    ))}
                  </div>
                ) : (
                  <span className="portfolio-analytics-muted">No exposure rows.</span>
                )}
              </section>

              <section className="portfolio-visual-panel">
                <SectionHead title="Top holdings" meta="by symbol" />
                {bySymbol.length ? (
                  <div className="portfolio-ladder u-mt-4">
                    {bySymbol.map((entry) => (
                      <ShareBarRow
                        key={entry.label}
                        label={entry.label}
                        value={Math.abs(entry.value)}
                        max={Math.abs(bySymbol[0]?.value ?? 1)}
                        text={fmtMoney(entry.value, true)}
                      />
                    ))}
                  </div>
                ) : (
                  <span className="portfolio-analytics-muted">No symbol exposure.</span>
                )}
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
          title="Account Overview"
          subtitle="Market value, unrealized P&L, and cross-account exposure"
          trailing={
            <FunctionControlGroup>
              <LoadStatePill state={state} status={str(payload?.status) ?? data?.status ?? null} />
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
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? formatMissing} ms</span>
          <span>sources · {data?.sources?.join(", ") || formatMissing}</span>
          <span>accounts · {accounts.length}</span>
          {warnings.length ? <span>{warnings.length} warn</span> : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

export default AccountOverviewPane;
