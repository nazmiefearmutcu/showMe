/**
 * FA — Bloomberg-grade fundamental snapshot.
 *
 * Header: symbol focus + period tab (Income/Balance/Cash/Ratios) + currency.
 * Ratios screen renders a StatCard ribbon (revenue / margin / EPS / P/E /
 * P/B / ROE) when present in the payload, plus a peer-style ratio grid.
 * Statement screens keep the dense column-grid view but add tabular numerics
 * and accent-tinted period headers.
 */
import { Fragment, useMemo } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  DataGrid,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatCard,
  Tabs,
  type DataGridColumn,
} from "@/design-system";
import { SymbolBar } from "@/shell/SymbolBar";
import { useFunction } from "@/lib/useFunction";
import { defaultSymbolForFunction } from "@/lib/symbols";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface FAData {
  status?: "ok" | "empty" | "input_error" | "provider_unavailable" | "calc_error";
  reason?: string;
  nextAction?: string;
  next_actions?: string[];
  income_statement?: Record<string, unknown>[] | Record<string, unknown>;
  balance_sheet?: Record<string, unknown>[] | Record<string, unknown>;
  cash_flow?: Record<string, unknown>[] | Record<string, unknown>;
  ratios?: Record<string, unknown>;
  methodology?: string;
  field_dictionary?: Record<string, unknown>;
  currency?: string;
  filing_date?: string;
  restated?: boolean;
  [key: string]: unknown;
}

const TABS = [
  { id: "income", label: "Income" },
  { id: "balance", label: "Balance" },
  { id: "cash", label: "Cash flow" },
  { id: "ratios", label: "Ratios" },
] as const;

type TabId = (typeof TABS)[number]["id"];
const TAB_IDS = TABS.map((t) => t.id);

// Hero ratio keys that drive the KPI ribbon. The fundamentals payload
// usually exposes a subset; we lookup variants per-key.
const HERO_RATIO_KEYS: { key: string; label: string; variants: string[] }[] = [
  { key: "revenue", label: "Revenue", variants: ["revenue", "total_revenue", "revenues"] },
  { key: "gross_margin", label: "Gross margin", variants: ["gross_margin", "gross_profit_margin"] },
  { key: "operating_margin", label: "Op. margin", variants: ["operating_margin", "op_margin"] },
  { key: "eps", label: "EPS", variants: ["eps", "earnings_per_share", "diluted_eps"] },
  { key: "pe", label: "P/E", variants: ["pe", "p_e", "price_to_earnings", "pe_ratio"] },
  { key: "pb", label: "P/B", variants: ["pb", "price_to_book", "p_b"] },
];

