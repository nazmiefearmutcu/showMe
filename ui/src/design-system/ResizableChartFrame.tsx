/**
 * ResizableChartFrame — two-directional chart resize (corner + edges),
 * size persisted to localStorage.
 *
 * Built on top of `re-resizable` (Bokuweb, MIT). The component renders a
 * `<div>` wrapper that becomes the chart's containing block. Three live
 * resize handles are exposed:
 *   - bottom-right corner (primary, two-directional) — big visible grip
 *   - right edge (single-axis width)
 *   - bottom edge (single-axis height)
 *
 * Default size:
 *   - Width: 100% of the parent column.
 *   - Height: viewport-aware (defaults to ``"min(48vh, 460px)"``). Callers
 *     can override via the ``defaultHeight`` prop with any CSS length or
 *     a number (interpreted as px).
 *
 * Persistence: ``localStorage["showme.chart-size.<storageId>"]`` carries a
 * ``{width, height}`` JSON record once the user has dragged. The legacy
 * vertical-only hook used the same key; surviving entries are honoured.
 *
 * UX:
 *   - Double-click the corner grip to reset to the viewport-aware default.
 *   - Hovering any handle reveals an accent-coloured fill.
 *   - ``onResize`` fires during the drag so chart libraries can re-measure
 *     immediately (instead of waiting for the next ResizeObserver tick).
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import { Resizable, type ResizableProps } from "re-resizable";

export type ChartFrameSize = {
  width: number;
  height: number;
};

export type ResizableChartFrameProps = {
  storageId: string;
  /**
   * Initial pixel height when no user-resized value is in localStorage.
   * Either a number (px) or an object describing a viewport-aware fit.
   * Default: ``{ vh: 0.46, max: 460, min: 220 }``.
   *
   * Why not a CSS string like ``"min(48vh, 460px)"``? re-resizable's
   * ``defaultSize`` only accepts pixel numbers or simple percentage/auto
   * strings — CSS ``min()`` / ``clamp()`` expressions are silently
   * ignored. So we resolve viewport math ourselves at mount time.
   */
  defaultHeight?: number | { vh: number; max: number; min?: number };
  minWidth?: number;
  minHeight?: number;
  maxWidth?: number;
  maxHeight?: number;
  className?: string;
  style?: CSSProperties;
  onResize?: (size: ChartFrameSize) => void;
  onResizeStop?: (size: ChartFrameSize) => void;
  ariaLabel?: string;
  children: ReactNode;
};

const DEFAULT_HEIGHT_FIT = { vh: 0.46, max: 460, min: 220 };
const DEFAULT_MIN_WIDTH = 360;
const DEFAULT_MIN_HEIGHT = 200;
const DEFAULT_MAX_WIDTH = 2400;
const DEFAULT_MAX_HEIGHT = 1600;

function resolveDefaultHeight(
  spec: ResizableChartFrameProps["defaultHeight"],
): number {
  const viewportH =
    typeof window !== "undefined" ? window.innerHeight || 720 : 720;
  if (typeof spec === "number") return spec;
  const fit = spec ?? DEFAULT_HEIGHT_FIT;
  const raw = Math.round(viewportH * fit.vh);
  const min = fit.min ?? DEFAULT_HEIGHT_FIT.min!;
  return Math.max(min, Math.min(fit.max, raw));
}

// Three visible handles. We deliberately skip bottomLeft/topLeft/topRight
// to avoid cluttering the chart with grips users will rarely use; the
// bottom-right corner is the primary affordance.
const ENABLE_HANDLES: ResizableProps["enable"] = {
  top: false,
  right: true,
  bottom: true,
  left: false,
  topRight: false,
  bottomRight: true,
  bottomLeft: false,
  topLeft: false,
};

