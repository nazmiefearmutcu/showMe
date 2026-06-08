/**
 * BOTS — Bot supervisor pane (plural; distinct from D's per-bot BOT pane).
 *
 * Three sections: aggregate KPI strip, per-bot table, unified signal feed.
 * Polling is driven by `useBotEcosystemPolling` so BOTS and PERF stay frame-
 * aligned (BUG #10 fix).  Legacy 10s setInterval was removed.
 *
 * Bug fixes shipped here:
 *   H-SUP-2 — "Sinyaller" column reads bot.signal_count (Agent 2 field) when
 *             present, with a feed-derived fallback that tooltips "(son N)".
 *   H-SUP-4 — bot.permission_revoked renders a red "izin iptal" badge so
 *             users see a stale live bot before clicking through.
 *   BUG #6  — timestamps render in the user's local timezone instead of a
 *             UTC ISO slice; KPI bucket logic (_localDateOf) already does
 *             this, so the table matches.
 *   BUG #11 — KPI refresh button moved next to the table heading and
 *             relabeled "Tümünü yenile".
 *
 * Terminal-grade pass (real supervision health, honesty, a11y, states):
 *   F1 — health-aware status Pill: OFF / STUCK / DEGRADED / LIVE / SHADOW,
 *        derived from is_running + last_action, with an accessible name.
 *   F2 — last-tick freshness ("Nm ago") computed from a single per-render
 *        `now`; stale ticks are de-emphasised; null renders "—" honestly.
 *   F3 — feed rows flagged with a warn badge when a live order was sized on
 *        the fallback ($10k) equity (equity_source === "fallback_10k").
 *   F4 — Skeleton while first load is in flight; design-system Empty for
 *        empty bot/feed tables; error region is a polite live region.
 *   F5 — both tables carry caption + scope + aria-label + numeric grid.
 *   F6 — refresh aria-label + busy state; feed window disclosed; KPI strip
 *        shows an at-a-glance Stuck/Degraded count.
 */
import { useMemo, useRef } from "react";
import {
  useBotsSupervisionStore,
  type FeedSignal,
  type SupervisedBot,
} from "@/lib/bots-supervision-store";
import { useBotEcosystemPolling } from "@/lib/useBotEcosystemPolling";
import { formatPrice } from "@/lib/format";
import { Empty, Pill, SkeletonRow } from "@/design-system";

// Sentinel the backend stamps onto a SignalEntry whose live order was sized
// on the fallback equity ($10k) rather than real broker equity.
const FALLBACK_EQUITY_SOURCE = "fallback_10k";

// F2 — a tick older than this is rendered de-emphasised. 15 min ≈ comfortably
// longer than any sane bot tick interval (the slowest, 1d/4h bots tick on a
// ≤3600s cadence), so a fresh-but-slow bot isn't falsely flagged.
const STALE_THRESHOLD_MS = 15 * 60 * 1000;

// The feed limit the store requests (loadAll's default). Disclosed in the
// feed heading so the supervisor knows the window size.
const FEED_WINDOW = 50;

type HealthTone = "negative" | "warn" | "muted";

/**
 * F1 — derive a supervision health status from the bot's runtime fields.
 *
 *   !enabled                                   → OFF       (muted)
 *   enabled && is_running === false            → STUCK     (negative, dot)
 *   enabled && is_running && last_action skip  → DEGRADED  (warn)
 *   enabled && is_running && mode === live     → LIVE      (negative)
 *   enabled && is_running && mode !== live     → SHADOW    (warn)
 *
 * Backward compat: when `is_running` is null/undefined (older payload, OR the
 * backend's "unknown" sentinel when runner-introspection failed — P2-B) we
 * fall back to the prior enabled/mode behaviour so LIVE/SHADOW/OFF still
 * resolve and a transient runner error does NOT flash every bot as STUCK.
 */
