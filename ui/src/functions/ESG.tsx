/**
 * ESG — Equity / ETF vendor sustainability scoring.
 *
 * KPI ribbon of {Total / E / S / G}, dense pillar grid with the controversy
 * row, and Empty fallback that surfaces the backend `reason` +
 * `next_actions` paragraph when the vendor is unavailable. ESG is symbol-
 * first; the pane echoes the resolved symbol in its subtitle.
 */
import { useMemo, type CSSProperties, type ReactNode } from "react";
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

interface ESGRow {
  pillar: string;
  score: number | null;
  scale: string;
  source_mode: string;
}

interface ESGData {
  status?: "ok" | "provider_unavailable" | "empty" | "input_error" | "calc_error";
  rows?: ESGRow[];
  totalEsg?: number | null;
  environmentScore?: number | null;
  socialScore?: number | null;
  governanceScore?: number | null;
  controversyLevel?: number | string | null;
  reason?: string;
  methodology?: string;
  field_dictionary?: Record<string, unknown>;
  next_actions?: string[];
  [key: string]: unknown;
}

export function ESGPane({ code, symbol }: FunctionPaneProps) {
  const effectiveSymbol =
    symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const { state, data, error, refetch } = useFunction<ESGData>({
    code,
    symbol: effectiveSymbol,
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const status = payload?.status ?? data?.status;
  const isProviderUnavailable = status === "provider_unavailable";

  const rows = useMemo<ESGRow[]>(() => {
    const raw = payload?.rows;
    return Array.isArray(raw) ? raw : [];
  }, [payload?.rows]);

  const total = normalizeScore(payload?.totalEsg);
  const env = normalizeScore(payload?.environmentScore);
  const soc = normalizeScore(payload?.socialScore);
  const gov = normalizeScore(payload?.governanceScore);
  const controversy = payload?.controversyLevel ?? null;

  const sources = data?.sources ?? [];
  const sourceMode =
    rows.find((r) => r.source_mode)?.source_mode ??
    (isProviderUnavailable ? "vendor_unavailable" : "—");

  const cols = useMemo<DataGridColumn<ESGRow>[]>(
    () => [
      {
        key: "pillar",
        header: "Pillar",
        width: 160,
        render: (row) => <PillarCell pillar={row.pillar} />,
      },
      {
        key: "score",
        header: "Score",
        numeric: true,
        width: 120,
        render: (row) => <ScoreCell score={row.score} />,
      },
      {
        key: "scale",
        header: "Scale",
        render: (row) => (
          <span style={mutedStyle}>{row.scale || "—"}</span>
        ),
      },
      {
        key: "source_mode",
        header: "Source",
        width: 180,
        render: (row) => <SourceModeCell mode={row.source_mode} />,
      },
    ],
    [],
  );

  const subtitleMode = isProviderUnavailable
    ? "vendor unavailable"
    : "vendor scoring";

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="ESG needs an equity or ETF ticker." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={56} />
      <Skeleton height={18} width="40%" />
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
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="ESG KPI ribbon">
        <KpiCell
          label="Total"
          score={total}
          unavailable={isProviderUnavailable}
        />
        <KpiCell
          label="Environment"
          score={env}
          unavailable={isProviderUnavailable}
        />
        <KpiCell
          label="Social"
          score={soc}
          unavailable={isProviderUnavailable}
        />
        <KpiCell
          label="Governance"
          score={gov}
          unavailable={isProviderUnavailable}
        />
      </section>

      {rows.length === 0 || rows.every((r) => r.score == null) ? (
        <Empty
          title={
            isProviderUnavailable
              ? "Vendor unavailable"
              : "No ESG rows"
          }
          body={
            <div style={emptyBodyStyle}>
              {payload?.reason && (
                <p style={emptyReasonStyle}>{payload.reason}</p>
              )}
              {Array.isArray(payload?.next_actions) &&
                payload.next_actions.length > 0 && (
                  <ul style={nextActionsStyle}>
                    {payload.next_actions.map((a, i) => (
                      <li key={i}>{a}</li>
                    ))}
                  </ul>
                )}
            </div>
          }
          icon={isProviderUnavailable ? "⌀" : "∅"}
        />
      ) : (
        <DataGrid
          columns={cols}
          rows={rows}
          rowKey={(r, i) => `${r.pillar}-${i}`}
          density="compact"
          ariaLabel="ESG pillars"
        />
      )}

      {payload?.methodology && (
        <p style={methodologyStyle}>{payload.methodology}</p>
      )}
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="ESG scores"
          subtitle={
            effectiveSymbol
              ? `${effectiveSymbol} · ${subtitleMode}`
              : subtitleMode
          }
          trailing={
            <FunctionControlGroup>
              <Pill
                tone={isProviderUnavailable ? "warn" : "muted"}
                variant="soft"
                withDot={false}
              >
                {sourceMode}
              </Pill>
              <Pill
                tone={controversyTone(controversy)}
                variant="soft"
                withDot={false}
              >
                CTRV · {controversy == null ? "—" : String(controversy)}
              </Pill>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh ESG"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={sources.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection
            label="status"
            value={status ?? state}
            tone={isProviderUnavailable ? "warn" : "neutral"}
          />
          <StatusDivider />
          <StatusSection
            label="controversy"
            value={controversy == null ? "—" : String(controversy)}
            tone={controversyTone(controversy)}
          />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function normalizeScore(value: unknown): number | null {
  if (value == null) return null;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function controversyTone(
  value: number | string | null | undefined,
): "positive" | "warn" | "negative" | "muted" {
  if (value == null) return "muted";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "muted";
  if (n >= 4) return "negative";
  if (n >= 2) return "warn";
  return "positive";
}

function PillarCell({ pillar }: { pillar: string }): ReactNode {
  const label = pillar ? pillar.toUpperCase() : "—";
  const tone =
    pillar === "controversy"
      ? "warn"
      : pillar === "total"
        ? "accent"
        : "muted";
  return (
    <Pill tone={tone} variant="soft" withDot={false}>
      {label}
    </Pill>
  );
}

function ScoreCell({ score }: { score: number | null }): ReactNode {
  if (score == null) {
    return <span style={mutedStyle}>—</span>;
  }
  return (
    <span style={scoreStyle}>
      {score.toLocaleString(undefined, { maximumFractionDigits: 2 })}
    </span>
  );
}

function SourceModeCell({ mode }: { mode: string }): ReactNode {
  if (!mode) return <span style={mutedStyle}>—</span>;
  const tone: "positive" | "warn" | "muted" =
    mode === "live_yfinance"
      ? "positive"
      : mode === "vendor_unavailable"
        ? "warn"
        : "muted";
  return (
    <Pill tone={tone} variant="soft" withDot={false}>
      {mode}
    </Pill>
  );
}

function KpiCell({
  label,
  score,
  unavailable,
}: {
  label: string;
  score: number | null;
  unavailable: boolean;
}) {
  const value =
    score == null
      ? "—"
      : score.toLocaleString(undefined, { maximumFractionDigits: 2 });
  const caption = unavailable ? "vendor unavailable" : "vendor score";
  const tone: "neutral" | "positive" | "negative" =
    score == null ? "neutral" : score >= 50 ? "positive" : "negative";
  return (
    <StatCard
      label={label}
      value={value}
      caption={caption.toUpperCase()}
      tone={tone}
      trend={[]}
    />
  );
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: 10,
};

const mutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
};

const scoreStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const emptyBodyStyle: CSSProperties = {
  display: "grid",
  gap: 8,
  textAlign: "left",
  maxWidth: 520,
  margin: "0 auto",
};

const emptyReasonStyle: CSSProperties = {
  color: "var(--text-primary)",
  fontSize: 12,
  lineHeight: 1.5,
};

const nextActionsStyle: CSSProperties = {
  margin: 0,
  paddingLeft: 18,
  color: "var(--text-mute)",
  fontSize: 11,
  lineHeight: 1.6,
};

const methodologyStyle: CSSProperties = {
  margin: 0,
  fontSize: 11,
  lineHeight: 1.6,
  color: "var(--text-mute)",
  borderTop: "1px solid var(--border-subtle)",
  paddingTop: 8,
};
