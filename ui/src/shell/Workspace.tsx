/**
 * Workspace renderer — recursive split tree with drag-resize handles.
 *
 * Single source of multi-pane layout. Each leaf renders the focused
 * pane via `resolvePane`; codes without a bespoke pane fall through to
 * `<ManifestPane code={code} />` which renders the contract-driven shell
 * (header, controls, sources, methodology) backed by `/api/fn/{code}`
 * with the function manifest as the source of truth.
 *
 * ROUND-2B (PERF-02): every pane (including the three "always-loaded"
 * panes Welcome / Preferences / ManifestPane) is lazy-loaded so the
 * entry chunk only ships the shell + design system. A small Suspense
 * fallback paints a token-coloured shimmer while the chunk arrives.
 *
 * 2026-05-24 — production-fakery removal: the legacy FunctionStub +
 * TemplateRenderer lazy imports were dropped from the production path
 * and the non-critical switch now ends in a single `<ManifestPane>`
 * fallback. The fakery modules still exist in the tree for dev
 * inspection and live test coverage, but no production-path file
 * imports them any more. The contract-driven ManifestPane handles its
 * own "manifest not registered" state internally, so the previous
 * native > template > stub ladder collapses to native > manifest.
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
  CRITICAL_CODES,
  isCriticalCode,
  resolvePaneRenderer,
  type PaneResolveAdapters,
} from "@/lib/pane-completeness";
import { fetchManifests } from "@/manifest/registry";
import { PaneChrome } from "./PaneChrome";
import { PaneErrorBoundary } from "./PaneErrorBoundary";

const Welcome = lazy(() => import("@/panes/Welcome").then((m) => ({ default: m.Welcome })));
const Preferences = lazy(() =>
  import("@/panes/Preferences").then((m) => ({ default: m.Preferences })),
);
const ManifestPane = lazy(() =>
  import("@/manifest/ManifestPane").then((m) => ({ default: m.ManifestPane })),
);

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
  // Populate the manifest registry once at mount so the contract-driven
  // ManifestPane fallback resolves manifests synchronously on first
  // render instead of flashing its own "Loading manifest…" placeholder
  // for every cold pane. ManifestPane also calls fetchManifests() in its
  // own effect; the duplicate call is cheap (the loader is idempotent
  // against the registry) and keeps the contract local-to-component.
  useEffect(() => {
    void fetchManifests().catch(() => {
      // Surfaced via the registry's error state; consumed by ManifestPane.
    });
  }, []);
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
  // After the QA-2026-05-23 fix, the only remaining "design-leaf" is the
  // Preferences shell, which still hosts SettingsDesignExportRenderer
  // (the only legitimate design-export consumer). Every other code now
  // routes to a native pane, template, or FunctionStub — all of which
  // need the outer PaneChrome for SymbolBar / RefreshButton wiring.
  //
  // S05 invariant kept: critical codes (GP, HP, DES, WATCH, SCAN, PORT,
  // TOP, NI, CN, MIS) are never design-leaves; PaneChrome stays around
  // the CriticalMissingPane guard so the trader still has the toolbar
  // surface and code header.
  // Post 2026-05-24 fakery removal: `hasTemplate` was deleted along with
  // the TemplateRenderer import; the design-leaf decision is now PREF-only.
  const hasNative = resolvePane(node.code) !== null;
  const isCritical = isCriticalCode(node.code);
  void hasNative;
  void isCritical;
  const isDesignLeaf = node.code === "PREF";
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
  leafId: _leafId,
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
    // QA-2026-05-23: non-critical precedence simplified from native >
    // template > design-export > stub to native > template > stub. The
    // design-export tier was serving the 39k-line static mockup for
    // ~110 codes (BLAK, DDM, OMON, BMC, BMTX, BOIL, BQL, BQUANT, MGN,
    // MICRO, MOSS, PCAS, PVAR, READ, RV, STRS, TAUC, TECH, WACC, YAS,
    // ...) instead of using the real `/api/fn/{code}` response that the
    // backend already returns. We collapse "design-export" → "stub" so
    // FunctionStub handles every catalog code that doesn't have a
    // bespoke pane or template. `resolvePaneRenderer` may still return
    // "design-export" for inventory/diagnostics consumers (which is why
    // we keep the resolver intact); Workspace just treats it the same
    // way it treats "stub".
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
      case "design-export":
      case "stub":
      default:
        // Production-fakery removal: every non-native pane now flows
        // through ManifestPane. If a manifest is registered for `code`,
        // the contract-driven shell renders header + controls + sources
        // + warnings + next-actions; otherwise ManifestPane shows its
        // own explicit "manifest not registered" state. Either way the
        // user sees honest information instead of a JSON dump or a
        // synthetic mock template.
        body = <ManifestPane code={code} initialInputs={symbol ? { symbol } : undefined} />;
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
        registered. ShowMe will not silently fall back to a template or
        the generic stub for these codes because they back real positions
        and live market data.
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

/**
 * CRITICAL #1 (UI-Shell-Bundle UB) — minimum size per child during
 * drag/keyboard resize. Centralised so the keyboard handler below shares
 * the exact same floor as the mouse handler.
 */
