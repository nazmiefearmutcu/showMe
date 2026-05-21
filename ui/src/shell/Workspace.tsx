/**
 * Workspace renderer — recursive split tree with drag-resize handles.
 *
 * Single source of multi-pane layout. Each leaf renders the focused
 * pane via `resolvePane`; the registry's `FunctionStub` handles codes
 * we haven't ported natively.
 *
 * ROUND-2B (PERF-02): every pane (including the three "always-loaded"
 * panes Welcome / Preferences / FunctionStub) is lazy-loaded so the
 * entry chunk only ships the shell + design system. A small Suspense
 * fallback paints a token-coloured shimmer while the chunk arrives.
 */
import { lazy, Suspense, useEffect, useRef } from "react";
import {
  useWorkspace,
  type LeafNode,
  type SplitNode,
  type WorkspaceNode,
} from "@/lib/workspace";
import { resolvePane } from "@/functions/registry";
import {
  DesignExportRenderer,
  hasDesignExportComponent,
} from "@/design-export/showme-design-export";
import {
  CRITICAL_CODES,
  isCriticalCode,
  resolvePaneRenderer,
  type PaneResolveAdapters,
} from "@/lib/pane-completeness";
import { PaneChrome } from "./PaneChrome";
import { PaneErrorBoundary } from "./PaneErrorBoundary";

const Welcome = lazy(() => import("@/panes/Welcome").then((m) => ({ default: m.Welcome })));
const Preferences = lazy(() =>
  import("@/panes/Preferences").then((m) => ({ default: m.Preferences })),
);
const FunctionStub = lazy(() =>
  import("@/panes/FunctionStub").then((m) => ({ default: m.FunctionStub })),
);
const TemplateRenderer = lazy(() =>
  import("@/templates/TemplateRenderer").then((m) => ({
    default: m.TemplateRenderer,
  })),
);
// Synchronously imported predicate — checking it must not lazy-load the
// template module on cold paint. The module is small, but importing
// asynchronously here would force a 2-tick render and a flash of stub.
import { hasTemplate } from "@/templates/TemplateRenderer";

function PaneFallback() {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Loading pane"
      className="pane-fallback"
    >
      loading…
    </div>
  );
}

const HANDLE_PX = 4;

export function Workspace() {
  const tree = useWorkspace((s) => s.tree);
  return <Node node={tree} />;
}

function Node({ node }: { node: WorkspaceNode }) {
  if (node.kind === "leaf") return <Leaf node={node} />;
  return <Split node={node} />;
}

function Leaf({ node }: { node: LeafNode }) {
  const focusedId = useWorkspace((s) => s.focusedId);
  const setFocused = useWorkspace((s) => s.setFocused);
  const isFocused = focusedId === node.id;
  // A leaf is "design-only" when there is NO native pane / template for it
  // and the only renderer left is the static Claude Design export. The
  // Pro design components ship their own PrShell chrome, so we suppress
  // the outer PaneChrome to avoid a doubled toolbar/statusbar. When the
  // native pane wins (current default for the 10 in-scope codes) the
  // outer PaneChrome still renders so SymbolBar / RefreshButton work.
  //
  // S05: critical codes (GP, HP, DES, WATCH, SCAN, PORT, TOP, NI, CN, MIS)
  // are *never* design-leaves even if the native renderer is missing —
  // they must show PaneChrome around the `<CriticalMissingPane>` guard
  // so the trader still has the toolbar surface and code header.
  const hasNative = resolvePane(node.code) !== null;
  const hasTpl = hasTemplate(node.code);
  const isCritical = isCriticalCode(node.code);
  const isDesignLeaf =
    node.code === "PREF" ||
    (!isCritical && !hasNative && !hasTpl && hasDesignExportComponent(node.code));
  return (
    <div
      onMouseDownCapture={() => setFocused(node.id)}
      className={`ws-leaf${isFocused ? " ws-leaf--focused" : ""}${isDesignLeaf ? " ws-leaf--design" : ""}`}
    >
      {!isDesignLeaf && (
        <PaneChrome
          leafId={node.id}
          code={node.code}
          symbol={node.symbol}
          linkGroup={node.linkGroup}
        />
      )}
      <div className="ws-leaf__body">
        <PaneContent leafId={node.id} code={node.code} symbol={node.symbol} />
      </div>
    </div>
  );
}

