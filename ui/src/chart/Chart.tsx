/**
 * showMe chart engine — React shell (milestone 1).
 *
 * Owns: /api/bars fetching (all timeframes incl. 1s for crypto), the
 * close-time timeframe picker, chart-type picker, the searchable indicator
 * picker (multi-select), the open-indicator tab strip with per-instance
 * settings, canvas rendering + interactions (unlimited zoom, price-axis
 * zoom, drag pan, dblclick fit, keyboard), and theme integration (palette
 * resolved from the live CSS variables — every theme works).
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { sidecarFetch } from "@/lib/sidecar";
import { Pill } from "@/design-system";
import { INDICATORS, indicatorById } from "./indicators";
import { TIMEFRAMES, timeframeById } from "./timeframes";
import { createPriceScale, createTimeScale } from "./scales";
import { drawChart, fitPriceToVisible, priceMapperFor, resolvePalette } from "./renderer";
import { addHline, addTrend, hitTestDrawing, removeDrawing } from "./drawings";
import type { Drawing, DrawTool } from "./drawings";
import type {
  Bar,
  BarsResponse,
  ChartType,
  IndicatorDef,
  IndicatorInstance,
  PriceMode,
  ThemePalette,
  Viewport,
} from "./types";
import "@/styles/chart-engine.css";

const PRICE_AXIS_W = 66;
const TIME_AXIS_H = 22;
const DEFAULT_TF = "15m";
const DEFAULT_BARS = 300;
/** Pointer hit radius for selecting an existing drawing (px). */
const DRAW_HIT_TOLERANCE = 6;

const SCALE_MODES: { id: PriceMode; label: string; title: string }[] = [
  { id: "linear", label: "LIN", title: "Linear price scale" },
  {
    id: "log",
    label: "LOG",
    title: "Logarithmic price scale (falls back to linear while the visible range is not positive)",
  },
  { id: "percent", label: "%", title: "Percent change from first visible bar" },
];

const CHART_TYPES: { id: ChartType; label: string }[] = [
  { id: "candles", label: "Candles" },
  { id: "line", label: "Line" },
  { id: "area", label: "Area" },
  { id: "bars", label: "OHLC" },
  { id: "heikin", label: "Heikin-Ashi" },
];

let _instSeq = 0;
function instanceId(): string {
  _instSeq += 1;
  return `ind-${Date.now().toString(36)}-${_instSeq}`;
}

export interface ChartProps {
  symbol: string;
  height?: number;
  /** Fill the parent's height instead of a fixed `height` (for frames). */
  fill?: boolean;
  /** Compact: canvas only (no toolbar/pickers) for embedded strips. */
  compact?: boolean;
  initialInterval?: string;
  initialType?: ChartType;
  /** Auto-refresh cadence; 0 disables. Defaults to 30s. */
  refreshMs?: number;
  className?: string;
}

