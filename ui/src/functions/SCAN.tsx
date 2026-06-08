/**
 * SCAN — Scanner Agent (Phase A + Phase B + Phase C/D enrichers).
 *
 * Bloomberg-grade redesign: filter rail with criteria chips, dense result
 * table with in-cell mini sparklines + volume hints, KPI summary strip,
 * and a contextual analysis drawer with phase decomposition.
 *
 * Lets the trader phrase a coarse intent ("crypto opportunities", "energy
 * pull-back", "EUR/USD overextended") and runs the ZAK-weighted scan
 * server-side. Results are clickable — clicking a row pushes the symbol
 * into a DES pane (or, in linked mode, into all sibling panes).
 */
import {
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import {
  Card,
  CardBody,
  CardHeader,
  ChangeText,
  CommandTile,
  DataGrid,
  type DataGridColumn,
  DeltaChip,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  Sparkline,
  StatCard,
} from "@/design-system";
import {
  listUniverses,
  runScan,
  type ScanResult,
  type ScanRow,
  type UniverseSummary,
} from "@/lib/scanner";
import { useAbortableFetch } from "@/lib/useAbortableFetch";
import { navigate } from "@/lib/router";
import { useWorkspace } from "@/lib/workspace";
import {
  FunctionControlGroup,
  LoadStatePill,
  RowLimitControl,
} from "./function-controls";
import {
  TOP_N_LIMITS,
  type TopNLimit,
  usePersistentOption,
} from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

const SAMPLE_INTENTS = [
  "crypto opportunities high conviction",
  "S&P 500 pullbacks near 200-day MA",
  "EUR/USD overextended",
  "energy commodities trending up",
];

const PRESET_SCREENS: Array<{
  code: string;
  description: string;
  intent: string;
}> = [
  { code: "CRY-HC", description: "High-conviction crypto", intent: "crypto opportunities high conviction" },
  { code: "SPX-PB", description: "S&P pullbacks @ 200d", intent: "S&P 500 pullbacks near 200-day MA" },
  { code: "FX-OEX", description: "EUR/USD overextended", intent: "EUR/USD overextended" },
  { code: "ENG-UP", description: "Energy momentum", intent: "energy commodities trending up" },
];

type SortKey = "score" | "confidence" | "change_pct";

function sortableHeader(
  label: string,
  key: SortKey,
  active: SortKey,
  setActive: (k: SortKey) => void,
) {
  const isActive = key === active;
  return (
    <button
      type="button"
      onClick={() => setActive(key)}
      className={`scan-sort-btn${isActive ? " scan-sort-btn--active" : ""}`}
      title={`Sort by ${label}`}
    >
      {label}
      {isActive && <span className="scan-sort-arrow">↓</span>}
    </button>
  );
}

function deterministicTrend(seed: string, n = 22): number[] {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  const out: number[] = [];
  let v = 50;
  for (let i = 0; i < n; i++) {
    h = (h * 1664525 + 1013904223) >>> 0;
    const x = ((h & 0xff) / 255 - 0.5) * 14;
    v = Math.max(15, Math.min(85, v + x));
    out.push(v);
  }
  return out;
}

function buildColumns(
  sortKey: SortKey,
  setSortKey: (k: SortKey) => void,
  activeSymbol: string | null,
  onJumpDES: (sym: string) => void,
  maxScore: number,
): DataGridColumn<ScanRow>[] {
  return [
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
      key: "symbol",
      header: "Symbol",
      width: 110,
      render: (r) => {
        const isActive = activeSymbol === r.symbol;
        return (
          <button
            type="button"
            onDoubleClick={(e) => {
              // Stop the event bubbling to the DataGrid's onRowDoubleClick,
              // which would otherwise fire jumpToDES a second time.
              e.stopPropagation();
              if (r.symbol) onJumpDES(r.symbol);
            }}
            onKeyDown={(e) => {
              // Keyboard parity with double-click: Enter on the focused
              // symbol launches DES for that symbol. The button is the
              // per-row launch affordance and is tab-reachable.
              if ((e.key === "Enter" || e.key === " ") && r.symbol) {
                e.preventDefault();
                e.stopPropagation();
                onJumpDES(r.symbol);
              }
            }}
            className={`scan-symbol${isActive ? " scan-symbol--active" : ""}`}
            title="Enter / double-click → DES"
            aria-label={`Open ${r.symbol} in DES`}
          >
            {r.symbol}
          </button>
        );
      },
    },
    {
      key: "asset_class",
      header: "Class",
      width: 76,
      render: (r) =>
        r.asset_class ? (
          <span className="scan-class">{r.asset_class}</span>
        ) : (
          "—"
        ),
    },
    {
      key: "direction",
      header: "Dir",
      width: 78,
      render: (r) => {
        if (!r.direction) return <span className="u-text-mute">—</span>;
        const tone =
          r.direction === "LONG"
            ? "positive"
            : r.direction === "SHORT"
              ? "negative"
              : "muted";
        return (
          <Pill
            tone={tone}
            variant="soft"
            withDot={false}
            arrow={r.direction === "LONG" ? "up" : r.direction === "SHORT" ? "down" : null}
          >
            {r.direction}
          </Pill>
        );
      },
    },
    {
      key: "confidence",
      header: sortableHeader("Conf %", "confidence", sortKey, setSortKey),
      numeric: true,
      width: 84,
      render: (r) => {
        if (r.confidence == null) return <span className="u-text-mute">—</span>;
        return <ConfidenceBar value={r.confidence} />;
      },
    },
    {
      key: "score",
      header: sortableHeader("Score", "score", sortKey, setSortKey),
      numeric: true,
      width: 96,
      render: (r) => {
        const v = r.score ?? 0;
        const ratio = maxScore > 0 ? Math.min(1, Math.abs(v) / maxScore) : 0;
        const tone = v > 0 ? "positive" : v < 0 ? "negative" : "neutral";
        return (
          <span className="u-inline-flex u-items-center u-gap-6">
            <Sparkline
              values={[0, ratio * (v >= 0 ? 1 : -1), ratio * (v >= 0 ? 1.4 : -1.4), ratio * (v >= 0 ? 1 : -1)]}
              width={28}
              height={14}
              tone={tone}
            />
            <ChangeText value={v} digits={3} />
          </span>
        );
      },
    },
    {
      key: "change_pct",
      header: sortableHeader("Δ today", "change_pct", sortKey, setSortKey),
      numeric: true,
      width: 92,
      render: (r) => {
        const v = r.fine?.quote?.change_pct;
        if (v == null) return <span className="u-text-mute">—</span>;
        return <DeltaChip value={v} format="percent" fractionDigits={2} />;
      },
    },
    {
      key: "timeframes",
      header: "TFs",
      render: (r) => {
        const tfs = r.timeframes ?? [];
        if (!tfs.length) {
          return (
            <span className="u-text-mute u-text-10">
              {r.skipped ?? "—"}
            </span>
          );
        }
        return (
          <span className="u-inline-flex u-gap-4 u-flex-wrap">
            {tfs.slice(0, 4).map((tf) => (
              <span key={tf} className="scan-tf-chip">
                {tf}
              </span>
            ))}
            {tfs.length > 4 && (
              <span className="scan-tf-chip u-text-mute">+{tfs.length - 4}</span>
            )}
          </span>
        );
      },
    },
  ];
}

