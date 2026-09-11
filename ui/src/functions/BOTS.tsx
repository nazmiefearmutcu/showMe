/**
 * BOTS — Bot supervisor pane (plural; distinct from D's per-bot BOT pane).
 *
 * Three sections: aggregate KPI strip, per-bot table, unified signal feed.
 * Polling is driven by `useBotEcosystemPolling` so BOTS and PERF stay frame-
 * aligned (BUG #10 fix).  Legacy 10s setInterval was removed.
 *
 * Bug fixes shipped here:
 *   H-SUP-2 — "Signals" column reads bot.signal_count (Agent 2 field) when
 *             present, with a feed-derived fallback that tooltips "(last N)".
 *   H-SUP-4 — bot.permission_revoked renders a red "permission revoked" badge
 *             so users see a stale live bot before clicking through.
 *   BUG #6  — timestamps render in the user's local timezone instead of a
 *             UTC ISO slice; KPI bucket logic (_localDateOf) already does
 *             this, so the table matches.
 *   BUG #11 — KPI refresh button moved next to the table heading and
 *             relabeled "Refresh all".
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
 *   F5 — both tables carry scope + aria-label (DataGrid) + numeric grid.
 *   F6 — refresh aria-label + busy state; feed window disclosed; KPI strip
 *        shows an at-a-glance Stuck/Degraded count.
 *   F10 (fix lane, audit A10) — "Signals today" uses the backend's
 *        authoritative per_bot_signal_count to disclose a truncated feed
 *        window (renders "≥N" instead of silently capping at 50); both
 *        supervision tables migrated to the DataGrid kit with full CSV
 *        exports.
 */
import { useCallback, useMemo, useRef } from "react";
import { useBotsSupervisionStore, type FeedSignal, type SupervisedBot } from "@/lib/bots-supervision-store";
import { useBotEcosystemPolling } from "@/lib/useBotEcosystemPolling";
import { useBotStore } from "@/lib/bot-store";
import { useStrategyStore } from "@/lib/strategy-store";
import { useWorkspace } from "@/lib/workspace";
import { navigate } from "@/lib/router";
import { formatPrice } from "@/lib/format";
import { isKaosRecord } from "@/lib/kaos-venues";
import { KaosEngineBadge, VenueBadges } from "@/functions/KaosBadges";
import {
  buildGridCsv,
  DataGrid,
  downloadGridCsv,
  Empty,
  gridCsvFilename,
  Pill,
  SkeletonRow,
  type DataGridColumn,
  type GridCsvColumn,
} from "@/design-system";

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

// G3 — row-level silence alert. The list payload carries the real per-bot
// cadence as `timeframe` (the finer-grained `tick_interval_seconds` lives on
// the record payload, not on `/api/bots` records). A bot that has produced
// no signal for more than N cadences — measured from its last event, or from
// `created_at` when it has never ticked — is flagged SILENT. An unknown
// timeframe makes no judgment (never guessed).
const SILENCE_CADENCES = 3;
const TIMEFRAME_MS: Record<string, number> = {
  "1m": 60_000,
  "5m": 300_000,
  "15m": 900_000,
  "1h": 3_600_000,
  "4h": 14_400_000,
  "1d": 86_400_000,
};

/**
 * Silence verdict for a bot row. Exported for tests. Returns `null` when no
 * honest judgment is possible (disabled bot, unknown timeframe, unparseable
 * timestamps); otherwise `{silent, cadenceMs}` where `silent` means the age
 * exceeds `SILENCE_CADENCES` cadences.
 */
export function silenceState(
  bot: SupervisedBot,
  now: number,
): { silent: boolean; cadenceMs: number } | null {
  if (!bot.enabled) return null;
  const cadenceMs = TIMEFRAME_MS[bot.timeframe];
  if (!cadenceMs) return null;
  const reference = bot.last_event_at ?? bot.created_at;
  if (!reference) return null;
  const t = new Date(reference).getTime();
  if (Number.isNaN(t)) return null;
  return { silent: now - t > cadenceMs * SILENCE_CADENCES, cadenceMs };
}