export function ResizableChartFrame({
  storageId,
  defaultHeight,
  minWidth = DEFAULT_MIN_WIDTH,
  minHeight = DEFAULT_MIN_HEIGHT,
  maxWidth = DEFAULT_MAX_WIDTH,
  maxHeight = DEFAULT_MAX_HEIGHT,
  className,
  style,
  onResize,
  onResizeStop,
  ariaLabel = "Resize chart",
  children,
}: ResizableChartFrameProps) {
  // ``size`` is null until the user actually drags. While null, re-resizable
  // falls back to ``defaultSize`` (a CSS string), so the chart adapts to
  // the viewport. After the first drag, we capture pixel dimensions.
  const [size, setSize] = useState<ChartFrameSize | null>(() => readChartSize(storageId));

  // Track parent dimensions so we can clamp max-width / max-height to the
  // chart's actual grid column / row. Without this, re-resizable cheerfully
  // grows the chart past its column and stomps on the right rail / sibling
  // panes. ResizeObserver keeps the bounds fresh as the window or workspace
  // splits change.
  const resizableRef = useRef<Resizable | null>(null);
  const [parentBounds, setParentBounds] = useState<{ w: number; h: number } | null>(null);

  useEffect(() => {
    const outerNode = resizableRef.current?.resizable;
    const parent = outerNode?.parentElement;
    if (!parent) return;
    const measure = () => {
      const rect = parent.getBoundingClientRect();
      // Subtract 1px so a max-clamped chart never lands *exactly* on the
      // parent's edge — WebKit otherwise rounds up and we still leak by 1.
      setParentBounds({
        w: Math.max(0, Math.floor(rect.width) - 1),
        h: Math.max(0, Math.floor(rect.height) - 1),
      });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(parent);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    setSize(readChartSize(storageId));
  }, [storageId]);

  useEffect(() => {
    writeChartSize(storageId, size);
  }, [storageId, size]);

  const handleResize = useCallback<NonNullable<ResizableProps["onResize"]>>(
    (_event, _direction, ref) => {
      const rect = ref.getBoundingClientRect();
      onResize?.({
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      });
    },
    [onResize],
  );

  const handleResizeStop = useCallback<NonNullable<ResizableProps["onResizeStop"]>>(
    (_event, _direction, ref) => {
      const rect = ref.getBoundingClientRect();
      const next: ChartFrameSize = {
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      };
      setSize(next);
      onResizeStop?.(next);
    },
    [onResizeStop],
  );

  const reset = useCallback((event: ReactMouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    setSize(null);
  }, []);

  // Controlled vs uncontrolled: pass ``size`` only when the user has
  // resized. While null, re-resizable uses ``defaultSize`` (viewport CSS).
  const controlledSize = size ?? undefined;

  // Resolve viewport-aware default once at mount. Re-resolves only when
  // ``defaultHeight`` changes — NOT on every viewport resize, since the
  // user expects the chart size to stay stable after page load.
  const resolvedDefaultHeight = useMemo(
    () => resolveDefaultHeight(defaultHeight),
    [defaultHeight],
  );

  const defaultSize = useMemo<ResizableProps["defaultSize"]>(
    () => ({ width: "100%", height: resolvedDefaultHeight }),
    [resolvedDefaultHeight],
  );

  const mergedStyle = useMemo<CSSProperties>(
    () => ({
      ...style,
      position: style?.position ?? "relative",
      // Allow the frame to shrink within flex/grid parents.
      minWidth: 0,
    }),
    [style],
  );

  // Clamp WIDTH to the parent column so the chart never overlaps the
  // right rail / sibling pane. HEIGHT is intentionally NOT clamped to
  // the parent — if we did, growing the chart would also grow its
  // containing row, which would grow our parentBounds, which feeds
  // back into the clamp: a cycle that effectively pins the chart at
  // the current row height. Height is instead clamped to the prop's
  // configured max (which the caller can tie to viewport with vh*).
  const effectiveMaxWidth = parentBounds
    ? Math.min(maxWidth, parentBounds.w)
    : maxWidth;
  const effectiveMaxHeight = maxHeight;

  // If the parent's WIDTH shrinks (workspace split, window resize) and
  // the saved size is wider than the new column, clamp it back down so
  // the chart never sticks out past its column.
  useEffect(() => {
    if (!parentBounds || !size) return;
    const clampedW = Math.min(size.width, parentBounds.w);
    if (clampedW !== size.width) {
      setSize({ width: clampedW, height: size.height });
    }
  }, [parentBounds, size]);

  return (
    <Resizable
      ref={(instance) => {
        resizableRef.current = instance;
      }}
      size={controlledSize}
      defaultSize={defaultSize}
      minWidth={minWidth}
      minHeight={minHeight}
      maxWidth={effectiveMaxWidth}
      maxHeight={effectiveMaxHeight}
      enable={ENABLE_HANDLES}
      onResize={handleResize}
      onResizeStop={handleResizeStop}
      handleStyles={HANDLE_STYLES}
      handleClasses={HANDLE_CLASSES}
      handleComponent={{
        bottomRight: (
          <span
            aria-hidden
            aria-label={ariaLabel}
            // pointer-events: none so the mousedown reaches re-resizable's
            // own listener on the wrapper. The grip is purely visual.
            style={CORNER_GRIP_STYLE}
            onDoubleClick={reset}
            title="Drag to resize · Double-click to reset"
          />
        ),
      }}
      style={mergedStyle}
      className={className}
    >
      {children}
    </Resizable>
  );
}

const HANDLE_CLASSES: ResizableProps["handleClasses"] = {
  right: "ds-resize-handle ds-resize-handle--edge-r",
  bottom: "ds-resize-handle ds-resize-handle--edge-b",
  bottomRight: "ds-resize-handle ds-resize-handle--corner-br",
};

// Hit areas. The bottom-right hit zone is generous (28×28) so users can
// grab the visible 20×20 grip even if their cursor is slightly off.
//
// IMPORTANT — explicit ``left: "auto"`` / ``top: "auto"`` overrides:
// re-resizable's internal default styles set ``left: 0px`` / ``top: 0px``
// on every edge handle (carry-over from its row/column base style). When
// our style is merged AFTER theirs, ``left: 0`` survives and the browser
// then resolves ``right: -3`` to nothing (CSS resolves left+width+right
// by ignoring right when all three are set). Result: the "right" handle
// renders on the LEFT side of the frame. We bypass this by explicitly
// re-asserting ``left: auto`` (and similarly for the bottom edge).
const HANDLE_STYLES: ResizableProps["handleStyles"] = {
  right: {
    width: 10,
    height: "100%",
    top: 0,
    right: -3,
    left: "auto",
    bottom: "auto",
    cursor: "ew-resize",
    zIndex: 40,
  },
  bottom: {
    height: 10,
    width: "100%",
    bottom: -3,
    left: 0,
    right: "auto",
    top: "auto",
    cursor: "ns-resize",
    zIndex: 40,
  },
  bottomRight: {
    width: 32,
    height: 32,
    right: 0,
    bottom: 0,
    left: "auto",
    top: "auto",
    cursor: "nwse-resize",
    zIndex: 1000,
  },
};

// Visible solid-accent triangle painted INSIDE the bottom-right hit
// zone. Used to be a translucent linear-gradient, but on dark
// lightweight-charts canvases the grip vanished. A solid coloured
// triangle (accent) with a darker outline reads against any chart
// background.
//
// ``pointer-events: none`` lets the underlying re-resizable wrapper
// own the drag, while a ``dblclick`` listener on the parent handle
// resets the size.
// Visible solid corner grip. SOLID FILL — not a gradient — because gradients
// blend into lightweight-charts' dark canvas and disappear visually. The grip
// uses a strong accent fill with a black outline so it reads on any chart
// background. ``pointer-events: none`` lets re-resizable's wrapper own the
// drag.
// Visible corner grip. A solid OPAQUE square (dark backing + accent
// foreground) sits in the chart's bottom-right corner. The dark
// backing means the grip never relies on the chart canvas behind it
// being a particular colour. ``pointer-events: none`` lets
// re-resizable's wrapper own the drag.
const CORNER_GRIP_STYLE: CSSProperties = {
  position: "absolute",
  right: 0,
  bottom: 0,
  width: 30,
  height: 30,
  pointerEvents: "none",
  zIndex: 1001,
  // Opaque dark background so the grip reads against any chart
  // colours (lightweight-charts canvases are dark by default — but
  // some panels use lighter surfaces). Combined with the bright
  // accent triangle clip-path it gives a clean ‟drag from here” cue.
  background:
    "linear-gradient(135deg, var(--bg-elev-3) 0 38%, var(--accent) 38% 100%)",
  borderTop: "2px solid var(--border-strong)",
  borderLeft: "2px solid var(--border-strong)",
  borderTopLeftRadius: 6,
  boxShadow: "var(--shadow-elev-2)",
  opacity: 1,
};

function chartStorageKey(id: string): string {
  return `showme.chart-size.${id}`;
}

function clampSize(value: number, min: number, max: number): number {
  return Math.round(Math.min(max, Math.max(min, value)));
}

function readChartSize(id: string): ChartFrameSize | null {
  try {
    if (typeof window === "undefined") return null;
    const raw = window.localStorage.getItem(chartStorageKey(id));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ChartFrameSize>;
    if (!Number.isFinite(parsed.width) || !Number.isFinite(parsed.height)) return null;
    const width = Number(parsed.width);
    const height = Number(parsed.height);
    // Width 0 was a sentinel used by the legacy hook ("ignore width, use
    // 100%"). Treat that case as "not user-resized".
    if (width <= 0 || height <= 0) return null;
    return {
      width: clampSize(width, DEFAULT_MIN_WIDTH, DEFAULT_MAX_WIDTH),
      height: clampSize(height, DEFAULT_MIN_HEIGHT, DEFAULT_MAX_HEIGHT),
    };
  } catch {
    return null;
  }
}

function writeChartSize(id: string, size: ChartFrameSize | null): void {
  try {
    if (typeof window === "undefined") return;
    if (!size) {
      window.localStorage.removeItem(chartStorageKey(id));
      return;
    }
    window.localStorage.setItem(chartStorageKey(id), JSON.stringify(size));
  } catch {
    // localStorage can be unavailable in hardened webviews; resize still
    // works for this session, just won't survive a reload.
  }
}
