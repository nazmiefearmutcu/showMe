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
import { toast } from "@/lib/toast";
import { Pill } from "@/design-system";
import { INDICATORS, indicatorById } from "./indicators";
import { TIMEFRAMES, timeframeById } from "./timeframes";
import { createPriceScale, createTimeScale } from "./scales";
import {
  drawChart,
  fitPriceToVisible,
  normalizeCompareSeries,
  priceMapperFor,
  resolveCssColor,
  resolvePalette,
} from "./renderer";
import { addFib, addHline, addTrend, hitTestDrawing, removeDrawing } from "./drawings";
import type { Drawing, DrawTool } from "./drawings";
import {
  ALERT_COOLDOWN_MS,
  alertRuleId,
  evaluateAlertRule,
  loadAlertStore,
  saveAlertStore,
} from "./chart-alerts";
import type { AlertFireState, AlertRule } from "./chart-alerts";
import { clearLayout, loadLayout, saveLayout } from "./chart-layout";
import type {
  Bar,
  BarsResponse,
  ChartType,
  CompareSeriesInput,
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
/** Compare-line palette tokens; resolved against the live theme at paint. */
const COMPARE_COLOR_TOKENS = [
  "var(--accent)",
  "var(--positive)",
  "var(--negative)",
  "var(--warn)",
] as const;
/** Bar-replay base speed: bars advanced per second at 1×. */
const REPLAY_BARS_PER_SEC = 2;

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
  /** Multi-symbol compare overlay (percent-normalized lines). Default []. */
  compareSymbols?: string[];
  className?: string;
}

/** Most recent finite plot value (alert default when the indicator has no levels). */
function lastFinite(data: (number | null)[]): number | null {
  for (let i = data.length - 1; i >= 0; i--) {
    const v = data[i];
    if (v != null && Number.isFinite(v)) return v;
  }
  return null;
}

