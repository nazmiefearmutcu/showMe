import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import {
  Empty,
  LogStream,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatCard,
  StatusDivider,
  StatusSection,
  type LogEntry,
} from "@/design-system";
import {
  fetchInstantEvents,
  fetchInstantStatus,
  runInstantBackfill,
  type InstantEvent,
  type InstantSourceHealth,
  type InstantStatus,
} from "@/lib/instant";
import { fetchXInstantEvents } from "@/lib/xai";
import { toast } from "@/lib/toast";
import { useXInjectStore } from "@/lib/xinject";
import { readTimezone as readTz } from "@/lib/timezone";
import { relativeTimeLabel } from "@/lib/time";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import type { FunctionPaneProps } from "./registry-types";

type LoadState = "idle" | "loading" | "ok" | "error";

const REFRESH_MS = 30_000;
const KNOWN_SPEEDUPS: Array<{ name: string; impact: string }> = [
  { name: "shared async http", impact: "Single httpx.AsyncClient with HTTP/2 keep-alive across all feeds." },
  { name: "conditional cache", impact: "ETag and Last-Modified headers skip unchanged feeds." },
  { name: "priority due ordering", impact: "Higher-priority sources poll on a tighter schedule." },
  { name: "fast lane after impact", impact: "Briefly tightens cadence after a high-score insert." },
];