function deriveHealth(bot: SupervisedBot): { tone: HealthTone; label: string; withDot: boolean } {
  if (!bot.enabled) return { tone: "muted", label: "OFF", withDot: false };
  const live = bot.mode === "live";
  // Older payload (undefined) OR honest "unknown" (null, P2-B): keep the
  // legacy live/shadow split. `== null` matches BOTH null and undefined.
  if (bot.is_running == null) {
    return live
      ? { tone: "negative", label: "LIVE", withDot: true }
      : { tone: "warn", label: "SHADOW", withDot: true };
  }
  if (bot.is_running === false) {
    return { tone: "negative", label: "STUCK", withDot: true };
  }
  if (bot.last_action === "skipped") {
    return { tone: "warn", label: "DEGRADED", withDot: true };
  }
  return live
    ? { tone: "negative", label: "LIVE", withDot: true }
    : { tone: "warn", label: "SHADOW", withDot: true };
}

/** True when a bot's derived status is one a supervisor must act on. */
function isUnhealthy(bot: SupervisedBot): boolean {
  const { label } = deriveHealth(bot);
  return label === "STUCK" || label === "DEGRADED";
}

function StatusPill({ bot }: { bot: SupervisedBot }) {
  const { tone, label, withDot } = deriveHealth(bot);
  // F1 — Pill carries the visible label; the wrapper gives it an accessible
  // name so screen readers + keyboard users get "Durum: STUCK/DEGRADED/LIVE/…".
  //
  // P2-A — this is a plain labelled <span>, NOT role="status". With N rows and
  // a 10s poll that re-renders the table, a per-row live region re-announces
  // every status on every cycle (SR-spam). The single pane-level summary live
  // region (SupervisionSummaryLive) carries the only announcement instead.
  return (
    <span aria-label={`Durum: ${label}`}>
      <Pill tone={tone} variant="soft" withDot={withDot}>
        {label}
      </Pill>
    </span>
  );
}

/**
 * P2-A — the SINGLE supervision live region. Announces "N bot, M
 * stuck/degraded" but only when the count actually changes: a `useRef` guards
 * the last announced string so a poll that yields an identical summary does
 * NOT mutate the DOM text node (and thus does not re-trigger the SR
 * announcement). Visually hidden; placed near the KPI strip.
 */
function SupervisionSummaryLive({ total, unhealthy }: { total: number; unhealthy: number }) {
  const summary = `${total} bot, ${unhealthy} stuck/degraded`;
  const lastRef = useRef<string | null>(null);
  // Only the changed summary reaches the DOM; an identical poll keeps the
  // previous text node, so the live region stays quiet.
  if (summary !== lastRef.current) {
    lastRef.current = summary;
  }
  return (
    <span className="u-sr-only" role="status" data-testid="bots-supervision-summary">
      {lastRef.current}
    </span>
  );
}

function PermRevokedBadge() {
  // H-SUP-4 UI half — backend cascade-disable is the real fix; this is the
  // visual warning so users notice a stale-permission bot in the supervisor.
  return (
    <span
      data-testid="bots-perm-revoked-badge"
      title="Bu botun credential trade izni iptal edilmiş; emirler reddediliyor."
      style={{ marginLeft: 6, display: "inline-block" }}
    >
      <Pill tone="negative" variant="soft" withDot={false}>
        İZİN İPTAL
      </Pill>
    </span>
  );
}

/** Render an ISO/RFC-3339 timestamp in the user's local zone (BUG #6). */
function formatLocalTimestamp(ts: string | undefined | null): string {
  if (!ts) return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts.slice(0, 19);
  // navigator.language available in jsdom + Chromium runtime; falls back to
  // the host's default locale when undefined.
  const locale = (typeof navigator !== "undefined" && navigator.language) || undefined;
  return d.toLocaleString(locale);
}

/**
 * F2 — relative "Nm ago" from a single `now` captured per render. Returns the
 * em-dash sentinel honestly when no timestamp exists and flags staleness so
 * the caller can de-emphasise an old tick. Kept pure + `now`-injected so the
 * date-frozen tests stay deterministic.
 */
