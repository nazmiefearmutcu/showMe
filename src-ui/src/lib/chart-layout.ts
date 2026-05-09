import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";

type ResizableChart = {
  applyOptions: (options: { width: number; height: number }) => void;
};

type ChartSize = {
  width: number;
  height: number;
};

type StoppableEvent = {
  preventDefault: () => void;
  stopPropagation: () => void;
};

export const terminalChartHeight = "clamp(380px, min(58vh, 44vw), 680px)";

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

export const chartResizeHandleStyle: CSSProperties = {
  position: "absolute",
  right: 8,
  bottom: 8,
  zIndex: 8,
  width: 18,
  height: 18,
  padding: 0,
  border: "1px solid color-mix(in srgb, var(--accent) 44%, transparent)",
  borderRadius: 4,
  background:
    "repeating-linear-gradient(135deg, transparent 0 4px, rgba(44,204,255,0.38) 4px 5px)",
  cursor: "nwse-resize",
  opacity: 0.78,
};

export function usePersistentChartSize(id: string) {
  const frameRef = useRef<HTMLElement | null>(null);
  const [size, setSize] = useState<ChartSize | null>(() => readChartSize(id));

  useEffect(() => {
    setSize(readChartSize(id));
  }, [id]);

  useEffect(() => {
    writeChartSize(id, size);
  }, [id, size]);

  const setFrameRef = useCallback((node: HTMLElement | null) => {
    frameRef.current = node;
  }, []);

  const resetSize = useCallback((event?: StoppableEvent) => {
    event?.preventDefault();
    event?.stopPropagation();
    setSize(null);
  }, []);

  const startResize = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    const frame = frameRef.current;
    if (!frame) return;
    event.preventDefault();
    event.stopPropagation();

    const startRect = frame.getBoundingClientRect();
    const parentRect = frame.parentElement?.getBoundingClientRect();
    const maxWidth = Math.max(420, Math.floor((parentRect?.width ?? window.innerWidth) - 2));
    const maxHeight = Math.max(420, Math.floor(window.innerHeight * 0.9));
    const startX = event.clientX;
    const startY = event.clientY;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "nwse-resize";
    document.body.style.userSelect = "none";

    const onMove = (moveEvent: PointerEvent) => {
      const nextWidth = clampSize(startRect.width + moveEvent.clientX - startX, 420, maxWidth);
      const nextHeight = clampSize(startRect.height + moveEvent.clientY - startY, 320, maxHeight);
      setSize({ width: nextWidth, height: nextHeight });
    };

    const cleanup = () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", cleanup);
      window.removeEventListener("pointercancel", cleanup);
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", cleanup);
    window.addEventListener("pointercancel", cleanup);
  }, []);

  const frameStyle = useMemo<CSSProperties>(
    () =>
      size
        ? {
            width: size.width,
            height: size.height,
            maxWidth: "100%",
          }
        : {},
    [size],
  );

  return {
    frameRef: setFrameRef,
    frameStyle,
    resetSize,
    startResize,
  };
}

export function measureChartElement(
  el: HTMLElement,
  fallbackHeight = 420,
): { width: number; height: number } {
  const rect = el.getBoundingClientRect();
  return {
    width: Math.max(320, Math.round(rect.width || el.clientWidth || 640)),
    height: Math.max(320, Math.round(rect.height || el.clientHeight || fallbackHeight)),
  };
}

export function resizeChartToElement(
  chart: ResizableChart,
  el: HTMLElement,
  fallbackHeight = 420,
): void {
  chart.applyOptions(measureChartElement(el, fallbackHeight));
}

function clampSize(value: number, min: number, max: number): number {
  return Math.round(Math.min(max, Math.max(min, value)));
}

function chartStorageKey(id: string): string {
  return `showme.chart-size.${id}`;
}

function readChartSize(id: string): ChartSize | null {
  try {
    if (typeof window === "undefined") return null;
    const raw = window.localStorage.getItem(chartStorageKey(id));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ChartSize>;
    if (!Number.isFinite(parsed.width) || !Number.isFinite(parsed.height)) return null;
    return {
      width: clampSize(Number(parsed.width), 420, 2400),
      height: clampSize(Number(parsed.height), 320, 1400),
    };
  } catch {
    return null;
  }
}

function writeChartSize(id: string, size: ChartSize | null): void {
  try {
    if (typeof window === "undefined") return;
    if (!size) {
      window.localStorage.removeItem(chartStorageKey(id));
      return;
    }
    window.localStorage.setItem(chartStorageKey(id), JSON.stringify(size));
  } catch {
    // localStorage can be disabled in hardened webviews; resizing still works for this session.
  }
}
