/**
 * MIS — Multi Indicator Scan.
 *
 * Sweeps every selected market with the engine's 23-indicator weighted
 * consensus and surfaces the highest-conviction symbols in a sortable
 * table. The + button adds a row's symbol to the WATCH function. A
 * second tab exposes per-market calibration (weights + indicator
 * thresholds) backed by `/api/mis/config`.
 *
 * Intentionally NOT a trade bot — there is no SL/TP, no order routing,
 * no PORT linkage. MIS only ranks. The user decides what to do next.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
} from "react";
import {
  Card,
  CardBody,
  CardHeader,
  ChangeText,
  DataGrid,
  type DataGridColumn,
  DeltaChip,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  ProgressBar,
  Skeleton,
  StatCard,
  Tabs,
} from "@/design-system";
import {
  MIS_FALLBACK_TFS,
  MIS_MARKETS,
  MIS_MARKET_LABELS,
  fetchMisConfig,
  fetchMisIndicators,
  fetchMisMarkets,
  fetchMisScanProgress,
  runMisScan,
  saveMisConfig,
  type MisConfigBundle,
  type MisMarket,
  type MisMarketSummary,
  type MisScanProgress,
  type MisScanResult,
  type MisScanRow,
} from "@/lib/mis";
import { addSymbol } from "@/lib/watchlist";
import { toast } from "@/lib/toast";
import { navigate } from "@/lib/router";
import { useWorkspace } from "@/lib/workspace";
import { formatMissing, formatNumber, formatPercent, formatPrice } from "@/lib/format";
import { FunctionControlGroup, LoadStatePill } from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

const TOP_N_OPTIONS: number[] = [25, 50, 100, 200, 500];

type TabId = "results" | "settings";

const TABS = [
  { id: "results" as TabId, label: "Sonuçlar" },
  { id: "settings" as TabId, label: "Ayarlar" },
];

const SIGNAL_TONE: Record<string, "positive" | "negative" | "warn" | "muted"> = {
  STRONG_BUY: "positive",
  BUY: "positive",
  STRONG_SELL: "negative",
  SELL: "negative",
  NEUTRAL: "muted",
};

function dirTone(dir: string): "positive" | "negative" | "muted" {
  if (dir === "LONG") return "positive";
  if (dir === "SHORT") return "negative";
  return "muted";
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function MISPane({ code }: FunctionPaneProps) {
  const [tab, setTab] = useState<TabId>("results");
  // Default: scan crypto + equity. User can toggle every market.
  const [selected, setSelected] = useState<Set<MisMarket>>(
    () => new Set<MisMarket>(["CRYPTO", "EQUITY"]),
  );
  // Per-market TF subset override. `null/undefined` for a market = use the
  // saved tf_set from the config (which is the full ZAK matrix by default).
  // Setting an explicit value = scan only those TFs this run.
  const [tfSets, setTfSets] = useState<Partial<Record<MisMarket, string[]>>>({});
  const [topN, setTopN] = useState<number>(50);
  // Defaults are deliberately permissive: multi-TF aggregation dilutes single
  // strong TFs, so a 30% floor would hide most rows. The user can opt back in.
  const [onlySignals, setOnlySignals] = useState<boolean>(false);
  const [minConfidence, setMinConfidence] = useState<number>(0);
  const [maxPerMarket, setMaxPerMarket] = useState<number | null>(null);

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<MisScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Inline validation message surfaced next to the market selector (in
  // addition to the toast) when the user runs with no markets selected.
  const [marketError, setMarketError] = useState<string | null>(null);
  const [progressNote, setProgressNote] = useState<string>("");

  // Live progress snapshot polled from ``GET /api/mis/scan/progress``
  // every ~250ms while a scan is in flight. The ref + interval id pair
  // is the standard React idiom for "interval that survives re-renders
  // but stops cleanly on unmount or scan completion".
  const [progress, setProgress] = useState<MisScanProgress | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current != null) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  // Hard-stop the poll on unmount — otherwise a stale interval keeps
  // fetching after the user navigates away. Belt-and-suspenders to the
  // ``finally`` in ``run`` below.
  useEffect(() => stopPolling, [stopPolling]);

  // Per-row drill-down: which symbols have their full indicator breakdown
  // expanded. Keyed by ``market:symbol`` so two markets can't collide.
  const [expandedRows, setExpandedRows] = useState<Set<string>>(() => new Set());
  const toggleExpanded = useCallback((key: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);
  // Mirror the expanded set into a ref so the grid's ``expand`` column can read
  // the *current* state without listing ``expandedRows`` in the ``cols``
  // useMemo deps. Keeping it out of the deps means toggling a row no longer
  // rebuilds the entire columns array → the memoized DataGrid stays stable and
  // only the cheap chevron / breakdown re-render. ``ExpandToggle`` (the chevron)
  // lives inside the memoized grid, which won't re-render on toggle, so it
  // subscribes to the change signal below via ``useSyncExternalStore`` and reads
  // its open state from the ref — that keeps its aria-expanded / icon in lockstep
  // with state without forcing a full grid re-render. The breakdown panels keep
  // reading ``expandedRows`` state directly (they live outside the grid and
  // re-render on the normal state change).
  const expandedRowsRef = useRef(expandedRows);
  const expandSubsRef = useRef<Set<() => void>>(new Set());
  const subscribeExpanded = useCallback((cb: () => void) => {
    expandSubsRef.current.add(cb);
    return () => {
      expandSubsRef.current.delete(cb);
    };
  }, []);
  useEffect(() => {
    expandedRowsRef.current = expandedRows;
    // Notify chevron subscribers after the state ref is fresh so their
    // useSyncExternalStore snapshot reads the new value.
    expandSubsRef.current.forEach((cb) => cb());
  }, [expandedRows]);
  const isRowExpanded = useCallback((key: string) => expandedRowsRef.current.has(key), []);

  const [markets, setMarkets] = useState<MisMarketSummary[]>([]);
  const [indicators, setIndicators] = useState<string[]>([]);
  const [config, setConfig] = useState<MisConfigBundle | null>(null);
  const [configMarket, setConfigMarket] = useState<MisMarket>("CRYPTO");
  const [configDirty, setConfigDirty] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);

  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);

  // Boot: pull markets + indicators + config in parallel.
  useEffect(() => {
    Promise.all([
      fetchMisMarkets().then((r) => setMarkets(r.markets)).catch(() => setMarkets([])),
      fetchMisIndicators().then(setIndicators).catch(() => setIndicators([])),
      fetchMisConfig().then(setConfig).catch(() => setConfig(null)),
    ]);
  }, []);

  // Quick math for the KPI strip.
  const totalUniverse = useMemo(() => {
    if (!markets.length) return 0;
    return markets
      .filter((m) => selected.has(m.key))
      .reduce(
        (acc, m) => acc + (maxPerMarket ? Math.min(maxPerMarket, m.size) : m.size),
        0,
      );
  }, [markets, selected, maxPerMarket]);

  const rows: MisScanRow[] = result?.rows ?? [];
  const longs = rows.filter((r) => r.direction === "LONG").length;
  const shorts = rows.filter((r) => r.direction === "SHORT").length;
  const medianConfidence = useMemo(
    () => median(rows.map((r) => r.confidence).filter((v) => Number.isFinite(v))),
    [rows],
  );
  const medianScore = useMemo(
    () => median(rows.map((r) => Math.abs(r.normalized_score ?? r.weighted_score))),
    [rows],
  );
  const completed = useMemo(() => {
    if (!result) return 0;
    return Object.values(result.per_market_counts).reduce(
      (acc, b) => acc + (b.completed ?? 0),
      0,
    );
  }, [result]);
  const skipped = useMemo(() => {
    if (!result) return 0;
    return Object.values(result.per_market_counts).reduce(
      (acc, b) => acc + (b.skipped ?? 0),
      0,
    );
  }, [result]);

  const toggleMarket = (m: MisMarket) => {
    setMarketError(null);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(m)) next.delete(m);
      else next.add(m);
      return next;
    });
  };

  const allOn = () => {
    setMarketError(null);
    setSelected(new Set(MIS_MARKETS));
  };
  const noneOn = () => setSelected(new Set());

  const run = useCallback(async () => {
    if (selected.size === 0) {
      // Inline ``role="alert"`` (rendered next to the market selector) is the
      // single immediate announcement here — no toast, otherwise screen readers
      // announce the same message twice.
      setMarketError("En az bir piyasa seçmelisiniz");
      return;
    }
    setMarketError(null);
    setRunning(true);
    setError(null);
    setProgressNote(
      `${selected.size} piyasa × ~${totalUniverse} sembol taranıyor — birkaç saniye / dakika sürebilir`,
    );
    // Seed an optimistic snapshot so the bar appears at 0% the instant
    // the user clicks "Tara" — the first real poll lands ~250ms later.
    setProgress({
      status: "running",
      total: totalUniverse,
      completed: 0,
      in_flight: 0,
      skipped: 0,
      markets: Array.from(selected),
      started_at: new Date().toISOString(),
      elapsed_ms: 0,
      current_symbol: "",
      current_market: "",
      percent: 0,
    });
    stopPolling();
    pollTimerRef.current = setInterval(async () => {
      try {
        const snap = await fetchMisScanProgress();
        setProgress(snap);
        // Stop polling once the backend reports a terminal state. The
        // POST will resolve a beat later with the actual rows.
        if (snap.status === "done" || snap.status === "error") {
          stopPolling();
        }
      } catch {
        // Swallow transient network errors — the poll will retry on the
        // next tick. We deliberately don't surface a toast here because
        // the user only cares whether the POST eventually returns.
      }
    }, 250);
    try {
      // Only attach explicit per-market TF overrides — leave the others
      // empty so the backend uses the saved config tf_set.
      const tfSetPayload: Partial<Record<MisMarket, string[]>> = {};
      for (const m of selected) {
        const override = tfSets[m];
        if (override && override.length) tfSetPayload[m] = override;
      }
      const r = await runMisScan({
        markets: Array.from(selected),
        tf_set: tfSetPayload,
        top_n: topN,
        min_confidence: minConfidence,
        only_signals: onlySignals,
        max_symbols_per_market: maxPerMarket,
      });
      setResult(r);
      const totalProcessed = Object.values(r.per_market_counts).reduce(
        (a, b) => a + (b.completed ?? 0) + (b.skipped ?? 0),
        0,
      );
      toast.success(
        "MIS tamamlandı",
        `${totalProcessed} sembol tarandı · ${r.rows.length} eşleşme`,
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      toast.error("MIS başarısız", msg);
    } finally {
      setRunning(false);
      setProgressNote("");
      stopPolling();
    }
  }, [
    selected,
    tfSets,
    topN,
    minConfidence,
    onlySignals,
    maxPerMarket,
    totalUniverse,
    stopPolling,
  ]);

  const handleAddToWatch = useCallback(async (sym: string) => {
    if (!sym) return;
    try {
      const next = await addSymbol(sym);
      toast.success(
        "Watchlist'e eklendi",
        `${sym} → ${next.length} sembol`,
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error("Eklenemedi", msg);
    }
  }, []);

  const jumpToDES = useCallback(
    (sym: string) => {
      setFocusedTarget("DES", sym);
      navigate(`/symbol/${sym}/DES`);
    },
    [setFocusedTarget],
  );

  const cols = useMemo<DataGridColumn<MisScanRow>[]>(
    () => [
      {
        key: "rank",
        header: "#",
        width: 36,
        numeric: true,
        render: (_r, idx) => (
          <span className="scan-rank">{String(idx + 1).padStart(2, "0")}</span>
        ),
      },
      {
        key: "add",
        header: "",
        width: 32,
        render: (r) => (
          <button
            type="button"
            className="btn btn--accent u-btn-mini"
            title={`${r.symbol} → Watchlist`}
            aria-label={`Add ${r.symbol} to watchlist`}
            onClick={(e) => {
              e.stopPropagation();
              handleAddToWatch(r.symbol);
            }}
            style={{ width: 22, height: 22, padding: 0, fontSize: 13, lineHeight: 1 }}
          >
            +
          </button>
        ),
      },
      {
        key: "symbol",
        header: "Sembol",
        width: 120,
        render: (r) => (
          <button
            type="button"
            className="u-symbol-link"
            onClick={(e) => {
              e.stopPropagation();
              jumpToDES(r.symbol);
            }}
            title="DES paneline aç"
          >
            {r.symbol}
          </button>
        ),
      },
      {
        key: "market",
        header: "Piyasa",
        width: 86,
        render: (r) => (
          <Pill tone="muted" variant="soft" withDot={false}>
            {MIS_MARKET_LABELS[r.market] ?? r.market}
          </Pill>
        ),
      },
      {
        key: "direction",
        header: "Yön",
        width: 84,
        render: (r) => (
          <Pill
            tone={dirTone(r.direction)}
            variant="soft"
            withDot={false}
            arrow={
              r.direction === "LONG"
                ? "up"
                : r.direction === "SHORT"
                  ? "down"
                  : null
            }
          >
            {r.direction}
          </Pill>
        ),
      },
      {
        key: "signal",
        header: "Sinyal",
        width: 110,
        render: (r) => {
          const tone = SIGNAL_TONE[r.final_signal] ?? "muted";
          return (
            <Pill tone={tone} variant="soft" withDot={false}>
              {r.final_signal.replace("_", " ")}
            </Pill>
          );
        },
      },
      {
        key: "confidence",
        header: "Güven %",
        width: 90,
        numeric: true,
        render: (r) => <ConfidenceBar value={r.confidence} />,
      },
      {
        key: "score",
        header: "Skor",
        width: 84,
        numeric: true,
        // Show the TF-count-invariant normalized score (range [-1, +1]).
        // This is also the sort key — keeps the displayed metric and the
        // visual order consistent across markets with different TF
        // success rates.
        render: (r) => (
          <span className="terminal-grid-numeric">
            <ChangeText
              value={r.normalized_score ?? r.weighted_score}
              digits={3}
            />
          </span>
        ),
      },
      {
        key: "change",
        header: "Δ today",
        width: 92,
        numeric: true,
        render: (r) =>
          r.change_pct == null ? (
            <span className="u-text-mute">{formatMissing}</span>
          ) : (
            <span className="terminal-grid-numeric">
              <DeltaChip value={r.change_pct} format="percent" fractionDigits={2} />
            </span>
          ),
      },
      {
        key: "last",
        header: "Son",
        width: 96,
        numeric: true,
        render: (r) =>
          r.last == null ? (
            <span className="u-text-mute">{formatMissing}</span>
          ) : (
            <span className="u-mono-xs terminal-grid-numeric">{formatPrice(r.last)}</span>
          ),
      },
      {
        key: "per_tf",
        header: "TF Konsensüs",
        render: (r) => <PerTfStrip row={r} />,
      },
      {
        key: "top",
        header: "İlk 3 Indikatör",
        render: (r) => (
          <span className="u-inline-flex u-gap-4 u-flex-wrap">
            {r.top_indicators.map((t, i) =>
              t.name ? (
                <span
                  key={`${r.symbol}-${i}-${t.name}`}
                  style={chipStyle}
                  title={`${t.reason ?? ""}${t.tf ? ` · ${t.tf}` : ""}`}
                >
                  {t.name}
                  <span style={{ marginLeft: 4, opacity: 0.6 }}>
                    {(t.signal ?? "").replace("STRONG_", "S")}
                  </span>
                  {t.tf ? (
                    <span style={{ marginLeft: 4, opacity: 0.5 }}>{t.tf}</span>
                  ) : null}
                </span>
              ) : null,
            )}
          </span>
        ),
      },
      {
        key: "expand",
        header: "",
        width: 32,
        align: "center",
        render: (r) => {
          const rowKey = `${r.market}:${r.symbol}`;
          const n = r.indicator_breakdown?.length ?? 0;
          return (
            <ExpandToggle
              rowKey={rowKey}
              symbol={r.symbol}
              count={n}
              subscribe={subscribeExpanded}
              isOpen={isRowExpanded}
              onToggle={toggleExpanded}
            />
          );
        },
      },
    ],
    [handleAddToWatch, jumpToDES, subscribeExpanded, isRowExpanded, toggleExpanded],
  );

  // ── Settings handlers ────────────────────────────────────────────────

  const cfg = config?.markets?.[configMarket];

  const updateWeight = (ind: string, value: number) => {
    if (!config) return;
    setConfigDirty(true);
    setConfig({
      ...config,
      markets: {
        ...config.markets,
        [configMarket]: {
          ...config.markets[configMarket],
          indicator_weights: {
            ...config.markets[configMarket].indicator_weights,
            [ind]: value,
          },
        },
      },
    });
  };

  const updateThreshold = (ind: string, key: string, value: number | string) => {
    if (!config) return;
    setConfigDirty(true);
    setConfig({
      ...config,
      markets: {
        ...config.markets,
        [configMarket]: {
          ...config.markets[configMarket],
          indicator_thresholds: {
            ...config.markets[configMarket].indicator_thresholds,
            [ind]: {
              ...(config.markets[configMarket].indicator_thresholds[ind] ?? {}),
              [key]: value,
            },
          },
        },
      },
    });
  };

  const updateConsensus = (key: keyof MisConfigBundle["markets"][MisMarket]["consensus"], value: number) => {
    if (!config) return;
    setConfigDirty(true);
    setConfig({
      ...config,
      markets: {
        ...config.markets,
        [configMarket]: {
          ...config.markets[configMarket],
          consensus: {
            ...config.markets[configMarket].consensus,
            [key]: value,
          },
        },
      },
    });
  };

  const updateTfWeight = (tf: string, value: number) => {
    if (!config) return;
    setConfigDirty(true);
    setConfig({
      ...config,
      markets: {
        ...config.markets,
        [configMarket]: {
          ...config.markets[configMarket],
          tf_weights: {
            ...(config.markets[configMarket].tf_weights ?? {}),
            [tf]: value,
          },
        },
      },
    });
  };

  const toggleTfSet = (tf: string) => {
    if (!config) return;
    const current = config.markets[configMarket]?.tf_set ?? [];
    const next = current.includes(tf)
      ? current.filter((t) => t !== tf)
      : [...current, tf];
    setConfigDirty(true);
    setConfig({
      ...config,
      markets: {
        ...config.markets,
        [configMarket]: {
          ...config.markets[configMarket],
          tf_set: next,
        },
      },
    });
  };

  const updateUniverseOverride = (text: string) => {
    if (!config) return;
    setConfigDirty(true);
    const list = text
      .split(/[\s,]+/g)
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    setConfig({
      ...config,
      markets: {
        ...config.markets,
        [configMarket]: {
          ...config.markets[configMarket],
          universe_override: list,
        },
      },
    });
  };

  const saveConfig = async () => {
    if (!config) return;
    setSavingConfig(true);
    try {
      const saved = await saveMisConfig(config);
      setConfig(saved);
      setConfigDirty(false);
      toast.success("Ayarlar kaydedildi", `${MIS_MARKET_LABELS[configMarket]} kalibrasyonu güncellendi`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error("Kayıt başarısız", msg);
    } finally {
      setSavingConfig(false);
    }
  };

  const resetConfig = async () => {
    setSavingConfig(true);
    try {
      // PUT an empty markets bundle so the backend rebuilds with defaults.
      // The backend `_merge_market_config` happily replaces missing fields,
      // so we send `{}` per market and trust the round-trip to return a
      // fully-formed bundle.
      const emptyMarkets = Object.fromEntries(
        MIS_MARKETS.map((m) => [m, {}]),
      ) as unknown as MisConfigBundle["markets"];
      const fresh = await saveMisConfig({
        version: 1,
        markets: emptyMarkets,
      });
      setConfig(fresh);
      setConfigDirty(false);
      toast.success("Sıfırlandı", "Tüm piyasalar varsayılan kalibrasyona alındı");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error("Sıfırlama başarısız", msg);
    } finally {
      setSavingConfig(false);
    }
  };

  // ── Render ───────────────────────────────────────────────────────────

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Multi Indicator Scan"
          subtitle={`${selected.size}/${MIS_MARKETS.length} piyasa · TOP ${topN}`}
          help={
            <div className="fn-help-grid fn-help-grid__hint fn-help-grid__hint-mute">
              <strong>MIS · Multi Indicator Scan</strong>
              <span>
                23 indikatörlü konsensüs ile seçtiğin piyasalarda tarama yapar. Tabloda + butonuyla sembolü WATCH listesine ekleyebilirsin.
              </span>
              <span>
                "Ayarlar" sekmesinden her piyasa için indikatör ağırlıklarını, eşiklerini ve konsensüs sınırlarını ayrı ayrı kalibre edebilirsin.
              </span>
            </div>
          }
          trailing={
            <FunctionControlGroup>
              <Pill tone="accent" variant="soft" withDot={false}>
                EVREN ≈ {totalUniverse}
              </Pill>
              <Pill tone={running ? "warn" : result ? "positive" : "muted"} variant="soft" withDot>
                {running ? "TARANIYOR" : result ? "HAZIR" : "HAZIR"}
              </Pill>
              <LoadStatePill state={running ? "loading" : error ? "error" : result ? "ok" : "idle"} />
              <button
                type="button"
                className="btn btn--accent u-btn-24"
                onClick={run}
                disabled={running || selected.size === 0}
              >
                {running ? "Taranıyor…" : "Tara"}
              </button>
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <div style={{ marginBottom: 12 }}>
            <Tabs
              items={TABS}
              active={tab}
              onChange={(id) => setTab(id as TabId)}
              variant="segmented"
            />
          </div>

          {tab === "results" && (
            <ResultsTab
              markets={markets}
              selected={selected}
              toggleMarket={toggleMarket}
              allOn={allOn}
              noneOn={noneOn}
              run={run}
              marketError={marketError}
              tfSets={tfSets}
              setTfSets={setTfSets}
              topN={topN}
              setTopN={setTopN}
              onlySignals={onlySignals}
              setOnlySignals={setOnlySignals}
              minConfidence={minConfidence}
              setMinConfidence={setMinConfidence}
              maxPerMarket={maxPerMarket}
              setMaxPerMarket={setMaxPerMarket}
              running={running}
              result={result}
              progressNote={progressNote}
              progress={progress}
              error={error}
              cols={cols}
              rows={rows}
              expandedRows={expandedRows}
              longs={longs}
              shorts={shorts}
              medianScore={medianScore}
              medianConfidence={medianConfidence}
              completed={completed}
              skipped={skipped}
            />
          )}

          {tab === "settings" && (
            <SettingsTab
              configMarket={configMarket}
              setConfigMarket={setConfigMarket}
              config={config}
              cfg={cfg}
              indicators={indicators}
              configDirty={configDirty}
              savingConfig={savingConfig}
              updateWeight={updateWeight}
              updateThreshold={updateThreshold}
              updateConsensus={updateConsensus}
              updateTfWeight={updateTfWeight}
              toggleTfSet={toggleTfSet}
              updateUniverseOverride={updateUniverseOverride}
              saveConfig={saveConfig}
              resetConfig={resetConfig}
              markets={markets}
            />
          )}
        </PaneBody>
        <PaneFooter>
          <span>indikatör · 23</span>
          <span>piyasa · {selected.size}/{MIS_MARKETS.length}</span>
          {result && <span>tarandı · {completed}</span>}
          {result && skipped > 0 && <span>atlanan · {skipped}</span>}
          {result && <span>süre · {Math.round(result.elapsed_ms)} ms</span>}
          <span>{running ? "yürütülüyor…" : configDirty ? "kayıt bekliyor" : "hazır"}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Results tab
// ─────────────────────────────────────────────────────────────────────────

function ResultsTab(props: {
  markets: MisMarketSummary[];
  selected: Set<MisMarket>;
  toggleMarket: (m: MisMarket) => void;
  allOn: () => void;
  noneOn: () => void;
  run: () => void;
  marketError: string | null;
  tfSets: Partial<Record<MisMarket, string[]>>;
  setTfSets: (next: Partial<Record<MisMarket, string[]>>) => void;
  topN: number;
  setTopN: (n: number) => void;
  onlySignals: boolean;
  setOnlySignals: (b: boolean) => void;
  minConfidence: number;
  setMinConfidence: (n: number) => void;
  maxPerMarket: number | null;
  setMaxPerMarket: (n: number | null) => void;
  running: boolean;
  result: MisScanResult | null;
  progressNote: string;
  progress: MisScanProgress | null;
  error: string | null;
  cols: DataGridColumn<MisScanRow>[];
  rows: MisScanRow[];
  expandedRows: Set<string>;
  longs: number;
  shorts: number;
  medianScore: number | null;
  medianConfidence: number | null;
  completed: number;
  skipped: number;
}) {
  const {
    markets,
    selected,
    toggleMarket,
    allOn,
    noneOn,
    run,
    marketError,
    tfSets,
    setTfSets,
    topN,
    setTopN,
    onlySignals,
    setOnlySignals,
    minConfidence,
    setMinConfidence,
    maxPerMarket,
    setMaxPerMarket,
    running,
    result,
    progressNote,
    progress,
    error,
    cols,
    rows,
    expandedRows,
    longs,
    shorts,
    medianScore,
    medianConfidence,
    completed,
    skipped,
  } = props;

  return (
    <div className="u-flex u-flex-col u-gap-14">
      <Card>
        <CardHeader
          trailing={
            <span className="u-inline-flex u-gap-6">
              <button type="button" className="btn btn--ghost u-btn-mini" onClick={allOn}>
                Tümünü seç
              </button>
              <button type="button" className="btn btn--ghost u-btn-mini" onClick={noneOn}>
                Temizle
              </button>
              <button
                type="button"
                className="btn btn--accent u-btn-mini"
                data-testid="mis-run-inline"
                onClick={run}
                disabled={running}
                aria-describedby={marketError ? "mis-market-error" : undefined}
              >
                {running ? "Taranıyor…" : "Şimdi tara"}
              </button>
            </span>
          }
        >
          Piyasa filtresi
        </CardHeader>
        <CardBody>
          {marketError && (
            <div
              id="mis-market-error"
              role="alert"
              style={{
                marginBottom: 10,
                padding: "6px 10px",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--negative)",
                background: "color-mix(in srgb, var(--negative) 12%, transparent)",
                color: "var(--negative)",
                fontSize: 11,
                fontFamily: "JetBrains Mono, monospace",
                letterSpacing: "0.03em",
              }}
            >
              {marketError}
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 8 }}>
            {MIS_MARKETS.map((m) => {
              const meta = markets.find((x) => x.key === m);
              const checked = selected.has(m);
              // ``default_tfs`` from /api/mis/markets is the authoritative
              // list (CRYPTO=12, EQUITY=4, etc.). The fallback covers the
              // first paint before that fetch returns.
              const allTfs = meta?.default_tfs ?? MIS_FALLBACK_TFS[m];
              const savedActive = meta?.active_tfs ?? allTfs;
              const userOverride = tfSets[m];
              const activeTfs = userOverride ?? savedActive;
              const activeSet = new Set(activeTfs);
              const toggleTf = (tf: string) => {
                const next = activeSet.has(tf)
                  ? activeTfs.filter((t) => t !== tf)
                  : [...activeTfs, tf];
                // Preserve the canonical TF order from the backend.
                const ordered = allTfs.filter((t) => next.includes(t));
                setTfSets({ ...tfSets, [m]: ordered });
              };
              const allOnThis = () => setTfSets({ ...tfSets, [m]: [...allTfs] });
              const allOffThis = () => setTfSets({ ...tfSets, [m]: [] });
              return (
                <div key={m} style={marketCardStyle(checked)}>
                  <label
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      cursor: "pointer",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleMarket(m)}
                    />
                    <strong style={{ fontFamily: "JetBrains Mono, monospace" }}>
                      {MIS_MARKET_LABELS[m]}
                    </strong>
                    <Pill tone="muted" variant="soft" withDot={false}>
                      {meta?.size ?? "—"} sembol
                    </Pill>
                    <span style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
                      <Pill
                        tone={activeTfs.length > 0 ? "accent" : "warn"}
                        variant="soft"
                        withDot={false}
                      >
                        {activeTfs.length}/{allTfs.length} TF
                      </Pill>
                    </span>
                  </label>
                  <fieldset
                    aria-label={`Timeframes for ${m}`}
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: 4,
                      border: 0,
                      margin: 0,
                      padding: 0,
                      minInlineSize: 0,
                      opacity: checked ? 1 : 0.55,
                      // ``disabled`` already makes the inner buttons inert, so
                      // drop ``pointerEvents: none`` (it swallowed the cursor
                      // hint) and surface a not-allowed cursor instead.
                      cursor: checked ? undefined : "not-allowed",
                    }}
                    disabled={!checked}
                    title={`ZAK ağırlıkları: ${allTfs.map((t) => `${t}=${meta?.tf_weights?.[t] ?? 50}`).join(" · ")}`}
                  >
                    {allTfs.map((tf) => {
                      const on = activeSet.has(tf);
                      const weight = meta?.tf_weights?.[tf];
                      return (
                        <button
                          key={tf}
                          type="button"
                          onClick={() => toggleTf(tf)}
                          style={tfChipStyle(on)}
                          aria-pressed={on}
                          aria-label={`Toggle ${tf} timeframe for ${m}`}
                          title={weight ? `${tf} · ZAK=${weight}` : tf}
                        >
                          {tf}
                        </button>
                      );
                    })}
                    <button
                      type="button"
                      className="btn btn--ghost u-btn-mini"
                      onClick={allOnThis}
                      style={{ marginLeft: 4 }}
                      aria-label={`Enable all timeframes for ${m}`}
                      title="Tümünü aç"
                    >
                      hepsi
                    </button>
                    <button
                      type="button"
                      className="btn btn--ghost u-btn-mini"
                      onClick={allOffThis}
                      aria-label={`Disable all timeframes for ${m}`}
                      title="Tümünü kapat"
                    >
                      hiçbiri
                    </button>
                  </fieldset>
                </div>
              );
            })}
          </div>

          <div style={{ display: "flex", gap: 12, marginTop: 12, flexWrap: "wrap" }}>
            <label style={fieldStyle}>
              <span style={fieldLabelStyle}>Üst sıra</span>
              <select
                value={topN}
                onChange={(e) => setTopN(Number(e.target.value))}
                style={selectStyle}
              >
                {TOP_N_OPTIONS.map((n) => (
                  <option key={n} value={n}>
                    TOP {n}
                  </option>
                ))}
              </select>
            </label>

            <label style={fieldStyle}>
              <span style={fieldLabelStyle}>Min güven %</span>
              <input
                type="number"
                value={minConfidence}
                min={0}
                max={100}
                step={5}
                onChange={(e) => setMinConfidence(Number(e.target.value) || 0)}
                style={inputStyle}
              />
            </label>

            <label style={fieldStyle}>
              <span style={fieldLabelStyle}>Piyasa başı max</span>
              <input
                type="number"
                value={maxPerMarket ?? ""}
                placeholder="hepsi"
                min={1}
                onChange={(e) =>
                  setMaxPerMarket(e.target.value ? Number(e.target.value) : null)
                }
                style={inputStyle}
              />
            </label>

            <label style={{ ...fieldStyle, flexDirection: "row", alignItems: "center", gap: 6, marginTop: 18 }}>
              <input
                type="checkbox"
                checked={onlySignals}
                onChange={(e) => setOnlySignals(e.target.checked)}
              />
              <span style={fieldLabelStyle}>Sadece sinyaller (NEUTRAL gizle)</span>
            </label>
          </div>
        </CardBody>
      </Card>

      {error && <Empty title="Tarama hatası" body={error} icon="!" />}

      {running && (
        <Card>
          <CardBody>
            <ScanProgressPanel
              progress={progress}
              progressNote={progressNote}
            />
          </CardBody>
        </Card>
      )}

      {result && !running && (
        <>
          <div style={kpiStripStyle}>
            <StatCard
              label="Eşleşme / Tarama"
              value={
                <span className="terminal-grid-numeric">
                  {rows.length} / {completed + skipped}
                </span>
              }
              caption={`${completed} başarılı · ${skipped} atlandı`}
              tone="neutral"
            />
            <StatCard
              label="Median güven"
              value={
                <span className="terminal-grid-numeric">
                  {formatPercent(medianConfidence, { digits: 1 })}
                </span>
              }
              caption={`min ${formatPercent(minConfidence)}`}
              tone={medianConfidence != null && medianConfidence >= 50 ? "positive" : "neutral"}
            />
            <StatCard
              label="Median skor"
              value={
                <span className="terminal-grid-numeric">
                  {formatNumber(medianScore, 3)}
                </span>
              }
              caption={`süre ${formatNumber(Math.round(result.elapsed_ms))} ms`}
              tone="neutral"
            />
            <StatCard
              label="LONG / SHORT"
              value={
                <span>
                  <span className="u-text-positive">{longs}</span>
                  <span style={{ margin: "0 6px", color: "var(--text-mute)" }}>·</span>
                  <span className="u-text-negative">{shorts}</span>
                </span>
              }
              caption={`piyasa ${result.markets.join(", ")}`}
              tone="neutral"
            />
          </div>

          <Card>
            <CardHeader
              trailing={
                <span className="u-inline-flex u-gap-6 u-flex-wrap">
                  {Object.entries(result.per_market_counts).map(([m, c]) => (
                    <Pill key={m} tone="muted" variant="soft" withDot={false}>
                      {MIS_MARKET_LABELS[m as MisMarket] ?? m} · {c.completed}/{c.requested}
                    </Pill>
                  ))}
                  {result.warnings.length > 0 && (
                    <Pill tone="warn" variant="soft" withDot>
                      {result.warnings.length} uyarı
                    </Pill>
                  )}
                </span>
              }
            >
              Tarama sonuçları
            </CardHeader>
            <CardBody>
              {rows.length === 0 ? (
                <Empty
                  title="Eşleşme yok"
                  body="Mevcut filtrelerle eşleşen sembol bulunamadı. Min. güveni düşürmeyi veya NEUTRAL'ları göstermeyi deneyin."
                />
              ) : (
                <>
                  <DataGrid
                    columns={cols}
                    rows={rows}
                    rowKey={(r) => `${r.market}:${r.symbol}`}
                    density="compact"
                    ariaLabel="Multi Indicator Scan results"
                  />
                  {rows
                    .filter((r) => expandedRows.has(`${r.market}:${r.symbol}`))
                    .map((r) => (
                      <IndicatorBreakdownPanel
                        key={`${r.market}:${r.symbol}`}
                        row={r}
                      />
                    ))}
                </>
              )}
            </CardBody>
          </Card>
        </>
      )}

      {!result && !running && !error && (
        <Empty
          title="Hazır"
          body="Piyasaları seçin ve 'Tara' butonuna basın. Tüm seçili piyasalardaki her sembol 23-indikatör konsensüsünden geçirilir."
          action={
            <button
              type="button"
              className="btn btn--accent u-btn-mini"
              data-testid="mis-empty-select-all"
              onClick={allOn}
            >
              Tüm piyasaları seç
            </button>
          }
        />
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Settings tab
// ─────────────────────────────────────────────────────────────────────────

function SettingsTab(props: {
  configMarket: MisMarket;
  setConfigMarket: (m: MisMarket) => void;
  config: MisConfigBundle | null;
  cfg: MisConfigBundle["markets"][MisMarket] | undefined;
  indicators: string[];
  configDirty: boolean;
  savingConfig: boolean;
  updateWeight: (ind: string, value: number) => void;
  updateThreshold: (ind: string, key: string, value: number | string) => void;
  updateConsensus: (key: keyof MisConfigBundle["markets"][MisMarket]["consensus"], value: number) => void;
  updateTfWeight: (tf: string, value: number) => void;
  toggleTfSet: (tf: string) => void;
  updateUniverseOverride: (text: string) => void;
  saveConfig: () => void;
  resetConfig: () => void;
  markets: MisMarketSummary[];
}) {
  const {
    configMarket,
    setConfigMarket,
    config,
    cfg,
    indicators,
    configDirty,
    savingConfig,
    updateWeight,
    updateThreshold,
    updateConsensus,
    updateTfWeight,
    toggleTfSet,
    updateUniverseOverride,
    saveConfig,
    resetConfig,
    markets,
  } = props;

  if (!config || !cfg) {
    return <Skeleton height={300} />;
  }

  return (
    <div className="u-flex u-flex-col u-gap-14">
      <Card>
        <CardHeader
          trailing={
            <span className="u-inline-flex u-gap-6">
              <button
                type="button"
                className="btn btn--ghost u-btn-mini"
                onClick={resetConfig}
                disabled={savingConfig}
                title="Tüm piyasalar için varsayılana dön"
              >
                Sıfırla
              </button>
              <button
                type="button"
                className="btn btn--accent u-btn-mini"
                onClick={saveConfig}
                disabled={!configDirty || savingConfig}
              >
                {savingConfig ? "Kaydediliyor…" : configDirty ? "Kaydet" : "Kayıtlı"}
              </button>
            </span>
          }
        >
          Piyasa kalibrasyonu
        </CardHeader>
        <CardBody>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {MIS_MARKETS.map((m) => {
              const active = configMarket === m;
              return (
                <button
                  type="button"
                  key={m}
                  onClick={() => setConfigMarket(m)}
                  className={`btn ${active ? "btn--accent" : "btn--ghost"} u-btn-mini`}
                >
                  {MIS_MARKET_LABELS[m]}
                </button>
              );
            })}
          </div>
        </CardBody>
      </Card>

      <TfCalibrationCard
        market={configMarket}
        cfg={cfg}
        marketMeta={markets.find((mm) => mm.key === configMarket)}
        updateTfWeight={updateTfWeight}
        toggleTfSet={toggleTfSet}
      />

      <Card>
        <CardHeader>Konsensüs eşikleri — {MIS_MARKET_LABELS[configMarket]}</CardHeader>
        <CardBody>
          <div style={consensusGridStyle}>
            <NumberField
              label="Güçlü Al"
              value={cfg.consensus.strong_buy_threshold}
              step={0.05}
              onChange={(v) => updateConsensus("strong_buy_threshold", v)}
            />
            <NumberField
              label="Al"
              value={cfg.consensus.buy_threshold}
              step={0.05}
              onChange={(v) => updateConsensus("buy_threshold", v)}
            />
            <NumberField
              label="Sat"
              value={cfg.consensus.sell_threshold}
              step={0.05}
              onChange={(v) => updateConsensus("sell_threshold", v)}
            />
            <NumberField
              label="Güçlü Sat"
              value={cfg.consensus.strong_sell_threshold}
              step={0.05}
              onChange={(v) => updateConsensus("strong_sell_threshold", v)}
            />
            <NumberField
              label="Çakışma oranı"
              value={cfg.consensus.conflict_ratio_threshold}
              step={0.05}
              onChange={(v) => updateConsensus("conflict_ratio_threshold", v)}
            />
            <NumberField
              label="Min aktif sinyal"
              value={cfg.consensus.min_active_signals}
              step={1}
              onChange={(v) => updateConsensus("min_active_signals", v)}
            />
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          trailing={
            <Pill tone="muted" variant="soft" withDot={false}>
              {indicators.length} indikatör
            </Pill>
          }
        >
          İndikatör ağırlıkları ve eşikleri
        </CardHeader>
        <CardBody>
          <div style={indicatorListStyle}>
            {indicators.map((ind) => (
              <IndicatorRow
                key={ind}
                name={ind}
                weight={cfg.indicator_weights[ind] ?? 0}
                thresholds={cfg.indicator_thresholds[ind] ?? {}}
                onWeightChange={(v) => updateWeight(ind, v)}
                onThresholdChange={(k, v) => updateThreshold(ind, k, v)}
              />
            ))}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          trailing={
            <Pill tone="muted" variant="soft" withDot={false}>
              {cfg.universe_override.length || "varsayılan"}
            </Pill>
          }
        >
          Evren geçersiz kıl — {MIS_MARKET_LABELS[configMarket]}
        </CardHeader>
        <CardBody>
          <span style={{ ...fieldLabelStyle, display: "block", marginBottom: 6 }}>
            Boş bırakırsanız varsayılan evren kullanılır. Aksi halde virgülle/boşlukla ayrılmış semboller (örn. <code>BTCUSDT ETHUSDT SOLUSDT</code>).
          </span>
          <textarea
            value={cfg.universe_override.join(" ")}
            onChange={(e) => updateUniverseOverride(e.target.value)}
            rows={3}
            placeholder="boş → varsayılan evren"
            spellCheck={false}
            style={textareaStyle}
          />
        </CardBody>
      </Card>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Small helpers
// ─────────────────────────────────────────────────────────────────────────

/**
 * Drill-down panel — the full per-indicator breakdown for one row. Shows
 * each indicator's signal direction + score + reason, plus the per-TF
 * consensus detail, so the user can see *why* the aggregate is bullish or
 * bearish. Rendered below the grid when the row's expand toggle is open.
 */