function relativeTickAge(ts: string | undefined | null, now: number): { text: string; stale: boolean } {
  if (!ts) return { text: "—", stale: false };
  const t = new Date(ts).getTime();
  if (Number.isNaN(t)) return { text: "—", stale: false };
  const deltaMs = Math.max(0, now - t);
  const stale = deltaMs > STALE_THRESHOLD_MS;
  const sec = Math.floor(deltaMs / 1000);
  if (sec < 60) return { text: `${sec}s ago`, stale };
  const min = Math.floor(sec / 60);
  if (min < 60) return { text: `${min}m ago`, stale };
  const hr = Math.floor(min / 60);
  if (hr < 24) return { text: `${hr}h ago`, stale };
  const day = Math.floor(hr / 24);
  return { text: `${day}d ago`, stale };
}

function KPIStrip({ unhealthy }: { unhealthy: number }) {
  const stats = useBotsSupervisionStore((s) => s.stats);
  const generatedAt = useBotsSupervisionStore((s) => s.generatedAt);
  return (
    <div style={{ display: "flex", gap: 24, alignItems: "center", padding: "8px 16px",
                  borderBottom: "1px solid var(--border-card)" }}>
      <KPI label="Toplam bot" value={stats.total} />
      <KPI label="Etkin" value={stats.enabled} />
      <KPI label="Canlı" value={stats.live} highlight={stats.live > 0 ? "negative" : undefined} />
      <KPI label="Bugünkü sinyal" value={stats.signals_today} />
      {/* F6 — at-a-glance unhealthy count so a supervisor sees problems
          immediately. Honest 0 when nothing is wrong. */}
      <div data-testid="bots-kpi-unhealthy">
        <KPI
          label="Stuck/Degraded"
          value={unhealthy}
          highlight={unhealthy > 0 ? "warn" : undefined}
        />
      </div>
      <div style={{ marginLeft: "auto", fontSize: 11 }} className="u-text-secondary">
        {generatedAt ? `Son: ${new Date(generatedAt).toLocaleTimeString()}` : ""}
      </div>
    </div>
  );
}

function KPI({ label, value, highlight }: {
  label: string; value: number; highlight?: "negative" | "warn";
}) {
  const cls = value > 0 && highlight === "negative"
    ? "u-text-negative"
    : value > 0 && highlight === "warn"
      ? "u-text-warn"
      : undefined;
  return (
    <div>
      <div style={{ fontSize: 10 }} className="u-text-secondary">{label}</div>
      <div style={{ fontSize: 22, fontWeight: 600 }} className={cls}>
        {value}
      </div>
    </div>
  );
}

/**
 * Resolve the per-bot signal count.  Prefer Agent 2's authoritative
 * `signal_count` field (total entries in signal_log; not feed-limited).
 * Fall back to counting feed rows when missing, but the cell title makes
 * clear that the fallback is constrained to "son N" (the feed limit).
 */
function resolveSignalCount(
  bot: SupervisedBot,
  feedRows: FeedSignal[] | undefined,
): { value: number; tooltip?: string } {
  if (typeof bot.signal_count === "number" && Number.isFinite(bot.signal_count)) {
    return { value: bot.signal_count };
  }
  const fallback = feedRows?.length ?? 0;
  return {
    value: fallback,
    tooltip: `Toplam sayım yok; son ${fallback} sinyal feed'den geliyor.`,
  };
}