export function INSTANTPane({ code }: FunctionPaneProps) {
  const [events, setEvents] = useState<InstantEvent[]>([]);
  const [xEvents, setXEvents] = useState<InstantEvent[]>([]);
  const [status, setStatus] = useState<InstantStatus | null>(null);
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [audio, setAudio] = useState(false);
  const [audioThreshold, setAudioThreshold] = useState(72);
  const [filterThreshold, setFilterThreshold] = useState(0);
  const [manualTick, setManualTick] = useState(0);
  // Bundle D / PERF-04. Background tabs paused the refresh interval; resume
  // when the tab returns. Combine with a manual nonce so Refresh + Backfill
  // buttons still bump the effect when the tab is foregrounded.
  const visTick = useVisibilityTick(REFRESH_MS);
  const tick = manualTick + visTick;
  const setTick = (next: ((prev: number) => number) | number) => {
    setManualTick((prev) => (typeof next === "function" ? next(prev) : next));
  };
  // PERF-03 P1: spoken-key set lives in a ref so the audio effect doesn't
  // depend on (and re-trigger from) its own setState. Bounded to prevent
  // unbounded growth during long trading sessions.
  //
  // UA-HIGH-14: switched from Set to Map<key, ts> for proper LRU eviction.
  // The previous Set fell back to Set iteration order (insertion order) and
  // evicted oldest first regardless of recency — which let a recently-seen
  // headline get evicted while older never-spoken keys lingered, replaying
  // the headline a second time. Now we evict the key with the lowest ts.
  const spokenRef = useRef<Map<string, number>>(new Map());
  const SPOKEN_MAX = 500;
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [regionFilter, setRegionFilter] = useState<string>("all");
  const [sourceFilter, setSourceFilter] = useState<string>("all");
  const [expandedSource, setExpandedSource] = useState<string | null>(null);
  const [backfillBusy, setBackfillBusy] = useState(false);
  const [xQueryDraft, setXQueryDraft] = useState<string>("");
  const [xQuery, setXQuery] = useState<string>("");
  const [xLoading, setXLoading] = useState(false);
  const [xWarning, setXWarning] = useState<string | null>(null);

  // Consume any pending XSEN→INSTANT injection on mount. XSEN's "→ INSTANT"
  // button stages the active query in `useXInjectStore`; we apply it here so
  // the X-merge query input lights up immediately. See FUNC-02 / UI-INT-09.
  useEffect(() => {
    const pending = useXInjectStore.getState().consumeInjection();
    if (!pending) return;
    setXQueryDraft(pending.symbol);
    setXQuery(pending.symbol);
    toast.info("INSTANT merge", `Injected "${pending.symbol}" from XSEN`);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    setError(null);
    Promise.all([fetchInstantStatus(), fetchInstantEvents(160)])
      .then(([nextStatus, nextEvents]) => {
        if (cancelled) return;
        setStatus(nextStatus);
        setEvents(nextEvents.events ?? []);
        setState("ok");
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [tick]);

  // Auto-refresh interval lives in `useVisibilityTick(REFRESH_MS)` above —
  // it pauses on hidden tabs and resumes on focus. No local setInterval.

  // X sentiment merge: when the user pins a symbol/topic, fetch INSTANT-shaped
  // events from /api/x/instant_events and refresh on the same cadence as the
  // SQLite feed below. Failures are surfaced as a warning chip, not a toast.
  useEffect(() => {
    if (!xQuery) {
      setXEvents([]);
      setXWarning(null);
      return;
    }
    let cancelled = false;
    setXLoading(true);
    fetchXInstantEvents(xQuery, { limit: 60 })
      .then((response) => {
        if (cancelled) return;
        setXEvents(response.events ?? []);
        setXWarning(response.warning ?? response.error ?? null);
      })
      .catch((err) => {
        if (cancelled) return;
        setXEvents([]);
        setXWarning(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setXLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [xQuery, tick]);

  // Bundle D / AUDIO-01. Original effect listed `events` in its deps so every
  // 30-second poll cycle re-ran the cleanup, which called
  // `window.speechSynthesis.cancel()` — wiping any utterance that was still
  // queued or speaking from a previous event batch. We split the loop and
  // the cleanup: the speak loop runs whenever inputs change (without
  // cancelling), and a separate one-shot effect cancels only on unmount or
  // when audio is toggled off.
  //
  // Use a ref to hold the latest events/threshold so the speak effect can
  // see fresh data without depending on those values.
  const audioEventsRef = useRef(events);
  const audioThresholdRef = useRef(audioThreshold);
  useEffect(() => {
    audioEventsRef.current = events;
  }, [events]);
  useEffect(() => {
    audioThresholdRef.current = audioThreshold;
  }, [audioThreshold]);

  useEffect(() => {
    if (!audio || !("speechSynthesis" in window)) return;
    const seen = spokenRef.current;
    const now = Date.now();
    for (const event of audioEventsRef.current) {
      const score = Number(event.priority_score ?? 0);
      const key = event.dedupe_key ?? event.link ?? event.title ?? "";
      if (!key || seen.has(key) || score < audioThresholdRef.current) continue;
      seen.set(key, now);
      if (seen.size > SPOKEN_MAX) {
        // UA-HIGH-14: evict the key with the oldest timestamp, not the
        // oldest *insertion* (Map preserves insertion order so they happen
        // to coincide today, but we keep this explicit in case a future
        // refresh updates ts on re-mention).
        let oldestKey: string | null = null;
        let oldestTs = Infinity;
        for (const [k, ts] of seen.entries()) {
          if (ts < oldestTs) {
            oldestTs = ts;
            oldestKey = k;
          }
        }
        if (oldestKey) seen.delete(oldestKey);
      }
      const utterance = new SpeechSynthesisUtterance(
        `${event.priority_label ?? "update"}. ${event.source_name ?? "instant"}. Score ${score}. ${event.title ?? ""}. ${event.generated_summary ?? ""}`,
      );
      utterance.rate = 1.02;
      window.speechSynthesis.speak(utterance);
    }
    // No-op cleanup on input/tick change so queued utterances keep going.
  }, [audio, tick]);

  // Single cancel point: only on unmount or when audio is explicitly toggled
  // off. Triggering this from the speak effect was the source of cut-off
  // headlines whenever a new event landed.
  useEffect(() => {
    if (audio) return;
    if ("speechSynthesis" in window) {
      try {
        window.speechSynthesis.cancel();
      } catch {
        // ignore
      }
    }
  }, [audio]);
  useEffect(() => {
    return () => {
      if ("speechSynthesis" in window) {
        try {
          window.speechSynthesis.cancel();
        } catch {
          // ignore
        }
      }
    };
  }, []);

  const sortedAll = useMemo(() => {
    const merged = [...events, ...xEvents];
    const seen = new Set<string>();
    const dedup: InstantEvent[] = [];
    for (const event of merged) {
      const key = event.dedupe_key || event.link || event.title || "";
      if (key && seen.has(key)) continue;
      if (key) seen.add(key);
      dedup.push(event);
    }
    return dedup.sort((a, b) => dateValue(b.fetched_at) - dateValue(a.fetched_at));
  }, [events, xEvents]);

  const categories = useMemo(() => uniqueValues(sortedAll, (e) => e.source_category), [sortedAll]);
  const regions = useMemo(() => uniqueValues(sortedAll, (e) => e.source_region), [sortedAll]);
  const sources = useMemo(() => uniqueValues(sortedAll, (e) => e.source_name), [sortedAll]);

  const sorted = useMemo(() => {
    return sortedAll.filter((event) => {
      if (filterThreshold > 0 && Number(event.priority_score ?? 0) < filterThreshold) return false;
      if (categoryFilter !== "all" && (event.source_category ?? "") !== categoryFilter) return false;
      if (regionFilter !== "all" && (event.source_region ?? "") !== regionFilter) return false;
      if (sourceFilter !== "all" && (event.source_name ?? "") !== sourceFilter) return false;
      return true;
    });
  }, [sortedAll, filterThreshold, categoryFilter, regionFilter, sourceFilter]);

  const breakingShown = sorted.filter((e) => Number(e.priority_score ?? 0) >= 75).length;
  const watchShown = sorted.filter((e) => {
    const s = Number(e.priority_score ?? 0);
    return s >= 58 && s < 75;
  }).length;

  const metrics = status?.health?.metrics ?? status?.performance?.metrics;
  // Flow Speed honesty: only treat speedups as live-measured when the backend
  // actually reported them. Otherwise we surface the hardcoded KNOWN_SPEEDUPS,
  // labeled as *documented* optimizations rather than live status.
  const liveSpeedups = status?.performance?.speedups ?? [];
  const speedupsAreLive = liveSpeedups.length > 0;
  const speedups = useMemo(() => {
    return speedupsAreLive ? liveSpeedups : KNOWN_SPEEDUPS;
  }, [speedupsAreLive, liveSpeedups]);
  const sourceHealth = status?.health?.sources ?? [];
  // QA-2026-05-24 (#10d): default to "loading" on first paint instead of
  // "unavailable". The pre-fetch state previously painted a misleading red
  // UNAVAILABLE pill even though backfill returns 100+ events within ~150ms.
  // Only escalate to "unavailable" once the first fetch has resolved AND
  // the backend reports no transport.
  const hasResolved = state === "ok" || state === "error";
  const transport = status?.transport ?? (hasResolved ? "unavailable" : "loading");
  const ok = Boolean(status?.ok);
  const newestAt = metrics?.newest_fetched_at ?? null;
  const stale = computeStale(newestAt);
  const streamState: "live" | "stale" | "unavailable" | "loading" = !hasResolved
    ? "loading"
    : transport === "unavailable"
      ? "unavailable"
      : stale ? "stale" : "live";
  const streamTone =
    streamState === "live"
      ? "positive"
      : streamState === "stale"
        ? "warn"
        : streamState === "loading"
          ? "neutral"
          : "negative";

  // Tail log: convert most recent events to LogEntry for the right-rail tail
  const recentTail = useMemo<LogEntry[]>(() => {
    return sorted.slice(0, 30).map((event) => {
      const score = Number(event.priority_score ?? 0);
      const level: LogEntry["level"] = score >= 75 ? "warn" : score >= 58 ? "info" : "debug";
      return {
        ts: event.fetched_at ?? event.published_at ?? new Date().toISOString(),
        level,
        source: event.source_name ?? event.source_category ?? "instant",
        message: `[${score.toFixed(0)}] ${event.title ?? "(untitled)"}`,
      };
    }).reverse();
  }, [sorted]);

  const triggerBackfill = () => {
    setBackfillBusy(true);
    setState("loading");
    runInstantBackfill(20)
      .then((res) => {
        const inserted = res.items_inserted ?? 0;
        const seen = res.items_seen ?? 0;
        const checked = res.checked_sources ?? 0;
        if (res.warning) {
          toast.warn("Backfill returned a warning", res.warning);
        } else if (inserted > 0) {
          toast.success(
            `Backfill inserted ${inserted} item${inserted === 1 ? "" : "s"}`,
            `${seen} seen across ${checked} source${checked === 1 ? "" : "s"}.`,
          );
        } else {
          toast.info(
            "Backfill complete",
            `No new items (${seen} seen across ${checked} source${checked === 1 ? "" : "s"}).`,
          );
        }
        setTick((value) => value + 1);
      })
      .catch((err) => {
        const message = err instanceof Error ? err.message : String(err);
        setError(message);
        setState("error");
        toast.error("Backfill failed", message);
      })
      .finally(() => setBackfillBusy(false));
  };

  return (
    <div className="u-pane-host--bb">
      <h2 className="u-sr-only">{code} — Instant squawk line</h2>
      <Pane>
        <PaneHeader
          code={code}
          title="Instant squawk line"
          subtitle={`${transport} · secondary data line · showing ${sorted.length} of ${sortedAll.length} events`}
          trailing={
            <div style={toolbar}>
              <Pill tone={streamTone} variant="soft" withDot>
                {streamState}
              </Pill>
              {newestAt ? (
                <Pill tone={stale ? "warn" : "positive"} variant="soft" withDot={false}>
                  {stale ? `${stale.label}` : `fresh · ${timeAgo(newestAt)}`}
                </Pill>
              ) : null}
              <label style={toggleLabel}>
                <input
                  type="checkbox"
                  checked={audio}
                  onChange={(event) => {
                    const enabled = event.target.checked;
                    setAudio(enabled);
                    if (!enabled && "speechSynthesis" in window) window.speechSynthesis.cancel();
                  }}
                />
                Audio
                {audio ? (
                  <span className="u-text-mute btn btn--ghost fn-help-grid fn-help-grid__hint fn-help-grid__hint-mute">&ge;{audioThreshold}</span>
                ) : null}
              </label>
              {audio ? (
                <label style={rangeLabel}>
                  <span>audio</span>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={audioThreshold}
                    onChange={(event) => setAudioThreshold(Number(event.target.value))}
                  />
                  <b>{audioThreshold}</b>
                </label>
              ) : null}
              <button
                type="button"
                className="btn btn--ghost u-btn-mini"
                onClick={() => setTick((value) => value + 1)}
                disabled={state === "loading"}
              >
                Refresh
              </button>
              <button
                type="button"
                className="btn btn--ghost u-btn-mini"
                onClick={triggerBackfill}
                disabled={state === "loading" || backfillBusy}
                aria-busy={backfillBusy}
              >
                {backfillBusy ? "Backfilling…" : "Backfill"}
              </button>
            </div>
          }
          help={
            <div className="fn-help-grid">
              <strong>INSTANT · secondary market-moving news line</strong>
              <span className="fn-help-grid__hint">
                Reads the auxiliary instant service through /api/instant/*. Falls back to the local
                SQLite store when the HTTP service is offline. It does not replace NI, CN, ECO, or
                other primary showMe news functions.
              </span>
              <span className="fn-help-grid__hint-mute">
                Score thresholds split: a viewer-side filter (which events appear) and a separate
                audio threshold (which trigger speech synthesis when Audio is on).
              </span>
            </div>
          }
        />
        {/* KPI ribbon */}
        <section style={kpiRibbon}>
          <StatCard
            label="Events shown"
            value={`${sorted.length} / ${sortedAll.length}`}
            caption={`refresh · ${REFRESH_MS / 1000}s`}
            tone="neutral"
          />
          <StatCard
            label="Breaking ≥75"
            value={String(breakingShown)}
            caption={`watch ${watchShown}`}
            tone={breakingShown > 0 ? "negative" : "neutral"}
          />
          <StatCard
            label="Avg latency"
            value={formatLatency(metrics?.avg_latency_seconds)}
            caption={transport}
            tone="neutral"
          />
          <StatCard
            label="Sources OK"
            value={`${sourceHealth.filter((s) => s.ok).length} / ${sourceHealth.length || "—"}`}
            caption={ok ? "service ok" : "degraded"}
            tone={ok ? "positive" : "negative"}
          />
        </section>
        <FilterStrip
          minScore={filterThreshold}
          onMinScore={setFilterThreshold}
          categories={categories}
          category={categoryFilter}
          onCategory={setCategoryFilter}
          regions={regions}
          region={regionFilter}
          onRegion={setRegionFilter}
          sources={sources}
          source={sourceFilter}
          onSource={setSourceFilter}
          breakingShown={breakingShown}
          watchShown={watchShown}
          onClear={() => {
            setFilterThreshold(0);
            setCategoryFilter("all");
            setRegionFilter("all");
            setSourceFilter("all");
          }}
        />
        <XInjectStrip
          draft={xQueryDraft}
          onDraft={setXQueryDraft}
          active={xQuery}
          loading={xLoading}
          mergedCount={xEvents.length}
          warning={xWarning}
          onApply={() => setXQuery(xQueryDraft.trim())}
          onClear={() => {
            setXQueryDraft("");
            setXQuery("");
          }}
        />
        <PaneBody style={{ padding: 0, overflow: "hidden" }}>
          <div style={layout}>
            <section style={feedColumn}>
              {state === "loading" && sorted.length === 0 ? (
                <Loading />
              ) : error ? (
                <Empty title="Instant line error" body={error} icon="!" />
              ) : sorted.length === 0 ? (
                <Empty
                  title={sortedAll.length ? "No events match the current filter" : "No instant events"}
                  body={
                    sortedAll.length
                      ? "Loosen the score / category / region filter to see more events."
                      : "The auxiliary instant line has not produced events yet. Run Backfill to attempt a fresh pull."
                  }
                />
              ) : (
                <EventList events={sorted} />
              )}
            </section>
            <aside style={sideColumn}>
              <Panel title="Line State">
                <StatusStrip
                  items={[
                    { label: "mode", value: "secondary", tone: "accent" },
                    { label: "transport", value: transport, tone: transportTone(transport, ok) },
                    { label: "newest", value: newestAt ? timeAgo(newestAt) : "n/a", tone: stale ? "warn" : "neutral" },
                  ]}
                />
                {status?.warning ? <p style={warningText}>{status.warning}</p> : null}
              </Panel>
              <Panel title="Counters">
                <Metric label="total events" value={String(metrics?.total_events ?? sortedAll.length)} />
                <Metric label="breaking (≥75)" value={String(metrics?.breaking_events ?? sortedAll.filter((event) => Number(event.priority_score ?? 0) >= 75).length)} />
                <Metric
                  label="filtered shown"
                  value={`${sorted.length} / ${sortedAll.length}`}
                  emphasize={sorted.length !== sortedAll.length}
                />
                <Metric label="avg latency" value={formatLatency(metrics?.avg_latency_seconds)} />
              </Panel>
              <Panel title="Live tail">
                <LogStream entries={recentTail} maxHeight={188} follow monoFontSize={10} />
              </Panel>
              <Panel title="Flow Speed">
                <div style={speedupCaption}>
                  {speedupsAreLive
                    ? "live-reported · active optimizations"
                    : "documented optimizations · active when the live feed service is connected"}
                </div>
                <div style={chipGrid}>
                  {speedups.map((item) => (
                    <span key={item.name} style={chip} title={item.impact}>
                      {item.name}
                    </span>
                  ))}
                </div>
                {!speedupsAreLive ? (
                  <p style={mutedNote}>
                    Live speedup metadata only ships when the instant HTTP service is reachable. The
                    chips above are documented optimizations, not live-measured metrics.
                  </p>
                ) : null}
              </Panel>
              <Panel title={`Source Health · ${sourceHealth.length}`}>
                <div className="u-grid-gap-6">
                  {sourceHealth.length === 0 ? (
                    <span style={mutedText}>No source rows reported.</span>
                  ) : (
                    sourceHealth.map((source) => (
                      <SourceHealthRow
                        key={source.source_id ?? source.source_name}
                        source={source}
                        expanded={expandedSource === (source.source_id ?? source.source_name ?? "")}
                        onToggle={() => {
                          const id = source.source_id ?? source.source_name ?? "";
                          setExpandedSource((current) => (current === id ? null : id));
                        }}
                      />
                    ))
                  )}
                </div>
              </Panel>
            </aside>
          </div>
        </PaneBody>
        <PaneFooter>
          <span>secondary · instant</span>
          <span>refresh · {REFRESH_MS / 1000}s</span>
          <span>filter · {filterThreshold === 0 ? "off" : `≥${filterThreshold}`}</span>
          <span>audio · {audio ? `≥${audioThreshold}` : "off"}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function StatusStrip({
  items,
}: {
  items: Array<{ label: string; value: string; tone: "neutral" | "positive" | "negative" | "accent" | "warn" | "muted" }>;
}) {
  return (
    <div style={statusStrip}>
      {items.map((item, index) => (
        <span key={item.label} className="u-inline-flex u-items-center">
          <StatusSection label={item.label} value={item.value} tone={item.tone} withDot />
          {index < items.length - 1 ? <StatusDivider /> : null}
        </span>
      ))}
    </div>
  );
}

function FilterStrip({
  minScore,
  onMinScore,
  categories,
  category,
  onCategory,
  regions,
  region,
  onRegion,
  sources,
  source,
  onSource,
  breakingShown,
  watchShown,
  onClear,
}: {
  minScore: number;
  onMinScore: (value: number) => void;
  categories: string[];
  category: string;
  onCategory: (value: string) => void;
  regions: string[];
  region: string;
  onRegion: (value: string) => void;
  sources: string[];
  source: string;
  onSource: (value: string) => void;
  breakingShown: number;
  watchShown: number;
  onClear: () => void;
}) {
  const filtersActive = minScore > 0 || category !== "all" || region !== "all" || source !== "all";
  return (
    <div style={filterStrip}>
      <div style={filterGroup}>
        <span style={filterLabel} id="instant-min-score-label">min score</span>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={minScore}
          onChange={(event) => onMinScore(Number(event.target.value))}
          className="instant-range"
          aria-labelledby="instant-min-score-label"
          aria-label={`Minimum priority score filter (${minScore || "off"})`}
          aria-valuetext={minScore ? `${minScore}` : "off"}
        />
        <strong className="instant-filter-count">{minScore || "off"}</strong>
      </div>
      <FilterChips
        label="category"
        all="all"
        items={categories}
        active={category}
        onSelect={onCategory}
      />
      <FilterChips
        label="region"
        all="all"
        items={regions}
        active={region}
        onSelect={onRegion}
      />
      <FilterChips
        label="source"
        all="all"
        items={sources}
        active={source}
        onSelect={onSource}
        truncate
      />
      <div style={filterGroup}>
        <Pill tone="warn" variant="soft" withDot={false}>
          breaking · {breakingShown}
        </Pill>
        <Pill tone="accent" variant="soft" withDot={false}>
          watch · {watchShown}
        </Pill>
        {filtersActive ? (
          <button type="button" className="btn btn--ghost instant-btn-mini-8" onClick={onClear}>
            Clear
          </button>
        ) : null}
      </div>
    </div>
  );
}

function XInjectStrip({
  draft,
  onDraft,
  active,
  loading,
  mergedCount,
  warning,
  onApply,
  onClear,
}: {
  draft: string;
  onDraft: (value: string) => void;
  active: string;
  loading: boolean;
  mergedCount: number;
  warning: string | null;
  onApply: () => void;
  onClear: () => void;
}) {
  return (
    <div style={xInjectStrip}>
      <span style={xInjectLabel}>X sentiment merge</span>
      <input
        type="text"
        value={draft}
        spellCheck={false}
        placeholder="symbol or query (e.g. AAPL, $TSLA, fed)"
        onChange={(e) => onDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onApply();
        }}
        style={xInjectInput}
      />
      <button
        type="button"
        onClick={onApply}
        disabled={loading || !draft.trim()}
        className="btn btn--primary instant-btn-mini-10"
      >
        {loading ? "Pulling…" : active === draft.trim() && active ? "Refresh" : "Merge"}
      </button>
      {active ? (
        <>
          <Pill tone="accent" variant="soft" withDot={false}>
            X · {active} · {mergedCount}
          </Pill>
          <button
            type="button"
            onClick={onClear}
            className="btn btn--ghost instant-btn-mini-10"
          >
            Stop
          </button>
        </>
      ) : null}
      {warning ? (
        <span title={warning} className="u-inline-flex">
          <Pill tone="warn" variant="soft" withDot={false}>
            warn
          </Pill>
        </span>
      ) : null}
    </div>
  );
}

function FilterChips({
  label,
  all,
  items,
  active,
  onSelect,
  truncate,
}: {
  label: string;
  all: string;
  items: string[];
  active: string;
  onSelect: (value: string) => void;
  truncate?: boolean;
}) {
  if (items.length === 0) return null;
  const visible = truncate ? items.slice(0, 4) : items;
  return (
    <div style={filterGroup}>
      <span style={filterLabel}>{label}</span>
      <ChipButton label={all} active={active === "all"} onClick={() => onSelect("all")} />
      {visible.map((item) => (
        <ChipButton
          key={item}
          label={item}
          active={active === item}
          onClick={() => onSelect(item)}
        />
      ))}
      {truncate && items.length > visible.length && active !== "all" && !visible.includes(active) ? (
        <ChipButton label={active} active onClick={() => undefined} />
      ) : null}
    </div>
  );
}

function ChipButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      aria-label={`${label} filter`}
      style={{
        ...chipButton,
        background: active ? "var(--accent)" : "var(--surface-2)",
        color: active ? "var(--accent-on)" : "var(--text-secondary)",
        borderColor: active ? "var(--accent)" : "var(--border-subtle)",
      }}
    >
      {label}
    </button>
  );
}

function EventList({ events }: { events: InstantEvent[] }) {
  return (
    <div
      style={eventList}
      role="log"
      aria-live="polite"
      aria-label="Instant event feed"
    >
      {events.map((event) => {
        const score = Number(event.priority_score ?? 0);
        // Stable identity across re-sorts/filters: prefer the server dedupe
        // key, then link/id, with title only as a last resort. Never append
        // the array index — that breaks React reconciliation on reorder.
        const key =
          event.dedupe_key || event.link || (event.id != null ? String(event.id) : null) || event.title || "instant-event";
        // New-item flash only for low/normal rows (score < 58); higher-score
        // rows already carry a persistent accent background that the flash
        // would fight with.
        const fresh = score < 58 && isFresh(event.fetched_at);
        return (
          <article
            key={key}
            style={eventRowStyle(score)}
            className={fresh ? "instant-event--fresh" : undefined}
          >
            <div style={scoreBoxStyle(score)}>
              <strong className="instant-score-num">{score.toFixed(0)}</strong>
              <span className="instant-score-label">
                {event.priority_label ?? "low"}
              </span>
            </div>
            <div className="u-min-w-0">
              <div style={titleLine}>
                <Pill tone={priorityTone(score)} variant="soft" withDot={false}>
                  {(event.source_name ?? "instant").length > 22
                    ? `${(event.source_name ?? "").slice(0, 20)}…`
                    : event.source_name ?? "instant"}
                </Pill>
                <a href={event.link} target="_blank" rel="noopener noreferrer" style={titleLink}>
                  {event.title ?? "(untitled)"}
                </a>
              </div>
              <p style={summary}>{event.generated_summary ?? event.summary}</p>
              <div style={metaLine}>
                <span style={metaCell}>{event.source_category ?? "news"}</span>
                <span style={metaCellMute}>·</span>
                <span style={metaCell}>{event.source_region ?? "global"}</span>
                <span style={metaCellMute}>·</span>
                <span
                  className="terminal-grid-numeric"
                  style={metaCell}
                  title={event.published_at ?? undefined}
                >
                  published {formatDate(event.published_at)}
                  {relativeTimeLabel(event.published_at) ? (
                    <span style={metaCellRel}> · {relativeTimeLabel(event.published_at)}</span>
                  ) : null}
                </span>
                <span style={metaCellMute}>·</span>
                <span className="terminal-grid-numeric" style={metaCell}>
                  latency {formatLatency(event.latency_seconds)}
                </span>
                {event.calendar_window ? (
                  <>
                    <span style={metaCellMute}>·</span>
                    <span style={metaCell}>cal {event.calendar_window}</span>
                  </>
                ) : null}
                {event.official_url ? (
                  <a
                    href={event.official_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={metaLink}
                  >
                    official
                  </a>
                ) : null}
              </div>
              {(event.matched_keywords ?? []).length > 0 ? (
                <div style={keywordRow}>
                  {(event.matched_keywords ?? []).slice(0, 8).map((keyword) => (
                    <span key={keyword} style={keywordChip}>
                      {keyword}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          </article>
        );
      })}
    </div>
  );
}

function SourceHealthRow({
  source,
  expanded,
  onToggle,
}: {
  source: InstantSourceHealth;
  expanded: boolean;
  onToggle: () => void;
}) {
  const enabled = Boolean(source.enabled);
  const ok = Boolean(source.ok);
  const tone: "positive" | "negative" | "warn" = ok ? "positive" : enabled ? "negative" : "warn";
  const label = ok ? "OK" : enabled ? "ERR" : "OFF";
  const collapsed = `${source.last_item_count ?? 0} items / ${source.last_latency_ms ?? "n/a"} ms`;
  const displayName = source.source_name ?? source.source_id ?? "source";
  return (
    <div style={sourceRowOuter}>
      <button
        type="button"
        onClick={onToggle}
        style={sourceRowButton}
        aria-expanded={expanded}
        aria-label={`${displayName} source health — ${label}, ${expanded ? "expanded" : "collapsed"}`}
      >
        <div className="instant-source-row-text">
          <strong style={sourceName}>{source.source_name ?? source.source_id}</strong>
          <span style={sourceMeta} className="terminal-grid-numeric">{collapsed}</span>
        </div>
        <Pill tone={tone} variant="soft" withDot={false}>{label}</Pill>
      </button>
      {expanded ? (
        <div style={sourceDetail}>
          <div style={kvRowSlim}>
            <span>id</span>
            <code style={codeMono}>{source.source_id ?? "—"}</code>
          </div>
          <div style={kvRowSlim}>
            <span>status</span>
            <strong style={kvValue}>{source.status ?? "—"}</strong>
          </div>
          {source.last_error ? (
            <p style={warningText}>{source.last_error}</p>
          ) : (
            <p style={mutedNote}>No recorded error.</p>
          )}
        </div>
      ) : null}
    </div>
  );
}

function Loading() {
  return (
    <div className="instant-loading">
      <Skeleton height={28} width="50%" />
      <Skeleton height={90} />
      <Skeleton height={90} />
      <Skeleton height={90} width="94%" />
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={panel}>
      <div style={panelTitle}>{title}</div>
      {children}
    </section>
  );
}

function Metric({
  label,
  value,
  emphasize,
}: {
  label: string;
  value: string;
  emphasize?: boolean;
}) {
  return (
    <div style={kvRow}>
      <span>{label}</span>
      <strong style={kvValue} className={emphasize ? "u-text-accent" : undefined}>{value}</strong>
    </div>
  );
}

function dateValue(value?: string | null): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

// True when an event was fetched within the last ~5 seconds, used to drive the
// brief new-item flash highlight on freshly-arrived rows.
function isFresh(value?: string | null): boolean {
  if (!value) return false;
  const ts = Date.parse(value);
  if (!Number.isFinite(ts)) return false;
  return Date.now() - ts < 5_000;
}

function formatDate(value?: string | null): string {
  if (!value) return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "n/a";
  try {
    return new Intl.DateTimeFormat("en-GB", {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: readTz(),
    }).format(date);
  } catch {
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  }
}

function formatLatency(seconds?: number | null): string {
  if (seconds == null || !Number.isFinite(Number(seconds))) return "n/a";
  const value = Number(seconds);
  if (value < 60) return `${value.toFixed(1)}s`;
  if (value < 3600) return `${(value / 60).toFixed(1)}m`;
  if (value < 86400) return `${(value / 3600).toFixed(1)}h`;
  return `${(value / 86400).toFixed(1)}d`;
}

function timeAgo(value: string | null | undefined): string {
  if (!value) return "n/a";
  const ts = Date.parse(value);
  if (!Number.isFinite(ts)) return "n/a";
  const seconds = Math.max(0, (Date.now() - ts) / 1000);
  return formatLatency(seconds);
}

function computeStale(value: string | null | undefined): { ageSeconds: number; label: string } | null {
  if (!value) return null;
  const ts = Date.parse(value);
  if (!Number.isFinite(ts)) return null;
  const ageSeconds = Math.max(0, (Date.now() - ts) / 1000);
  if (ageSeconds < 3600) return null;
  return { ageSeconds, label: formatLatency(ageSeconds) + " old" };
}

function uniqueValues(events: InstantEvent[], pick: (event: InstantEvent) => string | undefined): string[] {
  const set = new Set<string>();
  for (const event of events) {
    const value = pick(event);
    if (value) set.add(value);
  }
  return Array.from(set).sort();
}

function priorityTone(score: number): "neutral" | "accent" | "warn" | "muted" | "positive" | "negative" {
  if (score >= 75) return "warn";
  if (score >= 58) return "accent";
  if (score >= 40) return "neutral";
  return "muted";
}

function transportTone(transport: string, ok: boolean): "positive" | "warn" | "negative" | "neutral" {
  if (transport === "http") return ok ? "positive" : "warn";
  if (transport === "sqlite-fallback") return "warn";
  if (transport === "loading") return "neutral";
  return "negative";
}

function eventRowStyle(score: number): CSSProperties {
  const accent =
    score >= 75
      ? "var(--warn-soft)"
      : score >= 58
        ? "var(--accent-soft)"
        : "transparent";
  const borderLeft =
    score >= 75
      ? "3px solid var(--warn)"
      : score >= 58
        ? "3px solid var(--accent)"
        : score >= 40
          ? "3px solid var(--border-subtle)"
          : "3px solid transparent";
  return {
    display: "grid",
    gridTemplateColumns: "72px minmax(0, 1fr)",
    gap: 12,
    padding: "12px 14px 12px 11px",
    borderBottom: "1px solid var(--border-subtle)",
    borderLeft,
    background: accent,
  };
}

function scoreBoxStyle(score: number): CSSProperties {
  const tint =
    score >= 75
      ? "color-mix(in srgb, var(--warn) 18%, transparent)"
      : score >= 58
        ? "color-mix(in srgb, var(--accent) 16%, transparent)"
        : score >= 40
          ? "color-mix(in srgb, var(--text-primary) 6%, transparent)"
          : "var(--surface-2)";
  const accent =
    score >= 75
      ? "var(--warn)"
      : score >= 58
        ? "var(--accent)"
        : score >= 40
          ? "var(--text-primary)"
          : "var(--text-mute)";
  return {
    minHeight: 66,
    border: `1px solid ${score >= 58 ? accent : "var(--border-subtle)"}`,
    borderRadius: "var(--radius-md)",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    background: tint,
    color: accent,
    gap: 4,
  };
}

const toolbar: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  flexWrap: "wrap",
};

const toggleLabel: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  fontSize: 11,
  color: "var(--text-secondary)",
};

const rangeLabel: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  fontSize: 11,
  color: "var(--text-secondary)",
};

const kpiRibbon: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: 8,
  padding: "10px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "color-mix(in srgb, var(--surface) 80%, transparent)",
};

const filterStrip: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: 14,
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const filterGroup: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
};

const filterLabel: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
};


const chipButton: CSSProperties = {
  height: 22,
  padding: "0 9px",
  borderRadius: 11,
  border: "1px solid var(--border-subtle)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  letterSpacing: "0.04em",
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const layout: CSSProperties = {
  height: "100%",
  minHeight: 0,
  display: "grid",
  gridTemplateColumns: "minmax(0, 1fr) 340px",
};

const feedColumn: CSSProperties = {
  minWidth: 0,
  minHeight: 0,
  overflow: "auto",
  borderRight: "1px solid var(--border-subtle)",
};

const sideColumn: CSSProperties = {
  minWidth: 0,
  minHeight: 0,
  overflow: "auto",
  background: "color-mix(in srgb, var(--bg) 70%, transparent)",
};

const eventList: CSSProperties = {
  display: "grid",
};

const titleLine: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  gap: 8,
  minWidth: 0,
  flexWrap: "wrap",
};

const titleLink: CSSProperties = {
  color: "var(--text-primary)",
  fontSize: 13,
  fontWeight: 700,
  textDecoration: "none",
  overflowWrap: "anywhere",
};

const summary: CSSProperties = {
  margin: "7px 0 6px",
  color: "var(--text-secondary)",
  fontSize: 11,
  lineHeight: 1.45,
  overflowWrap: "anywhere",
};

const metaLine: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
  alignItems: "center",
  color: "var(--text-mute)",
  fontSize: 10,
};

const metaCell: CSSProperties = {
  color: "var(--text-mute)",
};

const metaCellRel: CSSProperties = {
  color: "var(--text-secondary)",
};

const metaCellMute: CSSProperties = {
  color: "var(--border-strong)",
};

const metaLink: CSSProperties = {
  color: "var(--accent)",
  textDecoration: "none",
  fontSize: 10,
};

const keywordRow: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 4,
  marginTop: 6,
};

const keywordChip: CSSProperties = {
  padding: "2px 7px",
  borderRadius: 9,
  background: "var(--accent-soft)",
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
};

const panel: CSSProperties = {
  padding: 12,
  borderBottom: "1px solid var(--border-subtle)",
};

const panelTitle: CSSProperties = {
  marginBottom: 8,
  color: "var(--text-mute)",
  fontSize: 10,
  fontWeight: 800,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
};

const statusStrip: CSSProperties = {
  display: "flex",
  alignItems: "center",
  height: 22,
  padding: "0 4px",
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  flexWrap: "wrap",
};

const kvRow: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
  padding: "6px 0",
  borderTop: "1px solid var(--border-subtle)",
  color: "var(--text-secondary)",
};

const kvRowSlim: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
  padding: "3px 0",
  color: "var(--text-secondary)",
  fontSize: 11,
};

const kvValue: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-primary)",
};