function SilencePill({ bot, now }: { bot: SupervisedBot; now: number }) {
  const state = silenceState(bot, now);
  if (!state?.silent) return null;
  return (
    <span
      data-testid={`bots-silence-${bot.id}`}
      title={`No signal for more than ${SILENCE_CADENCES} × ${bot.timeframe} cadences.`}
      aria-label={`Silence alert: no ${bot.timeframe} signal for more than ${SILENCE_CADENCES} cadences`}
    >
      <Pill tone="warn" variant="soft" withDot={false}>
        SILENT
      </Pill>
    </span>
  );
}

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
  // name so screen readers + keyboard users get "Status: STUCK/DEGRADED/LIVE/…".
  //
  // P2-A — this is a plain labelled <span>, NOT role="status". With N rows and
  // a 10s poll that re-renders the table, a per-row live region re-announces
  // every status on every cycle (SR-spam). The single pane-level summary live
  // region (SupervisionSummaryLive) carries the only announcement instead.
  return (
    <span aria-label={`Status: ${label}`}>
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
      title="This bot's credential had its trade permission revoked; orders are being rejected."
      style={{ marginLeft: 6, display: "inline-block" }}
    >
      <Pill tone="negative" variant="soft" withDot={false}>
        PERMISSION REVOKED
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
  // F10 (audit A10) — the feed window (last FEED_WINDOW signals) can truncate
  // the day's count. When the authoritative per-bot totals prove truncation,
  // the KPI renders "≥N" and explains the lower bound instead of silently
  // undercounting. Exact when the feed covers every known signal.
  const signalsTodayTitle = stats.feed_truncated
    ? `Lower bound: the feed window shows the newest ${FEED_WINDOW} of ` +
      `${stats.signals_total ?? "?"} signals on record, so more may have ` +
      `occurred today. Increase the feed window or query the bots directly.`
    : `Signals counted from the current feed; ` +
      `${stats.signals_total ?? "unknown"} signals on record across all bots.`;
  return (
    <div style={{ display: "flex", gap: 24, alignItems: "center", padding: "8px 16px",
                  borderBottom: "1px solid var(--border-card)" }}>
      <KPI label="Total bots" value={stats.total} />
      <KPI label="Enabled" value={stats.enabled} />
      <KPI label="Live" value={stats.live} highlight={stats.live > 0 ? "negative" : undefined} />
      <div data-testid="bots-kpi-signals-today" title={signalsTodayTitle}>
        <KPI
          label="Signals today"
          value={stats.signals_today}
          valuePrefix={stats.feed_truncated ? "≥" : undefined}
        />
      </div>
      {/* F6 — at-a-glance unhealthy count so a supervisor sees problems
          immediately. Honest 0 when nothing is wrong. */}
      <div data-testid="bots-kpi-unhealthy">
        <KPI
          label="Stuck/Degraded"
          value={unhealthy}
          highlight={unhealthy > 0 ? "warn" : undefined}
        />
      </div>
      <div style={{ marginLeft: "auto", fontSize: "var(--font-size-sm)" }} className="u-text-secondary">
        {generatedAt ? `Last: ${new Date(generatedAt).toLocaleTimeString()}` : ""}
      </div>
    </div>
  );
}

function KPI({ label, value, highlight, valuePrefix }: {
  label: string; value: number; highlight?: "negative" | "warn"; valuePrefix?: string;
}) {
  const cls = value > 0 && highlight === "negative"
    ? "u-text-negative"
    : value > 0 && highlight === "warn"
      ? "u-text-warn"
      : undefined;
  return (
    <div>
      <div style={{ fontSize: "var(--font-size-2xs)" }} className="u-text-secondary">{label}</div>
      <div style={{ fontSize: "var(--font-size-3xl)", fontWeight: 600 }} className={cls}>
        {valuePrefix}{value}
      </div>
    </div>
  );
}

/**
 * Resolve the per-bot signal count.  Prefer Agent 2's authoritative
 * `signal_count` field (total entries in signal_log; not feed-limited).
 * Fall back to counting feed rows when missing, but the cell title makes
 * clear that the fallback is constrained to "last N" (the feed limit).
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
    tooltip: `No total count; the last ${fallback} signals come from the feed.`,
  };
}

/** KAOS Multibot pinned first (stable); every other row keeps payload order. */
export function sortBotsForDisplay(bots: SupervisedBot[]): SupervisedBot[] {
  return [...bots].sort((a, b) => Number(isKaosRecord(b)) - Number(isKaosRecord(a)));
}