function BotTable() {
  const bots = useBotsSupervisionStore((s) => s.bots);
  const feed = useBotsSupervisionStore((s) => s.feed);
  // F2 — single `now` per render so every row's relative age is computed from
  // the same instant (and so a frozen clock makes the test deterministic).
  const now = Date.now();
  // UA-HIGH-19: memoize byBot so the per-row map() loop doesn't rebuild this
  // index on every render unrelated to the feed (e.g. parent KPI strip
  // ticking the polling clock).
  const byBot = useMemo(() => {
    const acc: Record<string, FeedSignal[]> = {};
    for (const s of feed) {
      (acc[s.bot_id] ||= []).push(s);
    }
    return acc;
  }, [feed]);
  if (bots.length === 0) {
    return (
      <div data-testid="bots-empty">
        <Empty title="Henüz bot yok" body="Bir bot oluşturup etkinleştirince burada görünür." />
      </div>
    );
  }
  return (
    <table
      className="terminal-grid-numeric"
      aria-label="Bot denetim tablosu"
      style={{ width: "100%", fontSize: 12, marginTop: 8 }}
    >
      <caption className="u-sr-only">
        Tüm botların denetim özeti — sembol, timeframe, sağlık durumu, sinyal
        sayısı ve son tick tazeliği.
      </caption>
      <thead>
        <tr className="u-text-secondary">
          <th scope="col" align="left">Symbol</th>
          <th scope="col">TF</th>
          <th scope="col">Durum</th>
          <th scope="col" align="right">Sinyaller</th>
          <th scope="col" align="left">Son tick</th>
          <th scope="col" align="left">Son sinyal</th>
        </tr>
      </thead>
      <tbody>
        {bots.map((b) => {
          const sig = byBot[b.id]?.[0];
          const sigCount = resolveSignalCount(b, byBot[b.id]);
          const age = relativeTickAge(b.last_event_at, now);
          return (
            <tr key={b.id} style={{ borderBottom: "1px solid var(--border-card)" }}>
              <td>
                <strong>{b.symbol}</strong>
                {b.permission_revoked && <PermRevokedBadge />}
              </td>
              <td align="center">{b.timeframe}</td>
              <td align="center"><StatusPill bot={b} /></td>
              <td
                align="right"
                title={sigCount.tooltip}
                data-testid={`bots-signal-count-${b.id}`}
              >
                {sigCount.value}
              </td>
              <td
                data-testid={`bots-last-tick-${b.id}`}
                className={age.stale ? "u-text-secondary" : undefined}
                title={b.last_event_at ? formatLocalTimestamp(b.last_event_at) : undefined}
              >
                {age.text}
              </td>
              <td>
                {sig ? (
                  <span>
                    {sig.kind} @ {formatPrice(sig.price)} ({sig.action})
                    <span className="u-text-secondary">
                      {" · " + formatLocalTimestamp(sig.timestamp ?? sig.bar_time)}
                    </span>
                  </span>
                ) : (
                  <span className="u-text-secondary">(no signals)</span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function SignalFeed() {
  const feed = useBotsSupervisionStore((s) => s.feed);
  if (feed.length === 0) {
    return (
      <div data-testid="bots-feed-empty">
        <Empty title="Henüz sinyal yok" body="Etkin botlar tick attıkça sinyaller burada akar." />
      </div>
    );
  }
  return (
    <table
      className="terminal-grid-numeric"
      aria-label="Birleşik sinyal akışı"
      style={{ width: "100%", fontSize: 11, marginTop: 8 }}
    >
      <caption className="u-sr-only">
        Tüm botlardan gelen son sinyaller, en yeni üstte — zaman, bot, tür,
        fiyat ve aksiyon.
      </caption>
      <thead>
        <tr className="u-text-secondary">
          <th scope="col" align="left">Time</th>
          <th scope="col" align="left">Bot</th>
          <th scope="col">Kind</th>
          <th scope="col" align="right">Price</th>
          <th scope="col">Action</th>
        </tr>
      </thead>
      <tbody>
        {feed.map((s) => {
          const isFallback = s.equity_source === FALLBACK_EQUITY_SOURCE;
          // P3-B — stable composite key. The old trailing array index `-${i}`
          // shifted for every row when a newer signal prepended, defeating key
          // stability. Disambiguate same-bar entry/exit via kind + action
          // (both on FeedSignal) instead of the positional index.
          const rowKey = `${s.bot_id}-${s.bar_time}-${s.bar_index}-${s.action ?? ""}-${s.kind ?? ""}`;
          return (
            <tr key={rowKey}>
              <td>{formatLocalTimestamp(s.timestamp ?? s.bar_time)}</td>
              <td>
                <span style={{ background: "var(--bg-elev-2)", padding: "1px 4px", borderRadius: 3 }}>
                  {s.bot_symbol}
                </span>
              </td>
              <td
                align="center"
                className={s.kind === "entry" ? "u-text-positive" : "u-text-warn"}
              >
                {s.kind}
              </td>
              <td align="right">{formatPrice(s.price)}</td>
              <td align="center">
                {s.action}
                {isFallback && (
                  <span
                    data-testid="bots-feed-fallback-equity"
                    title="Bu canlı emir gerçek broker bakiyesi yerine yedek ($10k) bakiye ile boyutlandırıldı."
                    style={{ marginLeft: 6, display: "inline-block" }}
                  >
                    <Pill tone="warn" variant="soft" withDot={false}>
                      ≈$10k
                    </Pill>
                  </span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function BOTSPane() {
  const loadAll = useBotsSupervisionStore((s) => s.loadAll);
  const error = useBotsSupervisionStore((s) => s.error);
  const loading = useBotsSupervisionStore((s) => s.loading);
  const bots = useBotsSupervisionStore((s) => s.bots);

  // BUG #10 — unified polling.  PERF mounts the same hook; once is enough,
  // but mounting it in both panes is safe (each install owns its own
  // interval handle).
  useBotEcosystemPolling();

  // F6 — at-a-glance unhealthy count for the KPI strip.
  const unhealthyCount = useMemo(
    () => bots.filter(isUnhealthy).length,
    [bots],
  );

  // F4 — first-load skeleton: only while loading AND we have nothing yet.
  const firstLoad = loading && bots.length === 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <KPIStrip unhealthy={unhealthyCount} />
      {/* P2-A — the ONLY supervision live region. Announces the at-a-glance
          summary, and only when it changes (guarded inside the component) so
          the 10s poll doesn't re-announce all N rows. */}
      <SupervisionSummaryLive total={bots.length} unhealthy={unhealthyCount} />
      <div style={{ overflowY: "auto", padding: "0 16px" }}>
        {/* F4 — async error is an announced live region. Rendered at the pane
            root (outside any bot/feed conditional) so a loadAll error that
            occurs with no bots/feed is still visible. */}
        {error && (
          <div
            data-testid="bots-pane-error"
            role="status"
            className="u-text-negative"
            style={{ padding: 8 }}
          >
            {error}
          </div>
        )}
        {/* BUG #11 — refresh control sits next to the table heading; the
            label spells out that it refreshes the WHOLE supervisor view. */}
        <div style={{ display: "flex", alignItems: "center", margin: "12px 0 4px" }}>
          <h4 style={{ margin: 0 }}>Botlar</h4>
          <button
            data-testid="bots-refresh-all"
            aria-label="Tüm denetim görünümünü yenile"
            aria-busy={loading}
            disabled={loading}
            onClick={() => loadAll()}
            style={{ marginLeft: "auto" }}
          >
            {loading ? "Yenileniyor…" : "Tümünü yenile"}
          </button>
        </div>
        {firstLoad ? (
          <div data-testid="bots-loading" aria-busy="true">
            {Array.from({ length: 5 }).map((_, i) => (
              <SkeletonRow key={i} columns={6} />
            ))}
          </div>
        ) : (
          <BotTable />
        )}
        <h4 style={{ margin: "16px 0 4px" }}>Sinyal akışı (son {FEED_WINDOW} sinyal)</h4>
        <SignalFeed />
      </div>
    </div>
  );
}

export default BOTSPane;