export function FAPane({ code, symbol }: FunctionPaneProps) {
  const [tab, setTab] = usePersistentOption<TabId>(
    "showme.fa-tab",
    TAB_IDS,
    "income",
  );
  // 2026-05-11 hotfix: when the palette opens FA without a symbol, fall
  // back to the equity default (AAPL/SPY/etc. depending on the recent-symbol
  // stack) so the panel renders immediately instead of stalling on
  // "Pick a symbol". FA is SEC-EDGAR-driven and only makes sense on equity
  // tickers, so a symbol-less render produces no useful state.
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY"]);
  const { state, data, error, refetch } = useFunction<FAData>({
    code,
    symbol: effectiveSymbol,
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const currency = (payload?.currency as string | undefined) ?? "USD";
  const filingDate =
    (payload?.filing_date as string | undefined) ??
    (typeof payload?.last_updated === "string" ? (payload.last_updated as string) : undefined);
  const restated = Boolean(payload?.restated);

  const heroRatios = useMemo(() => deriveHeroRatios(payload?.ratios), [payload?.ratios]);

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="FA needs a ticker." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={18} width="30%" />
      <Skeleton height={14} />
      <Skeleton height={14} />
      <Skeleton height={14} width="80%" />
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
  ) : data?.status && data.status !== "ok" ? (
    <FunctionStateNotice
      status={data.status}
      reason={data.reason}
      nextAction={data.nextAction}
    />
  ) : payload?.status && payload.status !== "ok" ? (
    <FunctionStateNotice
      status={payload.status}
      reason={payload.reason}
      nextAction={payload.nextAction ?? payload.next_actions?.[0]}
    />
  ) : (
    <FAView data={payload} tab={tab} heroRatios={heroRatios} />
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Fundamentals — ${symbol ?? ""}`}
          subtitle="Income · Balance · Cash · Ratios"
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {currency}
              </Pill>
              {restated ? (
                <Pill tone="warn" variant="soft" withDot={false}>
                  RESTATED
                </Pill>
              ) : null}
              <Tabs
                variant="segmented"
                items={TABS.map((t) => ({ id: t.id, label: t.label }))}
                active={tab}
                onChange={(id) => setTab(id as TabId)}
              />
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!symbol}
                title="Refresh fundamentals"
              />
            </FunctionControlGroup>
          }
        />
        <SymbolBar code={code} symbol={effectiveSymbol} />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <span data-testid="function-status">
            {data?.status ?? payload?.status ?? state}
          </span>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span data-testid="function-source">
            sources · {data?.sources?.join(", ") || "—"}
          </span>
          {filingDate ? <span>filing · {filingDate}</span> : null}
          {data?.warnings?.length ? <span>{data.warnings.length} warnings</span> : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

function FAView({
  data,
  tab,
  heroRatios,
}: {
  data?: FAData;
  tab: TabId;
  heroRatios: HeroRatio[];
}) {
  if (!data) return <Empty title="Payload unavailable" />;
  if (tab === "ratios") {
    return (
      <div data-testid="function-payload" className="u-grid-gap-12">
        {heroRatios.length ? <RatioRibbon ratios={heroRatios} /> : null}
        <Ratios data={data.ratios} />
        <Methodology data={data} />
      </div>
    );
  }
  const key: keyof FAData =
    tab === "income"
      ? "income_statement"
      : tab === "balance"
        ? "balance_sheet"
        : "cash_flow";
  const rows = toRows(data[key]);
  if (!rows.length) {
    return (
      <Empty
        title="Section empty"
        body="This statement section has no returned rows for the current input."
      />
    );
  }
  return (
    <div data-testid="function-payload" className="u-grid-gap-12">
      {heroRatios.length ? <RatioRibbon ratios={heroRatios} /> : null}
      <FinancialGrid rows={rows} />
      <Methodology data={data} />
    </div>
  );
}

interface HeroRatio {
  label: string;
  value: string;
  raw: number | null;
  tone: "positive" | "negative" | "neutral";
}

function deriveHeroRatios(ratios?: Record<string, unknown>): HeroRatio[] {
  if (!ratios) return [];
  const out: HeroRatio[] = [];
  for (const spec of HERO_RATIO_KEYS) {
    const found = spec.variants
      .map((v) => ratios[v])
      .find((value) => value != null);
    if (found == null) continue;
    const raw = typeof found === "number" ? found : Number(found);
    const value = formatHeroValue(spec.key, found);
    const tone: "positive" | "negative" | "neutral" =
      Number.isFinite(raw) && spec.key !== "pe" && spec.key !== "pb"
        ? raw > 0
          ? "positive"
          : raw < 0
            ? "negative"
            : "neutral"
        : "neutral";
    out.push({
      label: spec.label,
      value,
      raw: Number.isFinite(raw) ? raw : null,
      tone,
    });
  }
  return out;
}

function RatioRibbon({ ratios }: { ratios: HeroRatio[] }) {
  return (
    <div className="fa-ratio-ribbon">
      {ratios.map((r) => (
        <StatCard key={r.label} label={r.label} value={r.value} tone={r.tone} />
      ))}
    </div>
  );
}

function formatHeroValue(key: string, value: unknown): string {
  if (value == null) return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return String(value);
  if (key === "revenue") {
    const a = Math.abs(n);
    if (a >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
    if (a >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
    if (a >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
    return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  }
  if (key === "gross_margin" || key === "operating_margin") {
    // payload stores as 0-1 ratio or already-percent; detect.
    const pct = Math.abs(n) <= 1 ? n * 100 : n;
    return `${pct.toFixed(1)}%`;
  }
  if (key === "eps") {
    return `$${n.toFixed(2)}`;
  }
  if (key === "pe" || key === "pb") {
    return `${n.toFixed(2)}x`;
  }
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function toRows(value: unknown): Record<string, unknown>[] {
  if (Array.isArray(value)) return value as Record<string, unknown>[];
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>).map(([metric, row]) => ({
      metric,
      ...(row && typeof row === "object" ? (row as Record<string, unknown>) : { value: row }),
    }));
  }
  return [];
}

function FinancialGrid({ rows }: { rows: Record<string, unknown>[] }) {
  const cols = useMemo(() => buildColumns(rows), [rows]);
  return <DataGrid columns={cols} rows={rows} density="compact" />;
}

function buildColumns(
  rows: Record<string, unknown>[],
): DataGridColumn<Record<string, unknown>>[] {
  if (!rows.length) return [];
  const sample = rows[0];
  const keys = Object.keys(sample);
  return keys.map((k) => ({
    key: k,
    header: k,
    numeric: typeof sample[k] === "number",
    render: (r) =>
      typeof sample[k] === "number" ? (
        <span className="fa-cell-numeric">{formatCell(r[k])}</span>
      ) : (
        <span className="u-text-secondary">{formatCell(r[k])}</span>
      ),
  }));
}

function formatCell(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") {
    const a = Math.abs(v);
    if (a >= 1e12) return `${(v / 1e12).toFixed(2)}T`;
    if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
    if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
    if (a >= 1e3) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
    return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  return String(v);
}

function Ratios({ data }: { data?: Record<string, unknown> }) {
  if (!data || Object.keys(data).length === 0) {
    return (
      <Empty
        title="Ratios unavailable"
        body="Ratio fields are missing for the current input."
      />
    );
  }
  return (
    <Card>
      <CardHeader
        trailing={
          <Pill tone="accent" variant="soft" withDot={false}>
            {Object.keys(data).length} ratios
          </Pill>
        }
      >
        Comparable ratios
      </CardHeader>
      <CardBody>
        <div data-testid="function-payload" className="fa-ratio-grid">
          {Object.entries(data).map(([k, v]) => (
            <RatioCell key={k} label={k} value={v} />
          ))}
        </div>
      </CardBody>
    </Card>
  );
}

function RatioCell({ label, value }: { label: string; value: unknown }) {
  const n = typeof value === "number" ? value : Number(value);
  const tone =
    Number.isFinite(n)
      ? n > 0
        ? "var(--positive)"
        : n < 0
          ? "var(--negative)"
          : "var(--text-primary)"
      : "var(--text-primary)";
  return (
    <div className="fa-ratio-cell">
      <span className="fa-ratio-cell__label">
        {label.replace(/_/g, " ")}
      </span>
      <span className="fa-ratio-cell__value" style={{ color: tone }}>
        {formatCell(value)}
      </span>
    </div>
  );
}

function Methodology({ data }: { data: FAData }) {
  const entries = Object.entries(data.field_dictionary ?? {}).filter(
    ([, value]) => value != null && String(value).trim().length > 0,
  );
  if (!data.methodology && entries.length === 0) return null;
  return (
    <Card density="compact">
      <CardHeader>Methodology</CardHeader>
      <CardBody>
        <div className="u-grid-gap-10 u-text-12">
          {data.methodology ? (
            <p className="anr-card-meaning">{data.methodology}</p>
          ) : null}
          {entries.length ? (
            <dl className="fa-methodology-dl">
              {entries.map(([key, value]) => (
                <Fragment key={key}>
                  <dt className="u-text-primary">
                    {key.replace(/_/g, " ")}
                  </dt>
                  <dd className="fa-methodology-dd">
                    {String(value)}
                  </dd>
                </Fragment>
              ))}
            </dl>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}

function FunctionStateNotice({
  status,
  reason,
  nextAction,
}: {
  status: string;
  reason?: string;
  nextAction?: string;
}) {
  return (
    <div className="u-grid-gap-8">
      <Empty
        title={status.replace(/_/g, " ")}
        body={reason ?? "The backend marked this function result as not ready."}
        icon="!"
      />
      {reason ? (
        <span data-testid="function-reason" className="u-text-secondary">
          {reason}
        </span>
      ) : null}
      {nextAction ? (
        <span data-testid="function-next-action" className="u-text-mute">
          {nextAction}
        </span>
      ) : null}
    </div>
  );
}