export function Chart({
  symbol,
  height = 420,
  fill = false,
  compact = false,
  initialInterval = DEFAULT_TF,
  initialType = "candles",
  refreshMs = 30_000,
  className,
}: ChartProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const timeRef = useRef(createTimeScale());
  const priceRef = useRef(createPriceScale());
  const barsRef = useRef<Bar[]>([]);
  const paletteRef = useRef<ThemePalette | null>(null);
  const crosshairRef = useRef<{ x: number; y: number; index: number | null } | null>(null);
  const dragRef = useRef<{
    mode: "both" | "time" | "price";
    lastX: number;
    lastY: number;
  } | null>(null);
  const rafRef = useRef(0);

  const [interval, setInterval] = useState(initialInterval);
  const [chartType, setChartType] = useState<ChartType>(initialType);
  const [bars, setBars] = useState<Bar[]>([]);
  const [source, setSource] = useState("");
  const [reason, setReason] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [instances, setInstances] = useState<IndicatorInstance[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const [settingsFor, setSettingsFor] = useState<string | null>(null);
  const [tfOpen, setTfOpen] = useState(false);
  const [typeOpen, setTypeOpen] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [priceMode, setPriceMode] = useState<PriceMode>("linear");
  const [showVolume, setShowVolume] = useState(true);
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [drawTool, setDrawTool] = useState<DrawTool>(null);
  const pendingTrendRef = useRef<{ index: number; price: number } | null>(null);
  const priceTouchedRef = useRef(false);

  /* -- rendering primitives (declared before every consumer) ------ */

  const viewport = useCallback((): Viewport => {
    const el = hostRef.current;
    const w = el?.clientWidth ?? 600;
    const h = fill ? el?.clientHeight ?? height : height;
    return {
      width: w,
      height: Math.max(120, h),
      priceAxisWidth: PRICE_AXIS_W,
      timeAxisHeight: TIME_AXIS_H,
    };
  }, [height, fill]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const host = hostRef.current;
    if (!canvas || !host) return;
    const vp = viewport();
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    if (canvas.width !== Math.round(vp.width * dpr) || canvas.height !== Math.round(vp.height * dpr)) {
      canvas.width = Math.round(vp.width * dpr);
      canvas.height = Math.round(vp.height * dpr);
    }
    timeRef.current.setViewport(vp);
    priceRef.current.setViewport(vp);
    /* Observable view state for tests/E2E (and debugging): the visible bar
       index window + price range, written even when the canvas context is
       unavailable (jsdom). */
    const view = timeRef.current.range();
    canvas.dataset.viewFrom = view.from.toFixed(3);
    canvas.dataset.viewTo = view.to.toFixed(3);
    const pr = priceRef.current.range();
    canvas.dataset.priceMin = pr.min.toFixed(6);
    canvas.dataset.priceMax = pr.max.toFixed(6);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    if (!paletteRef.current) paletteRef.current = resolvePalette(host);
    const computed = instances.map((inst) => {
      const def = indicatorById(inst.indicator) as IndicatorDef;
      return { instance: inst, def, result: def.compute(barsRef.current, inst.params) };
    });
    drawChart({
      ctx,
      dpr,
      viewport: vp,
      palette: paletteRef.current,
      bars: barsRef.current,
      chartType,
      time: timeRef.current,
      price: priceRef.current,
      indicators: computed,
      crosshair: crosshairRef.current,
      symbol,
      legend: source ? `${source}${asOf ? ` · ${asOf.slice(11, 16)}Z` : ""}` : undefined,
      priceMode,
      showVolume,
      drawings,
    });
  }, [instances, chartType, source, asOf, symbol, viewport, priceMode, showVolume, drawings]);

  const schedule = useCallback(() => {
    if (rafRef.current) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0;
      draw();
    });
  }, [draw]);

  const fitAll = useCallback(
    (keepWindow = false) => {
      const barsNow = barsRef.current;
      if (!keepWindow) {
        const to = Math.max(0, barsNow.length - 1);
        const from = Math.max(0, barsNow.length - Math.min(barsNow.length, 180));
        timeRef.current.setRange(from, to);
      }
      priceTouchedRef.current = false;
      fitPriceToVisible(priceRef.current, barsNow, timeRef.current);
      draw();
    },
    [draw],
  );

  const load = useCallback(
    async (opts?: { silent?: boolean }) => {
      if (!symbol) return;
      if (!opts?.silent) setLoading(true);
      try {
        const res = await sidecarFetch<BarsResponse>(
          `/api/bars?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(
            interval,
          )}&limit=${DEFAULT_BARS}`,
        );
        const next = Array.isArray(res.bars) ? res.bars : [];
        setBars(next);
        barsRef.current = next;
        setSource(res.source ?? "");
        setReason(res.reason ?? null);
        setAsOf(res.asOf ?? null);
        setFetchError(null);
        if (opts?.silent) {
          if (!priceTouchedRef.current) {
            fitPriceToVisible(priceRef.current, next, timeRef.current);
          }
          draw();
        } else {
          fitAll(false);
        }
      } catch (err) {
        setFetchError(err instanceof Error ? err.message : String(err));
        setReason(null);
      } finally {
        setLoading(false);
      }
    },
    [symbol, interval, fitAll, draw],
  );

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, interval]);

  useEffect(() => {
    if (!refreshMs || !autoRefresh) return;
    const id = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void load({ silent: true });
    }, refreshMs);
    return () => window.clearInterval(id);
  }, [refreshMs, autoRefresh, load]);

  useEffect(() => {
    schedule();
  });

  useEffect(() => {
    const host = hostRef.current;
    if (!host || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      paletteRef.current = null;
      schedule();
    });
    ro.observe(host);
    return () => ro.disconnect();
  }, [schedule]);

  /* Theme switches mutate documentElement attributes/classes — redraw. */
  useEffect(() => {
    const mo = new MutationObserver(() => {
      paletteRef.current = null;
      schedule();
    });
    mo.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class", "data-theme", "style", "data-preset"],
    });
    return () => mo.disconnect();
  }, [schedule]);

  /* Esc cancels an active drawing tool — the window listener keeps it working
     even while focus sits on the toolbar button that armed the tool. */
  useEffect(() => {
    if (!drawTool) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        pendingTrendRef.current = null;
        setDrawTool(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawTool]);

  /* -- interactions -------------------------------------------------- */

  const localXY = (e: { clientX: number; clientY: number }) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    return {
      x: e.clientX - (rect?.left ?? 0),
      y: e.clientY - (rect?.top ?? 0),
    };
  };

  const onWheel = useCallback(
    (e: WheelEvent) => {
      const el = canvasRef.current;
      if (!el) return;
      const { x, y } = localXY(e);
      const vp = viewport();
      const plotW = vp.width - vp.priceAxisWidth;
      const plotH = vp.height - vp.timeAxisHeight;
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      e.preventDefault();
      if (x > plotW) {
        priceRef.current.zoomAt(y, factor);
        priceTouchedRef.current = true;
      } else if (y > plotH) {
        timeRef.current.zoomAt(x, factor);
      } else if (e.shiftKey) {
        priceRef.current.zoomAt(y, factor);
        priceTouchedRef.current = true;
      } else {
        timeRef.current.zoomAt(x, factor);
      }
      schedule();
    },
    [schedule, viewport],
  );

  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => onWheel(e);
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, [onWheel]);

  const onPointerDown = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const el = canvasRef.current;
    if (!el) return;
    const { x, y } = localXY(e);
    const vp = viewport();
    const plotW = vp.width - vp.priceAxisWidth;
    const plotH = vp.height - vp.timeAxisHeight;
    const inPlot = x >= 0 && x <= plotW && y >= 0 && y <= plotH;

    /* A draw tool owns the pointer: clicks commit points instead of panning.
       Hline commits on the first click; trend commits on the second. */
    if (drawTool) {
      if (inPlot) {
        const index = timeRef.current.toIndex(x);
        const price = priceMapperFor(priceRef.current, priceMode).toPrice(y);
        if (Number.isFinite(index) && Number.isFinite(price)) {
          if (drawTool === "hline") {
            setDrawings((prev) => addHline(prev, price));
          } else {
            const p1 = pendingTrendRef.current;
            if (!p1) {
              pendingTrendRef.current = { index, price };
            } else {
              pendingTrendRef.current = null;
              setDrawings((prev) => addTrend(prev, p1, { index, price }));
            }
          }
        }
      }
      return;
    }

    /* No tool active: clicking an existing drawing deletes it (documented in
       the canvas aria-label). Anything else pans as before. */
    if (inPlot && drawings.length > 0) {
      const mapper = priceMapperFor(priceRef.current, priceMode);
      const hit = [...drawings]
        .reverse()
        .find((d) =>
          hitTestDrawing(
            d,
            x,
            y,
            (i) => timeRef.current.toX(i),
            (v) => mapper.toY(v),
            DRAW_HIT_TOLERANCE,
          ),
        );
      if (hit) {
        setDrawings((prev) => removeDrawing(prev, hit.id));
        return;
      }
    }

    const mode = x > plotW ? "price" : y > plotH ? "time" : "both";
    dragRef.current = { mode, lastX: x, lastY: y };
    el.setPointerCapture?.(e.pointerId);
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const { x, y } = localXY(e);
    const drag = dragRef.current;
    if (drag) {
      const dx = x - drag.lastX;
      const dy = y - drag.lastY;
      drag.lastX = x;
      drag.lastY = y;
      /* Content follows the gesture (TradingView grab behavior): the scales'
         panBy(+d) shifts content by +d px, so the pointer delta maps 1:1 —
         passing -dx here inverted the horizontal pan (user report). */
      if (drag.mode === "both" || drag.mode === "time") timeRef.current.panBy(dx);
      if (drag.mode === "both" || drag.mode === "price") {
        priceRef.current.panBy(dy);
        priceTouchedRef.current = true;
      }
      schedule();
      return;
    }
    const rng = timeRef.current.range();
    const idx = Math.round(timeRef.current.toIndex(x));
    crosshairRef.current = {
      x,
      y,
      index: idx >= Math.floor(rng.from) && idx <= Math.ceil(rng.to) ? idx : null,
    };
    schedule();
  };

  const onPointerUp = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    dragRef.current = null;
    canvasRef.current?.releasePointerCapture?.(e.pointerId);
  };

  const onPointerLeave = () => {
    crosshairRef.current = null;
    schedule();
  };

  const onDoubleClick = () => {
    fitAll(false);
  };

  const onKeyDown = (e: ReactKeyboardEvent<HTMLCanvasElement>) => {
    const step = e.shiftKey ? 40 : 8;
    if (e.key === "ArrowLeft") {
      timeRef.current.panBy(step);
      e.preventDefault();
    } else if (e.key === "ArrowRight") {
      timeRef.current.panBy(-step);
      e.preventDefault();
    } else if (e.key === "ArrowUp") {
      priceRef.current.panBy(step);
      priceTouchedRef.current = true;
      e.preventDefault();
    } else if (e.key === "ArrowDown") {
      priceRef.current.panBy(-step);
      priceTouchedRef.current = true;
      e.preventDefault();
    } else if (e.key === "+" || e.key === "=") {
      timeRef.current.zoomAt(viewport().width / 2, 1.2);
      e.preventDefault();
    } else if (e.key === "-") {
      timeRef.current.zoomAt(viewport().width / 2, 1 / 1.2);
      e.preventDefault();
    }
    schedule();
  };

  /* -- indicator UX --------------------------------------------------- */

  const addIndicator = (def: IndicatorDef) => {
    setInstances((prev) => [
      ...prev,
      {
        id: instanceId(),
        indicator: def.id,
        params: Object.fromEntries(def.params.map((p) => [p.key, p.default])),
        visible: true,
        pane: def.overlayDefault ? "overlay" : "separate",
      },
    ]);
  };

  const removeIndicator = (id: string) =>
    setInstances((prev) => prev.filter((i) => i.id !== id));

  const toggleIndicator = (id: string) =>
    setInstances((prev) =>
      prev.map((i) => (i.id === id ? { ...i, visible: !i.visible } : i)),
    );

  const setParam = (id: string, key: string, value: number | string) =>
    setInstances((prev) =>
      prev.map((i) => (i.id === id ? { ...i, params: { ...i.params, [key]: value } } : i)),
    );

  /** Arm/disarm a drawing tool; starting one cancels any pending trend point. */
  const toggleTool = (tool: "hline" | "trend") => {
    pendingTrendRef.current = null;
    setDrawTool((cur) => (cur === tool ? null : tool));
    setTfOpen(false);
    setTypeOpen(false);
  };

  const pickerResults = useMemo(() => {
    const q = pickerQuery.trim().toLowerCase();
    const list = q
      ? INDICATORS.filter(
          (d) => d.name.toLowerCase().includes(q) || d.category.toLowerCase().includes(q),
        )
      : INDICATORS;
    const byCat = new Map<string, IndicatorDef[]>();
    for (const d of list) {
      const arr = byCat.get(d.category) ?? [];
      arr.push(d);
      byCat.set(d.category, arr);
    }
    return Array.from(byCat.entries());
  }, [pickerQuery]);

  const settingsInstance = instances.find((i) => i.id === settingsFor) ?? null;
  const settingsDef = settingsInstance ? indicatorById(settingsInstance.indicator) : undefined;
  const tf = timeframeById(interval);

  /* -- render --------------------------------------------------------- */

  return (
    <div
      className={`sm-chart${fill ? " sm-chart--fill" : ""}${compact ? " sm-chart--compact" : ""}${
        className ? ` ${className}` : ""
      }`}
      ref={hostRef}
    >
      <div className="sm-chart__toolbar" hidden={compact}>
        <div className="sm-chart__seg">
          <button
            type="button"
            className="sm-chart__btn sm-chart__btn--tf"
            aria-haspopup="listbox"
            aria-expanded={tfOpen}
            onClick={() => {
              setTfOpen((v) => !v);
              setTypeOpen(false);
            }}
          >
            {tf?.label ?? interval.toUpperCase()} <span aria-hidden>▾</span>
          </button>
          {tfOpen && (
            <div className="sm-chart__menu sm-chart__menu--tf" role="listbox" aria-label="Timeframe">
              {(["seconds", "minutes", "hours", "days", "weeks", "months"] as const).map((group) => (
                <div key={group} className="sm-chart__menu-group">
                  <span className="sm-chart__menu-title">{group}</span>
                  <div className="sm-chart__menu-grid">
                    {TIMEFRAMES.filter((t) => t.group === group).map((t) => (
                      <button
                        key={t.id}
                        type="button"
                        role="option"
                        aria-selected={t.id === interval}
                        className={`sm-chart__menu-item${t.id === interval ? " is-active" : ""}`}
                        onClick={() => {
                          setInterval(t.id);
                          setTfOpen(false);
                        }}
                      >
                        {t.label}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="sm-chart__seg">
          <button
            type="button"
            className="sm-chart__btn"
            aria-haspopup="listbox"
            aria-expanded={typeOpen}
            onClick={() => {
              setTypeOpen((v) => !v);
              setTfOpen(false);
            }}
          >
            {CHART_TYPES.find((c) => c.id === chartType)?.label ?? chartType}{" "}
            <span aria-hidden>▾</span>
          </button>
          {typeOpen && (
            <div className="sm-chart__menu sm-chart__menu--type" role="listbox" aria-label="Chart type">
              {CHART_TYPES.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  role="option"
                  aria-selected={c.id === chartType}
                  className={`sm-chart__menu-item${c.id === chartType ? " is-active" : ""}`}
                  onClick={() => {
                    setChartType(c.id);
                    setTypeOpen(false);
                  }}
                >
                  {c.label}
                </button>
              ))}
            </div>
          )}
        </div>

        <button
          type="button"
          className="sm-chart__btn"
          aria-expanded={pickerOpen}
          onClick={() => {
            setPickerOpen((v) => !v);
            setTfOpen(false);
            setTypeOpen(false);
          }}
        >
          ƒ Indicators
        </button>

        <div className="sm-chart__seg" role="group" aria-label="Price scale">
          {SCALE_MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              className={`sm-chart__btn${priceMode === m.id ? " is-active" : ""}`}
              data-testid={`sm-chart-scale-${m.id}`}
              aria-pressed={priceMode === m.id}
              title={m.title}
              onClick={() => {
                setPriceMode(m.id);
                setTfOpen(false);
                setTypeOpen(false);
              }}
            >
              {m.label}
            </button>
          ))}
        </div>

        <button
          type="button"
          className={`sm-chart__btn${showVolume ? " is-active" : ""}`}
          data-testid="sm-chart-volume-toggle"
          aria-pressed={showVolume}
          title="Volume"
          onClick={() => setShowVolume((v) => !v)}
        >
          VOL
        </button>

        <div className="sm-chart__seg" role="group" aria-label="Drawing tools">
          <button
            type="button"
            className={`sm-chart__btn sm-chart__btn--tool${drawTool === "hline" ? " is-active" : ""}`}
            data-testid="sm-chart-draw-hline"
            aria-pressed={drawTool === "hline"}
            aria-label="Horizontal line tool — click the chart to place; Esc cancels"
            title="Horizontal line (Esc cancels)"
            onClick={() => toggleTool("hline")}
          >
            ─
          </button>
          <button
            type="button"
            className={`sm-chart__btn sm-chart__btn--tool${drawTool === "trend" ? " is-active" : ""}`}
            data-testid="sm-chart-draw-trend"
            aria-pressed={drawTool === "trend"}
            aria-label="Trendline tool — click two points; Esc cancels"
            title="Trendline (Esc cancels)"
            onClick={() => toggleTool("trend")}
          >
            ╱
          </button>
        </div>

        <button
          type="button"
          className="sm-chart__btn"
          onClick={() => fitAll(false)}
          title="Fit content (double-click the chart)"
        >
          Fit
        </button>

        <button
          type="button"
          className={`sm-chart__btn${autoRefresh ? " is-active" : ""}`}
          aria-pressed={autoRefresh}
          onClick={() => setAutoRefresh((v) => !v)}
          title="Auto refresh"
        >
          {autoRefresh ? "LIVE" : "PAUSED"}
        </button>

        <div className="sm-chart__spacer" />
        {loading && <Pill tone="muted" variant="soft" withDot={false}>loading…</Pill>}
        {source && (
          <Pill tone="muted" variant="soft" withDot={false}>
            {source}
          </Pill>
        )}
      </div>

      {instances.length > 0 && (
        <div className="sm-chart__tabs" role="tablist" aria-label="Open indicators">
          {instances.map((inst) => {
            const def = indicatorById(inst.indicator);
            return (
              <div key={inst.id} className="sm-chart__tab" role="presentation">
                <button
                  type="button"
                  role="tab"
                  aria-selected={settingsFor === inst.id}
                  className={`sm-chart__tab-btn${inst.visible ? "" : " is-off"}`}
                  onClick={() => setSettingsFor(settingsFor === inst.id ? null : inst.id)}
                  title={`${def?.name ?? inst.indicator} settings`}
                >
                  {def?.name ?? inst.indicator}
                </button>
                <button
                  type="button"
                  className="sm-chart__tab-eye"
                  aria-label={`${inst.visible ? "Hide" : "Show"} ${def?.name ?? inst.indicator}`}
                  onClick={() => toggleIndicator(inst.id)}
                >
                  {inst.visible ? "◉" : "◌"}
                </button>
                <button
                  type="button"
                  className="sm-chart__tab-x"
                  aria-label={`Remove ${def?.name ?? inst.indicator}`}
                  onClick={() => removeIndicator(inst.id)}
                >
                  ×
                </button>
              </div>
            );
          })}
        </div>
      )}

      {pickerOpen && (
        <div className="sm-chart__picker" role="dialog" aria-label="Add indicator">
          <input
            autoFocus
            value={pickerQuery}
            onChange={(e) => setPickerQuery(e.target.value)}
            placeholder="Search indicators…"
            aria-label="Search indicators"
            className="sm-chart__search"
            spellCheck={false}
          />
          <div className="sm-chart__picker-list">
            {pickerResults.map(([category, defs]) => (
              <div key={category} className="sm-chart__picker-group">
                <span className="sm-chart__menu-title">{category}</span>
                {defs.map((d) => {
                  const active = instances.some((i) => i.indicator === d.id);
                  return (
                    <button
                      key={d.id}
                      type="button"
                      className={`sm-chart__picker-item${active ? " is-active" : ""}`}
                      onClick={() => addIndicator(d)}
                    >
                      <span>{d.name}</span>
                      <span className="sm-chart__picker-meta">
                        {active ? "✓ added" : d.overlayDefault ? "overlay" : "pane"}
                      </span>
                    </button>
                  );
                })}
              </div>
            ))}
            {pickerResults.length === 0 && (
              <div className="sm-chart__picker-empty">No indicators match “{pickerQuery}”.</div>
            )}
          </div>
          <button type="button" className="sm-chart__btn sm-chart__picker-close" onClick={() => setPickerOpen(false)}>
            Done
          </button>
        </div>
      )}

      {settingsInstance && settingsDef && (
        <div className="sm-chart__settings" role="dialog" aria-label={`${settingsDef.name} settings`}>
          <div className="sm-chart__settings-head">
            <strong>{settingsDef.name}</strong>
            <button
              type="button"
              className="sm-chart__tab-x"
              aria-label="Close settings"
              onClick={() => setSettingsFor(null)}
            >
              ×
            </button>
          </div>
          <label className="sm-chart__settings-row">
            <span>Pane</span>
            <select
              value={settingsInstance.pane}
              onChange={(e) =>
                setInstances((prev) =>
                  prev.map((i) =>
                    i.id === settingsInstance.id
                      ? { ...i, pane: e.target.value as "overlay" | "separate" }
                      : i,
                  ),
                )
              }
            >
              <option value="overlay">Price pane</option>
              <option value="separate">Separate pane</option>
            </select>
          </label>
          {settingsDef.params.map((param) => (
            <label key={param.key} className="sm-chart__settings-row">
              <span>{param.label}</span>
              {param.kind === "select" ? (
                <select
                  value={String(settingsInstance.params[param.key] ?? param.default)}
                  onChange={(e) => setParam(settingsInstance.id, param.key, e.target.value)}
                >
                  {(param.options ?? []).map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="number"
                  min={param.min}
                  max={param.max}
                  step={param.step ?? 1}
                  value={Number(settingsInstance.params[param.key] ?? param.default)}
                  onChange={(e) =>
                    setParam(settingsInstance.id, param.key, Number(e.target.value))
                  }
                />
              )}
            </label>
          ))}
        </div>
      )}

      <div
        className="sm-chart__canvas-wrap"
        style={fill ? { flex: 1, minHeight: 0 } : { height }}
      >
        <canvas
          ref={canvasRef}
          className={`sm-chart__canvas${drawTool ? " is-drawing" : ""}`}
          tabIndex={0}
          role="img"
          aria-label={`Price chart for ${symbol}, ${tf?.label ?? interval}, ${chartType}, ${
            priceMode === "percent" ? "percent scale" : `${priceMode} scale`
          }${drawTool ? `; ${drawTool} tool active — Esc cancels` : ""}. Click a drawing to delete it when no drawing tool is active.`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={onPointerLeave}
          onDoubleClick={onDoubleClick}
          onKeyDown={onKeyDown}
        />
        {bars.length === 0 && !loading && (
          <div className="sm-chart__empty" role="status">
            <strong>No bars</strong>
            <span>{fetchError ?? reason ?? "The provider returned no data for this interval."}</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default Chart;