function PaneContent({
  leafId,
  code,
  symbol,
}: {
  leafId: string;
  code: string;
  symbol?: string;
}) {
  let body: React.ReactNode;
  if (code === "HOME") {
    // S09 chart-blocker: HOME is the welcome surface and must NEVER fall
    // through to the design-export cockpit (PrChart with synthetic
    // SM_DATA.helpers.bigSpark, hardcoded SPX labels, fake SIDECAR :8421
    // status). The real "Overview" path now loads the markets-overview
    // preset (DES + GP + WEI + TOP); the HOME leaf renders <Welcome /> as
    // a safety net so any leftover HOME-coded leaf still shows a clean
    // surface with real sidecar data instead of the static cockpit.
    body = <Welcome />;
  } else if (code === "PREF") {
    body = <Preferences />;
  } else {
    // S05 — critical codes (GP, HP, DES, WATCH, SCAN, PORT, TOP, NI, CN,
    // MIS) MUST render the bespoke native pane. If a native renderer is
    // unavailable we show the explicit `<CriticalMissingPane>` guard —
    // never the template, design-export, or stub fallback. The trader
    // relies on those panes for real positions and live market data;
    // a degraded surface that pretends to work is more dangerous than a
    // visible "this is missing" notice.
    //
    // For non-critical codes the precedence stays: native > template >
    // design-export > stub. The design export is a token-styled fallback
    // for catalog codes that don't have a native pane yet; FunctionStub
    // is the last-resort generic `/api/fn/{code}` surface.
    const choice = resolvePaneRenderer(code);
    const Native = resolvePane(code);
    switch (choice) {
      case "native":
        // `Native` cannot be null here because `resolvePaneRenderer`
        // returned "native", but TypeScript can't see across the
        // module boundary — the fallthrough into `CriticalMissingPane`
        // keeps the type narrowing honest.
        body = Native ? (
          <Native code={code} symbol={symbol} />
        ) : (
          <CriticalMissingPane code={code} />
        );
        break;
      case "critical-missing":
        body = <CriticalMissingPane code={code} />;
        break;
      case "template":
        body = <TemplateRenderer code={code} symbol={symbol} />;
        break;
      case "design-export":
        body = <DesignExportRenderer code={code} symbol={symbol} variant="pro" />;
        break;
      case "stub":
      default:
        body = <FunctionStub leafId={leafId} code={code} symbol={symbol} />;
        break;
    }
  }
  return (
    <PaneErrorBoundary code={code}>
      <Suspense fallback={<PaneFallback />}>{body}</Suspense>
    </PaneErrorBoundary>
  );
}

/**
 * Explicit failure pane for a critical code whose native renderer is
 * missing from the registry. Static, dependency-free, on-purpose ugly —
 * the trader must notice immediately that something is wrong instead of
 * being shown a plausible-looking design mockup or a raw JSON stub.
 */
function CriticalMissingPane({ code }: { code: string }) {
  return (
    <section
      role="alert"
      aria-live="assertive"
      style={{
        padding: "16px 18px",
        margin: 12,
        border: "1px solid var(--negative)",
        background: "color-mix(in srgb, var(--negative) 8%, var(--surface-2))",
        borderRadius: "var(--radius-md)",
        color: "var(--text-primary)",
        fontFamily: "JetBrains Mono, monospace",
        display: "grid",
        gap: 8,
      }}
    >
      <strong style={{ fontSize: 13, letterSpacing: "0.04em", color: "var(--negative)" }}>
        Critical pane unavailable — {code.toUpperCase()}
      </strong>
      <span style={{ fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.5 }}>
        This pane is on the S05 critical list (GP, HP, DES, WATCH, SCAN,
        PORT, TOP, NI, CN, MIS) and its native React component is not
        registered. ShowMe will not silently fall back to a template, a
        design-export mockup, or the generic stub for these codes because
        they back real positions and live market data.
      </span>
      <span style={{ fontSize: 11, color: "var(--text-mute)" }}>
        Fix: register the native pane in
        <code style={{ marginLeft: 6, fontFamily: "JetBrains Mono, monospace" }}>
          ui/src/functions/registry.tsx
        </code>{" "}
        and rebuild.
      </span>
    </section>
  );
}