const BOT_CSV_COLUMNS: GridCsvColumn<SupervisedBot>[] = [
  { key: "symbol", header: "Symbol", value: (b) => b.symbol },
  { key: "timeframe", header: "TF", value: (b) => b.timeframe },
  { key: "mode", header: "Mode", value: (b) => b.mode },
  { key: "enabled", header: "Enabled", value: (b) => b.enabled },
  { key: "status", header: "Status", value: (b) => deriveHealth(b).label },
  {
    key: "signal_count",
    header: "Signals",
    value: (b) =>
      typeof b.signal_count === "number" && Number.isFinite(b.signal_count)
        ? b.signal_count
        : "",
  },
  { key: "last_event_at", header: "Last tick", value: (b) => b.last_event_at ?? "" },
  { key: "last_action", header: "Last action", value: (b) => b.last_action ?? "" },
  {
    key: "permission_revoked",
    header: "Permission revoked",
    value: (b) => b.permission_revoked ?? false,
  },
];

const FEED_CSV_COLUMNS: GridCsvColumn<FeedSignal>[] = [
  { key: "timestamp", header: "Time", value: (s) => s.timestamp ?? s.bar_time },
  { key: "bot_symbol", header: "Bot", value: (s) => s.bot_symbol },
  { key: "kind", header: "Kind", value: (s) => s.kind },
  { key: "price", header: "Price", value: (s) => s.price },
  { key: "action", header: "Action", value: (s) => s.action },
  { key: "equity_source", header: "Equity source", value: (s) => s.equity_source ?? "" },
];

export function buildBotsCsv(bots: SupervisedBot[]): string {
  return buildGridCsv(BOT_CSV_COLUMNS, sortBotsForDisplay(bots));
}

