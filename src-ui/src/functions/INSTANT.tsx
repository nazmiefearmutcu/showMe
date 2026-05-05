import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { Empty, Pane, PaneBody, PaneFooter, PaneHeader, Pill, Skeleton } from "@/design-system";
import {
  fetchInstantEvents,
  fetchInstantStatus,
  runInstantBackfill,
  type InstantEvent,
  type InstantStatus,
} from "@/lib/instant";
import type { FunctionPaneProps } from "./registry-types";

type LoadState = "idle" | "loading" | "ok" | "error";

const REFRESH_MS = 30_000;

export function INSTANTPane({ code }: FunctionPaneProps) {
  const [events, setEvents] = useState<InstantEvent[]>([]);
  const [status, setStatus] = useState<InstantStatus | null>(null);
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [audio, setAudio] = useState(false);
  const [threshold, setThreshold] = useState(72);
  const [tick, setTick] = useState(0);
  const [spoken, setSpoken] = useState<Set<string>>(() => new Set());

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
      if (!key || next.has(key) || score < threshold) continue;
      next.add(key);
      const utterance = new SpeechSynthesisUtterance(
        `${event.priority_label ?? "update"}. ${event.source_name ?? "instant"}. Score ${score}. ${event.title ?? ""}. ${event.generated_summary ?? ""}`,
      );
      utterance.rate = 1.02;
      window.speechSynthesis.speak(utterance);
    }
    if (next.size !== spoken.size) setSpoken(next);
  }, [audio, events, spoken, threshold]);

  const sorted = useMemo(
    () => [...events].sort((a, b) => dateValue(b.fetched_at) - dateValue(a.fetched_at)),
    [events],
  );

  const metrics = status?.health?.metrics ?? status?.performance?.metrics;
  const speedups = status?.performance?.speedups ?? [];
  const sourceHealth = status?.health?.sources ?? [];
  const transport = status?.transport ?? "unavailable";
  const ok = Boolean(status?.ok);

  return (
    <div style={{ padding: 18, height: "100%", minHeight: 0, boxSizing: "border-box" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="Instant squawk line"
          subtitle={`${transport} · secondary data line · ${sorted.length} events`}
          trailing={
            <div style={toolbar}>
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
              </label>
              <label style={rangeLabel}>
                <span>score</span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={threshold}
                  onChange={(event) => setThreshold(Number(event.target.value))}
                />
                <b>{threshold}</b>
              </label>
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
                onClick={() => {
                  setState("loading");
                  runInstantBackfill(20)
                    .then(() => setTick((value) => value + 1))
                    .catch((err) => {
                      setError(err instanceof Error ? err.message : String(err));
                      setState("error");
                    });
                }}
                disabled={state === "loading"}
              >
                Backfill
              </button>
            </div>
          }
          help={
            <div style={{ display: "grid", gap: 8 }}>
              <strong style={{ color: "var(--accent)", fontFamily: "JetBrains Mono, monospace" }}>
                INSTANT · secondary market-moving news line
              </strong>
              <span style={{ color: "var(--text-secondary)" }}>
                This pane reads the separate instant service through /api/instant/*. It does not replace NI, CN, ECO, or other primary showMe functions.
              </span>
              <span style={{ color: "var(--text-mute)" }}>
                Flow acceleration uses shared async HTTP, conditional feed cache, priority due ordering, and a short fast lane after high-impact inserts.
              </span>
            </div>
          }
        />
        <PaneBody style={{ padding: 0, overflow: "hidden" }}>
          <div style={layout}>
            <section style={feedColumn}>
              {state === "loading" && sorted.length === 0 ? (
                <Loading />
              ) : error ? (
                <Empty title="Instant line error" body={error} icon="!" />
              ) : sorted.length === 0 ? (
                <Empty title="No instant events" body="The auxiliary instant line has not produced events yet." />
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
                  <Pill tone={ok ? "positive" : "warn"} withDot={false}>{transport}</Pill>
                </div>
                {status?.warning ? <p style={warningText}>{status.warning}</p> : null}
              </Panel>
              <Panel title="Latency">
                <Metric label="events" value={String(metrics?.total_events ?? sorted.length)} />
                <Metric label="breaking" value={String(metrics?.breaking_events ?? sorted.filter((event) => Number(event.priority_score ?? 0) >= 75).length)} />
                <Metric label="avg latency" value={formatLatency(metrics?.avg_latency_seconds)} />
              </Panel>
              <Panel title="Flow Speed">
                <div style={chipGrid}>
                  {speedups.length
                    ? speedups.map((item) => (
                        <span key={item.name} style={chip} title={item.impact}>
                          {item.name}
                        </span>
                      ))
                    : <span style={mutedText}>No speed metadata yet.</span>}
                </div>
              </Panel>
              <Panel title="Source Health">
                <div style={{ display: "grid", gap: 8 }}>
                  {sourceHealth.map((source) => (
                    <div key={source.source_id ?? source.source_name} style={sourceRow}>
                      <div style={{ minWidth: 0 }}>
                        <strong style={sourceName}>{source.source_name ?? source.source_id}</strong>
                        <span style={sourceMeta}>
                          {source.last_error || `${source.last_item_count ?? 0} items / ${source.last_latency_ms ?? "n/a"} ms`}
                        </span>
                      </div>
                      <span style={{ color: source.ok ? "var(--positive)" : source.enabled ? "var(--negative)" : "var(--warn)", fontSize: 11 }}>
                        {source.ok ? "OK" : source.enabled ? "ERR" : "OFF"}
                      </span>
                    </div>
                  ))}
                </div>
              </Panel>
            </aside>
          </div>
        </PaneBody>
        <PaneFooter>
          <span>secondary · instant</span>
          <span>refresh · {REFRESH_MS / 1000}s</span>
          <span>audio threshold · {threshold}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function EventList({ events }: { events: InstantEvent[] }) {
  return (
    <div style={eventList}>
      {events.map((event, index) => {
        const score = Number(event.priority_score ?? 0);
        return (
          <article key={(event.dedupe_key ?? event.link ?? event.title ?? "") + index} style={eventRow}>
            <div style={scoreBox}>
              <strong>{score.toFixed(0)}</strong>
              <span>{event.priority_label ?? "low"}</span>
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={titleLine}>
                <Pill tone={score >= 75 ? "warn" : score >= 58 ? "accent" : "muted"} withDot={false}>
                  {event.source_name ?? "instant"}
                </Pill>
                <a href={event.link} target="_blank" rel="noopener noreferrer" style={titleLink}>
                  {event.title ?? "(untitled)"}
                </a>
              </div>
              <p style={summary}>{event.generated_summary ?? event.summary}</p>
              <div style={metaLine}>
                <span>{event.source_category ?? "news"} / {event.source_region ?? "global"}</span>
                <span>published {formatDate(event.published_at)}</span>
                <span>latency {formatLatency(event.latency_seconds)}</span>
                {(event.matched_keywords ?? []).slice(0, 4).map((keyword) => <span key={keyword}>{keyword}</span>)}
                {event.official_url ? (
                  <a href={event.official_url} target="_blank" rel="noopener noreferrer">official source</a>
                ) : null}
              </div>
            </div>
          </article>
        );
      })}
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

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div style={kvRow}>
      <span>{label}</span>
      <strong>{value}</strong>
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
  return `${(value / 3600).toFixed(1)}h`;
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

const eventRow: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "72px minmax(0, 1fr)",
  gap: 12,
  padding: "12px 14px",
  borderBottom: "1px solid var(--border-subtle)",
};

const scoreBox: CSSProperties = {
  minHeight: 66,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  background: "var(--bg-elev-2)",
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
  margin: "7px 0",
  color: "var(--text-secondary)",
  fontSize: 11,
  lineHeight: 1.45,
  overflowWrap: "anywhere",
};

const metaLine: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
  color: "var(--text-mute)",
  fontSize: 10,
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
  padding: "3px 6px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-secondary)",
  fontSize: 10,
  overflowWrap: "anywhere",
};

const sourceRow: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 10,
  minWidth: 0,
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