/**
 * Public renderer-choice type. Mirrors the union in
 * `@/lib/pane-completeness` — kept re-exported here so existing imports
 * (`import { choosePaneRenderer } from './Workspace'`) continue to work.
 */
export type PaneRendererChoice =
  | "native"
  | "template"
  | "design-export"
  | "stub"
  | "critical-missing";

/**
 * Public regression hook for pane resolution. Critical codes resolve to
 * "native" when the bespoke pane is present, "critical-missing" when it
 * is not — never to template / design / stub. Non-critical codes follow
 * native > template > design-export > stub.
 *
 * The optional `adapters` argument lets tests inject stubbed has-native
 * / has-template / has-design-export checks to exercise the
 * "critical-missing" branch without removing modules from the registry.
 */
export function choosePaneRenderer(
  code: string,
  adapters?: PaneResolveAdapters,
): PaneRendererChoice {
  return resolvePaneRenderer(code, adapters);
}

// Re-export the critical-code list so `import { CRITICAL_CODES } from
// '@/shell/Workspace'` keeps working from older callsites; the canonical
// source remains `@/lib/pane-completeness`.
export { CRITICAL_CODES };

function Split({ node }: { node: SplitNode }) {
  const setSplitSizes = useWorkspace((s) => s.setSplitSizes);
  const containerRef = useRef<HTMLDivElement>(null);
  const draggingIdx = useRef<number | null>(null);
  const startSizes = useRef<number[] | null>(null);
  const startCoord = useRef<number>(0);
  const containerSize = useRef<number>(0);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const idx = draggingIdx.current;
      if (idx == null) return;
      const start = startSizes.current;
      const total = containerSize.current;
      if (!start || !total) return;
      const delta =
        ((node.direction === "h" ? e.clientX : e.clientY) - startCoord.current) /
        total;
      const next = [...start];
      const min = 0.08;
      const a = Math.max(min, Math.min(start[idx] + delta, start[idx] + start[idx + 1] - min));
      const b = start[idx] + start[idx + 1] - a;
      next[idx] = a;
      next[idx + 1] = b;
      setSplitSizes(node.id, next);
    };
    const onUp = () => {
      draggingIdx.current = null;
      startSizes.current = null;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [node.direction, node.id, setSplitSizes]);

  const startDrag = (idx: number) => (e: React.MouseEvent) => {
    e.preventDefault();
    const el = containerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    containerSize.current = node.direction === "h" ? rect.width : rect.height;
    startSizes.current = [...node.sizes];
    startCoord.current = node.direction === "h" ? e.clientX : e.clientY;
    draggingIdx.current = idx;
  };

  const trackTemplate = node.sizes
    .map((s) => `${(s * 100).toFixed(4)}fr`)
    .join(` ${HANDLE_PX}px `);
  const splitStyle =
    node.direction === "h"
      ? { ["--ws-cols" as string]: trackTemplate }
      : { ["--ws-rows" as string]: trackTemplate };
  return (
    <div
      ref={containerRef}
      className={`ws-split ws-split--${node.direction}`}
      style={splitStyle}
    >
      {node.children.flatMap((child, i) => {
        const items: React.ReactNode[] = [
          <div key={`pane-${child.id}`} className="ws-split__cell">
            <Node node={child} />
          </div>,
        ];
        if (i < node.children.length - 1) {
          items.push(
            <div
              key={`handle-${child.id}`}
              onMouseDown={startDrag(i)}
              className={`ws-split__handle ws-split__handle--${node.direction}`}
              role="separator"
              aria-orientation={node.direction === "h" ? "vertical" : "horizontal"}
            />,
          );
        }
        return items;
      })}
    </div>
  );
}