export function buildFeedCsv(feed: FeedSignal[]): string {
  return buildGridCsv(FEED_CSV_COLUMNS, feed);
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
  const rows = useMemo(() => sortBotsForDisplay(bots), [bots]);
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);
  // G3 — jump-through helpers: open the bot draft / strategy (getState avoids
  // extra subscriptions), focus the target pane in the workspace, then route
  // there so single-pane mode follows too.
  const jumpToBot = useCallback(
    (bot: SupervisedBot) => {
      void useBotStore.getState().openExisting(bot.id);
      setFocusedTarget("BOT");
      navigate("/fn/BOT");
    },
    [setFocusedTarget],
  );
  const jumpToStrategy = useCallback(
    (bot: SupervisedBot) => {
      if (bot.strategy_id) void useStrategyStore.getState().openExisting(bot.strategy_id);
      setFocusedTarget("STRA");
      navigate("/fn/STRA");
    },
    [setFocusedTarget],
  );
  // F10 (audit A10) — DataGrid kit: sortable columns + keyboard-reachable
  // headers + clipboard support (the table previously had none of these).
  const columns = useMemo<DataGridColumn<SupervisedBot>[]>(() => [
    {
      key: "symbol",
      header: "Symbol",
      width: 150,
      sortable: true,
      sortValue: (b) => b.symbol,
      render: (b) => (
        <>
          <strong>{b.symbol}</strong>
          {isKaosRecord(b) && <KaosEngineBadge />}
          {b.permission_revoked && <PermRevokedBadge />}
        </>
      ),
    },
    {
      key: "venues",
      header: "Venues",
      width: 110,
      align: "center",
      // Venue chips render only when the payload carries venues (the list
      // payload currently does not) — hidden otherwise, never faked.
      render: (b) => <VenueBadges venues={b.venues} />,
    },
    {
      key: "timeframe",
      header: "TF",
      width: 60,
      align: "center",
      sortable: true,
      sortValue: (b) => b.timeframe,
      render: (b) => b.timeframe,
    },
    {
      key: "status",
      header: "Status",
      width: 110,
      align: "center",
      sortable: true,
      sortValue: (b) => deriveHealth(b).label,
      render: (b) => (
        // G3: the silence alert rides beside the health pill — a bot can be
        // RUNNING but silent (no signal for > N cadences).
        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <StatusPill bot={b} />
          <SilencePill bot={b} now={now} />
        </span>
      ),
    },
    {
      key: "signals",
      header: "Signals",
      width: 90,
      numeric: true,
      align: "right",
      sortable: true,
      sortValue: (b) => resolveSignalCount(b, byBot[b.id]).value,
      render: (b) => {
        const sigCount = resolveSignalCount(b, byBot[b.id]);
        return (
          <span
            data-testid={`bots-signal-count-${b.id}`}
            title={sigCount.tooltip}
          >
            {sigCount.value}
          </span>
        );
      },
    },
    {
      key: "last_event_at",
      header: "Last tick",
      width: 100,
      sortable: true,
      sortValue: (b) => b.last_event_at ?? "",
      render: (b) => {
        const age = relativeTickAge(b.last_event_at, now);
        return (
          <span
            data-testid={`bots-last-tick-${b.id}`}
            className={age.stale ? "u-text-secondary" : undefined}
            title={b.last_event_at ? formatLocalTimestamp(b.last_event_at) : undefined}
          >
            {age.text}
          </span>
        );
      },
    },
    {
      key: "last_signal",
      header: "Last signal",
      render: (b) => {
        const sig = byBot[b.id]?.[0];
        return sig ? (
          <span>
            {sig.kind} @ {formatPrice(sig.price)} ({sig.action})
            <span className="u-text-secondary">
              {" · " + formatLocalTimestamp(sig.timestamp ?? sig.bar_time)}
            </span>
          </span>
        ) : (
          <span className="u-text-secondary">(no signals)</span>
        );
      },
    },
    {
      // G3 — jump-through: open this bot's draft in BOT, or its strategy in
      // STRA. Buttons are labelled per row for screen readers.
      key: "open",
      header: "Open",
      width: 104,
      align: "center",
      render: (b) => (
        <span style={{ display: "inline-flex", gap: 4 }}>
          <button
            type="button"
            className="btn btn--ghost"
            data-testid={`bots-open-bot-${b.id}`}
            aria-label={`Open ${b.symbol} in the BOT pane`}
            title="Open the bot in BOT"
            onClick={() => jumpToBot(b)}
          >
            BOT
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            data-testid={`bots-open-stra-${b.id}`}
            aria-label={`Open strategy ${b.strategy_id} in STRA`}
            title="Open the strategy in STRA"
            disabled={!b.strategy_id}
            onClick={() => jumpToStrategy(b)}
          >
            STRA
          </button>
        </span>
      ),
    },
  ], [byBot, now, jumpToBot, jumpToStrategy]);
  if (bots.length === 0) {
    return (
      <div data-testid="bots-empty">
        <Empty title="No bots yet" body="Create and enable a bot and it will appear here." />
      </div>
    );
  }
  return (
    <div style={{ marginTop: 8 }}>
      <DataGrid
        columns={columns}
        rows={rows}
        rowKey={(b) => b.id}
        density="compact"
        ariaLabel="Bot supervision table"
        // Keep the KAOS-first payload order initially; headers cycle
        // asc → desc → none without re-pinning.
        defaultSortKey="symbol"
        defaultSortDir="none"
      />
    </div>
  );
}

