/**
 * TLH — Tax-Loss Harvesting (specialized portfolio pane, wave-2 lane L8).
 *
 * Harvest screen for `portfolio/tlh.py`: total estimated savings, loss-count /
 * bracket / rate metrics, the wash-sale window callout (with the backend's
 * §1091 note), and the candidate table (basis, last, unrealized loss, holding
 * period, tax rate applied, estimated savings, replacement ETF, wash window).
 * It always reads the real local portfolio (2026-11-07, strict truth
 * audit: the LIVE/MODEL toggle selected an invented single-row baseline —
 * cost 100, price 92 — which the backend no longer has, so the toggle is
 * gone). An empty book shows the backend's empty state.
 */
import { useMemo, type CSSProperties } from "react";
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
import { usePersistentNumber } from "../function-control-state";
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
  /** Positions with no quote; they were NOT evaluated for a loss. */
  unpriced_symbols?: string[];
  tax_bracket_used?: number;
  lt_cap_rate_used?: number;
  methodology?: string;
  [key: string]: unknown;
}

/**
 * Wash-sale window read derived from the real `wash_sale_window[2]` dates on
 * each candidate row (US §1091: 30 days before through 30 days after a sale).
 * Status is computed against the current clock; when a rebuy inside the
 * window actually happened the backend would have to send it — the probe
 * confirmed it does not, so no disallowed-loss amount is ever previewed.
 */
export interface WashWindowRead {
  open: string;
  close: string;
  status: "open" | "upcoming" | "expired";
  daysLeft: number | null;
}

const DAY_MS = 86_400_000;

export function deriveWashWindow(
  window: unknown,
  nowMs: number = Date.now(),
): WashWindowRead | null {
  if (!Array.isArray(window) || window.length < 2) return null;
  const [open, close] = window;
  if (typeof open !== "string" || typeof close !== "string") return null;
  const openMs = Date.parse(`${open}T00:00:00Z`);
  const closeMs = Date.parse(`${close}T00:00:00Z`);
  if (!Number.isFinite(openMs) || !Number.isFinite(closeMs) || closeMs < openMs) return null;
  const endOfCloseDay = closeMs + DAY_MS - 1;
  if (nowMs < openMs) {
    return { open, close, status: "upcoming", daysLeft: Math.ceil((closeMs - nowMs) / DAY_MS) };
  }
  if (nowMs <= endOfCloseDay) {
    return {
      open,
      close,
      status: "open",
      daysLeft: Math.max(0, Math.ceil((closeMs - nowMs) / DAY_MS)),
    };
  }
  return { open, close, status: "expired", daysLeft: null };
}

/** Clamp a percent-form value into [0, 100]; non-finite -> 0. */
function clampPct(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

/** Parse a percent input; empty / invalid falls back to the current value. */
function readPctInput(raw: string, fallback: number): number {
  if (raw.trim() === "") return fallback;
  const n = Number(raw);
  if (!Number.isFinite(n)) return fallback;
  return clampPct(n);
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
    width: 188,
    render: (row) => {
      const read = deriveWashWindow(row.wash_sale_window);
      if (!read) return <span className="portfolio-analytics-num">—</span>;
      const label =
        read.status === "open"
          ? `OPEN · ${read.daysLeft ?? 0}d left`
          : read.status.toUpperCase();
      return (
        <span
          className="u-flex u-items-center u-gap-2"
          title={`US §1091 window ${read.open} → ${read.close}: repurchasing a substantially identical security inside this window disallows the loss.`}
        >
          <Pill tone={read.status === "open" ? "warn" : "muted"} variant="soft" withDot={false}>
            {label}
          </Pill>
          <span className="portfolio-analytics-num">→ {read.close}</span>
          {washCheckPill(row)}
        </span>
      );
    },
  },
];

/**
 * Per-row wash-sale check result from the backend. A blocked row is a real
 * finding (its open date sits inside the window). A not-checked row is
 * labelled as such: the window above is an observation, not a clearance.
 * A row without a status field renders nothing rather than a guessed label.
 */
function washCheckPill(row: Row) {
  if (row.wash_sale_status === "blocked_open_date_in_window") {
    return (
      <Pill tone="warn" variant="soft" withDot={false}>
        BLOCKED
      </Pill>
    );
  }
  if (row.wash_sale_status === "not_checked") {
    return (
      <Pill tone="muted" variant="soft" withDot={false}>
        NOT CHECKED
      </Pill>
    );
  }
  return null;
}

