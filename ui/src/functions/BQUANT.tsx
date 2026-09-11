/**
 * BQUANT — BQuant Notebook bridge (explicitly not-configured state).
 *
 * The backend returns a readiness MANIFEST, not notebook data: a notebook
 * route, kernel module names, and example notebook paths. Without a mounted
 * Jupyter runtime the manifest is status=not_configured — and this pane
 * says exactly that instead of faking a notebook surface: it renders the
 * readiness checklist, the backend's reason, the concrete next actions,
 * and a plain statement of what the pane WOULD render once a Jupyter
 * server is actually mounted by the launcher.
 */
import { useMemo, type CSSProperties } from "react";
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

interface BQUANTRow {
  component?: string;
  status?: string;
  value?: string;
  action?: string;
}

interface BQUANTSummary {
  notebook_ready?: boolean;
  notebook_url?: string;
  examples_found?: number;
  preloaded_modules?: number;
}

interface BQUANTData {
  status?: string;
  reason?: string | null;
  next_actions?: string[];
  rows?: BQUANTRow[];
  summary?: BQUANTSummary;
  methodology?: string;
}

export function BQUANTPane({ code }: FunctionPaneProps) {
  const { state, data, error, refetch } = useFunction<BQUANTData>({
    code,
    params: {},
  });

  const payload = data?.data;
  const status = payload?.status ?? "—";
  const configured = status === "ok";

  const COLS: DataGridColumn<BQUANTRow>[] = useMemo(
    () => [
      {
        key: "component",
        header: "Component",
        width: 170,
        sortable: true,
        render: (r) => (
          <span style={monoStrongStyle}>{r.component ?? "—"}</span>
        ),
      },
      {
        key: "status",
        header: "Readiness",
        width: 160,
        sortable: true,
        sortValue: (r) => readinessRank(r.status),
        render: (r) => {
          const s = r.status ?? "unknown";
          const tone =
            s === "configured" || s === "available" || s === "found"
              ? "positive"
              : s === "not_configured" || s === "missing"
                ? "negative"
                : "muted";
          return (
            <Pill tone={tone} variant="soft" withDot={false}>
              {s}
            </Pill>
          );
        },
      },
      {
        key: "value",
        header: "Detail",
        render: (r) => <span style={monoPrimaryStyle}>{r.value ?? "—"}</span>,
      },
      {
        key: "action",
        header: "What it needs",
        width: 300,
        render: (r) => <span style={bodyStyle}>{r.action ?? "—"}</span>,
      },
      {
        key: "copy",
        header: "",
        width: 74,
        render: (r) => (
          <button
            type="button"
            className="btn"
            title={`Copy ${r.component ?? "component"} value`}
            aria-label={`Copy ${r.component ?? "component"} value to clipboard`}
            onClick={() =>
              copyTextToClipboard(r.value ?? r.action ?? "")
            }
            style={copyButtonStyle}
          >
            ⧉ copy
          </button>
        ),
      },
    ],
    [],
  );

  const rows = payload?.rows ?? [];

  const body = (
    <PaneState
      state={state}
      error={error}
      empty={rows.length === 0}
      emptyTitle="No readiness manifest"
      emptyBody="BQUANT returned no readiness components — the notebook bridge is not installed."
      onRetry={refetch}
    >
      <div className="u-grid-gap-14">
        {!configured ? (
          <div role="note" style={warnStyle} aria-label="BQUANT not-configured notice">
            <strong>BQuant is not configured.</strong>{" "}
            {payload?.reason ?? "No mounted Jupyter runtime was detected."} This
            pane intentionally renders NO notebook surface.
          </div>
        ) : null}
        <div role="note" style={noteStyle} aria-label="BQUANT would-render note">
          Once a Jupyter server is mounted by the ShowMe launcher, this pane
          would render a notebook launcher for{" "}
          {payload?.summary?.notebook_url ?? "/notebook"} with the preloaded
          kernel modules (showme.data, showme.functions, showme.portfolio) and
          the example notebooks listed below.
        </div>
        {(payload?.next_actions ?? []).length > 0 && !configured ? (
          <div style={actionsBoxStyle} aria-label="BQUANT next actions">
            <span style={sectionTitleStyle}>To enable BQuant</span>
            <ul style={actionsListStyle}>
              {(payload?.next_actions ?? []).map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <DataGrid
          columns={COLS}
          rows={rows}
          rowKey={(r, i) => `${r.component ?? "c"}-${i}`}
          density="compact"
          ariaLabel="BQUANT readiness checklist"
          defaultSortKey="component"
          defaultSortDir="none"
        />
      </div>
    </PaneState>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="BQuant Notebook"
          subtitle={
            configured
              ? `notebook bridge ready · ${payload?.summary?.notebook_url ?? "/notebook"}`
              : "notebook bridge · not configured"
          }
          trailing={
            <FunctionControlGroup>
              <Pill
                tone={configured ? "positive" : "negative"}
                variant="soft"
                withDot={false}
              >
                {configured ? "notebook ready" : "not configured"}
              </Pill>
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Re-check notebook readiness"
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
            label="examples"
            value={payload?.summary?.examples_found ?? 0}
          />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection
            label="ready"
            value={configured ? "yes" : "no"}
            tone={configured ? "positive" : "negative"}
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── styles ────────────────────────────────────────────────────────── */

function readinessRank(status: string | undefined): number {
  const s = (status ?? "").toLowerCase();
  if (s === "configured" || s === "available" || s === "found" || s === "ok" || s === "ready") {
    return 0;
  }
  if (s === "not_configured" || s === "missing") return 1;
  return 2;
}

const copyButtonStyle: CSSProperties = {
  fontSize: "var(--font-size-xs)",
  padding: "0 6px",
  height: 20,
  lineHeight: "20px",
  whiteSpace: "nowrap",
};

const warnStyle: CSSProperties = {
  border: "1px solid var(--negative, var(--text-mute))",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: "var(--font-size-md)",
  color: "var(--text-primary)",
};

const noteStyle: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: "var(--font-size-md)",
  color: "var(--text-mute)",
};

const actionsBoxStyle: CSSProperties = {
  display: "grid",
  gap: 6,
  border: "1px solid var(--border-subtle)",
  borderRadius: 6,
  padding: "8px 10px",
};

const sectionTitleStyle: CSSProperties = {
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  fontSize: "var(--font-size-2xs)",
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
};

const actionsListStyle: CSSProperties = {
  margin: 0,
  paddingLeft: 18,
  color: "var(--text-primary)",
  fontSize: "var(--font-size-md)",
  lineHeight: 1.6,
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

const monoPrimaryStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
};
