/**
 * FLDS — Field Lookup (Excel autocomplete over the ShowMe field catalog).
 *
 * Search box (committed prefix, persisted as `showme.flds.prefix`) + a
 * client-side category filter drive the backend catalog search. The
 * backend is explicit that this is a LOCAL catalog lookup, not a live
 * market-data request — the pane keeps that honesty in a header pill and
 * surfaces the methodology instead of dressing rows up as quotes.
 */
import { useMemo, useState, type CSSProperties, type FormEvent } from "react";
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
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption, usePersistentString } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface FLDSRow {
  field?: string;
  category?: string;
  description?: string;
  example?: string;
}

interface FLDSSummary {
  query?: string;
  matched?: number;
  shown?: number;
  catalog_fields?: number;
}

interface FLDSData {
  status?: string;
  rows?: FLDSRow[];
  summary?: FLDSSummary;
  methodology?: string;
}

const PREFIX_KEY = "showme.flds.prefix";

const CATEGORY_OPTIONS = [
  { value: "all", label: "All" },
  { value: "market", label: "Market" },
  { value: "valuation", label: "Val" },
  { value: "fundamental", label: "Fund" },
  { value: "statement", label: "Stmt" },
  { value: "cash_flow", label: "CF" },
  { value: "fixed_income", label: "FI" },
  { value: "options", label: "Opt" },
  { value: "risk", label: "Risk" },
  { value: "technical", label: "Tech" },
] as const;
const CATEGORY_IDS = CATEGORY_OPTIONS.map((o) => o.value);
type CategoryFilter = (typeof CATEGORY_IDS)[number];

export function FLDSPane({ code }: FunctionPaneProps) {
  const [category, setCategory] = usePersistentOption<CategoryFilter>(
    "showme.flds.category",
    CATEGORY_IDS,
    "all",
  );
  const [prefix, setPrefix] = usePersistentString(PREFIX_KEY, "");
  const [draft, setDraft] = useState<string>(prefix);

  const { state, data, error, refetch } = useFunction<FLDSData>({
    code,
    params: { prefix, limit: 50 },
  });

  const payload = data?.data;
  const status = payload?.status ?? "—";
  const summary = payload?.summary;
  const allRows = useMemo(() => payload?.rows ?? [], [payload]);
  const rows = useMemo(
    () =>
      category === "all"
        ? allRows
        : allRows.filter((r) => (r.category ?? "") === category),
    [allRows, category],
  );

  function submit(event: FormEvent) {
    event.preventDefault();
    const next = draft.trim().toLowerCase();
    setDraft(next);
    setPrefix(next);
  }

  const COLS: DataGridColumn<FLDSRow>[] = useMemo(
    () => [
      {
        key: "field",
        header: "Field",
        width: 170,
        render: (r) => (
          <span style={monoStrongStyle}>{r.field ?? "—"}</span>
        ),
      },
      {
        key: "category",
        header: "Category",
        width: 120,
        render: (r) => (
          <Pill tone="muted" variant="soft" withDot={false}>
            {r.category ?? "general"}
          </Pill>
        ),
      },
      {
        key: "description",
        header: "Description",
        render: (r) => <span style={bodyStyle}>{r.description ?? "—"}</span>,
      },
      {
        key: "example",
        header: "Where it is used",
        width: 320,
        render: (r) => (
          <span style={monoMutedStyle}>{r.example ?? "—"}</span>
        ),
      },
    ],
    [],
  );

  const body = state === "loading" || state === "idle" ? (
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
      title="No fields match"
      body={
        summary?.query && summary.query !== "all"
          ? `The local catalog has no field matching "${summary.query}" in the ${category === "all" ? "any" : category} category.`
          : "The local catalog returned no fields for this filter."
      }
      icon="∅"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <section style={kpiGridStyle} aria-label="FLDS catalog summary">
        <StatCard
          label="Catalog fields"
          value={String(summary?.catalog_fields ?? "—")}
          caption="LOCAL SHOWME CATALOG"
          tone="neutral"
        />
        <StatCard
          label="Matched"
          value={String(summary?.matched ?? allRows.length)}
          caption={`QUERY "${summary?.query ?? (prefix || "all")}"`}
          tone="neutral"
        />
        <StatCard
          label="Shown"
          value={String(summary?.shown ?? rows.length)}
          caption={`${rows.length} AFTER CATEGORY FILTER`}
          tone="neutral"
        />
      </section>
      <div role="note" style={noteStyle} aria-label="FLDS scope note">
        Field catalog lookup only — these names feed BQL get(...), screen
        filters, and analytics params. FLDS does not fetch live values.
      </div>
      <DataGrid
        columns={COLS}
        rows={rows}
        rowKey={(r, i) => `${r.field ?? "f"}-${i}`}
        density="compact"
        ariaLabel="FLDS field catalog"
      />
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Field Lookup"
          subtitle={`local catalog · ${summary?.catalog_fields ?? "—"} fields`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                catalog
              </Pill>
              <SegmentedControl
                label="CATEGORY"
                value={category}
                options={CATEGORY_OPTIONS}
                onChange={setCategory}
                title="Category filter"
              />
              <form onSubmit={submit} style={formStyle}>
                <input
                  type="text"
                  aria-label="Field search prefix"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  placeholder="pe, yield, rsi…"
                  style={inputStyle}
                />
                <button type="submit" className="btn" title="Search the field catalog">
                  Search
                </button>
              </form>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Re-run catalog search"
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
          <StatusSection label="matched" value={summary?.matched ?? "—"} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection
            label="query"
            value={prefix || "all"}
            tone="accent"
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

const formStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
};

const inputStyle: CSSProperties = {
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
  height: 24,
  padding: "0 6px",
  width: 140,
};

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const noteStyle: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: 12,
  color: "var(--text-mute)",
};

const bodyStyle: CSSProperties = {
  color: "var(--text-primary)",
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