export function TaxLossHarvestPane({ code }: FunctionPaneProps) {
  // User-controlled tax assumptions (persisted). These were previously
  // hardcoded and presented as authoritative; now the operator sets the
  // bracket / LT rate in PERCENT and they are sent to the backend as
  // FRACTIONS (the wire contract) with the applied values echoed in the hero.
  const [bracketPct, setBracketPct] = usePersistentNumber(
    "showme.tlh.tax-bracket-pct",
    24,
  );
  const [ltRatePct, setLtRatePct] = usePersistentNumber(
    "showme.tlh.lt-cap-rate-pct",
    15,
  );
  const params = useMemo(
    () => ({
      include_legacy: true,
      tax_bracket: clampPct(bracketPct) / 100,
      lt_cap_rate: clampPct(ltRatePct) / 100,
    }),
    [bracketPct, ltRatePct],
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
  const firstWindow = candidates.length
    ? deriveWashWindow(candidates[0].wash_sale_window)
    : null;
  const windowText = firstWindow ? `${firstWindow.open} → ${firstWindow.close}` : "—";
  const note = typeof data?.metadata?.note === "string" ? data.metadata.note : null;
  // The total is either netted against supplied realized gains or a gross
  // upper bound; the hero label says which one, never a bare "savings".
  const savingsLabel =
    payload?.savings_basis === "netted_against_supplied_realized_gains"
      ? "Estimated tax savings (netted)"
      : payload?.savings_basis === "gross_upper_bound_no_gains_supplied"
        ? "Estimated tax savings (gross, not netted)"
        : "Estimated tax savings";
  // The buy-history wash-sale check is not run by the backend; say so next
  // to the window, so an observation window is never read as clearance.
  const washNotChecked = payload?.wash_sale_checked === false;

  const badge = (
    <DataQualityBadge
      payload={payload as Row | undefined}
      metadata={data?.metadata}
      sources={data?.sources}
    />
  );
  const empty = emptyCopy(payload as Row | undefined);
  const unpricedSymbols = Array.isArray(payload?.unpriced_symbols)
    ? payload.unpriced_symbols.filter((s): s is string => typeof s === "string" && s.length > 0)
    : [];
  // Unpriced positions were never checked for a loss: say so instead of
  // claiming "nothing to harvest" (provider_unavailable keeps its own reason).
  const hasUnpriced = unpricedSymbols.length > 0 && status !== "provider_unavailable";
  const emptyTitle = hasUnpriced
    ? "Loss status unknown for some positions"
    : empty.title === "No data available"
      ? "No harvest candidates"
      : empty.title;
  const emptyBody = hasUnpriced
    ? `No current quote for ${unpricedSymbols.join(", ")}, so those positions could not be checked for a loss. Nothing is reported as harvestable for them until a quote is available.`
    : empty.title === "No data available"
      ? "No position is currently below its cost basis, so there is nothing to harvest."
      : empty.body;

  const body = (
    <PaneGate state={state} error={error} refetch={refetch}>
      {isEmpty ? (
        <>
          <WarningStrip warnings={warnings} />
          <PortfolioEmpty badge={badge} title={emptyTitle} body={emptyBody} />
        </>
      ) : (
        <div className="portfolio-analytics-view">
          {badge}
          <section className="portfolio-analytics-summary">
            <div className="portfolio-analytics-summary__hero">
              <span className="portfolio-analytics-label">{savingsLabel}</span>
              <strong className="u-text-positive">{fmtMoney(totalSavings)}</strong>
              <span>
                {payload?.n_loss_positions ?? candidates.length} loss position(s) · assumed bracket{" "}
                {fmtPct(payload?.tax_bracket_used, { fromFraction: true })} · assumed LT rate{" "}
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
              {washNotChecked ? (
                <p className="u-mt-4" style={{ margin: 0 }}>
                  Wash-sale check not run against broker buy history. Only a position opened inside the
                  window is BLOCKED; other rows are NOT CHECKED and may still have a repurchase inside the window.
                </p>
              ) : null}
            </section>
          ) : null}

          <WarningStrip warnings={warnings} />

          <section className="portfolio-table-panel">
            <SectionHead
              title="Harvest candidates"
              meta={`${candidates.length} position(s) · gross saving descending · not tax lots`}
            />
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
              <label
                style={assumptionStyle}
                title="Assumed marginal tax bracket on short-term losses (percent)"
              >
                Bracket %
                <input
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  value={bracketPct}
                  onChange={(e) =>
                    setBracketPct(readPctInput(e.target.value, bracketPct))
                  }
                  aria-label="Tax bracket percent"
                  style={assumptionInputStyle}
                />
              </label>
              <label
                style={assumptionStyle}
                title="Assumed long-term capital-gains rate (percent)"
              >
                LT %
                <input
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  value={ltRatePct}
                  onChange={(e) =>
                    setLtRatePct(readPctInput(e.target.value, ltRatePct))
                  }
                  aria-label="Long-term capital gains rate percent"
                  style={assumptionInputStyle}
                />
              </label>
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

const assumptionStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  fontSize: "var(--font-size-xs)",
  color: "var(--text-secondary)",
};

const assumptionInputStyle: CSSProperties = {
  width: 52,
  padding: "2px 4px",
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: "var(--font-size-xs)",
  background: "var(--surface-2)",
  color: "var(--text-primary)",
  border: "1px solid var(--border-subtle)",
  borderRadius: 4,
};

export default TaxLossHarvestPane;