function SignalFeed() {
  const feed = useBotsSupervisionStore((s) => s.feed);
  const columns = useMemo<DataGridColumn<FeedSignal>[]>(() => [
    {
      key: "timestamp",
      header: "Time",
      width: 180,
      sortable: true,
      sortValue: (s) => s.timestamp ?? s.bar_time ?? "",
      render: (s) => formatLocalTimestamp(s.timestamp ?? s.bar_time),
    },
    {
      key: "bot_symbol",
      header: "Bot",
      width: 120,
      sortable: true,
      sortValue: (s) => s.bot_symbol,
      render: (s) => (
        <span style={{ background: "var(--bg-elev-2)", padding: "1px 4px", borderRadius: 3 }}>
          {s.bot_symbol}
        </span>
      ),
    },
    {
      key: "kind",
      header: "Kind",
      width: 70,
      align: "center",
      sortable: true,
      sortValue: (s) => s.kind ?? "",
      render: (s) => (
        <span className={s.kind === "entry" ? "u-text-positive" : "u-text-warn"}>
          {s.kind}
        </span>
      ),
    },
    {
      key: "price",
      header: "Price",
      width: 110,
      numeric: true,
      align: "right",
      sortable: true,
      sortValue: (s) => s.price,
      render: (s) => formatPrice(s.price),
    },
    {
      key: "action",
      header: "Action",
      width: 120,
      align: "center",
      sortable: true,
      sortValue: (s) => s.action ?? "",
      render: (s) => (
        <>
          {s.action}
          {s.equity_source === FALLBACK_EQUITY_SOURCE && (
            <span
              data-testid="bots-feed-fallback-equity"
              title="This live order was sized with the fallback ($10k) balance instead of the real broker balance."
              style={{ marginLeft: 6, display: "inline-block" }}
            >
              <Pill tone="warn" variant="soft" withDot={false}>
                ≈$10k
              </Pill>
            </span>
          )}
        </>
      ),
    },
  ], []);
  if (feed.length === 0) {
    return (
      <div data-testid="bots-feed-empty">
        <Empty title="No signals yet" body="Signals from enabled bots stream here as they tick." />
      </div>
    );
  }
  return (
    <div style={{ marginTop: 8 }}>
      <DataGrid
        columns={columns}
        rows={feed}
        density="compact"
        ariaLabel="Unified signal feed"
        // P3-B — stable composite key (no positional index).
        rowKey={(s) => `${s.bot_id}-${s.bar_time}-${s.bar_index}-${s.action ?? ""}-${s.kind ?? ""}`}
        defaultSortKey="timestamp"
        defaultSortDir="none"
      />
    </div>
  );
}

export function BOTSPane() {
  const loadAll = useBotsSupervisionStore((s) => s.loadAll);
  const error = useBotsSupervisionStore((s) => s.error);
  const loading = useBotsSupervisionStore((s) => s.loading);
  const bots = useBotsSupervisionStore((s) => s.bots);
  const feed = useBotsSupervisionStore((s) => s.feed);

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
            label spells out that it refreshes the WHOLE supervisor view.
            F10 (audit A10) — CSV export of the full bot table next to it. */}
        <div style={{ display: "flex", alignItems: "center", margin: "12px 0 4px" }}>
          <h4 style={{ margin: 0 }}>Bots</h4>
          <button
            data-testid="bots-export-csv"
            type="button"
            aria-label={`Download all ${bots.length} bots as CSV`}
            title="Download CSV"
            disabled={bots.length === 0}
            onClick={() =>
              downloadGridCsv(gridCsvFilename("bots-supervision"), buildBotsCsv(bots))
            }
          >
            CSV
          </button>
          <button
            data-testid="bots-refresh-all"
            aria-label="Refresh the full audit view"
            aria-busy={loading}
            disabled={loading}
            onClick={() => loadAll()}
            style={{ marginLeft: "auto" }}
          >
            {loading ? "Refreshing…" : "Refresh all"}
          </button>
        </div>
        {firstLoad ? (
          <div data-testid="bots-loading" aria-busy="true">
            {Array.from({ length: 5 }).map((_, i) => (
              <SkeletonRow key={i} columns={7} />
            ))}
          </div>
        ) : (
          <BotTable />
        )}
        <div style={{ display: "flex", alignItems: "center", margin: "16px 0 4px" }}>
          <h4 style={{ margin: 0 }}>Signal feed (last {FEED_WINDOW} signals)</h4>
          <button
            data-testid="bots-feed-export-csv"
            type="button"
            aria-label={`Download all ${feed.length} feed signals as CSV`}
            title="Download CSV"
            disabled={feed.length === 0}
            onClick={() =>
              downloadGridCsv(gridCsvFilename("bots-signal-feed"), buildFeedCsv(feed))
            }
          >
            CSV
          </button>
        </div>
        <SignalFeed />
      </div>
    </div>
  );
}

export default BOTSPane;
