/**
 * DDIS — Debt Distribution by Maturity.
 *
 * Issuer maturity ladder (0-1Y / 1-3Y / 3-5Y / 5Y+) backed by SEC EDGAR
 * companyfacts long-term-debt concepts. Header: status pill + refresh.
 * Body: issuer headline cards (total debt, source mode, biggest wall,
 * nearest-bucket share) + ladder table where every % share row carries a
 * token-tinted bar. When no SEC schedule and no user-supplied maturities
 * exist the handler returns an honest EMPTY payload (status "empty" +
 * reason + next_actions) — no illustrative ladder, and the pane renders
 * that reason instead of inventing rows.
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
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface DDISRow {
  bucket?: string;
  tenor_years?: number;
  amount_usd_bn?: number;
  currency?: string;
  pct?: number;
}

interface DDISData {
  status?: string;
  rows?: DDISRow[];
  summary?: {
    issuer?: string;
    cik?: string;
    total_debt_usd_bn?: number;
    currency?: string;
    source_mode?: string;
  };
  reason?: string;
  next_actions?: string[];
  methodology?: string;
}

export function DDISPane({ code, symbol }: FunctionPaneProps) {
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "BOND"]);
  const { state, data, error, refetch } = useFunction<DDISData>({
    code,
    symbol: effectiveSymbol,
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows: DDISRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const summary = payload?.summary;
  const status = payload?.status ?? "—";
  const sourceMode = summary?.source_mode ?? "—";
  const nextActions = Array.isArray(payload?.next_actions)
    ? payload!.next_actions!.filter((a): a is string => typeof a === "string")
    : [];
  const isLive = state === "ok" && status === "ok";

  const stats = useMemo(() => deriveStats(rows), [rows]);

  const COLS: DataGridColumn<DDISRow>[] = useMemo(
    () => [
      {
        key: "bucket",
        header: "Bucket",
        width: 110,
        render: (r) => (
          <span style={monoStrongStyle}>{r.bucket ?? "—"}</span>
        ),
      },
      {
        key: "tenor_years",
        header: "Tenor",
        numeric: true,
        width: 84,
        render: (r) => (
          <span style={monoMutedStyle}>
            {r.tenor_years != null ? `${r.tenor_years.toFixed(1)}y` : "—"}
          </span>
        ),
      },
      {
        key: "amount_usd_bn",
        header: "Notional ($bn)",
        numeric: true,
        width: 132,
        render: (r) => (
          <span style={monoPrimaryStyle}>{fmtBn(r.amount_usd_bn)}</span>
        ),
      },
      {
        key: "pct",
        header: "Share",
        width: 220,
        render: (r) => <ShareBar pct={r.pct} />,
      },
      {
        key: "currency",
        header: "CCY",
        width: 72,
        render: (r) => (
          <span style={monoMutedStyle}>{r.currency ?? summary?.currency ?? "—"}</span>
        ),
      },
    ],
    [summary?.currency],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick an issuer" body="DDIS needs an issuer ticker to resolve the debt ladder." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={56} />
      <Skeleton height={20} />
      <Skeleton height={20} />
      <Skeleton height={20} width="80%" />
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
  ) : rows.length === 0 ? (
    <Empty
      title="No maturity ladder"
      body={
        <>
          <span>
            {payload?.reason ??
              "No debt schedule returned for this issuer — no illustrative filler is shown."}
          </span>
          {nextActions.length > 0 ? (
            <ul style={nextActionsStyle}>
              {nextActions.slice(0, 3).map((action) => (
                <li key={action}>{action}</li>
              ))}
            </ul>
          ) : null}
        </>
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="DDIS issuer headline">
        <StatCard
          label="Total debt"
          value={`$${fmtBn(summary?.total_debt_usd_bn)}bn`}
          caption={`${summary?.issuer ?? effectiveSymbol ?? "—"}${summary?.cik ? ` · CIK ${summary.cik}` : ""}`}
          tone="neutral"
        />
        <StatCard
          label="Largest wall"
          value={stats.largestBucket ?? "—"}
          caption={`$${fmtBn(stats.largestAmount)}bn · ${stats.largestPct.toFixed(1)}%`}
          tone="neutral"
        />
        <StatCard
          label="0-1Y share"
          value={stats.nearestPct != null ? `${stats.nearestPct.toFixed(1)}%` : "—"}
          caption="PAPER DUE WITHIN 12M"
          tone={
            stats.nearestPct != null && stats.nearestPct >= 25
              ? "negative"
              : "neutral"
          }
        />
        <StatCard
          label="Buckets"
          value={String(rows.length)}
          caption={sourceMode.toUpperCase()}
          tone="neutral"
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(r) => r.bucket ?? String(r.tenor_years ?? "")}
        density="compact"
        ariaLabel="DDIS maturity ladder"
        // Lane B4: nearest maturities first — the ladder is a wall-risk
        // read, so tenor-ascending is the decision-relevant default.
        defaultSortKey="tenor_years"
        defaultSortDir="ascending"
        keyboardNavigable
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Debt by Maturity — ${summary?.issuer ?? (effectiveSymbol || "")}`}
          subtitle={`${effectiveSymbol || "—"} · ${summary?.currency ?? "USD"} ladder`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} buckets
              </Pill>
              <Pill
                tone={isLive ? "positive" : "muted"}
                variant="soft"
              >
                {isLive ? "SEC live" : status}
              </Pill>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh maturity ladder"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="sources" value={data?.sources?.join(", ") || "—"} />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="buckets" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="mode" value={sourceMode} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function ShareBar({ pct }: { pct?: number }) {
  const width = pct != null && Number.isFinite(pct) ? Math.max(0, Math.min(100, pct)) : 0;
  return (
    <div style={shareWrapStyle} aria-label={pct != null ? `${pct.toFixed(1)}% share` : undefined}>
      <div style={shareTrackStyle}>
        <div style={{ ...shareFillStyle, width: `${width}%` }} />
      </div>
      <span style={shareLabelStyle}>
        {pct != null && Number.isFinite(pct) ? `${pct.toFixed(1)}%` : "—"}
      </span>
    </div>
  );
}

interface DDISStats {
  largestBucket: string | null;
  largestAmount: number | null;
  largestPct: number;
  nearestPct: number | null;
}

function deriveStats(rows: DDISRow[]): DDISStats {
  let largest: DDISRow | null = null;
  for (const r of rows) {
    if ((r.amount_usd_bn ?? 0) > (largest?.amount_usd_bn ?? -Infinity)) largest = r;
  }
  const nearest = rows.find((r) => r.bucket === "0-1Y");
  return {
    largestBucket: largest?.bucket ?? null,
    largestAmount: largest?.amount_usd_bn ?? null,
    largestPct: largest?.pct ?? 0,
    nearestPct: nearest?.pct ?? null,
  };
}

function fmtBn(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const nextActionsStyle: CSSProperties = {
  margin: "8px 0 0",
  paddingLeft: 18,
  display: "grid",
  gap: 4,
  color: "var(--text-mute)",
  fontSize: "var(--font-size-sm)",
};

const shareWrapStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  minWidth: 0,
};

const shareTrackStyle: CSSProperties = {
  flex: 1,
  height: 8,
  borderRadius: 4,
  background: "var(--grid-color, var(--text-mute))",
  overflow: "hidden",
};

const shareFillStyle: CSSProperties = {
  height: "100%",
  borderRadius: 4,
  background: "var(--accent)",
};

const shareLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: "var(--font-size-sm)",
  color: "var(--text-primary)",
  width: 52,
  textAlign: "right",
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const monoPrimaryStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
};

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
};
