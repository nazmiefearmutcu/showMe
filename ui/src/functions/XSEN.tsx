/**
 * XSEN — X / Twitter sentiment intelligence (RoBERTa).
 *
 * Bloomberg-grade layout: header strip with model + scrape source chips,
 * KPI ribbon (sentiment % split + top emotion), topic chips with frequency,
 * tweet sample feed with per-row sentiment dot + expand-for-rationale, and
 * a one-click INSTANT merge action that pushes the active query into the
 * INSTANT pane's X sentiment merge slot.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  Card,
  CardHeader,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatCard,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import {
  analyzeXTopic,
  fetchXHealth,
  type XAnalysisResponse,
  type XExample,
  type XHealth,
} from "@/lib/xai";
import { toast } from "@/lib/toast";
import { normalizeSymbolInput } from "@/lib/symbols";
import { useWorkspace } from "@/lib/workspace";
import { navigate } from "@/lib/router";
import { useXInjectStore } from "@/lib/xinject";
import { maxOf } from "@/lib/maxOf";
import { relativeTimeLabel } from "@/lib/time";
import { formatNumber, formatPercent, formatSignedDelta } from "@/lib/format";
import type { FunctionPaneProps } from "./registry-types";

type LoadState = "idle" | "loading" | "ok" | "error";

const DEFAULT_LIMIT = 120;
const SINCE_OPTIONS = [
  { value: "1d", label: "24h" },
  { value: "3d", label: "3d" },
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
] as const;
type SinceKey = (typeof SINCE_OPTIONS)[number]["value"];

export function XSENPane({ code, symbol }: FunctionPaneProps) {
  const initialQuery = symbol ? normalizeSymbolInput(symbol) || "" : "";
  const [draftQuery, setDraftQuery] = useState(initialQuery || "AAPL");
  const [draftLimit, setDraftLimit] = useState(DEFAULT_LIMIT);
  const [draftSince, setDraftSince] = useState<SinceKey>("7d");
  const [draftLang, setDraftLang] = useState("en");
  const [query, setQuery] = useState<string>("");
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [since, setSince] = useState<SinceKey>("7d");
  const [lang, setLang] = useState("en");
  const [runId, setRunId] = useState(0);
  const [data, setData] = useState<XAnalysisResponse | null>(null);
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<XHealth | null>(null);
  const [expandedTweet, setExpandedTweet] = useState<string | null>(null);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);
  // A6: SR-only live region announces the load result ONCE on completion.
  // useRef of the last announced message gates re-announcement so the region
  // doesn't re-fire on every render (mirrors INSTANT/AGENT).
  const [announcement, setAnnouncement] = useState("");
  const lastAnnouncedRef = useRef<string>("");

  // When the pane is symbol-bound (#/symbol/AAPL/XSEN), auto-run once on
  // mount so the user lands on data, not a blank state. Manual queries always
  // require an explicit Run press to keep the scraper rate budget intact.
  useEffect(() => {
    if (!symbol) return;
    const next = normalizeSymbolInput(symbol);
    if (!next) return;
    setDraftQuery(next);
    setQuery(next);
    setRunId((id) => id + 1);
  }, [symbol]);

  useEffect(() => {
    let cancelled = false;
    fetchXHealth()
      .then((h) => {
        if (!cancelled) setHealth(h);
      })
      .catch((err) => {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : String(err);
        setHealth({
          ok: false,
          model_loaded: false,
          model_dir: null,
          load_error: message,
          scraper: {
            backends: { guest_token: false, nitter_pool_size: 0, jina_proxy: true },
            guest_token_present: false,
            nitter_mirrors_active: [],
          },
        });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!query || runId === 0) return;
    const controller = new AbortController();
    let cancelled = false;
    setState("loading");
    setError(null);
    // UA-HIGH-09: thread signal so rapid Run-button clicks abort the
    // server-side scrape + classify pipeline instead of stacking N requests.
    analyzeXTopic(
      {
        query,
        limit,
        since: sinceToDate(since),
        lang,
      },
      controller.signal,
    )
      .then((response) => {
        if (cancelled || controller.signal.aborted) return;
        setData(response);
        if (response.error) {
          setState("error");
          setError(response.error);
        } else {
          setState("ok");
        }
      })
      .catch((err) => {
        if (cancelled || controller.signal.aborted) return;
        const message = err instanceof Error ? err.message : String(err);
        setError(message);
        setState("error");
        toast.error("XSEN analyze failed", message);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [runId]); // eslint-disable-line react-hooks/exhaustive-deps -- Run-button gated on purpose

  // A6: announce the load result exactly once when it lands. Gated on a ref
  // of the last spoken message so re-renders (hover, expand) don't re-announce.
  useEffect(() => {
    if (state !== "ok" || !data) return;
    const msg = `${data.post_count ?? 0} gönderi yüklendi, ruh hali ${data.mood ?? "—"}`;
    if (lastAnnouncedRef.current === msg) return;
    lastAnnouncedRef.current = msg;
    setAnnouncement(msg);
  }, [state, data]);

  const run = () => {
    setQuery(draftQuery.trim() || "AAPL");
    setLimit(Math.max(20, Math.min(500, draftLimit)));
    setSince(draftSince);
    setLang(draftLang);
    setRunId((id) => id + 1);
  };

  const examples = data?.examples ?? {};
  const sentimentOrder = useMemo(() => orderSentiments(Object.keys(examples)), [examples]);

  // Active scrape source label (Brave -> Nitter -> Jina order).
  // Bug #10e: When the model load times out the backend returns a partial
  // {ok:false, model_loaded:false} payload with no `scraper` key. The
  // previous `health.scraper.nitter_mirrors_active.length` access threw
  // TypeError and tore down the whole pane. All reads here are now
  // optional-chained.
  // UA-HIGH-22: replaced the `as Record<string, unknown>` cast with a typed
  // accessor — the previous version lied about the value type at every site
  // (truthy-check on `unknown` happens to work but typechecks would have
  // missed any rename of these fields).
  type ScraperBackends = {
    brave_syndication?: boolean;
    ddg_syndication?: boolean;
    bing_syndication?: boolean;
    jina_proxy?: boolean;
    guest_token?: boolean;
    [key: string]: unknown;
  };
  const scrapeSource = useMemo(() => {
    if (!health) return "checking";
    if (health?.ok === false) return "model offline";
    const backends: ScraperBackends = health?.scraper?.backends ?? {};
    const parts: string[] = [];
    if (backends.brave_syndication) parts.push("brave");
    else if (backends.ddg_syndication) parts.push("ddg");
    else if (backends.bing_syndication) parts.push("bing");
    const mirrorCount = health?.scraper?.nitter_mirrors_active?.length ?? 0;
    if (mirrorCount > 0) parts.push(`nitter×${mirrorCount}`);
    if (backends.jina_proxy) parts.push("jina");
    return parts.length ? parts.join("→") : "no backends";
  }, [health]);

  const handleInstantMerge = () => {
    // Push the active query into the cross-pane handoff store, then navigate
    // to INSTANT. INSTANT consumes the pending injection on mount and applies
    // it to the X-merge input. Previously this navigated to "/fn/INSTANT?xq=…"
    // which the router treated as a literal function code → 404. See FUNC-02
    // and UI-INT-09 in the quality audit.
    if (!query) return;
    useXInjectStore.getState().setInjection(query);
    setFocusedTarget("INSTANT");
    navigate("/fn/INSTANT");
    toast.info("INSTANT merge", `Injected "${query}" from XSEN`);
  };

  return (
    <div className="u-pane-host--bb">
      <h2 className="u-sr-only">{code} — X social sentiment</h2>
      <Pane>
        <PaneHeader
          code={code}
          title="X social sentiment"
          subtitle={`Yerel RoBERTa · sentiment + emotion + topic · query "${query || "—"}" · ${data?.post_count ?? 0} posts`}
          help={<XSENHelp health={health} />}
          trailing={
            <div style={toolbar}>
              <Pill tone={moodTone(data?.mood)} variant="soft" withDot>
                {data?.mood ?? "—"}
              </Pill>
              <button
                type="button"
                onClick={handleInstantMerge}
                disabled={!query}
                className="btn btn--accent instant-btn-mini-10"
                title="Push this query into the INSTANT squawk line as an X sentiment merge"
              >
                → INSTANT
              </button>
            </div>
          }
        />
        {/* Status strip: account count + RoBERTa model + scrape source */}
        <section style={statusStrip}>
          <StatusSection
            label="ACCOUNTS"
            value={String(
              (data?.engagement as { unique_users?: number } | undefined)?.unique_users ??
                data?.post_count ??
                "—",
            )}
            tone="accent"
            withDot
          />
          <StatusDivider />
          <StatusSection
            label="MODEL"
            value="RoBERTa"
            tone={health?.model_loaded ? "positive" : health?.ok ? "warn" : "negative"}
            withDot
          />
          <StatusDivider />
          <StatusSection label="SOURCE" value={scrapeSource} tone="muted" />
          <StatusDivider />
          <StatusSection
            label="DEVICE"
            value={data?.device ?? "—"}
            tone="neutral"
          />
          <StatusDivider />
          {/* F1: real freshness — when THIS response was served, from
              fetched_at. Distinct from the analysis-duration field below. */}
          <span
            data-testid="xsen-fetched-at"
            title="Veri alındı: bu sonucun sunulduğu (analizin tamamlandığı) an. Arama sonuçları sorgu başına ~30 dk'ya kadar önbelleğe alınmış olabilir."
          >
            <StatusSection
              label="VERİ ALINDI"
              value={
                data?.fetched_at
                  ? (relativeTimeLabel(data.fetched_at) ?? "—")
                  : "—"
              }
              tone="neutral"
            />
          </span>
          <StatusDivider />
          {/* F1: relabel scrape_seconds — it is processing duration (how long
              scrape+classify took), NOT data freshness. */}
          <span title="Analiz süresi: kazıma + sınıflandırma kaç saniye sürdü. Verinin tazeliği DEĞİL — bunun için 'VERİ ALINDI'ya bakın.">
            <StatusSection
              label="ANALİZ SÜRESİ"
              value={data?.scrape_seconds != null ? `${data.scrape_seconds}s` : "—"}
              tone="neutral"
            />
          </span>
          <StatusDivider />
          <StatusSection
            label="CONF"
            value={
              data?.scores?.confidence != null
                ? formatNumber(data.scores.confidence, 2, { minimumFractionDigits: 2 })
                : "—"
            }
            tone="neutral"
          />
        </section>
        {/* Control bar */}
        <div style={controlBar}>
          <label style={fieldLabel} htmlFor="xsen-query">
            <span style={fieldHint}>Query</span>
            <input
              id="xsen-query"
              type="text"
              value={draftQuery}
              spellCheck={false}
              onChange={(e) => setDraftQuery(e.target.value)}
              style={textInput}
              placeholder="AAPL  /  $TSLA  /  bitcoin"
            />
          </label>
          <label style={fieldLabel} htmlFor="xsen-posts">
            <span style={fieldHint}>Posts</span>
            <input
              id="xsen-posts"
              type="number"
              min={20}
              max={500}
              value={draftLimit}
              onChange={(e) => setDraftLimit(Number(e.target.value))}
              style={numberInput}
            />
          </label>
          <div style={fieldLabel} role="group" aria-label="Since">
            <span style={fieldHint}>Since</span>
            <div className="u-flex u-gap-4">
              {SINCE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setDraftSince(opt.value)}
                  style={{
                    ...chipButton,
                    background: draftSince === opt.value ? "var(--accent)" : "var(--surface-2)",
                    color: draftSince === opt.value ? "var(--accent-on)" : "var(--text-secondary)",
                    borderColor:
                      draftSince === opt.value ? "var(--accent)" : "var(--border-subtle)",
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
          <label style={fieldLabel} htmlFor="xsen-lang">
            <span style={fieldHint}>Lang</span>
            <input
              id="xsen-lang"
              type="text"
              value={draftLang}
              maxLength={5}
              onChange={(e) => setDraftLang(e.target.value.toLowerCase())}
              style={{ ...textInput, width: 60 }}
            />
          </label>
          <button
            type="button"
            className="btn btn--primary xsen-run-btn"
            onClick={run}
            disabled={state === "loading"}
            aria-busy={state === "loading"}
            aria-label={state === "loading" ? "X analizi çalışıyor" : "X analizini çalıştır"}
            title={state === "loading" ? "Analiz çalışıyor — bitince yeniden çalıştırabilirsiniz" : undefined}
          >
            {state === "loading" ? "Working…" : "Run"}
          </button>
        </div>

        <PaneBody className="xsen-pane-body">
          {/* A6: SR-only polite live region — announces the load result once
              (gated by lastAnnouncedRef) so SRs don't re-read on every render. */}
          <div className="u-sr-only" role="status" aria-live="polite">
            {announcement}
          </div>
          {/*
            Bug #10e: when /api/x/health returns {ok:false} because the
            RoBERTa load timed out, render an explicit "model offline"
            empty-state rather than letting the user press Run and watch
            it spin/fail. The state==="idle" guard keeps the message off
            screen while data is on screen.
          */}
          {health?.ok === false && state === "idle" && !data ? (
            <Empty
              title="Sentiment model offline"
              body={
                <div className="xsen-empty-body">
                  <p className="xsen-empty-body__hint">
                    The X sentiment classifier did not finish loading. Try again in a minute — the
                    sidecar retries the load on the next health probe.
                  </p>
                  {health?.load_error ? (
                    <p className="xsen-empty-body__hint xsen-empty-body__hint--mute">
                      Detail: {health.load_error}
                    </p>
                  ) : null}
                </div>
              }
            />
          ) : data?.verdict === "insufficient_data" ? (
            <Empty
              title="Not enough data for a verdict"
              body={
                <div className="xsen-empty-body xsen-empty-body--wide">
                  <p className="xsen-empty-body__hint">
                    {data.warning ??
                      `Only ${data.post_count ?? 0} post(s) scraped — need at least 5 for a reliable verdict.`}
                  </p>
                  <p className="xsen-empty-body__hint">
                    Try a more popular ticker or wait a minute for the scraper rate budget to refill.
                  </p>
                </div>
              }
            />
          ) : state === "idle" && !data ? (
            <Empty
              title="Ready to scan X"
              body={
                <div className="xsen-empty-body">
                  <p className="xsen-empty-body__hint">
                    Type a ticker / phrase above and press <strong>Run</strong>. The AI will scrape
                    recent X posts (no auth, no API limit) and produce a bullish gauge plus
                    sentiment / emotion / topic distribution.
                  </p>
                  <p className="xsen-empty-body__hint">
                    Cold model load adds ~30 s on the first call. Subsequent calls hit the warm
                    classifier and return in &lt;5 s.
                  </p>
                </div>
              }
            />
          ) : state === "loading" && !data ? (
            <div className="xsen-loading">
              <Skeleton height={92} />
              <Skeleton height={140} />
              <Skeleton height={120} />
            </div>
          ) : state === "error" ? (
            <Empty title="X analyze failed" body={error ?? "Unknown error"} />
          ) : !data || data.post_count === 0 ? (
            <Empty
              title="No posts found"
              body={
                <div className="xsen-empty-body xsen-empty-body--wide">
                  <p className="xsen-empty-body__hint">
                    {data?.warning ??
                      "All scraper backends returned empty for this query."}
                  </p>
                  <p className="xsen-empty-body__hint">
                    Popular tickers (AAPL / TSLA / NVDA) can hit Brave Search rate limits during back-to-back queries — wait ~60 s and press Run again, the in-process cache will then serve the page instantly. Less popular symbols (e.g. crypto pairs, smaller caps) usually return on the first try.
                  </p>
                  <div className="xsen-empty-suggestions">
                    {["TSLA", "NVDA", "MSFT", "bitcoin", "ETHUSDT"].map((suggestion) => (
                      <button
                        key={suggestion}
                        type="button"
                        className="btn btn--ghost u-btn-mini"
                        onClick={() => {
                          setDraftQuery(suggestion);
                          setQuery(suggestion);
                          setRunId((id) => id + 1);
                        }}
                      >
                        try {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              }
            />
          ) : (
            <div className="xsen-results">
              {/* F4 + F2: honest disclosure — local RoBERTa model (not an LLM /
                  keyword heuristic) + search-result cache caveat. */}
              <ScoringDisclosure fetchedAt={data.fetched_at} />
              {/* KPI ribbon */}
              <SentimentKPIRibbon data={data} />
              {/* Bullish gauge band */}
              <BullishBand data={data} />
              {/* Topic chips with frequency */}
              <TopicChipsRow pct={data.distributions?.topic_pct ?? {}} />
              {/* Distribution cards (sentiment / emotion / topic) */}
              <div className="xsen-dist-grid">
                <DistributionCard
                  title="Sentiment"
                  pct={data.distributions?.sentiment_pct ?? {}}
                  toneFor={sentimentTone}
                />
                <DistributionCard
                  title="Emotion"
                  pct={data.distributions?.emotion_pct ?? {}}
                  toneFor={emotionTone}
                />
                <DistributionCard
                  title="Topic"
                  pct={data.distributions?.topic_pct ?? {}}
                  toneFor={() => "neutral"}
                />
              </div>
              {/* Summary prose */}
              {data.summary_tr ? <SummaryProse text={data.summary_tr} /> : null}
              {/* Tweet sample feed */}
              <ExamplesSection
                examples={examples}
                order={sentimentOrder}
                expandedKey={expandedTweet}
                onToggle={(key) => setExpandedTweet((prev) => (prev === key ? null : key))}
              />
              <EngagementCard data={data} />
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <span>scraper · {scrapeSource}</span>
          <span>device · {data?.device ?? "—"}</span>
          <span title="Veri alındı: bu sonucun sunulduğu an (arama listesi ~30 dk'ya kadar önbellekli olabilir)">
            alındı · {data?.fetched_at ? (relativeTimeLabel(data.fetched_at) ?? "—") : "—"}
          </span>
          <span title="Analiz süresi (kazıma + sınıflandırma), tazelik değil">
            analiz · {data?.scrape_seconds != null ? `${data.scrape_seconds}s` : "—"}
          </span>
          <span>
            conf ·{" "}
            {data?.scores?.confidence != null
              ? formatNumber(data.scores.confidence, 2, { minimumFractionDigits: 2 })
              : "—"}
          </span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function ScoringDisclosure({ fetchedAt }: { fetchedAt?: string }) {
  // F4: reinforce the HONEST AI claim — the sentiment label comes from a
  // locally-run fine-tuned RoBERTa (`showme_x_v1`, 3 task heads), NOT an LLM
  // and NOT a keyword heuristic.
  // F2: search-result tweet-ID lists are cached up to ~30 min per query, while
  // per-post engagement (likes/retweets) is re-fetched each run — so the feed
  // is near-real-time, not guaranteed live.
  const fresh = fetchedAt ? relativeTimeLabel(fetchedAt) : null;
  return (
    <p data-testid="xsen-scoring-note" style={scoringNoteStyle}>
      Duygu skoru, yerel çalışan ince ayarlı bir <strong className="u-text-primary">RoBERTa</strong>{" "}
      modeliyle (<code>showme_x_v1</code>, 3 görev başlığı) üretilir — LLM ya da anahtar-kelime
      sezgiseli değildir. Arama sonuçları sorgu başına ~30 dakikaya kadar önbelleğe alınmış olabilir;
      her gönderinin etkileşimi (beğeni/RT) her çalıştırmada tazelenir — yani akış gerçek zamanlıya
      yakındır, garantili canlı değildir.
      {fresh ? <span className="u-text-mute"> Veri alındı: {fresh}.</span> : null}
    </p>
  );
}

function SentimentKPIRibbon({ data }: { data: XAnalysisResponse }) {
  const sentPct = data.distributions?.sentiment_pct ?? {};
  const emoPct = data.distributions?.emotion_pct ?? {};
  // Read "positive" / "bullish" off sentiment dist (case-insensitive)
  const posKey = Object.keys(sentPct).find((k) => /positive|bullish/i.test(k));
  const negKey = Object.keys(sentPct).find((k) => /negative|bearish/i.test(k));
  const neuKey = Object.keys(sentPct).find((k) => /neutral/i.test(k));
  const positivePct = posKey ? sentPct[posKey] : 0;
  const negativePct = negKey ? sentPct[negKey] : 0;
  const neutralPct = neuKey ? sentPct[neuKey] : 0;
  const topEmotion = data.dominant?.emotion ?? "—";
  const topEmotionPct = topEmotion in emoPct ? emoPct[topEmotion] : 0;
  return (
    <section style={kpiRibbonGrid}>
      <StatCard
        label="Positive"
        value={formatPercent(positivePct, { digits: 1 })}
        caption="of posts"
        tone="positive"
      />
      <StatCard
        label="Negative"
        value={formatPercent(negativePct, { digits: 1 })}
        caption="of posts"
        tone="negative"
      />
      <StatCard
        label="Neutral"
        value={formatPercent(neutralPct, { digits: 1 })}
        caption="of posts"
        tone="neutral"
      />
      <StatCard
        label="Top emotion"
        value={topEmotion}
        caption={formatPercent(topEmotionPct, { digits: 1 })}
        tone="neutral"
      />
    </section>
  );
}

function BullishBand({ data }: { data: XAnalysisResponse }) {
  const score = data.scores?.bullish_score_engagement_weighted ?? 0;
  const avgScore = data.scores?.bullish_score_avg ?? 0;
  return (
    <div style={bullishBandStyle}>
      <div className="xsen-band-row">
        <div className="xsen-band-row__left">
          <Pill tone={moodTone(data.mood)} variant="soft" withDot>
            {data.mood ?? "—"}
          </Pill>
          <strong
            className="xsen-band-score u-mono"
            style={{ color: bullishColor(score) }}
            title="engagement-weighted bullish score"
          >
            {formatSignedDelta(score, 2)}
          </strong>
          <span className="xsen-band-avg">
            avg <span className="u-mono">{formatSignedDelta(avgScore, 2)}</span> · conf{" "}
            <span className="u-mono">
              {data.scores?.confidence != null
                ? formatNumber(data.scores.confidence, 2, { minimumFractionDigits: 2 })
                : "—"}
            </span>
          </span>
        </div>
        <span className="xsen-band-meta">
          posts {data.post_count} · dom {data.dominant?.sentiment ?? "—"} · topic {data.dominant?.topic ?? "—"}
        </span>
      </div>
      <BullishGauge score={score} />
    </div>
  );
}

function BullishGauge({ score }: { score: number }) {
  const clamped = Math.max(-1, Math.min(1, score));
  const positiveWidth = clamped >= 0 ? clamped * 50 : 0;
  const negativeWidth = clamped < 0 ? Math.abs(clamped) * 50 : 0;
  return (
    <div
      className="xsen-gauge"
      role="meter"
      aria-label="Yükseliş skoru"
      aria-valuenow={clamped}
      aria-valuemin={-1}
      aria-valuemax={1}
    >
      <div
        className="xsen-gauge__neg"
        style={{
          ["--u-left" as string]: `${50 - negativeWidth}%`,
          ["--u-width" as string]: `${negativeWidth}%`,
        }}
      />
      <div
        className="xsen-gauge__pos"
        style={{ ["--u-width" as string]: `${positiveWidth}%` }}
      />
      <div className="xsen-gauge__mid" />
      {[-0.5, 0.5].map((tick) => (
        <div
          key={tick}
          className="xsen-gauge__tick"
          style={{ ["--u-left" as string]: `${50 + tick * 50}%` }}
        />
      ))}
    </div>
  );
}

function TopicChipsRow({ pct }: { pct: Record<string, number> }) {
  const entries = Object.entries(pct).sort((a, b) => b[1] - a[1]).slice(0, 12);
  if (!entries.length) return null;
  const total = entries.reduce((sum, [, v]) => sum + v, 0) || 1;
  return (
    <section style={topicChipsWrap}>
      <span style={topicChipsLabel}>TOPICS</span>
      {entries.map(([topic, value]) => {
        const share = (value / total) * 100;
        // Frequency is encoded by chip background opacity (0.10..0.42)
        const intensity = Math.max(0.1, Math.min(0.42, share / 100 * 0.6 + 0.1));
        return (
          <span
            key={topic}
            style={{
              ...topicChipBase,
              background: `color-mix(in srgb, var(--accent) ${(intensity * 100).toFixed(0)}%, transparent)`,
            }}
            title={`${topic} · ${value.toFixed(1)}% (${share.toFixed(1)}% of dist)`}
          >
            <span className="u-text-accent">{topic}</span>
            <span className="u-text-secondary u-text-9">{value.toFixed(0)}%</span>
          </span>
        );
      })}
    </section>
  );
}

function DistributionCard({
  title,
  pct,
  toneFor,
}: {
  title: string;
  pct: Record<string, number>;
  toneFor: (label: string) => "positive" | "negative" | "warn" | "neutral" | "accent";
}) {
  const entries = Object.entries(pct).sort((a, b) => b[1] - a[1]);
  // UA-HIGH-12: stack-safe.
  const max = Math.max(maxOf(entries.map(([, v]) => v)), 1);
  // A5: full breakdown for screen readers (e.g. "Sentiment dağılımı:
  // positive %67, neutral %20, negative %13"). The visual bars carry the same
  // information sighted users see.
  const ariaLabel = entries.length
    ? `${title} dağılımı: ${entries
        .map(([label, value]) => `${label} ${formatPercent(value, { digits: 0 })}`)
        .join(", ")}`
    : `${title} dağılımı: veri yok`;
  return (
    <Card>
      <CardHeader trailing={`${entries.length}`}>{title}</CardHeader>
      <div className="u-grid-gap-6" role="img" aria-label={ariaLabel}>
        {entries.length === 0 ? (
          <span className="u-text-mute u-text-11">No data</span>
        ) : (
          entries.map(([label, value]) => {
            const tone = toneFor(label);
            const color = toneColor(tone);
            return (
              <div key={label} className="xsen-dist-row">
                <span className="u-text-11 u-text-secondary" title={label}>
                  {label}
                </span>
                <div className="xsen-dist-row__track">
                  <div
                    className="xsen-dist-row__fill"
                    style={{
                      ["--u-width" as string]: `${(value / max) * 100}%`,
                      ["--u-color" as string]: color,
                    }}
                  />
                </div>
                <span className="xsen-dist-row__label u-mono">
                  {formatPercent(value, { digits: 1 })}
                </span>
              </div>
            );
          })
        )}
      </div>
    </Card>
  );
}

function SummaryProse({ text }: { text?: string }) {
  if (!text) return null;
  return (
    <div
      style={{
        border: "1px solid color-mix(in srgb, var(--accent) 22%, transparent)",
        borderRadius: "var(--radius-md)",
        background: "var(--accent-soft)",
        padding: "10px 12px",
        fontSize: 12,
        lineHeight: 1.55,
        color: "var(--text-secondary)",
      }}
    >
      {text}
    </div>
  );
}

function ExamplesSection({
  examples,
  order,
  expandedKey,
  onToggle,
}: {
  examples: Record<string, XExample[]>;
  order: string[];
  expandedKey: string | null;
  onToggle: (key: string) => void;
}) {
  if (!order.length) return null;
  return (
    <div className="u-grid-gap-10">
      {order.map((kind) => {
        const items = examples[kind] ?? [];
        if (!items.length) return null;
        return (
          <Card key={kind}>
            <CardHeader trailing={`${items.length}`}>
              <span className="u-inline-flex u-items-center u-gap-6">
                Top {kind} tweets
                <Pill tone={sentimentTone(kind)} variant="soft" withDot={false}>
                  {kind}
                </Pill>
              </span>
            </CardHeader>
            <div className="u-grid-gap-6">
              {items.map((item) => {
                const key = `${kind}-${item.url || item.text.slice(0, 60)}`;
                const isExpanded = expandedKey === key;
                // F3: per-post age from the real `date`. Honest "tarih yok"
                // when the date is absent/unparseable — never fabricated "now".
                const ago = relativeTimeLabel(item.date);
                return (
                  <article
                    key={key}
                    style={tweetCardStyle(isExpanded)}
                  >
                    <div style={tweetRowGrid}>
                      <SentimentDotInline sentiment={kind} />
                      <div className="u-min-w-0">
                        <div style={tweetMetaLine}>
                          <strong className="xsen-tweet__user" title={item.user}>
                            @{item.user || "x"}
                          </strong>
                          <span className="u-text-mute u-text-10 u-mono">
                            ❤ {formatNumber(item.likes ?? 0)} · ↻ {formatNumber(item.retweets ?? 0)} · score {item.score?.toFixed?.(2) ?? "—"}
                          </span>
                          <span
                            className="u-text-mute u-text-10"
                            title={item.date || "tarih yok"}
                            data-testid="xsen-tweet-date"
                          >
                            · {ago ?? "tarih yok"}
                          </span>
                          <span className="u-flex-1" />
                          <button
                            type="button"
                            onClick={() => onToggle(key)}
                            className="btn btn--ghost xsen-tweet__toggle"
                            aria-expanded={isExpanded}
                            aria-label={isExpanded ? "gerekçeyi kapat" : "gerekçeyi aç"}
                          >
                            {isExpanded ? "−" : "+"}
                          </button>
                        </div>
                        <p className="xsen-tweet__text">{item.text}</p>
                        <div style={tweetTagRow}>
                          <Pill tone={emotionTone(item.emotion)} variant="soft" withDot={false}>
                            {item.emotion}
                          </Pill>
                          <Pill tone="muted" variant="soft" withDot={false}>
                            {item.topic}
                          </Pill>
                          {item.url ? (
                            <a
                              href={item.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="xsen-tweet__open"
                              aria-label={`@${item.user || "x"} gönderisini aç`}
                            >
                              open ↗
                            </a>
                          ) : null}
                        </div>
                        {isExpanded ? (
                          <div style={tweetRationaleStyle}>
                            <strong className="xsen-tweet__rationale-title">RoBERTa sınıflandırması</strong>
                            <p className="xsen-tweet__rationale">
                              RoBERTa modeli <strong className="u-text-primary">{kind}</strong> · duygu <strong className="u-text-primary">{item.emotion}</strong> · tema <strong className="u-text-primary">{item.topic}</strong> olarak sınıflandırdı.
                              Etkileşim-ağırlıklı skor {item.score?.toFixed?.(3) ?? "—"} (beğeni: {formatNumber(item.likes ?? 0)}, RT: {formatNumber(item.retweets ?? 0)}).
                            </p>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          </Card>
        );
      })}
    </div>
  );
}

function SentimentDotInline({ sentiment }: { sentiment: string }) {
  const tone = sentimentTone(sentiment);
  const color =
    tone === "positive"
      ? "var(--positive)"
      : tone === "negative"
        ? "var(--negative)"
        : tone === "warn"
          ? "var(--warn)"
          : tone === "accent"
            ? "var(--accent)"
            : "var(--text-mute)";
  // A4: color is not the sole signal — label the dot for screen readers.
  const label =
    tone === "positive"
      ? "olumlu gönderi"
      : tone === "negative"
        ? "olumsuz gönderi"
        : "nötr gönderi";
  return (
    <span
      className="xsen-sent-dot"
      style={{ ["--u-color" as string]: color }}
      role="img"
      aria-label={label}
    />
  );
}

function EngagementCard({ data }: { data: XAnalysisResponse }) {
  const eng = data.engagement;
  if (!eng) return null;
  return (
    <Card>
      <CardHeader trailing="totals">Engagement</CardHeader>
      <div className="xsen-engage-grid">
        <EngageTile label="avg likes" value={formatNumber(eng.avg_likes, 1)} helper="per post" tone="accent" />
        <EngageTile label="avg retweets" value={formatNumber(eng.avg_retweets, 1)} helper="per post" tone="accent" />
        <EngageTile label="total likes" value={formatNumber(eng.total_likes)} helper="window" tone="neutral" />
        <EngageTile label="total retweets" value={formatNumber(eng.total_retweets)} helper="window" tone="neutral" />
      </div>
    </Card>
  );
}

function EngageTile({
  label,
  value,
  helper,
  tone,
}: {
  label: string;
  value: string;
  helper: string;
  tone: "positive" | "negative" | "warn" | "neutral" | "accent";
}) {
  const accent: Record<string, string> = {
    positive: "var(--positive)",
    negative: "var(--negative)",
    warn: "var(--warn)",
    accent: "var(--accent)",
    neutral: "var(--text-mute)",
  };
  return (
    <div
      className="xsen-engage-tile"
      style={{ ["--u-accent" as string]: accent[tone] }}
    >
      <div style={fieldHint}>{label}</div>
      <div className="xsen-engage-tile__value" title={value}>{value}</div>
      <div className="xsen-engage-tile__helper" title={helper}>{helper}</div>
    </div>
  );
}

function XSENHelp({ health }: { health: XHealth | null }) {
  // Bug #10e: scraper key may be missing when the model load times out;
  // optional-chain every access to avoid the TypeError that took down the
  // whole pane.
  return (
    <div className="fn-help-grid">
      <strong>XSEN · X Sentiment AI</strong>
      <span className="fn-help-grid__hint">
        Multi-strategy account-free X scraper feeds a locally-run fine-tuned RoBERTa model
        (<code>showme_x_v1</code>, three task heads: sentiment, emotion, topic). The label is the
        model's — not an LLM, not a keyword heuristic. Scraping order: Brave→syndication, then
        Nitter mirror pool, then Jina reader proxy. The model lives inside the .app bundle.
      </span>
      {/* F2: honest freshness caveat — search results cache, engagement refreshes. */}
      <span className="fn-help-grid__hint">
        Freshness: search-result tweet lists may be cached up to ~30 min per query, while per-post
        engagement (likes/retweets) is refreshed each run — so the feed is near-real-time, not
        guaranteed live. The "VERİ ALINDI" chip shows when this result was served; "ANALİZ SÜRESİ"
        is the scrape+classify processing time, NOT data age.
      </span>
      <span className="fn-help-grid__hint-mute">
        guest token: {health?.scraper?.guest_token_present ? "active" : "off"} · nitter mirrors:
        {" "}
        {health?.scraper?.nitter_mirrors_active?.length ?? 0}
      </span>
    </div>
  );
}

function moodTone(mood?: string): "positive" | "negative" | "warn" | "neutral" {
  if (mood === "bullish") return "positive";
  if (mood === "bearish") return "negative";
  return "warn";
}

function sentimentTone(label: string): "positive" | "negative" | "neutral" | "warn" | "accent" {
  const text = label.toLowerCase();
  if (text === "positive" || text === "bullish") return "positive";
  if (text === "negative" || text === "bearish") return "negative";
  if (text === "neutral") return "neutral";
  return "accent";
}

function emotionTone(label: string): "positive" | "negative" | "warn" | "neutral" | "accent" {
  const text = label.toLowerCase();
  if (text === "joy" || text === "love" || text === "optimism") return "positive";
  if (text === "anger" || text === "fear" || text === "sadness" || text === "disgust") return "negative";
  if (text === "surprise") return "warn";
  return "accent";
}

function toneColor(tone: string): string {
  switch (tone) {
    case "positive":
      return "color-mix(in srgb, var(--positive) 78%, transparent)";
    case "negative":
      return "color-mix(in srgb, var(--negative) 78%, transparent)";
    case "warn":
      return "color-mix(in srgb, var(--warn) 78%, transparent)";
    case "accent":
      return "color-mix(in srgb, var(--accent) 78%, transparent)";
    default:
      return "color-mix(in srgb, var(--neutral) 60%, transparent)";
  }
}

function bullishColor(score: number): string {
  if (score >= 0.18) return "var(--positive)";
  if (score <= -0.18) return "var(--negative)";
  return "var(--warn)";
}

function orderSentiments(keys: string[]): string[] {
  const priority = ["positive", "bullish", "neutral", "negative", "bearish"];
  return [...keys].sort((a, b) => {
    const ai = priority.indexOf(a.toLowerCase());
    const bi = priority.indexOf(b.toLowerCase());
    if (ai === -1 && bi === -1) return a.localeCompare(b);
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });
}

function sinceToDate(key: SinceKey): string | undefined {
  const days = { "1d": 1, "3d": 3, "7d": 7, "30d": 30 }[key];
  if (!days) return undefined;
  const d = new Date(Date.now() - days * 86400 * 1000);
  return d.toISOString().slice(0, 10);
}

// ─── styles ────────────────────────────────────────────────────────────

const toolbar: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  flexWrap: "wrap",
};

const statusStrip: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 0,
  height: 22,
  padding: "0 8px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const controlBar: CSSProperties = {
  display: "flex",
  alignItems: "end",
  gap: 10,
  padding: "10px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  flexWrap: "wrap",
};

const fieldLabel: CSSProperties = {
  display: "grid",
  gap: 4,
  minWidth: 120,
};

const fieldHint: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
};

const textInput: CSSProperties = {
  height: 26,
  padding: "0 8px",
  background: "var(--surface-1)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
  outline: "none",
  minWidth: 160,
};

const numberInput: CSSProperties = {
  ...textInput,
  width: 78,
  minWidth: 60,
};

const chipButton: CSSProperties = {
  height: 22,
  padding: "0 9px",
  borderRadius: 11,
  border: "1px solid var(--border-subtle)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const scoringNoteStyle: CSSProperties = {
  margin: 0,
  padding: "8px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-2)",
  fontSize: 11,
  lineHeight: 1.5,
  color: "var(--text-secondary)",
};

const kpiRibbonGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
  gap: 8,
};

const bullishBandStyle: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  padding: "10px 12px",
  background: "var(--surface-2)",
  display: "grid",
  gap: 8,
};

const topicChipsWrap: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  flexWrap: "wrap",
  padding: "8px 10px",
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
};

const topicChipsLabel: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  marginRight: 4,
};

const topicChipBase: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "3px 9px",
  borderRadius: 11,
  border: "1px solid var(--border-subtle)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  cursor: "default",
};

const tweetCardStyle = (expanded: boolean): CSSProperties => ({
  border: "1px solid var(--border-subtle)",
  borderLeft: expanded ? "2px solid var(--accent)" : "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  padding: 10,
  background: expanded ? "var(--surface-2)" : "var(--surface-1)",
  transition: "background var(--motion-fast), border-left-color var(--motion-fast)",
});

const tweetRowGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "12px minmax(0, 1fr)",
  gap: 8,
  alignItems: "start",
};

const tweetMetaLine: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const tweetTagRow: CSSProperties = {
  display: "flex",
  gap: 6,
  marginTop: 6,
  alignItems: "center",
};

const tweetRationaleStyle: CSSProperties = {
  marginTop: 8,
  padding: "8px 10px",
  background: "var(--accent-soft)",
  border: "1px solid color-mix(in srgb, var(--accent) 32%, transparent)",
  borderRadius: "var(--radius-sm)",
};