function IndicatorBreakdownPanel({ row }: { row: MisScanRow }) {
  const breakdown = row.indicator_breakdown ?? [];
  return (
    <section
      data-testid={`mis-breakdown-${row.symbol}`}
      aria-label={`Indicator breakdown for ${row.symbol}`}
      style={{
        marginTop: 8,
        padding: "10px 12px",
        background: "var(--surface-2)",
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-md)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 8,
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 12,
        }}
      >
        <strong>{row.symbol}</strong>
        <Pill tone={dirTone(row.direction)} variant="soft" withDot={false}>
          {row.direction}
        </Pill>
        <span style={fieldLabelStyle}>
          {breakdown.length} indikatör · {row.tf_count_with_signal}/{row.tf_count_scanned} TF sinyalli
        </span>
      </div>
      {breakdown.length === 0 ? (
        <span className="u-text-mute u-text-10">{formatMissing}</span>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(120px, 0.8fr) 80px 70px minmax(140px, 1.4fr)",
            gap: "2px 12px",
            fontSize: 11,
            fontFamily: "JetBrains Mono, monospace",
          }}
        >
          <span style={fieldLabelStyle}>İndikatör</span>
          <span style={fieldLabelStyle}>Sinyal</span>
          <span style={{ ...fieldLabelStyle, textAlign: "right" }}>Skor</span>
          <span style={fieldLabelStyle}>Gerekçe</span>
          {breakdown.map((ind, i) => {
            const tone = SIGNAL_TONE[ind.signal] ?? "muted";
            return [
              <strong key={`${ind.name}-${i}-n`}>{ind.name}</strong>,
              <span key={`${ind.name}-${i}-s`}>
                <Pill tone={tone} variant="soft" withDot={false}>
                  {ind.signal.replace("_", " ")}
                </Pill>
              </span>,
              <span
                key={`${ind.name}-${i}-sc`}
                className="terminal-grid-numeric"
                style={{ textAlign: "right" }}
              >
                <ChangeText value={ind.score} digits={3} />
              </span>,
              <span
                key={`${ind.name}-${i}-r`}
                className="u-text-mute"
                style={{
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={ind.reason}
              >
                {ind.reason || formatMissing}
              </span>,
            ];
          })}
        </div>
      )}
    </section>
  );
}

