/**
 * DAPI — ShowMe Data API explorer.
 *
 * Surfaces the sidecar's REST manifest (backend api/dapi.py via the
 * standard /api/fn/DAPI route): one row per route with method, path,
 * purpose and an honest mutates_state badge. Client-side filters over
 * method / state-changing / free text; selecting a row reveals the
 * request-body shape, response shape, an example path, and a one-click
 * "copy as cURL" so Excel/external clients can wire against the same
 * contract the engine serves. source_mode is surfaced verbatim:
 * curated_manifest vs live_router_introspection.
 *
 * L7: converted from an inert <ul> to the shared DataGrid (sortable
 * method/path/purpose columns, keyboard cell navigation) with row
 * expand-on-click and the method/state filter chips.
 */
import { useMemo, useState, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { PaneState } from "@/design-system/PaneState";
import { copyTextToClipboard } from "@/design-system/clipboard";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface DAPIRoute {
  method?: string;
  path?: string;
  purpose?: string;
  request_body?: string;
  response_shape?: string;
  mutates_state?: string;
  example?: string;
}

interface DAPISummary {
  base_url?: string;
  endpoints?: number;
  total_routes?: number;
  state_changing?: number;
  filter?: string;
  source_mode?: string;
}

interface DAPIData {
  rows?: DAPIRoute[];
  summary?: DAPISummary;
  methodology?: string;
}

function methodTone(method: string): "accent" | "warn" | "negative" | "muted" {
  if (/^DELETE/.test(method)) return "negative";
  if (/^(POST|PUT|PATCH)/.test(method)) return "warn";
  if (/^GET/.test(method)) return "accent";
  return "muted";
}

function mutatesBadge(state: string): { label: string; tone: "negative" | "warn" | "muted" } | null {
  const text = state.trim().toLowerCase();
  if (text.startsWith("yes")) return { label: "mutates state", tone: "negative" };
  if (text.startsWith("depends")) return { label: "may mutate", tone: "warn" };
  if (!text || text === "no") return null;
  return { label: state, tone: "warn" };
}

type StateFilter = "all" | "read" | "mutating";

export function DAPIPane({ code }: FunctionPaneProps) {
  const [filter, setFilter] = useState("");
  const [methodFilter, setMethodFilter] = useState("ALL");
  const [stateFilter, setStateFilter] = useState<StateFilter>("all");
  const [expanded, setExpanded] = useState<string | null>(null);
  const { state, data, error, refetch } = useFunction<DAPIData>({ code });

  const payload = data?.data;
  const routes: DAPIRoute[] = useMemo(() => payload?.rows ?? [], [payload]);
  const summary = payload?.summary;

  const methods = useMemo(() => {
    const set = new Set<string>();
    for (const route of routes) {
      if (route.method) set.add(route.method.toUpperCase());
    }
    return ["ALL", ...Array.from(set).sort()];
  }, [routes]);

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return routes.filter((route) => {
      if (methodFilter !== "ALL" && (route.method ?? "").toUpperCase() !== methodFilter) {
        return false;
      }
      if (stateFilter !== "all") {
        const mutates = (route.mutates_state ?? "").trim().toLowerCase().startsWith("yes") ||
          (route.mutates_state ?? "").trim().toLowerCase().startsWith("depends");
        if (stateFilter === "mutating" && !mutates) return false;
        if (stateFilter === "read" && mutates) return false;
      }
      if (!needle) return true;
      return `${route.method ?? ""} ${route.path ?? ""} ${route.purpose ?? ""}`
        .toLowerCase()
        .includes(needle);
    });
  }, [routes, filter, methodFilter, stateFilter]);

  const isLive =
    (summary?.source_mode ?? "") === "live_router_introspection";
  const baseUrl = summary?.base_url ?? "http://127.0.0.1:<sidecar-port>";

  const COLS: DataGridColumn<DAPIRoute>[] = useMemo(
    () => [
      {
        key: "method",
        header: "Method",
        width: 96,
        sortable: true,
        sortValue: (r) => r.method ?? "",
        render: (r) => (
          <Pill tone={methodTone(r.method ?? "")} variant="soft" withDot={false}>
            {r.method ?? "—"}
          </Pill>
        ),
      },
      {
        key: "path",
        header: "Path",
        width: 280,
        sortable: true,
        sortValue: (r) => r.path ?? "",
        render: (r) => <span style={pathStyle}>{r.path ?? "—"}</span>,
      },
      {
        key: "purpose",
        header: "Purpose",
        sortable: true,
        sortValue: (r) => r.purpose ?? "",
        render: (r) => <span style={purposeStyle}>{r.purpose ?? ""}</span>,
      },
      {
        key: "state",
        header: "State",
        width: 130,
        render: (r) => {
          const badge = mutatesBadge(r.mutates_state ?? "");
          return badge ? (
            <Pill tone={badge.tone} variant="soft" withDot={false}>
              {badge.label}
            </Pill>
          ) : (
            <span className="u-text-mute">read-only</span>
          );
        },
      },
    ],
    [],
  );

  const expandedRoute = useMemo(
    () => routes.find((r) => `${r.method ?? ""} ${r.path ?? ""}` === expanded),
    [routes, expanded],
  );

  const copyAsCurl = (route: DAPIRoute) => {
    const url = `${baseUrl.replace(/\/$/, "")}${route.path ?? ""}`;
    const body =
      route.request_body && route.request_body !== "-"
        ? ` \\\n  -H "Content-Type: application/json" \\\n  -d '${route.request_body.replace(/'/g, "'\\''")}'`
        : "";
    copyTextToClipboard(`curl -X ${route.method ?? "GET"} "${url}"${body}`);
  };

  const body = (
    <PaneState
      state={state}
      error={error}
      empty={routes.length === 0}
      emptyTitle="No API routes returned"
      emptyBody="The sidecar route manifest is empty — the engine may still be attaching."
      onRetry={refetch}
    >
      <div className="u-grid-gap-14">
        <div style={chipRowStyle} role="group" aria-label="Method filter">
          {methods.map((m) => {
            const active = methodFilter === m;
            return (
              <button
                key={m}
                type="button"
                className={`fn-segmented__opt${active ? " fn-segmented__opt--active" : ""}`}
                aria-pressed={active}
                onClick={() => setMethodFilter(m)}
                title={`Filter method ${m}`}
              >
                {m}
              </button>
            );
          })}
        </div>
        <div style={chipRowStyle} role="group" aria-label="State filter">
          {(["all", "read", "mutating"] as StateFilter[]).map((s) => {
            const active = stateFilter === s;
            return (
              <button
                key={s}
                type="button"
                className={`fn-segmented__opt${active ? " fn-segmented__opt--active" : ""}`}
                aria-pressed={active}
                onClick={() => setStateFilter(s)}
                title={`Filter state ${s}`}
              >
                {s}
              </button>
            );
          })}
        </div>
        {visible.length === 0 ? (
          <PaneState
            state="ok"
            empty
            emptyTitle={`No routes match the current filters`}
            emptyBody="Clear the filter box or chips to see all routes."
            emptyAction={
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setFilter("");
                  setMethodFilter("ALL");
                  setStateFilter("all");
                }}
              >
                Clear filters
              </button>
            }
          />
        ) : (
          <DataGrid
            columns={COLS}
            rows={visible}
            rowKey={(r) => `${r.method ?? ""} ${r.path ?? ""}`}
            density="compact"
            ariaLabel="Sidecar REST routes"
            defaultSortKey="path"
            defaultSortDir="none"
            keyboardNavigable
            onRowClick={(route) => {
              const key = `${route.method ?? ""} ${route.path ?? ""}`;
              setExpanded((prev) => (prev === key ? null : key));
            }}
          />
        )}
        {expandedRoute ? (
          <dl
            style={detailStyle}
            aria-label={`Route details for ${expandedRoute.path ?? "route"}`}
          >
            <div style={detailHeaderRowStyle}>
              <span style={sectionTitleStyle}>Route contract</span>
              <button
                type="button"
                className="btn"
                title="Copy as cURL"
                aria-label={`Copy ${expandedRoute.method ?? "GET"} ${expandedRoute.path ?? ""} as cURL`}
                onClick={() => copyAsCurl(expandedRoute)}
              >
                ⧉ copy as cURL
              </button>
            </div>
            <div style={detailRowStyle}>
              <dt style={dtStyle}>Request body</dt>
              <dd style={ddStyle}>{expandedRoute.request_body ?? "—"}</dd>
            </div>
            <div style={detailRowStyle}>
              <dt style={dtStyle}>Response</dt>
              <dd style={ddStyle}>{expandedRoute.response_shape ?? "—"}</dd>
            </div>
            <div style={detailRowStyle}>
              <dt style={dtStyle}>Example</dt>
              <dd style={ddStyle}>{expandedRoute.example ?? "—"}</dd>
            </div>
            <div style={detailRowStyle}>
              <dt style={dtStyle}>Base URL</dt>
              <dd style={ddStyle}>{baseUrl}</dd>
            </div>
          </dl>
        ) : null}
      </div>
    </PaneState>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Data API Explorer"
          subtitle={`${visible.length} of ${summary?.total_routes ?? routes.length} routes · ${summary?.state_changing ?? 0} state-changing`}
          trailing={
            <FunctionControlGroup>
              <Pill
                tone={isLive ? "positive" : "muted"}
                variant="soft"
                withDot={false}
              >
                {summary?.source_mode ?? "—"}
              </Pill>
              <input
                type="search"
                aria-label="Filter routes"
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="method, path, purpose"
                style={inputStyle}
              />
              <LoadStatePill state={state} status={state === "ok" ? "ok" : undefined} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh route manifest"
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
          <StatusSection label="routes" value={`${visible.length}/${summary?.total_routes ?? routes.length}`} />
          <StatusDivider />
          <StatusSection label="state-changing" value={summary?.state_changing ?? 0} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="source" value={summary?.source_mode ?? "—"} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

const pathStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-md)",
  color: "var(--text-primary)",
  whiteSpace: "nowrap",
};

const purposeStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: "var(--font-size-sm)",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const detailStyle: CSSProperties = {
  margin: 0,
  padding: "8px 10px",
  display: "grid",
  gap: 3,
  background: "var(--surface-1)",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border-subtle)",
};

const detailHeaderRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  marginBottom: 2,
};

const detailRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  gap: 10,
};

const dtStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: "var(--font-size-xs)",
  fontFamily: "JetBrains Mono, monospace",
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  width: 110,
  flexShrink: 0,
};

const ddStyle: CSSProperties = {
  margin: 0,
  color: "var(--text-primary)",
  fontSize: "var(--font-size-sm)",
  fontFamily: "JetBrains Mono, monospace",
  overflowWrap: "anywhere",
};

const sectionTitleStyle: CSSProperties = {
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
};

const chipRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
};

const inputStyle: CSSProperties = {
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-md)",
  height: 24,
  padding: "0 6px",
  width: 170,
};