function sortRows(rows: ScanRow[], key: SortKey): ScanRow[] {
  const score = (r: ScanRow): number => {
    if (key === "confidence") return r.confidence ?? -Infinity;
    if (key === "change_pct") {
      const v = r.fine?.quote?.change_pct;
      return v == null ? -Infinity : Math.abs(v);
    }
    return Math.abs(r.score ?? 0);
  };
  return [...rows].sort((a, b) => score(b) - score(a));
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function SCANPane({ code }: FunctionPaneProps) {
  const [intent, setIntent] = useState(SAMPLE_INTENTS[0]);
  const [universe, setUniverse] = useState<string>("");
  const [topN, setTopN] = usePersistentOption<TopNLimit>(
    "showme.scan-topn",
    TOP_N_LIMITS,
    20,
  );
  const [phaseC, setPhaseC] = useState(true);
  const [phaseD, setPhaseD] = useState(true);
  const [universes, setUniverses] = useState<UniverseSummary[]>([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openSymbol, setOpenSymbol] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);
  // Bundle D / ABORT-01. Outer guard so a navigation away mid-scan aborts
  // the in-flight `runScan()` instead of resolving into a setState-after-
  // unmount warning. Also auto-cancels a previous run if the user hits Run
  // again while one is still pending.
  const scanFetch = useAbortableFetch();
  const universeFetch = useAbortableFetch();

  const sortedRows = useMemo(
    () => (result ? sortRows(result.rows, sortKey) : []),
    [result, sortKey],
  );

  const longs = sortedRows.filter((r) => r.direction === "LONG").length;
  const shorts = sortedRows.filter((r) => r.direction === "SHORT").length;
  const medianConfidence = useMemo(
    () =>
      median(
        sortedRows.map((r) => r.confidence ?? null).filter((v): v is number => v != null),
      ),
    [sortedRows],
  );
  const medianChange = useMemo(
    () =>
      median(
        sortedRows
          .map((r) => r.fine?.quote?.change_pct ?? null)
          .filter((v): v is number => v != null),
      ),
    [sortedRows],
  );
  // UA-HIGH-12 / UA-HIGH-18: stack-safe; sortedRows can be 3000+ on full-universe scan.
  const maxScore = useMemo(
    () => {
      let m = 0;
      for (const r of sortedRows) {
        const v = Math.abs(r.score ?? 0);
        if (v > m) m = v;
      }
      return m;
    },
    [sortedRows],
  );
  const universeSize = useMemo(() => {
    const u = universes.find((x) => x.key === result?.universe_key);
    return u?.size ?? null;
  }, [universes, result?.universe_key]);

  const cols = useMemo(
    () =>
      buildColumns(sortKey, setSortKey, openSymbol, (sym) => jumpToDES(sym), maxScore),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sortKey, openSymbol, maxScore],
  );

  // Drawer keyboard navigation: ←/→ between rows, ⌘↩ Open DES, Esc close.
  useEffect(() => {
    if (!openSymbol || sortedRows.length === 0) return;
    const onKey = (e: KeyboardEvent) => {
      const idx = sortedRows.findIndex((r) => r.symbol === openSymbol);
      if (idx === -1) return;
      if (e.key === "Escape") {
        e.preventDefault();
        setOpenSymbol(null);
      } else if (e.key === "ArrowLeft" && idx > 0) {
        e.preventDefault();
        setOpenSymbol(sortedRows[idx - 1].symbol);
      } else if (e.key === "ArrowRight" && idx < sortedRows.length - 1) {
        e.preventDefault();
        setOpenSymbol(sortedRows[idx + 1].symbol);
      } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        jumpToDES(sortedRows[idx].symbol);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openSymbol, sortedRows]);

  useEffect(() => {
    universeFetch
      .run((signal) => listUniverses(signal))
      .then((u) => {
        if (universeFetch.isMounted()) setUniverses(u);
      })
      .catch(() => {
        if (universeFetch.isMounted()) setUniverses([]);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const run = async (overrides?: {
    universe?: string;
    phaseC?: boolean;
    phaseD?: boolean;
  }) => {
    // Round 24 MEDIUM — early-exit on rapid re-trigger. ⌘Enter from
    // composer + Run button click within one tick used to fire two
    // scans simultaneously.
    if (running) return;
    // Optional overrides let callers (e.g. "Reset & retry") scan with
    // freshly-reset values instead of the stale render-closure state —
    // the setState calls above haven't committed yet when run() fires.
    const effUniverse = overrides?.universe ?? universe;
    const effPhaseC = overrides?.phaseC ?? phaseC;
    const effPhaseD = overrides?.phaseD ?? phaseD;
    setRunning(true);
    setError(null);
    setResult(null);
    setOpenSymbol(null);
    try {
      const phases = ["A", "B"];
      if (effPhaseC) phases.push("C");
      if (effPhaseD) phases.push("D");
      const r = await scanFetch.run((signal) =>
        runScan(
          {
            intent,
            universe: effUniverse || undefined,
            top_n: topN,
            phases,
            fine_top_k: effPhaseC ? Math.min(topN, 8) : undefined,
          },
          signal,
        ),
      );
      if (!scanFetch.isMounted()) return;
      setResult(r);
    } catch (err) {
      if (!scanFetch.isMounted()) return;
      // AbortError is the expected path when the user navigates away or
      // hits Run again — swallow it so we don't paint a misleading error.
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (scanFetch.isMounted()) setRunning(false);
    }
  };

  const onRowClick = (row: ScanRow) => {
    if (row.skipped || !row.symbol) return;
    setOpenSymbol(row.symbol === openSymbol ? null : row.symbol);
  };

  const jumpToDES = (sym: string) => {
    setFocusedTarget("DES", sym);
    navigate(`/symbol/${sym}/DES`);
  };

  const phasesLabel = useMemo(() => {
    const out = ["A", "B"];
    if (phaseC) out.push("C");
    if (phaseD) out.push("D");
    return out.join("·");
  }, [phaseC, phaseD]);

  const activeFilters: Array<{ id: string; label: string; onRemove?: () => void }> = [];
  if (universe) {
    activeFilters.push({
      id: "universe",
      label: `UNIV · ${universe}`,
      onRemove: () => setUniverse(""),
    });
  }
  if (phaseC) activeFilters.push({ id: "phaseC", label: "PHASE C · FINE", onRemove: () => setPhaseC(false) });
  if (phaseD) activeFilters.push({ id: "phaseD", label: "PHASE D · RISK", onRemove: () => setPhaseD(false) });
  activeFilters.push({ id: "topn", label: `TOP · ${topN}` });
  activeFilters.push({ id: "sort", label: `SORT · ${sortKey.toUpperCase()}` });

  const matchedTotal = sortedRows.length;
  const universeTotal = universeSize ?? "—";

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Scanner Agent"
          subtitle={result ? `${result.universe_key} · ${phasesLabel}` : `Phase ${phasesLabel}`}
          trailing={
            <FunctionControlGroup>
              <Pill
                tone="accent"
                variant="soft"
                withDot={false}
              >
                MATCHED {matchedTotal} / {universeTotal}
              </Pill>
              <Pill
                tone={running ? "warn" : result ? "positive" : "muted"}
                variant="soft"
                withDot
              >
                {running ? "SCANNING" : result ? "READY" : "IDLE"}
              </Pill>
              <Pill tone="muted" variant="soft" withDot={false}>
                BY {sortKey.toUpperCase()} ↓
              </Pill>
              <RowLimitControl
                label="TOP"
                value={topN}
                onChange={(next) => setTopN(next as TopNLimit)}
                disabled={running}
              />
              <LoadStatePill state={running ? "loading" : error ? "error" : result ? "ok" : "idle"} />
              <button
                type="button"
                className="btn btn--accent u-btn-24"
                onClick={() => run()}
                disabled={running || !intent.trim()}
                aria-label="Run scan with current filters"
              >
                {running ? "Scanning..." : "Run scan"}
              </button>
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <div className="u-flex u-flex-col u-gap-14">
            <Card variant="elev-2">
              <CardHeader
                trailing={
                  <Pill tone="muted" variant="soft" withDot={false}>
                    {PRESET_SCREENS.length} SAVED
                  </Pill>
                }
              >
                Saved screens
              </CardHeader>
              <CardBody>
                <div style={presetGridStyle}>
                  {PRESET_SCREENS.map((p) => (
                    <CommandTile
                      key={p.code}
                      code={p.code}
                      description={p.description}
                      active={intent === p.intent}
                      onClick={() => setIntent(p.intent)}
                    />
                  ))}
                </div>
              </CardBody>
            </Card>

            <Card>
              <CardHeader
                trailing={
                  // Wrapper was a <span> styled as a single button while
                  // containing two real buttons that inherited nothing —
                  // visually one ghost+accent control, semantically two.
                  // Promote each child to its own visible btn class.
                  <span className="u-inline-flex u-gap-6 u-items-center">
                    <button
                      type="button"
                      className="btn btn--ghost u-btn-mini"
                      onClick={() => {
                        setIntent(SAMPLE_INTENTS[0]);
                        setUniverse("");
                        setPhaseC(true);
                        setPhaseD(true);
                        setSortKey("score");
                      }}
                      title="Reset intent, universe, phases, sort"
                    >
                      Reset
                    </button>
                    <button
                      type="button"
                      className="btn btn--accent u-btn-mini"
                      onClick={() => run()}
                      disabled={running || !intent.trim()}
                      aria-label="Apply scan filters"
                      title={
                        !intent.trim()
                          ? "Enter intent text first"
                          : running
                            ? "Scan in flight"
                            : "Run scan with current filters"
                      }
                    >
                      Apply
                    </button>
                  </span>
                }
              >
                Filter rail
              </CardHeader>
              <CardBody>
                <div className="u-flex u-flex-col u-gap-12">
                  <div style={filterChipRowStyle}>
                    {activeFilters.map((f) => (
                      <FilterChip key={f.id} label={f.label} onRemove={f.onRemove} />
                    ))}
                  </div>

                  <div>
                    <FieldLabel>Intent (NL)</FieldLabel>
                    <textarea
                      value={intent}
                      onChange={(e) => setIntent(e.target.value)}
                      rows={2}
                      spellCheck={false}
                      style={textareaStyle}
                    />
                    <div style={sampleRowStyle}>
                      {SAMPLE_INTENTS.map((s) => (
                        <button
                          key={s}
                          type="button"
                          className="btn btn--ghost u-text-10 u-mono"
                          onClick={() => setIntent(s)}
                          aria-label={`Load preset intent: ${s}`}
                        >
                          {s}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div style={twoColRowStyle}>
                    <label className="u-flex u-flex-col u-gap-4">
                      <FieldLabel>Universe (override)</FieldLabel>
                      <select
                        value={universe}
                        onChange={(e) => setUniverse(e.target.value)}
                        style={selectStyle}
                      >
                        <option value="">(auto from intent)</option>
                        {universes.map((u) => (
                          <option key={u.key} value={u.key}>
                            {u.key} · {u.size}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="u-flex u-flex-col u-gap-4">
                      <FieldLabel>Phases</FieldLabel>
                      <div className="u-flex u-gap-6 u-items-center prefs-h-28">
                        <PhaseToggle label="A+B" checked disabled />
                        <PhaseToggle
                          label="C · fine"
                          checked={phaseC}
                          onChange={() => setPhaseC((c) => !c)}
                        />
                        <PhaseToggle
                          label="D · risk"
                          checked={phaseD}
                          onChange={() => setPhaseD((d) => !d)}
                        />
                      </div>
                    </label>
                  </div>
                </div>
              </CardBody>
            </Card>

            {error && (
              <Empty
                title="Scan failed"
                body={error}
                icon="!"
                action={
                  <button
                    type="button"
                    className="btn btn--accent"
                    onClick={() => run()}
                    disabled={running}
                    aria-label="Retry the scan"
                  >
                    Retry
                  </button>
                }
              />
            )}

            {running && (
              <Card>
                <CardBody>
                  <div className="u-grid-gap-8">
                    <Skeleton height={64} />
                    <Skeleton height={20} />
                    <Skeleton height={20} />
                    <Skeleton height={20} width="80%" />
                  </div>
                </CardBody>
              </Card>
            )}

            {result && !running && (
              <>
                <div style={kpiStripStyle}>
                  <StatCard
                    label="Matched / Universe"
                    value={`${matchedTotal} / ${universeTotal}`}
                    caption={`UNIVERSE ${result.universe_key}`}
                    trend={deterministicTrend(`m-${result.universe_key}-${matchedTotal}`)}
                    tone="neutral"
                  />
                  <StatCard
                    label="Median confidence"
                    value={medianConfidence != null ? `${medianConfidence.toFixed(1)}%` : "—"}
                    caption={`SORT ${sortKey.toUpperCase()}`}
                    trend={deterministicTrend(`c-${sortKey}-${matchedTotal}`)}
                    tone="neutral"
                  />
                  <StatCard
                    label="Median Δ today"
                    value={medianChange != null ? `${medianChange >= 0 ? "+" : ""}${medianChange.toFixed(2)}%` : "—"}
                    caption={`PHASES ${phasesLabel}`}
                    trend={deterministicTrend(`d-${matchedTotal}-${phasesLabel}`)}
                    tone={medianChange == null ? "neutral" : medianChange >= 0 ? "positive" : "negative"}
                  />
                  <StatCard
                    label="Long / Short"
                    value={
                      <span>
                        <span className="u-text-positive">{longs}</span>
                        <span className="scan-divider">·</span>
                        <span className="u-text-negative">{shorts}</span>
                      </span>
                    }
                    caption={`ELAPSED ${Math.round(result.elapsed_ms)}MS`}
                    trend={deterministicTrend(`ls-${longs}-${shorts}`)}
                    tone="neutral"
                  />
                </div>

                <Card>
                  <CardHeader
                    trailing={
                      <span className="u-inline-flex u-gap-6 u-flex-wrap">
                        <Pill tone="accent" variant="soft" withDot={false}>
                          {result.asset_class}
                        </Pill>
                        {result.timeframes.length > 0 && (
                          <Pill tone="muted" variant="soft" withDot={false}>
                            {result.timeframes.join(" · ")}
                          </Pill>
                        )}
                        {result.phases.map((p) => (
                          <Pill key={p.name} tone="muted" variant="soft" withDot={false}>
                            {p.name} · {Math.round(p.elapsed_ms)}MS
                          </Pill>
                        ))}
                        {result.warnings.length > 0 && (
                          <Pill tone="warn" variant="soft" withDot>
                            {result.warnings.length} WARN
                          </Pill>
                        )}
                      </span>
                    }
                  >
                    Scan results
                  </CardHeader>
                  <CardBody>
                    {sortedRows.length === 0 ? (
                      <Empty
                        title="No matches with current filters"
                        body="Universe scanned but nothing produced a signal. Try relaxing phases or expanding the universe."
                        action={
                          <span className="u-inline-flex u-gap-6 u-items-center">
                            <button
                              type="button"
                              className="btn btn--ghost"
                              onClick={() => run()}
                              disabled={running}
                              aria-label="Retry the scan"
                            >
                              Retry
                            </button>
                            <button
                              type="button"
                              className="btn btn--accent"
                              onClick={() => {
                                setUniverse("");
                                setPhaseC(true);
                                setPhaseD(true);
                                // Pass the reset values inline — run() would
                                // otherwise read the stale pre-reset closure.
                                run({ universe: "", phaseC: true, phaseD: true });
                              }}
                              aria-label="Reset filters and retry the scan"
                            >
                              Reset & retry
                            </button>
                          </span>
                        }
                      />
                    ) : (
                      <DataGrid
                        columns={cols}
                        rows={sortedRows}
                        rowKey={(r) => r.symbol}
                        density="compact"
                        onRowClick={onRowClick}
                        onRowDoubleClick={(r) => {
                          if (!r.skipped && r.symbol) jumpToDES(r.symbol);
                        }}
                      />
                    )}
                  </CardBody>
                </Card>

                {openSymbol && (
                  <Drawer
                    row={sortedRows.find((r) => r.symbol === openSymbol)}
                    onClose={() => setOpenSymbol(null)}
                    onJumpDES={jumpToDES}
                    phaseC={phaseC}
                    hint={
                      sortedRows.length > 1
                        ? "← / → between rows · double-click row → DES · ⌘↵ Open DES · esc close"
                        : "double-click row → DES"
                    }
                  />
                )}
              </>
            )}
          </div>
        </PaneBody>
        <PaneFooter>
          <span>provider · ZAK</span>
          <span>elapsed · {result ? Math.round(result.elapsed_ms) : "—"} ms</span>
          <span>rows · {result?.rows.length ?? 0}/{topN}</span>
          <span>sort · {sortKey}</span>
          <span>phases · {phasesLabel}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function FieldLabel({ children }: { children: ReactNode }) {
  return (
    <span className="scan-field-label">{children}</span>
  );
}

function FilterChip({
  label,
  onRemove,
}: {
  label: string;
  onRemove?: () => void;
}) {
  return (
    <span className="scan-filter-chip">
      <span>{label}</span>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="scan-filter-chip-close"
          title="Remove filter"
          aria-label={`Remove filter ${label}`}
        >
          ×
        </button>
      )}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const v = Math.max(0, Math.min(100, value));
  return (
    <span className="scan-conf-bar">
      <span
        aria-hidden
        className="scan-conf-bar__fill"
        style={{ ["--u-pct" as string]: `${v}%` }}
      />
      <span className="scan-conf-bar__label">{v.toFixed(0)}</span>
    </span>
  );
}

function PhaseToggle({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange?: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onChange}
      disabled={disabled}
      className={`scan-phase-toggle${checked ? " scan-phase-toggle--active" : ""}${disabled ? " scan-phase-toggle--disabled" : ""}`}
    >
      {label}
    </button>
  );
}

function Drawer({
  row,
  onClose,
  onJumpDES,
  hint,
  phaseC,
}: {
  row?: ScanRow;
  onClose: () => void;
  onJumpDES: (sym: string) => void;
  hint?: string;
  // Phase C toggle state in the parent's filter rail. The drawer needs
  // this to tell apart "user disabled Phase C" from "Phase C ran but
  // produced no fine-scan output for this symbol" — the prior message
  // collapsed both cases into "enable the toggle and re-run", which
  // is misleading when the toggle is already enabled.
  phaseC: boolean;
}) {
  if (!row) return null;
  const fine = row.fine;
  const overlap = row.position_overlap;
  return (
    <Card variant="elev-2">
      <CardHeader
        trailing={
          <span className="u-inline-flex u-gap-6">
            <button
              type="button"
              className="btn btn--accent u-btn-mini btn--ghost"
              onClick={() => onJumpDES(row.symbol)}
            >
              Open DES
            </button>
            <button
              type="button"
              className="btn btn--ghost u-btn-mini"
              onClick={onClose}
            >
              Close
            </button>
          </span>
        }
      >
        <span className="scan-drawer-title">
          <strong className="u-text-accent">{row.symbol}</strong>
          <span className="u-text-mute u-text-11">
            {row.asset_class}
          </span>
          <Pill
            tone={
              row.direction === "LONG"
                ? "positive"
                : row.direction === "SHORT"
                  ? "negative"
                  : "muted"
            }
            variant="soft"
            withDot={false}
            arrow={
              row.direction === "LONG"
                ? "up"
                : row.direction === "SHORT"
                  ? "down"
                  : null
            }
          >
            {row.direction ?? "—"} · {row.confidence?.toFixed(0) ?? "—"}%
          </Pill>
          {overlap?.held && (
            <Pill tone="warn" variant="soft" withDot={false}>
              HELD
            </Pill>
          )}
          {overlap?.high_concentration && (
            <Pill tone="warn" variant="soft" withDot={false}>
              HIGH CONC
            </Pill>
          )}
          {fine?.overextension?.deviation_label === "OVERBOUGHT" && (
            <Pill tone="negative" variant="soft" withDot={false}>
              OVERBOUGHT
            </Pill>
          )}
          {fine?.overextension?.deviation_label === "OVERSOLD" && (
            <Pill tone="positive" variant="soft" withDot={false}>
              OVERSOLD
            </Pill>
          )}
        </span>
      </CardHeader>
      <CardBody>
        {hint && (
          <div className="scan-drawer-hint">{hint}</div>
        )}

        <div className="scan-drawer-grid">
          <div>
            <h4 style={H4}>Phase B contributions</h4>
            <ContribTable rows={row.contributions ?? []} />
          </div>
          <div>
            <h4 style={H4}>Phase C — fine scan</h4>
            {fine ? (
              <>
                {fine.quote && (
                  <div className="scan-drawer-quote">
                    <span>last</span>
                    <strong className="u-text-primary">
                      {fine.quote.last ?? "—"}
                    </strong>
                    {fine.quote.change_pct != null && (
                      <DeltaChip value={fine.quote.change_pct} format="percent" fractionDigits={2} />
                    )}
                  </div>
                )}
                {fine.overextension && (
                  <div className="scan-drawer-quote">
                    <span>z(30d):</span>
                    <strong className="u-text-primary">
                      {fine.overextension.z_score_30d.toFixed(2)}
                    </strong>
                    <Pill
                      tone={
                        fine.overextension.deviation_label === "OVERBOUGHT"
                          ? "negative"
                          : fine.overextension.deviation_label === "OVERSOLD"
                            ? "positive"
                            : "muted"
                      }
                      variant="soft"
                      withDot={false}
                    >
                      {fine.overextension.deviation_label}
                    </Pill>
                  </div>
                )}
                <ContribTable rows={fine.contributions ?? []} />
              </>
            ) : phaseC ? (
              // Phase C was enabled in this scan but the backend returned
              // no fine-scan payload for this symbol. Don't claim the
              // user disabled it — that would tell them to re-run the
              // exact run they're already looking at.
              <div className="u-text-11 u-text-mute">
                Phase C ran but produced no fine-scan output for this symbol.
              </div>
            ) : (
              // The toggle lives in the filter rail above the results,
              // not inside this drawer. Spell out where it is.
              <div className="u-text-11 u-text-mute">
                Phase C is disabled. Toggle <strong>C · fine</strong> in
                the filter rail above and re-run the scan.
              </div>
            )}
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

const H4: CSSProperties = {
  margin: "0 0 6px 0",
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
};

function ContribTable({
  rows,
}: {
  rows: NonNullable<ScanRow["contributions"]>;
}) {
  if (rows.length === 0) {
    return (
      <div className="u-text-11 u-text-mute">
        no contributions
      </div>
    );
  }
  return (
    <table className="scan-contrib-table">
      <thead>
        <tr className="u-text-mute">
          <th style={CTH}>TF</th>
          <th style={CTH}>Wt</th>
          <th style={CTH}>Dir</th>
          <th style={CTH}>Conf%</th>
          <th style={CTH}>Contrib</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => (
          <tr key={c.tf} className="scan-contrib-table__row">
            <td style={CTD}>{c.tf}</td>
            <td style={CTD} className="u-justify-end">{c.weight}</td>
            <td style={CTD}>
              <span
                className={`scan-contrib-dir scan-contrib-dir--${c.direction === "LONG" ? "long" : c.direction === "SHORT" ? "short" : "neutral"}`}
              >
                {c.direction}
              </span>
            </td>
            <td style={CTD} className="u-justify-end">
              {c.confidence.toFixed(0)}
            </td>
            <td style={CTD} className="u-justify-end">
              <ChangeText value={c.contribution} digits={3} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const CTH: CSSProperties = {
  padding: "4px 6px",
  textAlign: "left",
  fontSize: 9,
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  fontWeight: 500,
};
const CTD: CSSProperties = {
  padding: "4px 6px",
  color: "var(--text-primary)",
};

const presetGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
  gap: 8,
};

const filterChipRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
  alignItems: "center",
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

const sampleRowStyle: CSSProperties = {
  display: "flex",
  gap: 6,
  marginTop: 6,
  flexWrap: "wrap",
};

const twoColRowStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
  gap: 12,
};

const selectStyle: CSSProperties = {
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
  height: 28,
  padding: "0 8px",
};

const kpiStripStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};