function PerTfStrip({ row }: { row: MisScanRow }) {
  if (!row.per_tf || row.per_tf.length === 0) {
    return <span className="u-text-mute u-text-10">—</span>;
  }
  return (
    <span style={{ display: "inline-flex", flexWrap: "wrap", gap: 3 }}>
      {row.per_tf.map((t) => {
        const skipped = !!t.skipped;
        const tone =
          skipped
            ? "muted"
            : t.direction === "LONG"
              ? "positive"
              : t.direction === "SHORT"
                ? "negative"
                : "neutral";
        const title = skipped
          ? `${t.tf} · atlandı (${t.skipped})`
          : `${t.tf} · ${t.direction} · güven=${t.confidence.toFixed(0)} · ZAK=${t.weight} · katkı=${t.contribution.toFixed(3)}`;
        const bg =
          tone === "positive"
            ? "color-mix(in srgb, var(--positive) 18%, transparent)"
            : tone === "negative"
              ? "color-mix(in srgb, var(--negative) 18%, transparent)"
              : tone === "neutral"
                ? "color-mix(in srgb, var(--text-mute) 14%, transparent)"
                : "var(--surface-3)";
        const fg =
          tone === "positive"
            ? "var(--positive)"
            : tone === "negative"
              ? "var(--negative)"
              : "var(--text-secondary)";
        return (
          <span
            key={`${row.symbol}-${t.tf}`}
            title={title}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 2,
              height: 16,
              padding: "0 4px",
              borderRadius: 3,
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 9.5,
              letterSpacing: "0.02em",
              background: bg,
              color: fg,
              opacity: skipped ? 0.45 : 1,
            }}
          >
            <span>{t.tf}</span>
            <span style={{ opacity: 0.65 }}>
              {skipped ? "—" : `${t.confidence.toFixed(0)}`}
            </span>
          </span>
        );
      })}
    </span>
  );
}