const codeMono: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  color: "var(--text-mute)",
  fontSize: 10,
};

const warningText: CSSProperties = {
  margin: "8px 0 0",
  color: "var(--warn)",
  fontSize: 11,
  lineHeight: 1.4,
  overflowWrap: "anywhere",
};

const chipGrid: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
};

const chip: CSSProperties = {
  padding: "3px 8px",
  border: "1px solid var(--border-subtle)",
  borderRadius: 9,
  background: "var(--surface-2)",
  color: "var(--text-secondary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  overflowWrap: "anywhere",
  cursor: "default",
};

const sourceRowOuter: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-2)",
};

const sourceRowButton: CSSProperties = {
  width: "100%",
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "7px 9px",
  background: "transparent",
  border: "none",
  cursor: "pointer",
  textAlign: "left",
};

const sourceDetail: CSSProperties = {
  padding: "6px 10px 10px",
  borderTop: "1px solid var(--border-subtle)",
  display: "grid",
  gap: 4,
};

const sourceName: CSSProperties = {
  display: "block",
  color: "var(--text-primary)",
  fontSize: 11,
  overflowWrap: "anywhere",
};

const sourceMeta: CSSProperties = {
  display: "block",
  color: "var(--text-mute)",
  fontSize: 10,
  overflowWrap: "anywhere",
};

const mutedText: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: 11,
};

const mutedNote: CSSProperties = {
  margin: "6px 0 0",
  color: "var(--text-mute)",
  fontSize: 10,
  lineHeight: 1.4,
};

const speedupCaption: CSSProperties = {
  marginBottom: 6,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  textTransform: "uppercase",
  letterSpacing: "0.06em",
};

const xInjectStrip: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "6px 14px 8px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--accent-soft)",
  flexWrap: "wrap",
};

const xInjectLabel: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--accent)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
};

const xInjectInput: CSSProperties = {
  height: 22,
  minWidth: 220,
  padding: "0 8px",
  background: "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  outline: "none",
  flex: "1 1 240px",
  maxWidth: 320,
};