export function Chart({
  symbol,
  height = 420,
  fill = false,
  compact = false,
  initialInterval = DEFAULT_TF,
  initialType = "candles",
  refreshMs = 30_000,
  compareSymbols = [],
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

  /* Layout restore (milestone 3): one snapshot read at mount; only fields
     that were actually saved and passed validation are applied. */
  const [restored] = useState(() => loadLayout(symbol));

  const [interval, setInterval] = useState(restored?.interval ?? initialInterval);
  const [chartType, setChartType] = useState<ChartType>(restored?.chartType ?? initialType);
  const [bars, setBars] = useState<Bar[]>([]);
  const [source, setSource] = useState("");
  const [reason, setReason] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [instances, setInstances] = useState<IndicatorInstance[]>(
    restored?.indicators ?? [],
  );
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const [settingsFor, setSettingsFor] = useState<string | null>(null);
  const [tfOpen, setTfOpen] = useState(false);
  const [typeOpen, setTypeOpen] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [priceMode, setPriceMode] = useState<PriceMode>(restored?.priceMode ?? "linear");
  const [showVolume, setShowVolume] = useState(restored?.showVolume ?? true);
  const [drawings, setDrawings] = useState<Drawing[]>(restored?.drawings ?? []);
  const [drawTool, setDrawTool] = useState<DrawTool>(null);
  const [compare, setCompare] = useState<string[]>(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const raw of restored?.compareSymbols ?? compareSymbols) {
      const s = raw.trim();
      if (!s || seen.has(s)) continue;
      seen.add(s);
      out.push(s);
    }
    return out;
  });
  const [compareInput, setCompareInput] = useState("");
  const [compareData, setCompareData] = useState<
    Record<string, { bars: Bar[]; error: string | null }>
  >({});
  const [replayOn, setReplayOn] = useState(false);
  const [replayIndex, setReplayIndex] = useState(0);
  const [replayPlaying, setReplayPlaying] = useState(false);
  const [replaySpeed, setReplaySpeed] = useState<1 | 2 | 5>(1);
  const [alertRules, setAlertRules] = useState<AlertRule[]>(() => loadAlertStore(symbol).rules);
  const [alertLog, setAlertLog] = useState<{ id: string; text: string; title: string }[]>([]);
  const pendingTrendRef = useRef<{ index: number; price: number } | null>(null);
  const priceTouchedRef = useRef(false);
  const replayIdxRef = useRef(0);
  const compareSeqRef = useRef(0);
  const compareCacheRef = useRef<Map<string, Bar[]>>(new Map());
  const firedRef = useRef<Record<string, AlertFireState>>(loadAlertStore(symbol).fired);
  const skipPersistRef = useRef(false);

  const settingsInstance = instances.find((i) => i.id === settingsFor) ?? null;
  const settingsDef = settingsInstance ? indicatorById(settingsInstance.indicator) : undefined;

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
    if (replayOn) canvas.dataset.replayIndex = String(replayIndex);
    else delete canvas.dataset.replayIndex;
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
    /* Compare overlay: normalize each series vs. its first bar at/after the
       main series' first visible bar (timestamp alignment, not index luck),
       then align values onto the main bar grid by exact timestamp. */
    const comparePaint: CompareSeriesInput[] = [];
    if (compare.length > 0 && compareData) {
      const mainBars = barsRef.current;
      const anchorIdx = Math.max(
        0,
        Math.min(mainBars.length - 1, Math.floor(view.from)),
      );
      const mainT = mainBars[anchorIdx]?.t ?? null;
      for (let ci = 0; ci < compare.length; ci++) {
        const sym = compare[ci];
        const entry = compareData[sym];
        if (!entry || entry.error || entry.bars.length === 0) continue;
        let firstIdx = 0;
        if (mainT != null) {
          firstIdx = entry.bars.length;
          for (let i = 0; i < entry.bars.length; i++) {
            if (entry.bars[i].t >= mainT) {
              firstIdx = i;
              break;
            }
          }
        }
        const values = normalizeCompareSeries(entry.bars, firstIdx);
        const byTime = new Map<number, number | null>();
        for (let i = 0; i < entry.bars.length; i++) byTime.set(entry.bars[i].t, values[i]);
        comparePaint.push({
          symbol: sym,
          color: resolveCssColor(host, COMPARE_COLOR_TOKENS[ci % COMPARE_COLOR_TOKENS.length]),
          values: mainBars.map((b) => (byTime.has(b.t) ? (byTime.get(b.t) ?? null) : null)),
        });
      }
    }
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
      replayIndex: replayOn ? replayIndex : undefined,
      compare: comparePaint,
    });
  }, [
    instances,
    chartType,
    source,
    asOf,
    symbol,
    viewport,
    priceMode,
    showVolume,
    drawings,
    compare,
    compareData,
    replayOn,
    replayIndex,
  ]);

  /* Latest-closure indirection: rAF callbacks must paint with the CURRENT
     render state, not the closure captured when the frame was requested
     (a state-driven schedule used to be dropped by the pending-frame
     guard and then repaint with the previous state). */
  const drawRef = useRef(draw);
  drawRef.current = draw;

  const schedule = useCallback(() => {
    if (rafRef.current) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0;
      drawRef.current();
    });
  }, []);

  const fitAll = useCallback(
    (keepWindow = false) => {
      const barsNow = barsRef.current;
      if (!keepWindow) {
        const to = Math.max(0, barsNow.length - 1);
        const from = Math.max(0, barsNow.length - Math.min(barsNow.length, 180));
        timeRef.current.setRange(from, to);
      }
      priceTouchedRef.current = false;
      fitPriceToVisible(
        priceRef.current,
        barsNow,
        timeRef.current,
        0.08,
        replayOn ? replayIdxRef.current : undefined,
      );
      draw();
    },
    [draw, replayOn],
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
            fitPriceToVisible(
              priceRef.current,
              next,
              timeRef.current,
              0.08,
              replayOn ? replayIdxRef.current : undefined,
            );
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
    [symbol, interval, fitAll, draw, replayOn],
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

  /* -- compare overlay data (milestone 3) ------------------------------ */

  const compareKey = compare.join("\u0001");

  const refreshCompare = useCallback(async (syms: string[], iv: string) => {
    const seq = ++compareSeqRef.current;
    if (syms.length === 0) {
      setCompareData({});
      return;
    }
    const results = await Promise.all(
      syms.map(async (s) => {
        const key = `${s}|${iv}`;
        const cached = compareCacheRef.current.get(key);
        if (cached) return [s, { bars: cached, error: null }] as const;
        try {
          const res = await sidecarFetch<BarsResponse>(
            `/api/bars?symbol=${encodeURIComponent(s)}&interval=${encodeURIComponent(
              iv,
            )}&limit=${DEFAULT_BARS}`,
          );
          const bars = Array.isArray(res.bars) ? res.bars : [];
          if (bars.length === 0) {
            return [s, { bars, error: res.reason ?? "provider returned no bars" }] as const;
          }
          compareCacheRef.current.set(key, bars);
          return [s, { bars, error: null }] as const;
        } catch (err) {
          return [
            s,
            { bars: [], error: err instanceof Error ? err.message : String(err) },
          ] as const;
        }
      }),
    );
    if (seq !== compareSeqRef.current) return;
    setCompareData(Object.fromEntries(results));
  }, []);

  useEffect(() => {
    /* A non-silent main reload (symbol/interval change) invalidates the
       cache: compare series are fetched once per symbol+interval and
       refreshed together with the main series. */
    compareCacheRef.current.clear();
    const syms = compareKey ? compareKey.split("\u0001") : [];
    void refreshCompare(syms, interval);
  }, [compareKey, interval, symbol, refreshCompare]);

  /* -- bar replay (milestone 3) ---------------------------------------- */

  const applyReplayCursor = useCallback(
    (value: number) => {
      const len = barsRef.current.length;
      const clamped = Math.max(0, Math.min(Math.max(0, len - 1), Math.floor(value)));
      replayIdxRef.current = clamped;
      setReplayIndex(clamped);
      fitPriceToVisible(priceRef.current, barsRef.current, timeRef.current, 0.08, clamped);
      schedule();
    },
    [schedule],
  );

  const toggleReplay = useCallback(() => {
    if (replayOn) {
      setReplayOn(false);
      setReplayPlaying(false);
      priceTouchedRef.current = false;
      fitPriceToVisible(priceRef.current, barsRef.current, timeRef.current);
      schedule();
      return;
    }
    const len = barsRef.current.length;
    const start = Math.max(
      0,
      Math.min(Math.max(0, len - 1), Math.floor(timeRef.current.range().from)),
    );
    replayIdxRef.current = start;
    setReplayIndex(start);
    setReplayPlaying(false);
    setReplayOn(true);
    if (len > 0) {
      priceTouchedRef.current = false;
      fitPriceToVisible(priceRef.current, barsRef.current, timeRef.current, 0.08, start);
    }
    schedule();
  }, [replayOn, schedule]);

  useEffect(() => {
    if (!replayOn || !replayPlaying) return;
    let raf = 0;
    let last = performance.now();
    let acc = 0;
    const step = (now: number) => {
      const dt = Math.max(0, now - last);
      last = now;
      acc += (dt / 1000) * REPLAY_BARS_PER_SEC * replaySpeed;
      const advance = Math.floor(acc);
      const len = barsRef.current.length;
      if (advance > 0 && len > 0) {
        acc -= advance;
        const next = Math.min(len - 1, replayIdxRef.current + advance);
        replayIdxRef.current = next;
        setReplayIndex(next);
        if (next >= len - 1) {
          setReplayPlaying(false);
          return;
        }
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [replayOn, replayPlaying, replaySpeed]);

  /* -- indicator alerts (milestone 3) ---------------------------------- */

  useEffect(() => {
    if (alertRules.length === 0 || bars.length === 0) return;
    const fires: { rule: AlertRule; barT: number | null }[] = [];
    const nextFired = { ...firedRef.current };
    const barTimes = bars.map((b) => b.t);
    for (const rule of alertRules) {
      const inst = instances.find((i) => i.id === rule.instanceId);
      if (!inst) continue;
      const def = indicatorById(inst.indicator);
      if (!def) continue;
      const result = def.compute(bars, inst.params);
      const plot = result.plots.find((p) => p.key === rule.plotKey);
      if (!plot) continue;
      const out = evaluateAlertRule(plot.data, rule, nextFired[rule.id] ?? null, {
        barTimes,
        nowMs: Date.now(),
        cooldownMs: ALERT_COOLDOWN_MS,
      });
      if (out.fired) {
        nextFired[rule.id] = out.state;
        fires.push({ rule, barT: out.crossingBarT });
      }
    }
    if (fires.length === 0) return;
    firedRef.current = nextFired;
    saveAlertStore(symbol, { rules: alertRules, fired: nextFired });
    const stamp = Date.now();
    const entries = fires.map((f, i) => ({
      id: `${f.rule.id}-${f.barT ?? "x"}-${stamp}-${i}`,
      text: `${f.rule.indicator} · ${f.rule.plotLabel} ${
        f.rule.op === "crossesAbove" ? "crosses above" : "crosses below"
      } ${f.rule.value}`,
      title: f.barT != null ? new Date(f.barT).toISOString() : "bar time unavailable",
    }));
    setAlertLog((prev) => [...entries, ...prev].slice(0, 20));
    for (const f of fires) {
      toast.warn(
        `Alert · ${f.rule.indicator}`,
        `${f.rule.plotLabel} ${
          f.rule.op === "crossesAbove" ? "crossed above" : "crossed below"
        } ${f.rule.value}`,
      );
    }
  }, [bars, instances, alertRules, symbol]);

  useEffect(() => {
    saveAlertStore(symbol, { rules: alertRules, fired: firedRef.current });
  }, [symbol, alertRules]);

  /* -- layout persistence (milestone 3) -------------------------------- */

  useEffect(() => {
    if (skipPersistRef.current) {
      /* One run after Reset: the store was just cleared — do not re-save
         the default state over the empty key. */
      skipPersistRef.current = false;
      return;
    }
    saveLayout(symbol, {
      interval,
      chartType,
      priceMode,
      showVolume,
      indicators: instances,
      drawings,
      compareSymbols: compare,
    });
  }, [symbol, interval, chartType, priceMode, showVolume, instances, drawings, compare]);

  const resetLayout = useCallback(() => {
    clearLayout(symbol);
    skipPersistRef.current = true;
    setInterval(initialInterval);
    setChartType(initialType);
    setPriceMode("linear");
    setShowVolume(true);
    setInstances([]);
    setDrawings([]);
    setCompare([]);
    setCompareInput("");
    setDrawTool(null);
    pendingTrendRef.current = null;
    setSettingsFor(null);
    setReplayOn(false);
    setReplayPlaying(false);
    setAlertRules([]);
    setAlertLog([]);
    firedRef.current = {};
    saveAlertStore(symbol, { rules: [], fired: {} });
    priceTouchedRef.current = false;
    fitAll(false);
  }, [symbol, initialInterval, initialType, fitAll]);

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
       Hline commits on the first click; trend/fib commit on the second. */
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
              setDrawings((prev) =>
                drawTool === "fib"
                  ? addFib(prev, p1, { index, price })
                  : addTrend(prev, p1, { index, price }),
              );
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

  const removeIndicator = (id: string) => {
    setInstances((prev) => prev.filter((i) => i.id !== id));
    /* Alerts belong to the instance — drop them so no orphan rule lingers. */
    setAlertRules((prev) => prev.filter((r) => r.instanceId !== id));
  };

  const toggleIndicator = (id: string) =>
    setInstances((prev) =>
      prev.map((i) => (i.id === id ? { ...i, visible: !i.visible } : i)),
    );

  const setParam = (id: string, key: string, value: number | string) =>
    setInstances((prev) =>
      prev.map((i) => (i.id === id ? { ...i, params: { ...i.params, [key]: value } } : i)),
    );

  /** Arm/disarm a drawing tool; starting one cancels any pending point. */
  const toggleTool = (tool: "hline" | "trend" | "fib") => {
    pendingTrendRef.current = null;
    setDrawTool((cur) => (cur === tool ? null : tool));
    setTfOpen(false);
    setTypeOpen(false);
  };

  /* -- compare + alert handlers ---------------------------------------- */

  const addCompare = () => {
    const s = compareInput.trim();
    if (!s) return;
    setCompare((prev) => (prev.includes(s) ? prev : [...prev, s]));
    setCompareInput("");
  };

  const removeCompare = (s: string) =>
    setCompare((prev) => prev.filter((x) => x !== s));

  const settingsResult = useMemo(
    () => (settingsInstance && settingsDef ? settingsDef.compute(bars, settingsInstance.params) : null),
    [settingsInstance, settingsDef, bars],
  );
  const settingsRules = alertRules.filter((r) => r.instanceId === (settingsInstance?.id ?? ""));

  const addAlertRule = () => {
    if (!settingsInstance || !settingsResult) return;
    const plot = settingsResult.plots[0];
    if (!plot) return;
    const levels = settingsResult.levels ?? [];
    const fallback =
      levels.length > 0 ? levels[levels.length - 1] : lastFinite(plot.data) ?? 0;
    setAlertRules((prev) => [
      ...prev,
      {
        id: alertRuleId(),
        instanceId: settingsInstance.id,
        indicator: settingsDef?.name ?? settingsInstance.indicator,
        plotKey: plot.key,
        plotLabel: plot.label,
        op: "crossesAbove",
        value: fallback,
      },
    ]);
  };

  const setAlertRule = (id: string, patch: Partial<AlertRule>) =>
    setAlertRules((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  const removeAlertRule = (id: string) =>
    setAlertRules((prev) => prev.filter((r) => r.id !== id));

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
          <button
            type="button"
            className={`sm-chart__btn sm-chart__btn--tool sm-chart__btn--fib${
              drawTool === "fib" ? " is-active" : ""
            }`}
            data-testid="sm-chart-draw-fib"
            aria-pressed={drawTool === "fib"}
            aria-label="Fibonacci retracement tool — click two anchors; Esc cancels"
            title="Fibonacci retracement (Esc cancels)"
            onClick={() => toggleTool("fib")}
          >
            FIB
          </button>
        </div>

        <div className="sm-chart__seg sm-chart__compare">
          <input
            value={compareInput}
            onChange={(e) => setCompareInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addCompare();
              }
            }}
            placeholder="+ Compare"
            aria-label="Compare symbol — type a symbol and press Enter"
            title="Add a comparison symbol (percent-normalized line)"
            data-testid="sm-chart-compare-add"
            className="sm-chart__compare-input"
            spellCheck={false}
          />
        </div>
        {compare.map((sym, i) => {
          const entry = compareData[sym];
          const failed = !!entry && (!!entry.error || entry.bars.length === 0);
          return (
            <span
              key={sym}
              className={`sm-chart__chip${failed ? " is-warn" : ""}`}
              data-testid={`sm-chart-compare-chip-${sym}`}
              style={{ color: COMPARE_COLOR_TOKENS[i % COMPARE_COLOR_TOKENS.length] }}
              title={
                failed
                  ? `Compare ${sym} failed — ${entry?.error ?? "no data"}`
                  : entry
                    ? `Compare ${sym} (percent change)`
                    : `Compare ${sym} — loading…`
              }
            >
              {sym}
              <button
                type="button"
                className="sm-chart__chip-x"
                aria-label={`Remove compare ${sym}`}
                onClick={() => removeCompare(sym)}
              >
                ×
              </button>
            </span>
          );
        })}

        <button
          type="button"
          className={`sm-chart__btn${replayOn ? " is-active" : ""}`}
          data-testid="sm-chart-replay-toggle"
          aria-pressed={replayOn}
          title="Bar replay — replays the loaded window only"
          onClick={toggleReplay}
        >
          ↻ Replay
        </button>

        <button
          type="button"
          className="sm-chart__btn"
          data-testid="sm-chart-reset-layout"
          title="Reset chart layout to defaults (clears the saved layout)"
          onClick={resetLayout}
        >
          Reset
        </button>

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

      {replayOn && !compact && (
        <div
          className="sm-chart__replay"
          role="group"
          aria-label="Bar replay transport — loaded window only"
        >
          <button
            type="button"
            className="sm-chart__btn"
            data-testid="sm-chart-replay-play"
            aria-pressed={replayPlaying}
            disabled={bars.length === 0}
            title={replayPlaying ? "Pause" : "Play (2 bars/sec × speed)"}
            onClick={() => setReplayPlaying((v) => !v)}
          >
            {replayPlaying ? "❚❚" : "▶"}
          </button>
          {([1, 2, 5] as const).map((s) => (
            <button
              key={s}
              type="button"
              className={`sm-chart__btn${replaySpeed === s ? " is-active" : ""}`}
              data-testid={`sm-chart-replay-speed-${s}x`}
              aria-pressed={replaySpeed === s}
              onClick={() => setReplaySpeed(s)}
            >
              {s}×
            </button>
          ))}
          <input
            type="range"
            min={0}
            max={Math.max(0, bars.length - 1)}
            step={1}
            value={replayIndex}
            data-testid="sm-chart-replay-slider"
            aria-label={`Bar replay cursor — bar ${Math.min(
              replayIndex + 1,
              Math.max(1, bars.length),
            )} of ${bars.length} (loaded window only)`}
            title="Bar replay — loaded window only"
            className="sm-chart__replay-slider"
            onChange={(e) => {
              setReplayPlaying(false);
              applyReplayCursor(Number(e.target.value));
            }}
          />
          <span className="sm-chart__replay-pos" aria-hidden>
            {bars.length === 0 ? "0/0" : `${replayIndex + 1}/${bars.length}`}
          </span>
        </div>
      )}

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
          <div className="sm-chart__settings-section">
            <span className="sm-chart__menu-title">Alerts</span>
            {settingsRules.map((rule) => (
              <div key={rule.id} className="sm-chart__alert-rule">
                <select
                  value={rule.plotKey}
                  aria-label="Alert plot"
                  onChange={(e) => {
                    const plot = settingsResult?.plots.find((p) => p.key === e.target.value);
                    setAlertRule(rule.id, {
                      plotKey: e.target.value,
                      plotLabel: plot?.label ?? e.target.value,
                    });
                  }}
                >
                  {(settingsResult?.plots ?? []).map((p) => (
                    <option key={p.key} value={p.key}>
                      {p.label}
                    </option>
                  ))}
                </select>
                <select
                  value={rule.op}
                  aria-label="Alert operator"
                  onChange={(e) =>
                    setAlertRule(rule.id, { op: e.target.value as AlertRule["op"] })
                  }
                >
                  <option value="crossesAbove">above</option>
                  <option value="crossesBelow">below</option>
                </select>
                <input
                  type="number"
                  step="any"
                  value={rule.value}
                  aria-label="Alert value"
                  onChange={(e) => setAlertRule(rule.id, { value: Number(e.target.value) })}
                />
                <button
                  type="button"
                  className="sm-chart__tab-x"
                  aria-label="Remove alert"
                  onClick={() => removeAlertRule(rule.id)}
                >
                  ×
                </button>
              </div>
            ))}
            <button
              type="button"
              className="sm-chart__btn"
              data-testid="sm-chart-alert-add"
              disabled={(settingsResult?.plots.length ?? 0) === 0}
              title={
                settingsResult && settingsResult.plots.length > 0
                  ? "Add an alert on a plot of this indicator"
                  : "This indicator exposes no plottable series"
              }
              onClick={addAlertRule}
            >
              + Alert
            </button>
          </div>
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
          }${drawTool ? `; ${drawTool} tool active — Esc cancels` : ""}${
            replayOn ? "; bar replay active — loaded window only" : ""
          }. Click a drawing to delete it when no drawing tool is active.`}
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
        {alertLog.length > 0 && (
          <div
            className="sm-chart__alerts"
            data-testid="sm-chart-alert-list"
            role="log"
            aria-label="Indicator alerts (latest 20)"
          >
            {alertLog.map((entry) => (
              <div key={entry.id} className="sm-chart__alert-item" title={entry.title}>
                {entry.text}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default Chart;
