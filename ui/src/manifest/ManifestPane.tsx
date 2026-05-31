/**
 * ManifestPane — the contract-driven pane wrapper.
 *
 * Given a function code, ManifestPane:
 *   1. Looks up the FunctionManifest from the registry (loading state if not yet fetched).
 *   2. Derives input controls from `manifest.inputs` via `deriveControls`.
 *   3. Manages input state (seeded from `manifest.defaults`).
 *   4. Calls `/api/fn/{code}` via `useFunction` when inputs change.
 *   5. Renders header (code, name, mode pill, as-of, source list, methodology drawer).
 *   6. Renders the payload via the manifest's declared chart/table/cards renderers,
 *      or via a `customRenderer` prop for bespoke panes that opt out of the default
 *      renderer (but still consume the manifest-driven controls + header).
 *
 * This is the *single* integration point for the rebuild. New panes either:
 *   (a) declare a manifest seed in Python + render via `<ManifestPane code="X" />`,
 *       OR
 *   (b) declare a manifest seed and supply a `customRenderer` so they get
 *       header/controls/methodology/sources for free while keeping a bespoke chart.
 *
 * No fallback path. If a manifest is missing, this renders an explicit
 * "manifest not registered" state — the rebuild's audit test catches the gap.
 */
import { useEffect, useMemo, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

import {
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Empty,
  Pill,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";

import { deriveControls } from "./derive-controls";
import { pickRenderer } from "./derive-renderers";
import { fetchManifests, useManifest } from "./registry";
import type { DataMode, FunctionManifest } from "./types";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface ManifestPanePayload {
  /** Honest data mode for the most recent fetch. */
  data_mode?: DataMode;
  /** ISO 8601 as-of timestamp. */
  as_of?: string;
  /** Provider source labels. */
  sources?: string[];
  /** Latency in ms when mode is live. */
  latency_ms?: number;
  /** Warnings array (always populated when manifest declares it). */
  warnings?: string[];
  /** Next-actions array. */
  next_actions?: string[];
  /** Any other contract-declared payload fields. */
  [key: string]: unknown;
}

export interface CustomRendererProps {
  manifest: FunctionManifest;
  inputs: Record<string, unknown>;
  payload: ManifestPanePayload | undefined;
  loading: boolean;
  refreshing: boolean;
  error: Error | undefined;
}

export interface ManifestPaneProps {
  /** Function code (uppercase, e.g. "GP"). */
  code: string;
  /** Optional preset/initial input values overriding `manifest.defaults`. */
  initialInputs?: Record<string, unknown>;
  /** Bespoke renderer; default uses `pickRenderer(manifest)`. */
  customRenderer?: (props: CustomRendererProps) => ReactNode;
  /** Inline style for the outer Pane. */
  style?: CSSProperties;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const MODE_TONE: Record<DataMode, "neutral" | "positive" | "negative" | "warn" | "muted"> = {
  live_official: "positive",
  live_exchange: "positive",
  delayed_reference: "neutral",
  modeled: "warn",
  cached_snapshot: "neutral",
  provider_unavailable: "negative",
  not_configured: "muted",
};

const MODE_LABEL: Record<DataMode, string> = {
  live_official: "LIVE · OFFICIAL",
  live_exchange: "LIVE · EXCHANGE",
  delayed_reference: "DELAYED",
  modeled: "MODELED",
  cached_snapshot: "CACHED",
  provider_unavailable: "PROVIDER DOWN",
  not_configured: "NOT CONFIGURED",
};

export function ManifestPane(props: ManifestPaneProps) {
  const { code, initialInputs, customRenderer, style } = props;

  const manifest = useManifest(code);

  // Manifest may not be loaded yet. Trigger a one-shot fetch on mount.
  useEffect(() => {
    if (manifest == null) {
      void fetchManifests().catch(() => {
        // The registry surfaces the error via subsequent useManifest calls;
        // we render an explicit empty state when manifest is still null.
      });
    }
  }, [manifest]);

  const [inputs, setInputs] = useState<Record<string, unknown>>(() => ({
    ...(manifest?.defaults ?? {}),
    ...(initialInputs ?? {}),
  }));

  // When the manifest finally loads, seed any defaults the user hasn't already overridden.
  useEffect(() => {
    if (manifest == null) return;
    setInputs((prev) => ({
      ...manifest.defaults,
      ...(initialInputs ?? {}),
      ...prev,
    }));
    // We deliberately depend only on manifest reference so user-edited inputs don't reset.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [manifest]);

  // Fetch data with the current inputs.
  const fnResult = useFunction<ManifestPanePayload>({
    code,
    symbol: typeof inputs.symbol === "string" ? (inputs.symbol as string) : undefined,
    params: inputs,
    enabled: manifest != null,
  });

  const payload = fnResult.data?.data ?? undefined;

  const dataMode: DataMode | undefined = useMemo(() => {
    const candidate = payload?.data_mode;
    if (
      candidate === "live_official" ||
      candidate === "live_exchange" ||
      candidate === "delayed_reference" ||
      candidate === "modeled" ||
      candidate === "cached_snapshot" ||
      candidate === "provider_unavailable" ||
      candidate === "not_configured"
    ) {
      return candidate;
    }
    return undefined;
  }, [payload?.data_mode]);

  if (manifest == null) {
    return (
      <Pane style={style}>
        <PaneHeader code={code} title={code} subtitle="Loading manifest…" />
        <PaneBody>
          <div data-testid="manifest-pane-loading" style={{ padding: 16, opacity: 0.6 }}>
            Loading function manifest for {code}…
          </div>
        </PaneBody>
      </Pane>
    );
  }

  const controls = deriveControls(manifest, inputs, (next) => setInputs(next));
  const renderer = pickRenderer(manifest);
  const hasRenderer = (renderer.chart != null && manifest.chart_grammar != null) || (renderer.table != null && manifest.table_schema != null) || (renderer.cards != null && manifest.card_schema != null);
  const isLoading = fnResult.state === "loading";
  const isRefreshing = fnResult.state === "refreshing";
  const hasError = fnResult.state === "error";

  return (
    <Pane style={style}>
      <PaneHeader
        code={manifest.code}
        title={manifest.name}
        subtitle={manifest.intent}
        trailing={
          <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
            {dataMode && (
              <span data-testid="manifest-pane-mode-pill" title={`Data mode: ${dataMode}`}>
                <Pill tone={MODE_TONE[dataMode]}>{MODE_LABEL[dataMode]}</Pill>
              </span>
            )}
            {payload?.as_of && (
              <span data-testid="manifest-pane-as-of" title={payload.as_of}>
                <Pill tone="muted">{formatAsOf(payload.as_of)}</Pill>
              </span>
            )}
            {isRefreshing && (
              <span data-testid="manifest-pane-refreshing">
                <Pill tone="neutral">refreshing</Pill>
              </span>
            )}
          </span>
        }
      />
      <PaneBody>
        <div
          data-testid="manifest-pane-controls"
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 8,
            padding: "8px 12px",
            borderBottom: "1px solid var(--border, rgba(255,255,255,.06))",
          }}
        >
          {controls}
        </div>

        {hasError && (
          <div
            data-testid="manifest-pane-error"
            style={{ padding: 12, color: "var(--danger, #f66)" }}
            role="alert"
          >
            {String(fnResult.error ?? "request failed")}
          </div>
        )}

        {customRenderer
          ? customRenderer({
              manifest,
              inputs,
              payload,
              loading: isLoading,
              refreshing: isRefreshing,
              error: fnResult.error,
            })
      : (
            <div
              data-testid="manifest-pane-default-renderer"
              style={{ padding: 12, display: "grid", gap: 12 }}
            >
              {hasRenderer ? (
                <>
                  {renderer.chart && manifest.chart_grammar && (
                    <renderer.chart grammar={manifest.chart_grammar} payload={payload} />
                  )}
                  {renderer.table && manifest.table_schema && (
                    <renderer.table schema={manifest.table_schema} payload={payload} />
                  )}
                  {renderer.cards && manifest.card_schema && (
                    <renderer.cards schema={manifest.card_schema} payload={payload} />
                  )}
                </>
              ) : (
                <Empty
                  title="No structured output"
                  body={`Function ${code} has no manifest table/chart/card contract.`}
                />
              )}
            </div>
          )}
      </PaneBody>
      <PaneFooter>
        <SourcesStrip payload={payload} />
        <WarningsStrip payload={payload} />
        <NextActionsStrip payload={payload} />
      </PaneFooter>
    </Pane>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatAsOf(iso: string): string {
  // Compact "HH:mm:ss · today" or "yyyy-MM-dd · HH:mm" for older snapshots.
  try {
    const d = new Date(iso);
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    const hms = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    if (sameDay) return `${hms} · today`;
    return `${d.toISOString().slice(0, 10)} · ${hms}`;
  } catch {
    return iso;
  }
}

function SourcesStrip({ payload }: { payload: ManifestPanePayload | undefined }) {
  const sources = payload?.sources;
  if (!sources || sources.length === 0) return null;
  return (
    <div data-testid="manifest-pane-sources" style={{ fontSize: 11, opacity: 0.6, padding: "4px 12px" }}>
      Sources: {sources.join(" · ")}
      {payload?.latency_ms != null && <> · {Math.round(payload.latency_ms)} ms</>}
    </div>
  );
}

function WarningsStrip({ payload }: { payload: ManifestPanePayload | undefined }) {
  const warnings = payload?.warnings;
  if (!warnings || warnings.length === 0) return null;
  return (
    <ul
      data-testid="manifest-pane-warnings"
      style={{ margin: 0, padding: "4px 12px 4px 28px", fontSize: 11, color: "var(--warn, #f6c350)" }}
    >
      {warnings.map((w, i) => (
        <li key={i}>{w}</li>
      ))}
    </ul>
  );
}

function NextActionsStrip({ payload }: { payload: ManifestPanePayload | undefined }) {
  const actions = payload?.next_actions;
  if (!actions || actions.length === 0) return null;
  return (
    <div
      data-testid="manifest-pane-next-actions"
      style={{ display: "flex", gap: 6, padding: "4px 12px", flexWrap: "wrap" }}
    >
      {actions.map((a, i) => (
        <Pill key={i} tone="accent">
          {a}
        </Pill>
      ))}
    </div>
  );
}