function TfCalibrationCard({
  market,
  cfg,
  marketMeta,
  updateTfWeight,
  toggleTfSet,
}: {
  market: MisMarket;
  cfg: MisConfigBundle["markets"][MisMarket];
  marketMeta?: MisMarketSummary;
  updateTfWeight: (tf: string, value: number) => void;
  toggleTfSet: (tf: string) => void;
}) {
  // ``default_tfs`` is the canonical, ordered list (1m→1d for CRYPTO,
  // etc.). The user can toggle which TFs are active but cannot invent
  // new ones — weights only exist for what the backend supports.
  const allTfs = marketMeta?.default_tfs ?? Object.keys(cfg.tf_weights ?? {});
  const activeSet = new Set(cfg.tf_set ?? allTfs);
  return (
    <Card>
      <CardHeader
        trailing={
          <Pill tone="muted" variant="soft" withDot={false}>
            {activeSet.size}/{allTfs.length} aktif · ZAK
          </Pill>
        }
      >
        Zaman dilimleri ve ZAK ağırlıkları — {MIS_MARKET_LABELS[market]}
      </CardHeader>
      <CardBody>
        <div style={{ fontSize: 10, color: "var(--text-mute)", marginBottom: 8 }}>
          Her sembol seçili TF'lerde ayrı ayrı 23-indikatör konsensüsünden geçer. Final
          skor = Σ (yön × güven% × ZAK%). ZAK ağırlığı arttıkça o TF'nin etkisi artar.
          (TBV3 ile aynı agregasyon.)
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
            gap: 8,
          }}
        >
          {allTfs.map((tf) => {
            const w = cfg.tf_weights?.[tf] ?? 50;
            const on = activeSet.has(tf);
            return (
              <div
                key={tf}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 4,
                  padding: "8px 10px",
                  background: on
                    ? "color-mix(in srgb, var(--accent) 6%, var(--surface-2))"
                    : "var(--surface-2)",
                  border: `1px solid ${on ? "var(--accent)" : "var(--border-subtle)"}`,
                  borderRadius: "var(--radius-md)",
                }}
              >
                <label
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    cursor: "pointer",
                  }}
                >
                  <input type="checkbox" checked={on} onChange={() => toggleTfSet(tf)} />
                  <strong style={{ fontFamily: "JetBrains Mono, monospace" }}>{tf}</strong>
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={fieldLabelStyle}>ZAK</span>
                  <input
                    type="number"
                    value={w}
                    min={0}
                    max={100}
                    step={1}
                    onChange={(e) => updateTfWeight(tf, Number(e.target.value))}
                    style={{ ...inputStyle, width: 56 }}
                  />
                </label>
              </div>
            );
          })}
        </div>
      </CardBody>
    </Card>
  );
}

