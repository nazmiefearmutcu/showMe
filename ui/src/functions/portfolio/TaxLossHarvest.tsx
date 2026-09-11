/**
 * TLH — Tax-Loss Harvesting (specialized portfolio pane, wave-2 lane L8).
 *
 * Harvest screen for `portfolio/tlh.py`: total estimated savings, loss-count /
 * bracket / rate metrics, the wash-sale window callout (with the backend's
 * §1091 note), and the candidate table (basis, last, unrealized loss, holding
 * period, tax rate applied, estimated savings, replacement ETF, wash window).
 * LIVE reads real positions; MODEL serves the labelled single-row baseline
 * (`tax_loss_model`) which the shared data-quality badge discloses.
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
import { formatNumber, formatPrice } from "@/lib/format";
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
  fmtMoney,
  fmtPct,
  MetricStrip,
  PaneGate,
  PortfolioEmpty,
  SectionHead,
  sortByField,
  str,
  toneClass,
  WarningStrip,
  type Row,
} from "./shared";

interface TlhPayload {
  status?: string;
  reason?: string;
  candidates?: Row[];
  rows?: Row[];
  total_estimated_tax_savings?: number | null;
  n_loss_positions?: number;
  tax_bracket_used?: number;
  lt_cap_rate_used?: number;
  methodology?: string;
  [key: string]: unknown;
}

function washWindow(row: Row): string {
  const window = row.wash_sale_window;
  if (!Array.isArray(window) || window.length < 2) return "—";
  const [open, close] = window;
  if (typeof open !== "string" || typeof close !== "string") return "—";
  return `${open} → ${close}`;
}

const CANDIDATE_COLUMNS: DataGridColumn<Row>[] = [
  {
    key: "symbol",
    header: "Symbol",
    width: 104,
    render: (row) => <span className="portfolio-analytics-num">{str(row.symbol) ?? "—"}</span>,
  },
  {
    key: "quantity",
    header: "Qty",
    width: 84,
    align: "right",
    numeric: true,
    render: (row) =>
      typeof row.quantity === "number" ? formatNumber(row.quantity, 4) : "—",
  },
  {
    key: "avg_cost",
    header: "Avg Cost",
    width: 90,
    align: "right",
    numeric: true,
    render: (row) => (typeof row.avg_cost === "number" ? formatPrice(row.avg_cost) : "—"),
  },
  {
    key: "current_price",
    header: "Last",
    width: 90,
    align: "right",
    numeric: true,
    render: (row) => (typeof row.current_price === "number" ? formatPrice(row.current_price) : "—"),
  },
  {
    key: "unrealized_pnl",
    header: "Unrealized",
    width: 112,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className={`portfolio-analytics-num ${toneClass(typeof row.unrealized_pnl === "number" ? row.unrealized_pnl : null) ?? ""}`}>
        {fmtMoney(row.unrealized_pnl)}
      </span>
    ),
  },
  {
    key: "held_days",
    header: "Held (d)",
    width: 80,
    align: "right",
    numeric: true,
    render: (row) => (typeof row.held_days === "number" ? formatNumber(row.held_days) : "—"),
  },
  {
    key: "long_term",
    header: "Term",
    width: 74,
    render: (row) =>
      row.long_term === true ? (
        <Pill tone="accent" variant="soft" withDot={false}>
          LONG
        </Pill>
      ) : (
        <Pill tone="warn" variant="soft" withDot={false}>
          SHORT
        </Pill>
      ),
  },
  {
    key: "tax_rate_applied",
    header: "Rate",
    width: 72,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className="portfolio-analytics-num">{fmtPct(row.tax_rate_applied, { fromFraction: true })}</span>
    ),
  },
  {
    key: "estimated_tax_savings",
    header: "Est. Savings",
    width: 112,
    align: "right",
    numeric: true,
    render: (row) => (
      <span className="portfolio-analytics-num u-text-positive">{fmtMoney(row.estimated_tax_savings)}</span>
    ),
  },
  {
    key: "replacement_etf",
    header: "Replacement",
    width: 100,
    render: (row) => str(row.replacement_etf) ?? "—",
  },
  {
    key: "wash_sale_window",
    header: "Wash Window",
    width: 180,
    render: (row) => <span className="portfolio-analytics-num">{washWindow(row)}</span>,
  },
];

export function TaxLossHarvestPane({ code }: FunctionPaneProps) {
  const [live, setLive] = useState(true);
  const params = useMemo(
    () => ({ live_tax: live, include_legacy: true, tax_bracket: 0.24, lt_cap_rate: 0.15 }),
    [live],
  );
  const { state, data, error, refetch } = useFunction<TlhPayload>({ code, params });
  const payload = data?.data;

  const candidates = useMemo(
    () => sortByField(asRows(payload?.candidates ?? payload?.rows), "estimated_tax_savings"),
    [payload],
  );
  const warnings = data?.warnings ?? [];
  const status = str(payload?.status) ?? data?.status ?? "ok";
  const isEmpty = !payload || candidates.length === 0;

  const totalSavings =
    typeof payload?.total_estimated_tax_savings === "number" ? payload.total_estimated_tax_savings : null;
  const replacements = candidates.filter((row) => str(row.replacement_etf) != null).length;
  const windowText = candidates.length ? washWindow(candidates[0]) : "—";
  const note = typeof data?.metadata?.note === "string" ? data.metadata.note : null;

  const badge = (
    <DataQualityBadge
      payload={payload as Row | undefined}
      metadata={data?.metadata}
      sources={data?.sources}
    />
  );
  const empty = emptyCopy(payload as Row | undefined);
  const emptyTitle = empty.title === "No data available" && live ? "No harvest candidates" : empty.title;
  const emptyBody =
    empty.title === "No data available" && live
      ? "No position is currently below its cost basis, so there is nothing to harvest."
      : empty.body;

  const body = (
    <PaneGate state={state} error={error} refetch={refetch}>
      {isEmpty ? (
        <PortfolioEmpty badge={badge} title={emptyTitle} body={emptyBody} />
      ) : (
        <div className="portfolio-analytics-view">
          {badge}
          <section className="portfolio-analytics-summary">
            <div className="portfolio-analytics-summary__hero">
              <span className="portfolio-analytics-label">Estimated tax savings</span>
              <strong className="u-text-positive">{fmtMoney(totalSavings)}</strong>
              <span>
                {payload?.n_loss_positions ?? candidates.length} loss position(s) · bracket{" "}
                {fmtPct(payload?.tax_bracket_used, { fromFraction: true })} · LT rate{" "}
                {fmtPct(payload?.lt_cap_rate_used, { fromFraction: true })}
              </span>
            </div>
            <MetricStrip
              metrics={[
                {
                  key: "n_loss",
                  label: "Loss Positions",
                  value: String(payload?.n_loss_positions ?? candidates.length),
                },
                {
                  key: "savings",
                  label: "Total Savings",
                  value: fmtMoney(totalSavings),
                },
                {
                  key: "replacements",
                  label: "Swaps Available",
                  value: `${replacements}/${candidates.length}`,
                  title: "Candidates with a similar-not-identical replacement ETF",
                },
                {
                  key: "wash",
                  label: "Wash Window",
                  value: windowText,
                  title: "US §1091 window: 30 days before through 30 days after the sale",
                },
              ]}
            />
          </section>

          {note || windowText !== "—" ? (
            <section className="portfolio-visual-panel" role="status" aria-label="Wash-sale rule">
              <SectionHead title="Wash-sale rule" meta={`observation window ${windowText}`} />
              <p className="u-text-secondary u-mt-4" style={{ margin: 0 }}>
                {note ??
                  "US wash-sale rule (§1091): repurchasing a substantially identical security within 30 days before or after the sale disallows the loss. Replacement ETFs are similar, not identical."}
              </p>
            </section>
          ) : null}

          <WarningStrip warnings={warnings} />

          <section className="portfolio-table-panel">
            <SectionHead title="Harvest candidates" meta={`${candidates.length} row(s) · est. savings descending`} />
            <DataGrid
              columns={CANDIDATE_COLUMNS}
              rows={candidates}
              rowKey={(row, idx) => `${String(row.symbol ?? idx)}-${idx}`}
              density="compact"
              ariaLabel="TLH harvest candidate table"
            />
          </section>

          {payload?.methodology ? (
            <section className="portfolio-method-panel">
              <h3>Method</h3>
              <p>{payload.methodology}</p>
            </section>
          ) : null}
        </div>
      )}
    </PaneGate>
  );

  return (
    <div className="portfolio-analytics-host">
      <Pane>
        <PaneHeader
          code={code.toUpperCase()}
          title="Tax-Loss Harvesting"
          subtitle="Harvest candidates and wash-sale risk"
          trailing={
            <FunctionControlGroup>
              <button
                type="button"
                className={`btn btn--ghost portfolio-analytics-live${live ? " portfolio-analytics-live--on" : ""}`}
                onClick={() => setLive((value) => !value)}
                aria-pressed={live}
                title="Toggle real positions vs the labelled single-row baseline"
              >
                {live ? "LIVE" : "MODEL"}
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
          <span>candidates · {candidates.length}</span>
          {warnings.length ? <span>{warnings.length} warn</span> : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

export default TaxLossHarvestPane;
