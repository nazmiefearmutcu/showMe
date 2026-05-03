/**
 * DES — Description / company snapshot.
 *
 * yfinance + finnhub profile, sector/industry/country, headcount, IPO,
 * latest financial snapshot. The pane is symbol-required.
 */
import {
  Card,
  CardBody,
  CardHeader,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { SymbolBar } from "@/shell/SymbolBar";
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface DESData {
  longName?: string;
  shortName?: string;
  symbol?: string;
  sector?: string;
  industry?: string;
  country?: string;
  city?: string;
  fullTimeEmployees?: number;
  website?: string;
  longBusinessSummary?: string;
  marketCap?: number;
  exchange?: string;
  currency?: string;
  ipoDate?: string;
  [key: string]: unknown;
}

const fmtNum = (n?: number) =>
  n == null ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
const fmtMcap = (n?: number) => {
  if (n == null) return "—";
  const a = Math.abs(n);
  if (a >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  return `$${fmtNum(n)}`;
};

export function DESPane({ code, symbol }: FunctionPaneProps) {
  const { state, data, error, refetch } = useFunction<DESData>({
    code,
    symbol,
    enabled: !!symbol,
  });

  const body = !symbol ? (
    <Empty
      title="Pick a symbol"
      body="DES needs a ticker. Try the bar above or ⌘K — e.g. AAPL, MSFT, TSLA."
      icon="⌖"
    />
  ) : state === "loading" || state === "idle" ? (
    <div style={{ display: "grid", gap: 10 }}>
      <Skeleton height={20} width="40%" />
      <Skeleton height={14} width="80%" />
      <Skeleton height={14} width="64%" />
      <Skeleton height={120} />
    </div>
  ) : state === "error" ? (
    <Empty
      title="Function error"
      body={error?.message ?? "Unknown error"}
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <DESView data={data?.data} />
  );

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title={data?.data?.longName || data?.data?.shortName || symbol || "Description"}
          subtitle={
            data?.data
              ? [
                  data.data.exchange,
                  data.data.industry,
                  data.data.country,
                ]
                  .filter(Boolean)
                  .join(" · ") || "Description"
              : symbol
                ? "Description"
                : "Description"
          }
          trailing={
            <FunctionControlGroup>
              {data?.data?.sector && <Pill tone="accent" withDot={false}>{data.data.sector}</Pill>}
              {symbol && <Pill tone="muted" withDot={false}>{symbol}</Pill>}
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!symbol}
                title="Refresh description"
              />
            </FunctionControlGroup>
          }
        />
        <SymbolBar code={code} symbol={symbol} />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span>sources · {data?.sources?.join(", ") || "—"}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function DESView({ data }: { data?: DESData }) {
  if (!data) return <Empty title="No description data" />;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)",
        gap: 14,
      }}
    >
      <Card>
        <CardHeader>Business summary</CardHeader>
        <CardBody>
          <p
            style={{
              margin: 0,
              fontSize: 12,
              lineHeight: 1.5,
              color: "var(--text-secondary)",
            }}
          >
            {data.longBusinessSummary ?? "(no summary)"}
          </p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>Snapshot</CardHeader>
        <CardBody>
          <dl
            style={{
              display: "grid",
              gridTemplateColumns: "120px 1fr",
              gap: "6px 12px",
              fontSize: 12,
              margin: 0,
            }}
          >
            <Term k="Sector">{data.sector ?? "—"}</Term>
            <Term k="Industry">{data.industry ?? "—"}</Term>
            <Term k="HQ">
              {[data.city, data.country].filter(Boolean).join(", ") || "—"}
            </Term>
            <Term k="Employees">{fmtNum(data.fullTimeEmployees)}</Term>
            <Term k="Market cap">{fmtMcap(data.marketCap)}</Term>
            <Term k="Exchange">{data.exchange ?? "—"}</Term>
            <Term k="Currency">{data.currency ?? "—"}</Term>
            <Term k="IPO">{data.ipoDate ?? "—"}</Term>
            <Term k="Website">
              {data.website ? (
                <a href={data.website} target="_blank" rel="noopener noreferrer">
                  {data.website}
                </a>
              ) : (
                "—"
              )}
            </Term>
          </dl>
        </CardBody>
      </Card>
    </div>
  );
}

function Term({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <>
      <dt style={{ color: "var(--text-mute)" }}>{k}</dt>
      <dd
        style={{
          margin: 0,
          color: "var(--text-primary)",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {children}
      </dd>
    </>
  );
}