const MIN_PANE_FRACTION = 0.08;

/**
 * CRITICAL #1 — resize-by-delta that survives 3+ siblings.
 *
 * The legacy code paired `start[idx]` with `start[idx+1]` and used the
 * `start[idx] + start[idx+1] - min` clamp. That math only ever balances
 * with the immediate right neighbour, which silently corrupts a row of 3+
 * panes: any size left over after the clamp gets discarded because every
 * sibling after `idx+1` is overwritten by the in-place `next[idx+1] = b`
 * pattern below. With 3 children the third pane's width "ghost-shifts"
 * during drag; with 4+ the bottom row can briefly snap to zero before the
 * normaliser resurrects it.
 *
 * The new helper:
 *   - moves only `idx` (and rebalances mass into `idx+1..end` proportionally
 *     to their pre-drag size, so panes 3..N keep their visual weight),
 *   - clamps `idx` against `MIN_PANE_FRACTION` and against the total mass
 *     downstream (`totalSize - min*(children-idx-1)` per the spec),
 *   - preserves every sibling after `idx+1` instead of forcing the legacy
 *     two-pane assumption.
 *
 * Returns a fresh sizes array (no mutation of `start`). The caller is
 * responsible for calling `setSplitSizes` with the result.
 */
export function applySplitDragDelta(
  start: number[],
  idx: number,
  delta: number,
): number[] {
  const n = start.length;
  if (n < 2 || idx < 0 || idx >= n - 1) return [...start];
  const min = MIN_PANE_FRACTION;
  // Mass that must stay reserved for every pane after `idx` (idx+1 and
  // everything to its right). For n=2 that's exactly one min; for n=3
  // it's two; etc.
  const downstreamFloor = min * (n - idx - 1);
  // Upper bound on `idx` — total minus the combined downstream floor.
  // Matches the spec `min(start[idx]+delta, totalSize - min*(children-idx-1))`.
  const totalSize = start.reduce((s, v) => s + v, 0); // sums to ~1.0 in practice
  const max = totalSize - downstreamFloor;
  const a = Math.max(min, Math.min(start[idx] + delta, max));
  // Mass freed up by moving `idx`. Distribute proportionally to the
  // pre-drag share of panes `idx+1..n-1`, preserving their relative
  // weights. Because `a` was clamped to honour `downstreamFloor`, the
  // remaining mass is always >= min*(n-idx-1) — every downstream pane
  // can sit above the MIN floor with proportional weight.
  const remaining = totalSize - a;
  const downstreamStart = start.slice(idx + 1);
  const downstreamSum = downstreamStart.reduce((s, v) => s + v, 0);
  const next = [...start];
  next[idx] = a;
  if (downstreamSum <= 0) {
    // Degenerate zero-mass siblings (test fixture / corrupted state) —
    // split the remaining mass equally with no Math.max leak.
    const per = remaining / downstreamStart.length;
    for (let i = idx + 1; i < n; i += 1) next[i] = per;
  } else {
    // Proportional first pass. Then enforce the MIN floor in a second
    // pass that reclaims excess from above-floor panes so the row still
    // sums to `remaining` (a naive `Math.max(min, ...)` would over-
    // allocate when the proportional share fell below MIN).
    for (let i = idx + 1; i < n; i += 1) {
      const share = start[i] / downstreamSum;
      next[i] = remaining * share;
    }
    // Reconciliation: any pane below MIN steals from the largest pane
    // above MIN until every downstream pane is >= MIN. Bounded number
    // of iterations since `remaining >= min*(n-idx-1)` is invariant.
    const isBelow = (i: number) => next[i] < min - 1e-12;
    let guard = n * 2;
    while (guard-- > 0) {
      let belowIdx = -1;
      let donor = -1;
      let donorVal = -Infinity;
      for (let i = idx + 1; i < n; i += 1) {
        if (belowIdx < 0 && isBelow(i)) belowIdx = i;
        if (next[i] > donorVal) {
          donorVal = next[i];
          donor = i;
        }
      }
      if (belowIdx < 0 || donor < 0 || donor === belowIdx) break;
      const deficit = min - next[belowIdx];
      next[belowIdx] = min;
      next[donor] -= deficit;
    }
  }
  return next;
}

