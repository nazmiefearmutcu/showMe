/**
 * FA — Fundamental Analysis.
 *
 * Income statement / balance sheet / cash flow + key ratios. The ShowMe FA
 * function returns a dict with keyed pandas DataFrames; the sidecar's
 * `to_dict()` helper converts those to records arrays.
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
  Skeleton,
  Tabs,
  type DataGridColumn,
} from "@/design-system";
import { SymbolBar } from "@/shell/SymbolBar";
import { useFunction } from "@/lib/useFunction";
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

export function FAPane({ code, symbol }: FunctionPaneProps) {
  const [tab, setTab] = usePersistentOption<TabId>(
    "showme.fa-tab",
    TAB_IDS,
    "income",
  );
  const { state, data, error, refetch } = useFunction<FAData>({
    code,
    symbol,
    enabled: !!symbol,
  });

  const body = !symbol ? (
    <Empty title="Pick a symbol" body="FA needs a ticker." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
    <div style={{ display: "grid", gap: 8 }}>
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
  ) : data?.data?.status && data.data.status !== "ok" ? (
    <FunctionStateNotice
      status={data.data.status}
      reason={data.data.reason}
      nextAction={data.data.nextAction ?? data.data.next_actions?.[0]}
    />
  ) : (
    <FAView data={data?.data} tab={tab} />
  );

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title={`Fundamentals — ${symbol ?? ""}`}
          subtitle="Income · Balance · Cash · Ratios"
          trailing={
            <FunctionControlGroup>
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
        <SymbolBar code={code} symbol={symbol} />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <span data-testid="function-status">{data?.status ?? data?.data?.status ?? state}</span>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span data-testid="function-source">sources · {data?.sources?.join(", ") || "—"}</span>
          {data?.warnings?.length ? <span>{data.warnings.length} warnings</span> : null}
        </PaneFooter>
      </Pane>
    </div>
  );
}

function FAView({ data, tab }: { data?: FAData; tab: TabId }) {
  if (!data) return <Empty title="Payload unavailable" />;
  if (tab === "ratios") {
    return (
      <div data-testid="function-payload" style={{ display: "grid", gap: 12 }}>
        <Ratios data={data.ratios} />
        <Methodology data={data} />
      </div>
    );
  }
  const key: keyof FAData =
    tab === "income" ? "income_statement" : tab === "balance" ? "balance_sheet" : "cash_flow";
  const rows = toRows(data[key]);
  if (!rows.length) {
    return <Empty title="Section empty" body="This statement section has no returned rows for the current input." />;
  }
  return (
    <div data-testid="function-payload" style={{ display: "grid", gap: 12 }}>
      <FinancialGrid rows={rows} />
      <Methodology data={data} />
    </div>
  );
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

function buildColumns(rows: Record<string, unknown>[]): DataGridColumn<Record<string, unknown>>[] {
  if (!rows.length) return [];
  const sample = rows[0];
  const keys = Object.keys(sample);
  return keys.map((k) => ({
    key: k,
    header: k,
    numeric: typeof sample[k] === "number",
    render: (r) => formatCell(r[k]),
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
    return <Empty title="Ratios unavailable" body="Ratio fields are missing for the current input." />;
  }
  return (
    <div
      data-testid="function-payload"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: 12,
      }}
    >
      {Object.entries(data).map(([k, v]) => (
        <Card key={k} density="compact">
          <CardHeader>{k.replace(/_/g, " ")}</CardHeader>
          <CardBody>
            <span
              style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 17,
                color: "var(--text-primary)",
              }}
            >
              {formatCell(v)}
            </span>
          </CardBody>
        </Card>
      ))}
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
        <div style={{ display: "grid", gap: 10, fontSize: 12 }}>
          {data.methodology ? (
            <p style={{ margin: 0, color: "var(--text-secondary)", lineHeight: 1.45 }}>
              {data.methodology}
            </p>
          ) : null}
          {entries.length ? (
            <dl
              style={{
                margin: 0,
                display: "grid",
                gridTemplateColumns: "180px minmax(0, 1fr)",
                gap: "6px 14px",
              }}
            >
              {entries.map(([key, value]) => (
                <Fragment key={key}>
                  <dt style={{ color: "var(--text-primary)" }}>
                    {key.replace(/_/g, " ")}
                  </dt>
                  <dd style={{ margin: 0, color: "var(--text-mute)" }}>
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
    <div style={{ display: "grid", gap: 8 }}>
      <Empty
        title={status.replace(/_/g, " ")}
        body={reason ?? "The backend marked this function result as not ready."}
        icon="!"
      />
      {reason ? (
        <span data-testid="function-reason" style={{ color: "var(--text-secondary)" }}>
          {reason}
        </span>
      ) : null}
      {nextAction ? (
        <span data-testid="function-next-action" style={{ color: "var(--text-mute)" }}>
          {nextAction}
        </span>
      ) : null}
    </div>
  );
}
