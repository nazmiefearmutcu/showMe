/**
 * FLW — FlowMap depth heatmap.
 *
 * Full-pane WebGL2 order-book density map (price rows × time columns) streamed
 * over the sidecar's binary `/ws/flowmap` feed by the vendored FlowMap library
 * (`@/functions/flowmap`). The pane owns only chrome + wiring:
 *
 *  - the canvas is full-bleed and sized by the pane; the library attaches its
 *    own ResizeObserver, so we never set pixel dimensions ourselves;
 *  - the WS URL mirrors `lib/stream.ts`'s quote-feed recipe: `sidecarWsUrl()`
 *    base + `/ws/flowmap` + `?token=` from `loadSidecarAuthToken()` (the async
 *    per-process sidecar token — the same auth contract as `/ws/quote/*`);
 *  - sidecar port discovery is async (Tauri publishes the port after boot), so
 *    the pane re-opens the session via `onSidecarPort` when the port changes;
 *  - symbol / band changes re-subscribe on the SAME handle via
 *    `handle.subscribe(...)` — the library resets its GL session state itself;
 *  - StrictMode-safe: the create effect is disposal-guarded and `destroy()`
 *    runs on unmount.
 *
 * Data honesty: FLW streams crypto depth only. A non-crypto symbol renders an
 * explicit "crypto depth only" info state and never touches the library —
 * there is no synthetic fallback and no fake heatmap. Same for a missing
 * WebGL2 context (`status.webgl === false`).
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { inferAssetClassName, defaultSymbolForFunction } from "@/lib/symbols";
import {
  loadSidecarAuthToken,
  onSidecarPort,
  sidecarWsUrl,
} from "@/lib/sidecar";
import {
  createFlowMap,
  type FlowMapConnState,
  type FlowMapHandle,
  type FlowMapStatus,
  type FlowMapTarget,
} from "./flowmap";
import { FunctionControlGroup, SegmentedControl } from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

const FLOWMAP_WS_PATH = "/ws/flowmap";

const BAND_OPTIONS = ["native", "wide", "full", "deep"] as const;
type FlowBand = (typeof BAND_OPTIONS)[number];
const DEFAULT_BAND: FlowBand = "wide";

export function FLWPane({ code, symbol }: FunctionPaneProps) {
  const [band, setBand] = usePersistentOption<FlowBand>(
    "showme.flw.band",
    BAND_OPTIONS,
    DEFAULT_BAND,
  );
  // FLW is crypto-only: prefer a recent crypto symbol, fall back to BTCUSDT.
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["CRYPTO"]);
  const isCrypto = inferAssetClassName(effectiveSymbol) === "CRYPTO";

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const handleRef = useRef<FlowMapHandle | null>(null);
  // Latest target, readable from the async create path without re-triggering it.
  const targetRef = useRef<FlowMapTarget>({ market: "crypto", symbol: effectiveSymbol, band });
  targetRef.current = { market: "crypto", symbol: effectiveSymbol, band };
  const lastTargetKeyRef = useRef<string>(targetKey(targetRef.current));
  const [status, setStatus] = useState<FlowMapStatus | null>(null);
  // Resolved once the sidecar WS base is known; port discovery re-resolves it.
  const [wsBase, setWsBase] = useState<string | null>(null);

  useEffect(() => {
    setWsBase(sidecarWsUrl());
    // Later port publications (sidecar respawn) must re-open the feed.
    return onSidecarPort(() => setWsBase(sidecarWsUrl()));
  }, []);

  // Session lifecycle — one FlowMap handle per (crypto-gated) mount × wsBase.
  // Symbol/band changes deliberately do NOT re-run this: they re-subscribe on
  // the existing handle below, letting the library reset its GL state itself.
  useEffect(() => {
    if (!isCrypto) return;
    const canvas = canvasRef.current;
    if (!canvas || !wsBase) return;
    let disposed = false;
    void (async () => {
      const token = await loadSidecarAuthToken();
      if (disposed) return;
      const target = targetRef.current;
      const handle = createFlowMap(canvas, {
        wsUrl: buildFlowMapWsUrl(wsBase, token),
        target,
        onStatus: setStatus,
      });
      handleRef.current = handle;
      lastTargetKeyRef.current = targetKey(target);
    })();
    return () => {
      disposed = true;
      handleRef.current?.destroy();
      handleRef.current = null;
      lastTargetKeyRef.current = "";
      setStatus(null);
    };
  }, [isCrypto, wsBase]);

  // Re-subscribe on the SAME handle when symbol or band changes.
  useEffect(() => {
    const handle = handleRef.current;
    if (!handle) return;
    const key = targetKey(targetRef.current);
    if (lastTargetKeyRef.current === key) return;
    lastTargetKeyRef.current = key;
    handle.subscribe(targetRef.current);
  }, [effectiveSymbol, band, isCrypto]);

  // A missing WebGL2 context makes the whole session pointless — release it.
  useEffect(() => {
    if (status?.webgl === false) {
      handleRef.current?.destroy();
      handleRef.current = null;
    }
  }, [status?.webgl]);

  const capability = status?.capability ?? null;
  const depthLabel = useMemo(() => {
    const depth = capability?.depth;
    return typeof depth === "string" ? `depth ${depth}` : null;
  }, [capability]);
  const historyReconstructed = capability?.history === "reconstructed";
  const feedDegraded = status?.feedState === "degraded";
  const conn = status ? connPill(status.conn) : { label: "connecting", tone: "warn" as const };
  const latencyLabel =
    typeof status?.latencyMs === "number" && Number.isFinite(status.latencyMs)
      ? `${Math.round(status.latencyMs)} ms`
      : "—";

  const headerControls = (
    <FunctionControlGroup>
      {isCrypto && (
        <Pill tone={conn.tone} variant="soft" aria-label="FlowMap stream status">
          {conn.label}
        </Pill>
      )}
      {isCrypto && feedDegraded && (
        <Pill tone="warn" variant="soft">
          feed degraded
        </Pill>
      )}
      {isCrypto && depthLabel && (
        <Pill tone="muted" variant="soft" withDot={false}>
          {depthLabel}
        </Pill>
      )}
      <SegmentedControl
        label="BAND"
        value={band}
        options={BAND_OPTIONS}
        onChange={setBand}
        disabled={!isCrypto}
        title="FlowMap price band"
      />
    </FunctionControlGroup>
  );

  const body = !isCrypto ? (
    <Empty
      icon="⌁"
      title="Crypto depth only"
      body={
        <>
          FLW streams the FlowMap order-book depth heatmap for crypto pairs
          (Binance L2 over the sidecar&apos;s <code>/ws/flowmap</code> feed).
          {" "}
          {effectiveSymbol} is not a crypto symbol, so there is nothing to
          stream — no synthetic heatmap is rendered. Switch to a USDT pair such
          as BTCUSDT or ETHUSDT.
        </>
      }
    />
  ) : status?.webgl === false ? (
    <Empty
      icon="▦"
      title="WebGL2 unavailable"
      body="This environment exposes no WebGL2 context, so the FlowMap depth heatmap cannot render. No substitute chart is shown — the stream stays idle rather than faking one."
    />
  ) : (
    <div style={canvasHostStyle}>
      <canvas ref={canvasRef} style={canvasStyle} aria-label="FlowMap depth heatmap canvas" />
      <div style={overlayStyle} role="status" aria-label="FlowMap stream status">
        {historyReconstructed && (
          <Pill tone="accent" variant="soft" withDot={false}>
            history: reconstructed
          </Pill>
        )}
      </div>
      <div style={legendStyle} aria-hidden="true">
        <span style={legendItemStyle}>
          <span style={densityChipStyle} />
          density
        </span>
        <span style={legendItemStyle}>
          <span style={bidChipStyle} />
          bid
        </span>
        <span style={legendItemStyle}>
          <span style={askChipStyle} />
          ask
        </span>
      </div>
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="FlowMap"
          subtitle={`Crypto order-book depth heatmap — ${effectiveSymbol} · ${band} band`}
          trailing={headerControls}
        />
        <PaneBody style={bodyStyle}>{body}</PaneBody>
        <PaneFooter>
          <StatusSection label="symbol" value={effectiveSymbol} />
          <StatusDivider />
          <StatusSection label="band" value={band} tone="accent" />
          <StatusDivider />
          <StatusSection
            label="feed"
            value={status?.feedState ?? "—"}
          />
          <StatusDivider />
          <StatusSection label="latency" value={latencyLabel} />
          <StatusDivider />
          <StatusSection label="endpoint" value={FLOWMAP_WS_PATH} />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function targetKey(target: FlowMapTarget): string {
  return `${target.market}|${target.symbol}|${target.band ?? ""}`;
}

/**
 * Mirror of the `/ws/quote/{symbol}` auth recipe: token as a `?token=` query
 * parameter (SEC-13 accepts query / header / subprotocol; query is the only
 * one browsers can set on `new WebSocket`).
 */