/**
 * The per-row drill-down chevron. Lives inside the memoized DataGrid, which
 * does *not* re-render when only ``expandedRows`` changes (so the columns array
 * can stay referentially stable for perf). To keep its ``aria-expanded`` + icon
 * in lockstep with state regardless, it subscribes to the expand change signal
 * via ``useSyncExternalStore`` and reads its open flag from the live ref — so it
 * re-renders on toggle without rebuilding ``cols`` or the whole grid body.
 */
function ExpandToggle({
  rowKey,
  symbol,
  count,
  subscribe,
  isOpen,
  onToggle,
}: {
  rowKey: string;
  symbol: string;
  count: number;
  subscribe: (cb: () => void) => () => void;
  isOpen: (key: string) => boolean;
  onToggle: (key: string) => void;
}) {
  const open = useSyncExternalStore(
    subscribe,
    () => isOpen(rowKey),
    () => isOpen(rowKey),
  );
  return (
    <button
      type="button"
      className="btn btn--ghost u-btn-mini"
      aria-expanded={open}
      aria-label={`Show indicator breakdown for ${symbol}`}
      title={`${symbol} · ${count} indikatör detayı`}
      disabled={count === 0}
      onClick={(e) => {
        e.stopPropagation();
        onToggle(rowKey);
      }}
      style={{ width: 22, height: 22, padding: 0, fontSize: 11, lineHeight: 1 }}
    >
      {open ? "▾" : "▸"}
    </button>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const v = Math.max(0, Math.min(100, value || 0));
  const rounded = Math.round(v);
  return (
    <span
      className="scan-conf-bar terminal-grid-numeric"
      role="meter"
      aria-label={`Confidence ${rounded}%`}
      aria-valuenow={rounded}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <span aria-hidden className="scan-conf-bar__fill" style={{ ["--u-pct" as string]: `${v}%` }} />
      <span className="scan-conf-bar__label">{formatNumber(rounded)}</span>
    </span>
  );
}

/**
 * Live MIS scan progress — header note + wide-thin progress bar +
 * footer counter line. Replaces the old Skeleton shimmer block. The
 * counter format ``{completed} / {total}`` mirrors how the
 * ``per_market_counts`` chip reads in the results card, so the user
 * sees consistent language pre/post scan.
 */
function ScanProgressPanel({
  progress,
  progressNote,
}: {
  progress: MisScanProgress | null;
  progressNote: string;
}) {
  const pct = progress?.percent ?? 0;
  const total = progress?.total ?? 0;
  const completed = progress?.completed ?? 0;
  const inFlight = progress?.in_flight ?? 0;
  const skippedSoFar = progress?.skipped ?? 0;
  const elapsedSec = progress?.elapsed_ms
    ? Math.round(progress.elapsed_ms / 100) / 10
    : null;

  // Stop the clock as soon as the backend reports a terminal state so
  // the user gets a stable final % to look at while the POST resolves.
  const headline =
    total > 0
      ? `${formatNumber(completed)} / ${formatNumber(total)} sembol tarandı`
      : "Tarama hazırlanıyor…";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {progressNote && (
        <span
          style={{
            fontSize: 11,
            color: "var(--text-secondary)",
            fontFamily: "JetBrains Mono, monospace",
            letterSpacing: "0.04em",
          }}
        >
          {progressNote}
        </span>
      )}
      <ProgressBar value={pct} height={14} ariaLabel="MIS scan progress" />
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          fontSize: 10,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          color: "var(--text-mute)",
          fontFamily: "JetBrains Mono, monospace",
        }}
      >
        <span>{headline}</span>
        <span>
          {inFlight > 0 && <span style={{ marginRight: 10 }}>uçuşta {inFlight}</span>}
          {skippedSoFar > 0 && (
            <span style={{ marginRight: 10 }}>atlanan {skippedSoFar}</span>
          )}
          {elapsedSec != null && elapsedSec > 0 && <span>{elapsedSec.toFixed(1)}s</span>}
        </span>
      </div>
    </div>
  );
}

