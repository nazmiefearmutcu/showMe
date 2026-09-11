/**
 * Shared building blocks for the specialized portfolio panes (wave-2 lane L8).
 *
 * Every pane in `functions/portfolio/` composes from these helpers so the
 * load-state gate, honesty badge, warning strip, KPI tiles and the
 * currency/percent formatting contract stay identical across the family.
 *
 * Data-quality classification is NOT duplicated here: it re-uses the
 * canonical `portfolioDataMode` / `PortfolioDataBadge` from the generic
 * `PortfolioAnalytics` pane (single source of truth — the same
 * /model|template|synthetic|sample/ rules that already lift all 20
 * portfolio codes). Do not fork that logic.
 */
import { type CSSProperties, type ReactNode, useMemo } from "react";
import { Empty, Pill, Skeleton } from "@/design-system";
import { formatCurrency, formatMissing, formatNumber, formatPercent } from "@/lib/format";
import { PortfolioDataBadge, portfolioDataMode } from "../PortfolioAnalytics";

export type Row = Record<string, unknown>;

/* ── value access ──────────────────────────────────────────────────── */

export function asRows(value: unknown): Row[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (row): row is Row => row != null && typeof row === "object" && !Array.isArray(row),
  );
}

export function asRecord(value: unknown): Row | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Row;
}

export function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * Numeric coercion that also accepts numeric strings — the ACCT backend
 * accepts user-supplied position JSON where `quantity`/`avg_cost`/`last`
 * arrive as strings, and it keeps the original values in the response.
 */
