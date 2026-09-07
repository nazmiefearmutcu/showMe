/**
 * DAPI — ShowMe Data API explorer.
 *
 * Surfaces the sidecar's REST manifest (backend api/dapi.py via the
 * standard /api/fn/DAPI route): one row per route with method, path,
 * purpose and an honest mutates_state badge. Client-side filter box
 * over method+path+purpose; expanding a row reveals the request-body
 * shape, response shape, and an example path so Excel/external
 * clients can wire against the same contract the engine serves.
 * source_mode is surfaced verbatim: curated_manifest vs
 * live_router_introspection.
 */
import { useMemo, useState, type CSSProperties } from "react";
import {
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

export function DAPIPane({ code }: FunctionPaneProps) {
  const [filter, setFilter] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const { state, data, error, refetch } = useFunction<DAPIData>({ code });

  const payload = data?.data;
  const routes: DAPIRoute[] = useMemo(() => payload?.rows ?? [], [payload]);
  const summary = payload?.summary;

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return routes;
    return routes.filter((route) =>
      `${route.method ?? ""} ${route.path ?? ""} ${route.purpose ?? ""}`
        .toLowerCase()
        .includes(needle),
    );
  }, [routes, filter]);

  const isLive =
    (summary?.source_mode ?? "") === "live_router_introspection";

  const body = state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={24} />
      <Skeleton height={24} />
      <Skeleton height={24} />
      <Skeleton height={24} width="80%" />
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
  ) : routes.length === 0 ? (
    <Empty
      title="No API routes returned"
      body="The sidecar route manifest is empty — the engine may still be attaching."
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : visible.length === 0 ? (
    <Empty
      title={`No routes match "${filter}"`}
      body="Filter matches method, path, or purpose text. Clear it to see all routes."
      action={
        <button onClick={() => setFilter("")} className="btn">
          Clear filter
        </button>
      }
    />
  ) : (
    <ul style={listStyle} aria-label="Sidecar REST routes">
      {visible.map((route) => {
        const key = `${route.method ?? ""} ${route.path ?? ""}`;
        const isOpen = expanded === key;
        const badge = mutatesBadge(route.mutates_state ?? "");
        return (
          <li key={key} style={itemStyle}>
            <button
              type="button"
              className="dapi-route-row"
              style={rowStyle}
              aria-expanded={isOpen}
              onClick={() => setExpanded(isOpen ? null : key)}
              title={isOpen ? "Collapse route details" : "Expand route details"}
            >
              <Pill tone={methodTone(route.method ?? "")} variant="soft" withDot={false}>
                {route.method ?? "—"}
              </Pill>
              <span style={pathStyle}>{route.path ?? "—"}</span>
              <span style={purposeStyle}>{route.purpose ?? ""}</span>
              {badge ? (
                <Pill tone={badge.tone} variant="soft" withDot={false}>
                  {badge.label}
                </Pill>
              ) : null}
            </button>
            {isOpen ? (
              <dl style={detailStyle} aria-label={`Route details for ${route.path ?? "route"}`}>
                <div style={detailRowStyle}>
                  <dt style={dtStyle}>Request body</dt>
                  <dd style={ddStyle}>{route.request_body ?? "—"}</dd>
                </div>
                <div style={detailRowStyle}>
                  <dt style={dtStyle}>Response</dt>
                  <dd style={ddStyle}>{route.response_shape ?? "—"}</dd>
                </div>
                <div style={detailRowStyle}>
                  <dt style={dtStyle}>Example</dt>
                  <dd style={ddStyle}>{route.example ?? "—"}</dd>
                </div>
                <div style={detailRowStyle}>
                  <dt style={dtStyle}>Base URL</dt>
                  <dd style={ddStyle}>{summary?.base_url ?? "http://127.0.0.1:<sidecar-port>"}</dd>
                </div>
              </dl>
            ) : null}
          </li>
        );
      })}
    </ul>
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

const listStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "grid",
  gap: 4,
};

const itemStyle: CSSProperties = {
  borderBottom: "1px solid var(--border-row)",
  paddingBottom: 4,
};

const rowStyle: CSSProperties = {
  all: "unset",
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  gap: 8,
  width: "100%",
  padding: "3px 2px",
  boxSizing: "border-box",
};

const pathStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
  color: "var(--text-primary)",
  whiteSpace: "nowrap",
};

const purposeStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: 11,
  flex: 1,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
  textAlign: "left",
};

const detailStyle: CSSProperties = {
  margin: 0,
  padding: "4px 8px 8px 8px",
  display: "grid",
  gap: 3,
  background: "var(--surface-1)",
  borderRadius: "var(--radius-sm)",
};

const detailRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  gap: 10,
};

const dtStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: 9,
  fontFamily: "JetBrains Mono, monospace",
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  width: 110,
  flexShrink: 0,
};

const ddStyle: CSSProperties = {
  margin: 0,
  color: "var(--text-primary)",
  fontSize: 11,
  fontFamily: "JetBrains Mono, monospace",
  overflowWrap: "anywhere",
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
  width: 170,
};
