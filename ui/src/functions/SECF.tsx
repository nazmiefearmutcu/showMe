/**
 * SECF — Security Finder.
 *
 * Universal symbol search over the ShowMe security master (backend
 * screen/_funcs.py SECFFunction). Natural-language text query plus a
 * client-side asset-class chip filter over the matched set. The master
 * is reference-grade (static), so the pane labels it honestly — this is
 * a finder, not a live quote board. Empty results surface the
 * backend's next_actions guidance.
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
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface SECFRow {
  symbol?: string;
  name?: string;
  asset_class?: string;
  exchange?: string;
  country?: string;
  sector?: string;
  tags?: string[];
  match?: string;
}

interface SECFData {
  status?: string;
  reason?: string;
  query?: string;
  match_mode?: string;
  rows?: SECFRow[];
  scanned?: number;
  matched?: number;
  next_actions?: string[];
}

const DEFAULT_QUERY = "technology";

export function SECFPane({ code }: FunctionPaneProps) {
  const [input, setInput] = useState(DEFAULT_QUERY);
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [assetClass, setAssetClass] = useState("ALL");
  const { state, data, error, refetch } = useFunction<SECFData>({
    code,
    params: { query },
  });

  const payload = data?.data;
  const rows: SECFRow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";

  const classes = useMemo(() => {
    const set = new Set<string>();
    for (const row of rows) {
      if (row.asset_class) set.add(row.asset_class);
    }
    return ["ALL", ...Array.from(set).sort()];
  }, [rows]);

  const visible = useMemo(
    () =>
      assetClass === "ALL"
        ? rows
        : rows.filter(
            (row) =>
              (row.asset_class ?? "").toUpperCase() === assetClass.toUpperCase(),
          ),
    [rows, assetClass],
  );

  function submit(event: FormEvent) {
    event.preventDefault();
    const next = input.trim();
    if (!next) return;
    setQuery(next);
    setAssetClass("ALL");
  }

  const COLS: DataGridColumn<SECFRow>[] = useMemo(
    () => [
      {
        key: "symbol",
        header: "Symbol",
        width: 120,
        render: (r) => <span style={monoStrongStyle}>{r.symbol ?? "—"}</span>,
      },
      {
        key: "name",
        header: "Name",
        render: (r) => <span style={monoPrimaryStyle}>{r.name ?? "—"}</span>,
      },
      {
        key: "exchange",
        header: "Exchange",
        width: 130,
        render: (r) => (
          <span style={monoMutedStyle}>{r.exchange ?? "—"}</span>
        ),
      },
      {
        key: "asset_class",
        header: "Type",
        width: 110,
        render: (r) =>
          r.asset_class ? (
            <Pill tone="accent" variant="soft" withDot={false}>
              {r.asset_class}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
      {
        key: "match",
        header: "Match",
        width: 100,
        render: (r) =>
          r.match ? (
            <Pill
              tone={r.match === "all_terms" ? "positive" : "muted"}
              variant="soft"
              withDot={false}
            >
              {r.match === "all_terms" ? "all terms" : "partial"}
            </Pill>
          ) : (
            <span className="u-text-mute">—</span>
          ),
      },
    ],
    [],
  );

  const isReferenceMaster = (data?.sources ?? []).some((source) =>
    source.includes("security_master"),
  );

  const body = state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={28} />
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
  ) : status === "empty" || rows.length === 0 ? (
    <Empty
      title={`No securities matched "${payload?.query ?? query}"`}
      body={
        payload?.next_actions?.[0] ??
        "Try a broader symbol, company name, asset class, or tag."
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      <div
        style={chipRowStyle}
        role="group"
        aria-label="Asset class filter"
      >
        {classes.map((cls) => {
          const active = assetClass === cls;
          return (
            <button
              key={cls}
              type="button"
              className={`fn-segmented__opt${active ? " fn-segmented__opt--active" : ""}`}
              aria-pressed={active}
              onClick={() => setAssetClass(cls)}
              title={`Filter asset class ${cls}`}
            >
              {cls}
            </button>
          );
        })}
      </div>
      <DataGrid
        columns={COLS}
        rows={visible}
        rowKey={(r, i) => `${r.symbol ?? ""}-${i}`}
        density="compact"
        ariaLabel="Security finder results"
      />
      <p style={noteStyle} aria-label="Match count note">
        {visible.length} of {payload?.matched ?? rows.length} matched
        {" · "}
        {payload?.scanned ?? "—"} scanned
        {" · "}
        query "{payload?.query ?? query}"
        {assetClass !== "ALL" ? ` · filtered to ${assetClass}` : ""}
      </p>
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Security Finder"
          subtitle={`${payload?.matched ?? 0} matches · ${payload?.scanned ?? 0} scanned`}
          trailing={
            <FunctionControlGroup>
              {isReferenceMaster ? (
                <Pill tone="muted" variant="soft" withDot={false}>
                  reference master
                </Pill>
              ) : null}
              <form onSubmit={submit} style={formStyle}>
                <input
                  type="search"
                  aria-label="Security query"
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  placeholder="symbol, name, tag"
                  style={inputStyle}
                />
                <button type="submit" className="btn" title="Run security query">
                  Find
                </button>
              </form>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Re-run security query"
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
          <StatusSection label="matches" value={payload?.matched ?? 0} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="query" value={payload?.query ?? query} tone="accent" />
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
  width: 150,
};

const chipRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
};

const noteStyle: CSSProperties = {
  margin: 0,
  color: "var(--text-mute)",
  fontSize: 11,
  fontFamily: "JetBrains Mono, monospace",
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const monoPrimaryStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-primary)",
};

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-mute)",
};
