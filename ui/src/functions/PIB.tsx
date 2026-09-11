/**
 * PIB — Public Information Book (SEC filing index + public-info section map).
 *
 * Header: FORM filter segmented control (all / 8-K / 10-K & Q / insider 3-4-5)
 * + status pill + refresh. Body: a labeled section map (profile / financials /
 * filings / holders / news — each carrying the backend availability stamp and
 * the ShowMe function that serves it), a KPI ribbon (filings in view, latest
 * filed date, 8-K count, insider forms) and a dense filing table with per-row
 * source pills.
 *
 * Data honesty: when the SEC EDGAR feed is unavailable the backend returns
 * status "provider_unavailable" with a reason; the pane renders that reason in
 * an explicit empty state instead of a stale or fabricated book.
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
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface PIBRow {
  symbol?: string;
  section?: string;
  form?: string | null;
  filingDate?: string | null;
  reportDate?: string | null;
  accession?: string | null;
  url?: string | null;
  source_mode?: string;
}

interface PIBSection {
  section?: string;
  status?: string;
  function?: string;
  count?: number;
}

interface PIBData {
  status?: string;
  reason?: string;
  rows?: PIBRow[];
  sections?: PIBSection[];
  methodology?: string;
}

type FormBucket = "8k" | "10k" | "insider" | "other";
type FormFilter = "all" | FormBucket;

const FORM_OPTIONS = [
  { value: "all", label: "ALL" },
  { value: "8k", label: "8-K" },
  { value: "10k", label: "10-K/Q" },
  { value: "insider", label: "INSIDER" },
] as const satisfies readonly { value: FormFilter; label: string }[];
const FORM_IDS = FORM_OPTIONS.map((o) => o.value);

function classifyForm(form: string | null | undefined): FormBucket {
  const f = String(form ?? "").toUpperCase();
  if (f.startsWith("8-K")) return "8k";
  if (f.startsWith("10-")) return "10k";
  if (/^[345](\/|$)/.test(f)) return "insider";
  return "other";
}

export function PIBPane({ code, symbol }: FunctionPaneProps) {
  const [formFilter, setFormFilter] = usePersistentOption<FormFilter>(
    "showme.pib.form",
    FORM_IDS,
    "all",
  );
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const { state, data, error, refetch } = useFunction<PIBData>({
    code,
    symbol: effectiveSymbol,
    params: {},
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows: PIBRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const sections: PIBSection[] = useMemo(() => payload?.sections ?? [], [payload]);
  const status = payload?.status ?? "—";
  const providerDown = state === "ok" && status === "provider_unavailable";

  const filtered = useMemo(
    () =>
      rows.filter(
        (r) => formFilter === "all" || classifyForm(r.form) === formFilter,
      ),
    [rows, formFilter],
  );

  const counts = useMemo(
    () => ({
      eightK: rows.filter((r) => classifyForm(r.form) === "8k").length,
      insider: rows.filter((r) => classifyForm(r.form) === "insider").length,
      latest: rows
        .map((r) => (r.filingDate ?? "").slice(0, 10))
        .filter((d) => /^\d{4}-\d{2}-\d{2}/.test(d))
        .sort()
        .at(-1) ?? "—",
    }),
    [rows],
  );

  const COLS: DataGridColumn<PIBRow>[] = useMemo(
    () => [
      {
        key: "filingDate",
        header: "Filed",
        width: 116,
        sortValue: (r) => r.filingDate ?? null,
        render: (r) => (
          <span style={monoPrimaryStyle}>
            {(r.filingDate ?? "—").slice(0, 10)}
          </span>
        ),
      },
      {
        key: "reportDate",
        header: "Reported",
        width: 116,
        render: (r) => (
          <span style={monoMutedStyle}>
            {(r.reportDate ?? "—").slice(0, 10) || "—"}
          </span>
        ),
      },
      {
        key: "form",
        header: "Form",
        width: 108,
        render: (r) => {
          const bucket = classifyForm(r.form);
          return (
            <Pill
              tone={
                r.form == null
                  ? "muted"
                  : bucket === "8k"
                    ? "accent"
                    : bucket === "10k"
                      ? "positive"
                      : "muted"
              }
              variant="soft"
              withDot={false}
            >
              {r.form ?? "—"}
            </Pill>
          );
        },
      },
      {
        key: "accession",
        header: "Accession",
        width: 208,
        render: (r) => (
          <span style={monoMutedStyle}>{r.accession ?? "—"}</span>
        ),
      },
      {
        key: "source_mode",
        header: "Source",
        width: 232,
        render: (r) =>
          r.source_mode ? (
            <Pill
              tone={r.source_mode.includes("unavailable") ? "warn" : "muted"}
              variant="soft"
              withDot={false}
            >
              {r.source_mode}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
    ],
    [],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="PIB needs an equity / ETF ticker." icon="⌖" />
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
  ) : providerDown ? (
    <Empty
      title="Public information book unavailable"
      body={
        payload?.reason ??
        "SEC filing feed returned no rows; the book cannot be rendered without filing evidence."
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : rows.length === 0 ? (
    // Audit A3 PIB L: a legitimately empty (but healthy) feed is not an
    // "unavailable" book — keep the honest distinction.
    <Empty
      title="No filings returned"
      body={
        payload?.reason ??
        `The SEC feed returned no filings for ${effectiveSymbol} in the selected window.`
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={sectionGridStyle} aria-label="PIB section map">
        {sections.map((s, i) => (
          <div key={`${s.section ?? "section"}-${i}`} style={factCardStyle}>
            <span style={factLabelStyle}>{(s.section ?? "?").toUpperCase()}</span>
            <span style={factValueStyle}>{s.status ?? "—"}</span>
            {s.function ? (
              <Pill tone="muted" variant="soft" withDot={false}>
                {`via ${s.function}`}
              </Pill>
            ) : null}
          </div>
        ))}
      </section>
      <section style={kpiGridStyle} aria-label="PIB KPI ribbon">
        <StatCard
          label="Filings in view"
          value={String(filtered.length)}
          caption={`${rows.length} TOTAL RETURNED`}
          tone="neutral"
        />
        <StatCard
          label="Latest filed"
          value={counts.latest}
          caption="SEC EDGAR FEED"
          tone="neutral"
        />
        <StatCard
          label="8-K events"
          value={String(counts.eightK)}
          caption="CURRENT EVENTS FORM"
          tone="neutral"
        />
        <StatCard
          label="Insider forms"
          value={String(counts.insider)}
          caption="FORMS 3 / 4 / 5"
          tone="neutral"
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={filtered}
        rowKey={(r, i) => `${r.accession ?? ""}-${i}`}
        density="compact"
        ariaLabel="PIB filings table"
        // Audit A3 PIB M: filings grid gets the kit's built-in sorter
        // (newest first) + keyboard cell navigation/clipboard copy.
        defaultSortKey="filingDate"
        defaultSortDir="descending"
        keyboardNavigable
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Public Information Book — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${filtered.length} of ${rows.length} filings`}
          trailing={
            <FunctionControlGroup>
              <Pill tone={providerDown ? "warn" : "muted"} variant="soft" withDot={false}>
                {sections.length} sections
              </Pill>
              <SegmentedControl
                label="FORM"
                value={formFilter}
                options={FORM_OPTIONS}
                onChange={setFormFilter}
                title="Filing form filter"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh public information book"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="rows" value={`${filtered.length}/${rows.length}`} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="form" value={formFilter} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

const sectionGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 8,
};

const factCardStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "flex-start",
  gap: 4,
  padding: "8px 10px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border)",
  background: "var(--surface-2)",
};

const factLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  letterSpacing: "0.08em",
  color: "var(--text-mute)",
};

const factValueStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: "var(--font-size-xs)",
  color: "var(--text-primary)",
};

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
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
