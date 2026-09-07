/**
 * TRAN — Earnings Call Transcript.
 *
 * Renders the most recent earnings-call transcript harvested by the backend
 * (SEC 8-K exhibit flow): sections (Prepared Remarks / Q&A) of speaker+role
 * utterances, a persisted speaker filter built from the payload's distinct
 * speakers, and jump-to-section anchors. Data honesty: when the provider is
 * unavailable / not configured the pane says so explicitly — never fake text.
 */
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { defaultSymbolForFunction } from "@/lib/symbols";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface TranUtterance {
  section?: string;
  speaker?: string;
  role?: string;
  utterance?: string;
  timestamp_seconds?: number | null;
  position?: number | null;
}

interface TranEvent {
  quarter?: string;
  form?: string;
  event_date?: string;
  filing_date?: string;
  source?: string;
  title?: string;
  source_url?: string;
}

interface TRANData {
  symbol?: string;
  status?: string;
  reason?: string;
  next_actions?: string[] | string;
  event?: TranEvent;
  utterances?: TranUtterance[];
}

const SECTION_LABELS: Record<string, string> = {
  prepared_remarks: "Prepared Remarks",
  qa: "Q&A",
};

const SPEAKER_KEY = "showme.tran.speaker";

function sectionLabel(section: string): string {
  return (
    SECTION_LABELS[section] ??
    section
      .split(/[_\s-]+/)
      .filter(Boolean)
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ")
  );
}

function sectionDomId(section: string): string {
  return `tran-section-${section.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`;
}

function formatTimestamp(seconds: number | null | undefined): string | null {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) {
    return null;
  }
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/**
 * Speaker persistence without the options list: distinct speakers only exist
 * after the payload arrives, so the stored raw string is read/written directly
 * (usePersistentOption validates against options at mount and would clobber
 * the stored choice before the payload loads).
 */
function usePersistedSpeaker(): readonly [string, (v: string) => void] {
  const [speaker, setSpeaker] = useState<string>(() => {
    if (typeof localStorage === "undefined") return "all";
    return localStorage.getItem(SPEAKER_KEY) ?? "all";
  });
  useEffect(() => {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(SPEAKER_KEY, speaker);
    }
  }, [speaker]);
  return [speaker, setSpeaker] as const;
}

interface TranSection {
  key: string;
  label: string;
  utterances: TranUtterance[];
}

function groupBySection(rows: TranUtterance[]): TranSection[] {
  const order: string[] = [];
  const buckets = new Map<string, TranUtterance[]>();
  for (const r of rows) {
    const key = (r.section ?? "").trim() || "other";
    if (!buckets.has(key)) {
      buckets.set(key, []);
      order.push(key);
    }
    buckets.get(key)?.push(r);
  }
  return order.map((key) => ({
    key,
    label: sectionLabel(key),
    utterances: buckets.get(key) ?? [],
  }));
}

