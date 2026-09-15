/**
 * showMe chart engine — drawing-tool primitives.
 *
 * Pure list helpers + a pixel-space hit test. The renderer paints whatever
 * list it is handed; the React shell owns the interaction state machine
 * (tool selection, click-to-commit, click-to-delete). Nothing here touches
 * the DOM, so every helper is unit-testable in isolation.
 *
 * Coordinates: trend endpoints live in (bar index, price) space — the same
 * space the renderer already maps through the time/price scales. Horizontal
 * lines need only a price, so they survive time-range changes.
 */

export interface Drawing {
  id: string;
  kind: "hline" | "trend" | "fib";
  /** kind === "hline": the price level. */
  price?: number;
  /** kind === "trend" | "fib": endpoints. */
  p1?: { index: number; price: number };
  p2?: { index: number; price: number };
}

export type DrawTool = null | "hline" | "trend" | "fib";

/** Canonical Fibonacci retracement ratios (0 = p2 anchor, 1 = p1 anchor). */
export const FIB_RATIOS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const;

/**
 * Fib level price for a ratio. Convention matches the drawing gesture:
 * the drag ends at p2, so 0 sits on p2 and 1 on p1 (TradingView grammar —
 * draw from the swing low up to the high and the levels retrace down).
 */
export function fibLevelPrice(p1: number, p2: number, ratio: number): number {
  return p2 + (p1 - p2) * ratio;
}

/** All canonical levels between two anchor prices; [] on non-finite input. */
export function fibLevels(
  p1: number,
  p2: number,
): { ratio: number; price: number }[] {
  if (!Number.isFinite(p1) || !Number.isFinite(p2)) return [];
  return FIB_RATIOS.map((ratio) => ({ ratio, price: fibLevelPrice(p1, p2, ratio) }));
}

let _seq = 0;
function nextId(): string {
  _seq += 1;
  return `drw-${_seq.toString(36)}-${Date.now().toString(36)}`;
}

function isFinitePoint(
  p: { index: number; price: number } | undefined,
): p is { index: number; price: number } {
  return !!p && Number.isFinite(p.index) && Number.isFinite(p.price);
}

/** Append a horizontal line at `price`; non-finite prices are ignored. */
export function addHline(list: Drawing[], price: number): Drawing[] {
  if (!Number.isFinite(price)) return list;
  return [...list, { id: nextId(), kind: "hline", price }];
}

/** Append a trendline through two (index, price) points; degenerate input is ignored. */
export function addTrend(
  list: Drawing[],
  p1: { index: number; price: number },
  p2: { index: number; price: number },
): Drawing[] {
  if (!isFinitePoint(p1) || !isFinitePoint(p2)) return list;
  return [...list, { id: nextId(), kind: "trend", p1: { ...p1 }, p2: { ...p2 } }];
}

/** Append a Fibonacci retracement between two (index, price) anchors. */
export function addFib(
  list: Drawing[],
  p1: { index: number; price: number },
  p2: { index: number; price: number },
): Drawing[] {
  if (!isFinitePoint(p1) || !isFinitePoint(p2)) return list;
  if (!Number.isFinite(fibLevelPrice(p1.price, p2.price, 0.5))) return list;
  return [...list, { id: nextId(), kind: "fib", p1: { ...p1 }, p2: { ...p2 } }];
}

/** Remove by id; unknown ids leave the list contents untouched. */
export function removeDrawing(list: Drawing[], id: string): Drawing[] {
  return list.filter((d) => d.id !== id);
}

/** The renderer's "empty" list — a fresh array each call (never shared). */
export function clearDrawings(): Drawing[] {
  return [];
}

function distanceToSegment(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): number {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const lenSq = dx * dx + dy * dy;
  if (lenSq <= 0) return Math.hypot(px - x1, py - y1);
  let t = ((px - x1) * dx + (py - y1) * dy) / lenSq;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

/**
 * Pixel-space hit test. `toX`/`toY` are the live axis mappers (price mode
 * aware — callers pass the same mapper the renderer painted with), so the
 * hit region always matches what is on screen. Horizontal lines span the
 * full plot width; only the vertical distance is tested.
 */
export function hitTestDrawing(
  drawing: Drawing,
  x: number,
  y: number,
  toX: (index: number) => number,
  toY: (price: number) => number,
  tolerancePx: number,
): boolean {
  if (!drawing || !Number.isFinite(x) || !Number.isFinite(y)) return false;
  const tol = Number.isFinite(tolerancePx) && tolerancePx > 0 ? tolerancePx : 0;
  if (drawing.kind === "hline") {
    if (drawing.price == null || !Number.isFinite(drawing.price)) return false;
    const py = toY(drawing.price);
    return Number.isFinite(py) && Math.abs(py - y) <= tol;
  }
  if (drawing.kind === "trend") {
    const { p1, p2 } = drawing;
    if (!isFinitePoint(p1) || !isFinitePoint(p2)) return false;
    const x1 = toX(p1.index);
    const y1 = toY(p1.price);
    const x2 = toX(p2.index);
    const y2 = toY(p2.price);
    if (![x1, y1, x2, y2].every(Number.isFinite)) return false;
    return distanceToSegment(x, y, x1, y1, x2, y2) <= tol;
  }
  if (drawing.kind === "fib") {
    const { p1, p2 } = drawing;
    if (!isFinitePoint(p1) || !isFinitePoint(p2)) return false;
    const x1 = toX(p1.index);
    const x2 = toX(p2.index);
    if (!Number.isFinite(x1) || !Number.isFinite(x2)) return false;
    const loX = Math.min(x1, x2) - tol;
    const hiX = Math.max(x1, x2) + tol;
    if (x < loX || x > hiX) return false;
    for (const level of fibLevels(p1.price, p2.price)) {
      const levelY = toY(level.price);
      if (Number.isFinite(levelY) && Math.abs(levelY - y) <= tol) return true;
    }
    return false;
  }
  return false;
}
