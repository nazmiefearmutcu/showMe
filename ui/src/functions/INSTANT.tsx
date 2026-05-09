import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { Empty, Pane, PaneBody, PaneFooter, PaneHeader, Pill, Skeleton } from "@/design-system";
import {
  fetchInstantEvents,
  fetchInstantStatus,
  runInstantBackfill,
  type InstantEvent,
  type InstantSourceHealth,
  type InstantStatus,
} from "@/lib/instant";
import { toast } from "@/lib/toast";
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
  const [status, setStatus] = useState<InstantStatus | null>(null);
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [audio, setAudio] = useState(false);
  const [audioThreshold, setAudioThreshold] = useState(72);
  const [filterThreshold, setFilterThreshold] = useState(0);
  const [tick, setTick] = useState(0);
  const [spoken, setSpoken] = useState<Set<string>>(() => new Set());
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [regionFilter, setRegionFilter] = useState<string>("all");
  const [sourceFilter, setSourceFilter] = useState<string>("all");
  const [expandedSource, setExpandedSource] = useState<string | null>(null);
  const [backfillBusy, setBackfillBusy] = useState(false);

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

  useEffect(() => {
    const id = window.setInterval(() => setTick((value) => value + 1), REFRESH_MS);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!audio || !("speechSynthesis" in window)) return;
    const next = new Set(spoken);
    for (const event of events) {
      const score = Number(event.priority_score ?? 0);
      const key = event.dedupe_key ?? event.link ?? event.title ?? "";
      if (!key || next.has(key) || score < audioThreshold) continue;
      next.add(key);
      const utterance = new SpeechSynthesisUtterance(
        `${event.priority_label ?? "update"}. ${event.source_name ?? "instant"}. Score ${score}. ${event.title ?? ""}. ${event.generated_summary ?? ""}`,
      );
      utterance.rate = 1.02;
      window.speechSynthesis.speak(utterance);
    }
    if (next.size !== spoken.size) setSpoken(next);
  }, [audio, events, spoken, audioThreshold]);

  const sortedAll = useMemo(
    () => [...events].sort((a, b) => dateValue(b.fetched_at) - dateValue(a.fetched_at)),
    [events],
  );

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
  const speedups = useMemo(() => {
    const fromStatus = status?.performance?.speedups ?? [];
    if (fromStatus.length) return fromStatus;
    return KNOWN_SPEEDUPS;
  }, [status]);
  const sourceHealth = status?.health?.sources ?? [];
  const transport = status?.transport ?? "unavailable";
  const ok = Boolean(status?.ok);
  const newestAt = metrics?.newest_fetched_at ?? null;
  const stale = computeStale(newestAt);

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
    <div style={{ padding: 18, height: "100%", minHeight: 0, boxSizing: "border-box" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="Instant squawk line"
          subtitle={`${transport} · secondary data line · showing ${sorted.length} of ${sortedAll.length} events`}
          trailing={
            <div style={toolbar}>
              {stale ? (
                <Pill tone="warn" withDot={false}>
                  stale · {stale.label}
                </Pill>
              ) : newestAt ? (
                <Pill tone="positive" withDot={false}>fresh · {timeAgo(newestAt)}</Pill>
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
                  <span style={{ color: "var(--text-mute)" }}>&ge;{audioThreshold}</span>
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
                className="btn btn--ghost"
                onClick={() => setTick((value) => value + 1)}
                disabled={state === "loading"}
              >
                Refresh
              </button>
              <button
                type="button"
                className="btn"
                onClick={triggerBackfill}
                disabled={state === "loading" || backfillBusy}
              >
                {backfillBusy ? "Backfilling…" : "Backfill"}
              </button>
            </div>
          }
          help={
            <div style={{ display: "grid", gap: 8 }}>
              <strong style={{ color: "var(--accent)", fontFamily: "JetBrains Mono, monospace" }}>
                INSTANT · secondary market-moving news line
              </strong>
              <span style={{ color: "var(--text-secondary)" }}>
                Reads the auxiliary instant service through /api/instant/*. Falls back to the local
                SQLite store when the HTTP service is offline. It does not replace NI, CN, ECO, or
                other primary showMe news functions.
              </span>
              <span style={{ color: "var(--text-mute)" }}>
                Score thresholds split: a viewer-side filter (which events appear) and a separate
                audio threshold (which trigger speech synthesis when Audio is on).
              </span>
            </div>
          }
        />
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
                <div style={kvRow}>
                  <span>mode</span>
                  <Pill tone="accent" withDot={false}>secondary</Pill>
                </div>
                <div style={kvRow}>
                  <span>transport</span>
                  <Pill tone={transportTone(transport, ok)} withDot={false}>
                    {transport}
                  </Pill>
                </div>
                <div style={kvRow}>
                  <span>newest fetch</span>
                  <strong style={kvValue}>{newestAt ? timeAgo(newestAt) : "n/a"}</strong>
                </div>
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
              <Panel title="Flow Speed">
                <div style={chipGrid}>
                  {speedups.map((item) => (
                    <span key={item.name} style={chip} title={item.impact}>
                      {item.name}
                    </span>
                  ))}
                </div>
                {!status?.performance?.speedups?.length ? (
                  <p style={mutedNote}>
                    Live speedup metadata only ships when the instant HTTP service is reachable. The
                    chips above are the documented optimizations.
                  </p>
                ) : null}
              </Panel>
              <Panel title={`Source Health · ${sourceHealth.length}`}>
                <div style={{ display: "grid", gap: 6 }}>
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
        <span style={filterLabel}>min score</span>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={minScore}
          onChange={(event) => onMinScore(Number(event.target.value))}
          style={{ width: 120 }}
        />
        <strong style={{ ...filterCount, minWidth: 26 }}>{minScore || "off"}</strong>
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
        <Pill tone="warn" withDot={false}>
          breaking · {breakingShown}
        </Pill>
        <Pill tone="accent" withDot={false}>
          watch · {watchShown}
        </Pill>
        {filtersActive ? (
          <button type="button" className="btn btn--ghost" onClick={onClear} style={{ height: 22, padding: "0 8px", fontSize: 10 }}>
            Clear
          </button>
        ) : null}
      </div>
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
      style={{
        ...chipButton,
        background: active ? "var(--accent)" : "var(--bg-elev-2)",
        color: active ? "#0a0d12" : "var(--text-secondary)",
        borderColor: active ? "var(--accent)" : "var(--border-subtle)",
      }}
    >
      {label}
    </button>
  );
}

function EventList({ events }: { events: InstantEvent[] }) {
  return (
    <div style={eventList}>
      {events.map((event, index) => {
        const score = Number(event.priority_score ?? 0);
        return (
          <article
            key={(event.dedupe_key ?? event.link ?? event.title ?? "") + index}
            style={eventRowStyle(score)}
          >
            <div style={scoreBoxStyle(score)}>
              <strong style={{ fontSize: 16, lineHeight: 1 }}>{score.toFixed(0)}</strong>
              <span style={{ fontSize: 9, opacity: 0.85, textTransform: "uppercase" }}>
                {event.priority_label ?? "low"}
              </span>
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={titleLine}>
                <Pill tone={priorityTone(score)} withDot={false}>
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
                <span style={metaCell} title={event.published_at ?? undefined}>
                  published {formatDate(event.published_at)}
                </span>
                <span style={metaCellMute}>·</span>
                <span style={metaCell}>latency {formatLatency(event.latency_seconds)}</span>
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
  return (
    <div style={sourceRowOuter}>
      <button type="button" onClick={onToggle} style={sourceRowButton} aria-expanded={expanded}>
        <div style={{ minWidth: 0, flex: 1, textAlign: "left" }}>
          <strong style={sourceName}>{source.source_name ?? source.source_id}</strong>
          <span style={sourceMeta}>{collapsed}</span>
        </div>
        <Pill tone={tone} withDot={false}>{label}</Pill>
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
    <div style={{ padding: 14, display: "grid", gap: 8 }}>
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
      <strong style={emphasize ? { ...kvValue, color: "var(--accent)" } : kvValue}>{value}</strong>
    </div>
  );
}

function dateValue(value?: string | null): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatDate(value?: string | null): string {
  if (!value) return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "n/a";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
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

function transportTone(transport: string, ok: boolean): "positive" | "warn" | "negative" {
  if (transport === "http") return ok ? "positive" : "warn";
  if (transport === "sqlite-fallback") return "warn";
  return "negative";
}

function eventRowStyle(score: number): CSSProperties {
  const accent =
    score >= 75
      ? "rgba(255,122,0,0.06)"
      : score >= 58
        ? "rgba(43,201,255,0.045)"
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
      ? "rgba(255,122,0,0.18)"
      : score >= 58
        ? "rgba(43,201,255,0.16)"
        : score >= 40
          ? "rgba(255,255,255,0.06)"
          : "var(--bg-elev-2)";
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

const filterStrip: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: 14,
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--bg-elev-2)",
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

const filterCount: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  color: "var(--text-secondary)",
  display: "inline-block",
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
  background: "rgba(0,0,0,0.14)",
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

const metaCellMute: CSSProperties = {
  color: "rgba(255,255,255,0.18)",
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
  background: "rgba(43,201,255,0.10)",
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
  background: "var(--bg-elev-2)",
  color: "var(--text-secondary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  overflowWrap: "anywhere",
  cursor: "default",
};

const sourceRowOuter: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  background: "var(--bg-elev-2)",
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