function Split({ node }: { node: SplitNode }) {
  const setSplitSizes = useWorkspace((s) => s.setSplitSizes);
  const containerRef = useRef<HTMLDivElement>(null);
  /**
   * CRITICAL #2 (UI-Shell-Bundle UB) — drag session ref.
   *
   * The mousemove listener used to read `node.direction` and call
   * `setSplitSizes(node.id, …)` directly. If a sibling pane closed mid-
   * drag, React unmounted this `<Split>` and remounted a fresh one for
   * the new tree, leaving the old listener with a *stale* node.sizes /
   * node.id closure attached to `window`. The new listener wouldn't
   * trigger because the dependency array (`[node.direction, node.id,
   * setSplitSizes]`) was satisfied, and the old listener wrote the wrong
   * sizes (or wrote to a node that no longer existed).
   *
   * The fix folds every dragable value into a single ref. The listener
   * reads from `session.current`; the cleanup tears down the listener
   * pair unconditionally. Each `<Split>` instance owns exactly one
   * listener pair for its lifetime, regardless of sibling churn.
   */
  type DragSession = {
    idx: number;
    startSizes: number[];
    startCoord: number;
    containerSize: number;
    direction: SplitNode["direction"];
    nodeId: string;
  } | null;
  const session = useRef<DragSession>(null);

  // Keep a stable ref to `setSplitSizes` (zustand selector returns the
  // same function reference each render in practice, but we don't want
  // to rely on that — and we want the effect below to mount exactly once
  // per `<Split>` instance lifetime).
  const setSplitSizesRef = useRef(setSplitSizes);
  setSplitSizesRef.current = setSplitSizes;

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const s = session.current;
      if (!s) return;
      const delta =
        ((s.direction === "h" ? e.clientX : e.clientY) - s.startCoord) / s.containerSize;
      const next = applySplitDragDelta(s.startSizes, s.idx, delta);
      setSplitSizesRef.current(s.nodeId, next);
    };
    const onUp = () => {
      session.current = null;
    };
    const onKey = (e: KeyboardEvent) => {
      // Escape during drag cancels the session without writing anything
      // back — the on-screen sizes snap back to the last `setSplitSizes`
      // call. Reduces the "I clicked the wrong handle" frustration.
      if (e.key === "Escape" && session.current) {
        session.current = null;
      }
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      window.removeEventListener("keydown", onKey);
      // If unmount fires mid-drag (sibling closed → tree restructured)
      // wipe the session ref too, so a stray late-firing event from a
      // browser quirk can't write to the now-gone node id.
      session.current = null;
    };
  }, []); // mount-once: read from refs, never from props.

  // CRITICAL #2 — when React reuses this <Split> instance for a new
  // node id (sibling collapse rebuilds the tree but keeps the same
  // component slot), the active drag session is still keyed on the
  // *old* id and would write back to a now-missing split. Detect the
  // id swap and wipe the session so the next mousemove early-returns.
  useEffect(() => {
    if (session.current && session.current.nodeId !== node.id) {
      session.current = null;
    }
  }, [node.id]);

  const startDrag = (idx: number) => (e: React.MouseEvent) => {
    e.preventDefault();
    const el = containerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    session.current = {
      idx,
      startSizes: [...node.sizes],
      startCoord: node.direction === "h" ? e.clientX : e.clientY,
      containerSize: node.direction === "h" ? rect.width : rect.height,
      direction: node.direction,
      nodeId: node.id,
    };
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
          // A11Y: WAI-ARIA window-splitter role — focusable + ArrowKey
          // resize so keyboard-only users can resize panes (was previously
          // mouse-drag only). Step is 5% of the parent; ArrowUp/Down on a
          // vertical-direction split (horizontal separator) shrinks/grows
          // the upper child, ArrowLeft/Right do the same on horizontal
          // direction (vertical separator). Home/End jump to extremes.
          const pct = Math.round((node.sizes[i] ?? 0) * 100);
          const onKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
            const STEP = 0.05;
            const start = [...node.sizes];
            const adjust = (delta: number) => {
              // CRITICAL #1: share the 3+ pane resize math with mouse-drag
              // so keyboard resizing also preserves siblings past idx+1.
              setSplitSizes(node.id, applySplitDragDelta(start, i, delta));
            };
            const horiz = node.direction === "h";
            if ((horiz && e.key === "ArrowLeft") || (!horiz && e.key === "ArrowUp")) {
              e.preventDefault();
              adjust(-STEP);
            } else if ((horiz && e.key === "ArrowRight") || (!horiz && e.key === "ArrowDown")) {
              e.preventDefault();
              adjust(STEP);
            } else if (e.key === "Home") {
              e.preventDefault();
              adjust(-1);
            } else if (e.key === "End") {
              e.preventDefault();
              adjust(1);
            }
          };
          items.push(
            <div
              key={`handle-${child.id}`}
              onMouseDown={startDrag(i)}
              onKeyDown={onKey}
              tabIndex={0}
              className={`ws-split__handle ws-split__handle--${node.direction}`}
              role="separator"
              aria-orientation={node.direction === "h" ? "vertical" : "horizontal"}
              aria-valuemin={8}
              aria-valuemax={92}
              aria-valuenow={pct}
              aria-label={`Resize panes (${pct}% / ${100 - pct}%)`}
              data-testid={`ws-split-handle-${node.id}-${i}`}
            />,
          );
        }
        return items;
      })}
    </div>
  );
}
