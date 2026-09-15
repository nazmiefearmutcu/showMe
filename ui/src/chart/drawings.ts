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
  kind: "hline" | "trend";
  /** kind === "hline": the price level. */
  price?: number;
  /** kind === "trend": endpoints. */
  p1?: { index: number; price: number };
  p2?: { index: number; price: number };
}

export type DrawTool = null | "hline" | "trend";

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
  return false;
}