export function TRANPane({ code, symbol }: FunctionPaneProps) {
  const [speaker, setSpeaker] = usePersistedSpeaker();
  const effectiveSymbol = symbol || defaultSymbolForFunction(code, ["EQUITY", "ETF"]);
  const { state, data, error, refetch } = useFunction<TRANData>({
    code,
    symbol: effectiveSymbol,
    params: {},
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const utterances: TranUtterance[] = useMemo(
    () => (Array.isArray(payload?.utterances) ? payload.utterances : []),
    [payload],
  );
  const status = payload?.status ?? "—";

  const speakers = useMemo(() => {
    const set = new Set<string>();
    for (const r of utterances) {
      const name = (r.speaker ?? "").trim();
      if (name) set.add(name);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [utterances]);

  const speakerOptions = useMemo(
    () => [{ value: "all", label: "All" }, ...speakers.map((s) => ({ value: s, label: s }))],
    [speakers],
  );

  const filtered = useMemo(
    () =>
      speaker === "all"
        ? utterances
        : utterances.filter((r) => (r.speaker ?? "").trim() === speaker),
    [utterances, speaker],
  );
  const sections = useMemo(() => groupBySection(filtered), [filtered]);

  const quarter = payload?.event?.quarter ?? "";
  const eventDate = payload?.event?.event_date ?? "";
  const isLive = state === "ok" && status === "ok";
  const totalUtterances = utterances.length;

  const jumpTo = (key: string) => {
    const el = document.getElementById(sectionDomId(key));
    el?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  };

  const body = !effectiveSymbol ? (
    <Empty title="Pick a symbol" body="TRAN needs an equity ticker." icon="⌖" />
  ) : state === "loading" || state === "idle" ? (
    <div className="u-grid-gap-8">
      <Skeleton height={28} />
      <Skeleton height={56} />
      <Skeleton height={72} />
      <Skeleton height={56} width="90%" />
    </div>
  ) : state === "error" ? (
    <Empty
      title="Function error"
      body={error?.message ?? "—"}
      icon="!"
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : totalUtterances === 0 ? (
    <Empty
      title={
        status === "provider_unavailable"
          ? "Transcript provider unavailable"
          : status === "not_configured"
            ? "Transcript source not configured"
            : "No transcript returned"
      }
      body={
        payload?.reason ??
        "No earnings-call transcript was available for this symbol. Nothing is fabricated here — try refresh or another quarter."
      }
      action={
        <button onClick={refetch} className="btn">
          Retry
        </button>
      }
    />
  ) : sections.length === 0 ? (
    <Empty
      title="No utterances for this speaker"
      body={`The transcript has ${totalUtterances} utterances, none from "${speaker}".`}
      action={
        <button onClick={() => setSpeaker("all")} className="btn">
          Show all speakers
        </button>
      }
    />
  ) : (
    <div className="u-grid-gap-14">
      {sections.length > 1 ? (
        <nav style={jumpNavStyle} aria-label="Jump to transcript section">
          <span style={jumpNavLabelStyle}>JUMP</span>
          {sections.map((s) => (
            <button
              key={s.key}
              type="button"
              className="btn"
              aria-label={`Jump to ${s.label}`}
              onClick={() => jumpTo(s.key)}
            >
              {s.label} · {s.utterances.length}
            </button>
          ))}
        </nav>
      ) : null}
      {sections.map((s) => (
        <section
          key={s.key}
          id={sectionDomId(s.key)}
          aria-label={`Transcript section: ${s.label}`}
          style={sectionStyle}
        >
          <h3 style={sectionHeadingStyle}>
            {s.label}
            <span style={sectionCountStyle}>{s.utterances.length} utt</span>
          </h3>
          {s.utterances.map((u, i) => {
            const ts = formatTimestamp(u.timestamp_seconds);
            return (
              <article
                key={u.position ?? i}
                className="tran-utterance"
                style={utteranceStyle}
              >
                <header style={utteranceHeadStyle}>
                  <span style={speakerStyle}>{(u.speaker ?? "").trim() || "Unknown"}</span>
                  {u.role ? <Pill tone="muted" variant="soft" withDot={false}>{u.role}</Pill> : null}
                  {ts ? <span style={tsStyle}>{ts}</span> : null}
                </header>
                <p style={utteranceTextStyle}>{u.utterance ?? "—"}</p>
              </article>
            );
          })}
        </section>
      ))}
    </div>
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Earnings Call Transcript — ${effectiveSymbol || ""}`}
          subtitle={
            [
              effectiveSymbol || "—",
              quarter,
              eventDate,
              `${totalUtterances} utterances`,
            ]
              .filter(Boolean)
              .join(" · ")
          }
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {speakers.length} spk
              </Pill>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : status}
              </Pill>
              {speakers.length > 0 ? (
                <SegmentedControl
                  label="SPEAKER"
                  value={speakerOptions.some((o) => o.value === speaker) ? speaker : "all"}
                  options={speakerOptions}
                  onChange={setSpeaker}
                />
              ) : null}
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                disabled={!effectiveSymbol}
                title="Refresh transcript"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection
            label="source"
            value={payload?.event?.source || data?.sources?.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection label="status" value={status} />
          <StatusDivider />
          <StatusSection label="utterances" value={filtered.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="speaker" value={speaker === "all" ? "all" : speaker} tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

const jumpNavStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  flexWrap: "wrap",
};

const jumpNavLabelStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: 1,
  color: "var(--text-mute)",
};

const sectionStyle: CSSProperties = {
  display: "grid",
  gap: 10,
};

const sectionHeadingStyle: CSSProperties = {
  margin: 0,
  fontSize: 12,
  letterSpacing: 1.2,
  textTransform: "uppercase",
  color: "var(--accent, var(--text-primary))",
  display: "flex",
  alignItems: "baseline",
  gap: 8,
};

const sectionCountStyle: CSSProperties = {
  fontSize: 10,
  color: "var(--text-mute)",
  textTransform: "none",
  letterSpacing: 0.5,
};

const utteranceStyle: CSSProperties = {
  borderLeft: "2px solid var(--grid-color, var(--text-mute))",
  paddingLeft: 10,
  display: "grid",
  gap: 4,
};

const utteranceHeadStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  flexWrap: "wrap",
};

const speakerStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontWeight: 600,
  fontSize: 12,
  color: "var(--text-primary)",
};

const tsStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  color: "var(--text-mute)",
};

const utteranceTextStyle: CSSProperties = {
  margin: 0,
  whiteSpace: "pre-wrap",
  lineHeight: 1.5,
  color: "var(--text-primary)",
};
