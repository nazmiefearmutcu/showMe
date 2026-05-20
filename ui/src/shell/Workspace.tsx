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
  const hasNative = resolvePane(node.code) !== null;
  const hasTpl = hasTemplate(node.code);
  const isDesignLeaf =
    node.code === "PREF" ||
    (!hasNative && !hasTpl && hasDesignExportComponent(node.code));
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
    body = hasDesignExportComponent(code) ? (
      <DesignExportRenderer code={code} symbol={symbol} variant="pro" />
    ) : (
      <Welcome />
    );
  } else if (code === "PREF") {
    body = <Preferences />;
  } else {
    // Resolution precedence — native pane wins so that bespoke, live-data
    // panes (HP, GP, BTMM, DES, EQS, FA, ASK, BIO, MIS, NI/CN, …) take
    // priority over the Claude Design export's static Pro mockups. The
    // design export is kept as a token-styled fallback for catalog codes
    // that don't have a native pane yet, and as a last resort we fall
    // back to FunctionStub (the generic `/api/fn/{code}` surface).
    const Native = resolvePane(code);
    if (Native) {
      body = <Native code={code} symbol={symbol} />;
    } else if (hasTemplate(code)) {
      // Design-template-backed renderer (Claude Design Basic variant ported
      // into a token-driven layout). Preferred over the static Pro design
      // export and FunctionStub whenever a matching template exists in
      // ui/src/templates/mock-data.ts.
      body = <TemplateRenderer code={code} symbol={symbol} />;
    } else if (hasDesignExportComponent(code)) {
      body = <DesignExportRenderer code={code} symbol={symbol} variant="pro" />;
    } else {
      body = <FunctionStub leafId={leafId} code={code} symbol={symbol} />;
    }
  }
  return (
    <PaneErrorBoundary code={code}>
      <Suspense fallback={<PaneFallback />}>{body}</Suspense>
    </PaneErrorBoundary>
  );
}

export type PaneRendererChoice = "native" | "template" | "design-export" | "stub";

/**
 * Public regression hook for pane resolution. The actual render path above
 * intentionally keeps the same order: native > template > design-export > stub.
 */
export function choosePaneRenderer(code: string): PaneRendererChoice {
  if (resolvePane(code)) return "native";
  if (hasTemplate(code)) return "template";
  if (hasDesignExportComponent(code)) return "design-export";
  return "stub";
}

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