function NumberField({
  label,
  value,
  step,
  onChange,
}: {
  label: string;
  value: number;
  step?: number;
  onChange: (v: number) => void;
}) {
  return (
    <label style={fieldStyle}>
      <span style={fieldLabelStyle}>{label}</span>
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        step={step ?? 0.05}
        onChange={(e) => onChange(Number(e.target.value))}
        style={inputStyle}
      />
    </label>
  );
}

function IndicatorRow({
  name,
  weight,
  thresholds,
  onWeightChange,
  onThresholdChange,
}: {
  name: string;
  weight: number;
  thresholds: Record<string, number | string>;
  onWeightChange: (v: number) => void;
  onThresholdChange: (k: string, v: number | string) => void;
}) {
  const [open, setOpen] = useState(false);
  const keys = Object.keys(thresholds);
  return (
    <div style={indicatorRowStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <strong style={{ fontFamily: "JetBrains Mono, monospace", minWidth: 130 }}>
          {name}
        </strong>
        <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={fieldLabelStyle}>Ağırlık</span>
          <input
            type="number"
            value={weight}
            step={0.1}
            min={0}
            onChange={(e) => onWeightChange(Number(e.target.value))}
            style={{ ...inputStyle, width: 70 }}
          />
        </label>
        {keys.length > 0 && (
          <button
            type="button"
            className="btn btn--ghost u-btn-mini"
            onClick={() => setOpen((o) => !o)}
            style={{ marginLeft: "auto" }}
          >
            {open ? "Eşikleri gizle" : `Eşikler (${keys.length})`}
          </button>
        )}
      </div>
      {open && (
        <div style={thresholdGridStyle}>
          {keys.map((k) => {
            const raw = thresholds[k];
            const isNumeric = typeof raw === "number";
            return (
              <label key={k} style={fieldStyle}>
                <span style={fieldLabelStyle}>{k}</span>
                <input
                  type={isNumeric ? "number" : "text"}
                  value={String(raw ?? "")}
                  step={isNumeric ? 0.1 : undefined}
                  onChange={(e) =>
                    onThresholdChange(k, isNumeric ? Number(e.target.value) : e.target.value)
                  }
                  style={inputStyle}
                />
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Styles (token-based; no hardcoded hex) ──────────────────────────────

function marketCardStyle(checked: boolean): CSSProperties {
  return {
    display: "flex",
    flexDirection: "column",
    gap: 6,
    padding: "10px 12px",
    background: checked ? "color-mix(in srgb, var(--accent) 8%, var(--surface-2))" : "var(--surface-2)",
    border: `1px solid ${checked ? "var(--accent)" : "var(--border-subtle)"}`,
    borderRadius: "var(--radius-md)",
    transition: "background 120ms, border-color 120ms",
  };
}

function tfChipStyle(on: boolean): CSSProperties {
  return {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    minWidth: 30,
    height: 20,
    padding: "0 6px",
    fontFamily: "JetBrains Mono, monospace",
    fontSize: 10,
    letterSpacing: "0.03em",
    borderRadius: 4,
    border: `1px solid ${on ? "var(--accent)" : "var(--border-subtle)"}`,
    background: on
      ? "color-mix(in srgb, var(--accent) 18%, transparent)"
      : "var(--surface-3)",
    color: on ? "var(--accent-strong, var(--accent))" : "var(--text-secondary)",
    cursor: "pointer",
  };
}

const chipStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  height: 18,
  padding: "0 6px",
  background: "var(--surface-3)",
  border: "1px solid var(--border-subtle)",
  borderRadius: 4,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  color: "var(--text-secondary)",
  letterSpacing: "0.03em",
};

const kpiStripStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const fieldStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
  minWidth: 0,
};

const fieldLabelStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
};

const inputStyle: CSSProperties = {
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
  height: 24,
  padding: "0 6px",
  width: 90,
};

const selectStyle: CSSProperties = {
  ...inputStyle,
  width: "auto",
  minWidth: 80,
};

const textareaStyle: CSSProperties = {
  width: "100%",
  resize: "vertical",
  background: "var(--surface-2)",
  color: "var(--text-primary)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
  padding: 8,
  outline: "none",
};

const consensusGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 12,
};

const indicatorListStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
};

const indicatorRowStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
  padding: "8px 10px",
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
};

const thresholdGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
  gap: 8,
  paddingLeft: 140,
  paddingTop: 4,
};
