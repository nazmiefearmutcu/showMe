/**
 * SPLC — Supply Chain (approximate 10-K relationship table).
 *
 * Header: RELATIONSHIP filter segmented control (all / customers / suppliers
 * / competitors) + extraction-state pill + status pill + refresh. Body: an
 * "approximate" honesty banner whenever the backend serves labelled
 * reference rows, a KPI strip (relationships in view + per-type counts), a
 * dense relationship table — relationship pill, counterparty, ticker when
 * the reference peer list provides one, extraction confidence, per-row
 * source stamp — and the raw 10-K debt-maturity excerpt when the backend
 * extracted one.
 *
 * Data honesty: SPLC is regex text-mining over recent 10-K sections, not a
 * verified relationship graph. Rows whose source_mode contains "reference"
 * are labelled reference rows (confidence is a heuristic, not a measured
 * exposure); when no EDGAR feed is available the pane renders the backend's
 * provider-unavailable state instead of a fabricated chain.
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

interface SPLCRow {
  symbol?: string;
  relationship?: string | null;
  counterparty?: string | null;
  ticker?: string | null;
  confidence?: number | null;
  source_mode?: string;
  filingDate?: string | null;
  exposure?: string | null;
}

interface SPLCData {
  status?: string;
  reason?: string;
  rows?: SPLCRow[];
  customers?: unknown[];
  suppliers?: unknown[];
  debt_maturity_section?: string;
  methodology?: string;
  field_dictionary?: Record<string, unknown>;
}

type RelBucket = "customer" | "supplier" | "competitor" | "other";
type RelFilter = "all" | RelBucket;

const REL_OPTIONS = [
  { value: "all", label: "ALL" },
  { value: "customer", label: "CUSTOMERS" },
  { value: "supplier", label: "SUPPLIERS" },
  { value: "competitor", label: "COMPETITORS" },
] as const satisfies readonly { value: RelFilter; label: string }[];
const REL_IDS = REL_OPTIONS.map((o) => o.value);

function classifyRelationship(rel: string | null | undefined): RelBucket {
  const r = String(rel ?? "").toLowerCase();
  if (r.includes("customer")) return "customer";
  if (r.includes("supplier")) return "supplier";
  if (r.includes("competitor")) return "competitor";
  return "other";
}

function relationshipTone(rel: string | null | undefined) {
  const bucket = classifyRelationship(rel);
  if (bucket === "customer") return "accent" as const;
  if (bucket === "supplier") return "positive" as const;
  if (bucket === "competitor") return "warn" as const;
  return "muted" as const;
}

export function SPLCPane({ code, symbol }: FunctionPaneProps) {
  const [relFilter, setRelFilter] = usePersistentOption<RelFilter>(
    "showme.splc.relationship",
    REL_IDS,
    "all",
  );
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const { state, data, error, refetch } = useFunction<SPLCData>({
    code,
    symbol: effectiveSymbol,
    params: { live: true },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const rows: SPLCRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";
  const providerDown = state === "ok" && status === "provider_unavailable";

  const isReference = useMemo(() => {
    if (providerDown) return false;
    if (status === "reference_relationships") return true;
    if (!rows.length) return false;
    const withMode = rows.filter((r) => !!r.source_mode);
    if (!withMode.length) return false;
    return withMode.every((r) => (r.source_mode ?? "").includes("reference"));
  }, [rows, status, providerDown]);

  const matters = useMemo(
    () => rows.filter((r) => r.relationship !== "provider_unavailable"),
    [rows],
  );

  const filtered = useMemo(
    () =>
      relFilter === "all"
        ? matters
        : matters.filter(
            (r) => classifyRelationship(r.relationship) === relFilter,
          ),
    [matters, relFilter],
  );

  const counts = useMemo(
    () => ({
      customer: matters.filter(
        (r) => classifyRelationship(r.relationship) === "customer",
      ).length,
      supplier: matters.filter(
        (r) => classifyRelationship(r.relationship) === "supplier",
      ).length,
      competitor: matters.filter(
        (r) => classifyRelationship(r.relationship) === "competitor",
      ).length,
    }),
    [matters],
  );

  const debtExcerpt = useMemo(() => {
    const text = (payload?.debt_maturity_section ?? "").trim();
    if (!text) return null;
    return text.length > 260 ? `${text.slice(0, 260)}…` : text;
  }, [payload]);

  const COLS: DataGridColumn<SPLCRow>[] = useMemo(
    () => [
      {
        key: "relationship",
        header: "Relationship",
        width: 150,
        render: (r) =>
          r.relationship ? (
            <Pill
              tone={relationshipTone(r.relationship)}
              variant="soft"
              withDot={false}
            >
              {r.relationship}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
      {
        key: "counterparty",
        header: "Counterparty",
        width: 300,
        render: (r) => (
          <span style={monoStrongStyle}>{r.counterparty ?? "—"}</span>
        ),
      },
      {
        key: "ticker",
        header: "Ticker",
        width: 110,
        render: (r) => (
          <span style={monoMutedStyle}>{r.ticker ?? "—"}</span>
        ),
      },
      {
        key: "confidence",
        header: "Confidence",
        width: 120,
        numeric: true,
        render: (r) => (
          <span style={monoMutedStyle}>
            {typeof r.confidence === "number"
              ? r.confidence.toFixed(2)
              : "—"}
          </span>
        ),
      },
      {
        key: "source_mode",
        header: "Source",
        width: 300,
        render: (r) => {
          const mode = r.source_mode ?? "";
          const isRef = mode.includes("reference");
          const isDown = mode.includes("unavailable");
          return mode ? (
            <Pill
              tone={isDown ? "warn" : isRef ? "warn" : "muted"}
              variant="soft"
              withDot={false}
            >
              {mode}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          );
        },
      },
    ],
    [],
  );

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="SPLC needs an equity / ETF ticker." icon="⌖" />
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
  ) : providerDown || matters.length === 0 ? (
    <Empty
      title="Supply-chain relationships unavailable"
      body={
        payload?.reason ??
        "No relationship rows were extracted or labelled for this symbol; SPLC will not invent a supply chain."
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : filtered.length === 0 ? (
    <Empty
      title="No relationships match the current filter"
      body="Set the RELATIONSHIP control back to ALL to see every labelled row returned for this symbol."
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {isReference ? (
        <div
          role="status"
          aria-label="Reference data notice"
          style={referenceBannerStyle}
        >
          <Pill tone="warn" variant="soft">
            Reference data
          </Pill>
          <span style={referenceNoteStyle}>
            No explicit counterparties were extracted from recent 10-K
            sections, so these are labelled reference rows from the ShowMe
            supply-chain model — NOT a verified relationship graph.
          </span>
        </div>
      ) : null}
      <section style={kpiGridStyle} aria-label="SPLC KPI strip">
        <StatCard
          label="Relationships in view"
          value={String(filtered.length)}
          caption={`${matters.length} RETURNED`}
          tone="neutral"
        />
        <StatCard
          label="Customers"
          value={String(counts.customer)}
          caption="10-K CONCENTRATION LANGUAGE"
          tone="neutral"
        />
        <StatCard
          label="Suppliers"
          value={String(counts.supplier)}
          caption="10-K SUPPLY RISK LANGUAGE"
          tone="neutral"
        />
        <StatCard
          label="Competitors"
          value={String(counts.competitor)}
          caption="REFERENCE SECTOR PEERS"
          tone="neutral"
        />
      </section>
      <DataGrid
        columns={COLS}
        rows={filtered}
        rowKey={(r, i) => `${r.relationship ?? ""}-${r.counterparty ?? ""}-${i}`}
        density="compact"
        ariaLabel="SPLC supply-chain relationships table"
      />
      {debtExcerpt ? (
        <section
          aria-label="SPLC debt maturity excerpt"
          style={excerptStyle}
        >
          <span style={excerptLabelStyle}>10-K DEBT-MATURITY EXCERPT</span>
          <p style={excerptTextStyle}>{debtExcerpt}</p>
        </section>
      ) : null}
      <p style={disclaimerStyle} role="note">
        Approximate by construction: SPLC regex-scans recent 10-K sections for
        customer/supplier concentration language and labels reference rows when
        extraction finds nothing. Confidence is an extraction heuristic, not a
        measured revenue or purchase exposure.
      </p>
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Supply Chain — ${effectiveSymbol || ""}`}
          subtitle={`${effectiveSymbol || "—"} · ${filtered.length} of ${matters.length} relationships`}
          trailing={
            <FunctionControlGroup>
              {state === "ok" && !providerDown ? (
                <Pill
                  tone={isReference ? "warn" : "accent"}
                  variant="soft"
                  withDot={false}
                >
                  {isReference ? "REFERENCE" : "10-K EXTRACT"}
                </Pill>
              ) : null}
              <SegmentedControl
                label="RELATIONSHIP"
                value={relFilter}
                options={REL_OPTIONS}
                onChange={setRelFilter}
                title="Relationship type filter"
              />
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh supply-chain relationships"
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
          <StatusSection
            label="rows"
            value={`${filtered.length}/${matters.length}`}
          />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="rel" value={relFilter} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const referenceBannerStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  padding: "8px 10px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--warn-soft)",
  background: "var(--warn-soft)",
};

const referenceNoteStyle: CSSProperties = {
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-xs)",
  lineHeight: 1.45,
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
};

const excerptStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
  padding: "8px 10px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border)",
  background: "var(--surface-2)",
};

const excerptLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  letterSpacing: "0.08em",
  color: "var(--text-mute)",
};

const excerptTextStyle: CSSProperties = {
  margin: 0,
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-xs)",
  lineHeight: 1.45,
};

const disclaimerStyle: CSSProperties = {
  margin: 0,
  color: "var(--text-mute)",
  fontSize: "var(--font-size-xs)",
  lineHeight: 1.45,
};