function buildFlowMapWsUrl(wsBase: string, token: string | null): string {
  const url = `${wsBase}${FLOWMAP_WS_PATH}`;
  return token ? `${url}?token=${encodeURIComponent(token)}` : url;
}

function connPill(conn: FlowMapConnState): { label: string; tone: "positive" | "warn" | "negative" | "muted" } {
  switch (conn) {
    case "live":
      return { label: "live", tone: "positive" };
    case "reconnecting":
      return { label: "reconnecting", tone: "warn" };
    case "error":
      return { label: "error", tone: "negative" };
    case "closed":
      return { label: "offline", tone: "muted" };
    case "idle":
      return { label: "idle", tone: "muted" };
    case "connecting":
    default:
      return { label: "connecting", tone: "warn" };
  }
}

const bodyStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  padding: 0,
  overflow: "hidden",
};

const canvasHostStyle: CSSProperties = {
  position: "relative",
  flex: 1,
  minHeight: 0,
  width: "100%",
  // Paint the terminal surface BEFORE the GL context clears to the same token,
  // so there is no dark flash between mount and first frame.
  background: "var(--bg)",
};

// Full-bleed canvas — the FlowMap library owns sizing via its ResizeObserver;
// we only make it fill the pane.
const canvasStyle: CSSProperties = {
  position: "absolute",
  inset: 0,
  width: "100%",
  height: "100%",
  display: "block",
};