export function numLoose(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function boolOf(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

/** Sum a numeric field across rows, ignoring non-numeric entries. */
export function sumField(rows: Row[], key: string): number | null {
  let total = 0;
  let seen = false;
  for (const row of rows) {
    const n = num(row[key]);
    if (n == null) continue;
    total += n;
    seen = true;
  }
  return seen ? total : null;
}

/** Sort rows descending by a numeric field; non-numeric rows sink. */
export function sortByField(rows: Row[], key: string): Row[] {
  return [...rows].sort((a, b) => {
    const av = num(a[key]);
    const bv = num(b[key]);
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return Math.abs(bv) - Math.abs(av);
  });
}

/* ── formatting ────────────────────────────────────────────────────── */

export function fmtMoney(value: unknown, compact = false): string {
  const n = num(value);
  if (n == null) return formatMissing;
  return formatCurrency(n, { compact: compact || Math.abs(n) >= 100000 });
}

export function fmtPct(
  value: unknown,
  opts: { fromFraction?: boolean; digits?: number; signed?: boolean } = {},
): string {
  const n = num(value);
  if (n == null) return formatMissing;
  return formatPercent(n, opts);
}

export function fmtNum(value: unknown, digits = 2): string {
  const n = num(value);
  if (n == null) return formatMissing;
  return formatNumber(n, digits);
}

/** Sign tone class for financial numerics; neutral for 0 / missing. */
export function toneClass(value: number | null | undefined): string | undefined {
  if (value == null || value === 0) return undefined;
  return value < 0 ? "u-text-negative" : "u-text-positive";
}

/* ── load-state gate + honesty badge ───────────────────────────────── */

export function PaneGate({
  state,
  error,
  refetch,
  children,
}: {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  error?: Error | null;
  refetch: () => void;
  children: ReactNode;
}) {
  if (state === "idle" || state === "loading") {
    return (
      <div className="portfolio-analytics-loading" aria-busy="true">
        <Skeleton height={64} />
        <Skeleton height={160} />
        <Skeleton height={24} width="60%" />
      </div>
    );
  }
  if (state === "error") {
    return (
      <div role="status">
        <Empty
          title="Function error"
          body={error?.message ?? formatMissing}
          icon="!"
          action={
            <button type="button" className="btn" onClick={refetch}>
              Retry
            </button>
          }
        />
      </div>
    );
  }
  return <>{children}</>;
}

export function DataQualityBadge({
  payload,
  metadata,
  sources,
}: {
  payload: Row | undefined;
  metadata: Record<string, unknown> | undefined;
  sources: string[] | undefined;
}) {
  const quality = useMemo(
    () => portfolioDataMode(payload, metadata, sources),
    [payload, metadata, sources],
  );
  return <PortfolioDataBadge quality={quality} />;
}

export function WarningStrip({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null;
  return (
    <div
      className="portfolio-warning-strip"
      role="status"
      aria-live="polite"
      data-testid="portx-warning-strip"
    >
      {warnings.slice(0, 3).map((warning) => (
        <Pill key={warning} tone="warn" variant="soft" withDot={false}>
          {warning}
        </Pill>
      ))}
    </div>
  );
}

/* ── empty states ──────────────────────────────────────────────────── */

interface EmptyCopy {
  title: string;
  body: string;
}

function firstNextAction(payload: Row | undefined): string | null {
  const list = payload?.next_actions;
  if (!Array.isArray(list)) return null;
  for (const item of list) {
    if (typeof item === "string" && item.length > 0) return item;
  }
  return null;
}

/**
 * Honest empty-state copy keyed off the backend status vocabulary shared by
 * the portfolio functions. `reason` / the first `next_actions` entry win over
 * the canned text so the real upstream explanation always survives.
 */
export function emptyCopy(payload: Row | undefined): EmptyCopy {
  const status = str(payload?.status) ?? "";
  const reason = str(payload?.reason) ?? firstNextAction(payload);
  switch (status) {
    case "ready_no_positions":
    case "empty_portfolio":
    case "empty":
      // "empty" is the PVAR/RPAR-family status for an empty portfolio book;
      // the generic pane renders it as the no-positions state too.
      return {
        title: "No portfolio positions",
        body:
          reason ??
          "No open positions are available to this function. Connect a broker or add positions to the portfolio state.",
      };
    case "provider_unavailable":
      return {
        title: "Provider unavailable",
        body: reason ?? "The required data provider is offline. Retry once it is reachable.",
      };
    case "input_required":
      return { title: "Input required", body: reason ?? "This function requires additional inputs." };
    case "input_error":
      return { title: "Invalid parameters", body: reason ?? "Check the input parameters and try again." };
    case "not_configured":
      return { title: "Not configured", body: reason ?? "This function has not been configured yet." };
    default:
      return { title: "No data available", body: reason ?? "This portfolio function returned no data." };
  }
}

export function PortfolioEmpty({
  badge,
  title,
  body,
  action,
}: {
  badge?: ReactNode;
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="portfolio-analytics-empty">
      {badge}
      <div>
        <Empty title={title} body={body} icon="∅" action={action} />
      </div>
    </div>
  );
}

/* ── presentational atoms ──────────────────────────────────────────── */

export function SectionHead({ title, meta }: { title: string; meta?: ReactNode }) {
  return (
    <header className="port-section-head">
      <div>
        <h3>{title}</h3>
        {meta != null ? <span>{meta}</span> : null}
      </div>
    </header>
  );
}

export interface Metric {
  key: string;
  label: string;
  value: ReactNode;
  tone?: string | undefined;
  title?: string;
}

export function MetricStrip({ metrics }: { metrics: Metric[] }) {
  return (
    <div className="portfolio-analytics-summary__metrics">
      {metrics.map((metric) => (
        <div key={metric.key} className="portfolio-analytics-metric" title={metric.title}>
          <span>{metric.label}</span>
          <strong className={metric.tone}>{metric.value}</strong>
        </div>
      ))}
    </div>
  );
}

/**
 * Signed horizontal bar (reuses the generic pane's ladder geometry, which
 * already carries a `--u-width` custom property contract). Pass `signed`
 * when the bar should flip colour on negative values.
 */
export function BarRow({
  label,
  value,
  max,
  text,
  title,
}: {
  label: string;
  value: number;
  max: number;
  text: string;
  title?: string;
}) {
  const width = max > 0 ? Math.min(100, (Math.abs(value) / max) * 100) : 0;
  const barClass =
    value < 0
      ? "portfolio-ladder__bar portfolio-ladder__bar--neg"
      : "portfolio-ladder__bar";
  return (
    <div className="portfolio-ladder__row" title={title}>
      <span title={label}>{label}</span>
      <div className="portfolio-ladder__track">
        <i
          className={barClass}
          style={{ ["--u-width" as string]: `${width}%` } as CSSProperties}
        />
      </div>
      <strong className={toneClass(value)}>{text}</strong>
    </div>
  );
}

/** Horizontal extent bars for non-negative magnitudes (weights, variance). */
export function ShareBarRow({
  label,
  value,
  max,
  text,
}: {
  label: string;
  value: number;
  max: number;
  text: string;
}) {
  const width = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="portfolio-ladder__row">
      <span title={label}>{label}</span>
      <div className="portfolio-ladder__track">
        <i
          className="portfolio-ladder__bar"
          style={{ ["--u-width" as string]: `${width}%` } as CSSProperties}
        />
      </div>
      <strong className="portfolio-analytics-num">{text}</strong>
    </div>
  );
}

/** Uppercase mono label used inside panel headers. */
export function PanelLabel({ children }: { children: ReactNode }) {
  return <span className="portfolio-analytics-label">{children}</span>;
}
