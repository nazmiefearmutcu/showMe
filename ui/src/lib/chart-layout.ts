/**
 * chart-layout — shared chart sizing helpers + reusable style tokens.
 *
 * The user-driven 2-axis resize lives in ``design-system/ResizableChartFrame``
 * (built on re-resizable). This module retains only the lightweight glue that
 * chart-rendering code still depends on: a measure helper, a quick
 * "apply current container size to a lightweight-charts instance" helper,
 * and a small bundle of chart-surface CSS tokens shared by function_stub.
 */

import type { CSSProperties } from "react";

type ResizableChart = {
  applyOptions: (options: { width: number; height: number }) => void;
};

// Viewport-aware default height for legacy chart surfaces (used by
// function_stub/styles.ts). The clamp keeps charts from overflowing the
// PaneBody on shorter laptop displays.
export const terminalChartHeight = "clamp(300px, min(48vh, 38vw), 580px)";

export const terminalChartViewportStyle: CSSProperties = {
  position: "relative",
  boxSizing: "border-box",
  width: "100%",
  height: terminalChartHeight,
  minHeight: 360,
  minWidth: 0,
};

export const terminalChartSurfaceStyle: CSSProperties = {
  ...terminalChartViewportStyle,
  display: "grid",
  gridTemplateRows: "auto minmax(0, 1fr)",
  gap: 6,
  border: "1px solid var(--border-subtle)",
  background: "var(--bg-elev-2)",
  borderRadius: 8,
  padding: 10,
};

export const terminalChartHostStyle: CSSProperties = {
  boxSizing: "border-box",
  width: "100%",
  height: "100%",
  minWidth: 0,
  minHeight: 0,
};

export const terminalSvgChartStyle: CSSProperties = {
  width: "100%",
  height: "100%",
  minHeight: 0,
  display: "block",
  overflow: "visible",
};

export function measureChartElement(
  el: HTMLElement,
  fallbackHeight = 240,
): { width: number; height: number } {
  // Read the host element's *current* layout box. Floors are kept tiny
  // (80px) so the chart always fits the container — never the other way
  // around. The old 320px floor caused the chart canvas to overflow its
  // ResizableChartFrame when the user shrank the chart vertically.
  const rect = el.getBoundingClientRect();
  const w = Math.round(rect.width || el.clientWidth || 640);
  const h = Math.round(rect.height || el.clientHeight || fallbackHeight);
  return {
    width: Math.max(80, w),
    height: Math.max(80, h),
  };
}

export function resizeChartToElement(
  chart: ResizableChart,
  el: HTMLElement,
  fallbackHeight = 420,
): void {
  chart.applyOptions(measureChartElement(el, fallbackHeight));
}