const overlayStyle: CSSProperties = {
  position: "absolute",
  top: 0,
  left: 0,
  right: 0,
  display: "flex",
  justifyContent: "flex-end",
  gap: 6,
  padding: "6px 8px",
  pointerEvents: "none",
};

// Reading legend, top-left (the honesty badge sits top-right). Pure CSS vars:
// the chips re-theme with the active preset without any JS — the same tokens
// the canvas theme bridge maps into the GL palette.
const legendStyle: CSSProperties = {
  position: "absolute",
  bottom: 0,
  left: 0,
  display: "flex",
  alignItems: "center",
  gap: 12,
  padding: "6px 10px",
  pointerEvents: "none",
  fontFamily: "var(--font-mono)",
  fontSize: 10,
  letterSpacing: "0.04em",
  color: "var(--text-faint)",
};

const legendItemStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
};

const densityChipStyle: CSSProperties = {
  width: 22,
  height: 8,
  borderRadius: 2,
  // Abbreviated hint of the themed ramp (bg → accent → ink); the real ramp is
  // rasterized from the same tokens inside the library's theme bridge.
  background:
    "linear-gradient(90deg, var(--bg) 0%, var(--accent) 60%, var(--text-display-hex) 100%)",
  boxShadow: "inset 0 0 0 1px var(--line-strong)",
};

function chipStyle(bg: string): CSSProperties {
  return {
    width: 8,
    height: 8,
    borderRadius: 2,
    background: bg,
    boxShadow: "inset 0 0 0 1px var(--line-strong)",
  };
}
const bidChipStyle = chipStyle("var(--positive-hex)");
const askChipStyle = chipStyle("var(--negative-hex)");
