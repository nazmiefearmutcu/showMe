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
 */
import {
  useBotsSupervisionStore,
  type FeedSignal,
  type SupervisedBot,
} from "@/lib/bots-supervision-store";
import { useBotEcosystemPolling } from "@/lib/useBotEcosystemPolling";
import { formatPrice } from "@/lib/format";

function ModePill({ mode, enabled }: { mode: string; enabled: boolean }) {
  const live = mode === "live";
  const color = !enabled ? "var(--fg-2)"
              : live ? "var(--accent-err)"
              : "var(--accent-warn)";
  return (
    <span style={{
      fontSize: 10, fontWeight: 600, color, border: `1px solid ${color}`,
      padding: "1px 6px", borderRadius: 4,
    }}>
      {enabled ? (live ? "LIVE" : "SHADOW") : "OFF"}
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
      style={{
        fontSize: 9, fontWeight: 700, color: "var(--accent-err)",
        border: "1px solid var(--accent-err)",
        padding: "1px 4px", borderRadius: 4, marginLeft: 6,
      }}
    >
      İZİN İPTAL
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

function KPIStrip() {
  const stats = useBotsSupervisionStore((s) => s.stats);
  const generatedAt = useBotsSupervisionStore((s) => s.generatedAt);
  return (
    <div style={{ display: "flex", gap: 24, alignItems: "center", padding: "8px 16px",
                  borderBottom: "1px solid var(--border-1)" }}>
      <KPI label="Toplam bot" value={stats.total} />
      <KPI label="Etkin" value={stats.enabled} />
      <KPI label="Canlı" value={stats.live} colorIfNonzero="var(--accent-err)" />
      <KPI label="Bugünkü sinyal" value={stats.signals_today} />
      <div style={{ marginLeft: "auto", fontSize: 11, color: "var(--fg-2)" }}>
        {generatedAt ? `Son: ${new Date(generatedAt).toLocaleTimeString()}` : ""}
      </div>
    </div>
  );
}

function KPI({ label, value, colorIfNonzero }: { label: string; value: number; colorIfNonzero?: string }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: "var(--fg-2)" }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 600,
                    color: value > 0 && colorIfNonzero ? colorIfNonzero : undefined }}>
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
  if (bots.length === 0) {
    return <div style={{ padding: 16, color: "var(--fg-2)" }}>Henüz bot yok.</div>;
  }
  // Index feed by bot_id for quick lookup of latest:
  const byBot: Record<string, FeedSignal[]> = {};
  for (const s of feed) {
    (byBot[s.bot_id] ||= []).push(s);
  }
  return (
    <table style={{ width: "100%", fontSize: 12, marginTop: 8 }}>
      <thead>
        <tr style={{ color: "var(--fg-2)" }}>
          <th align="left">Symbol</th>
          <th>TF</th>
          <th>Mode</th>
          <th align="right">Sinyaller</th>
          <th align="left">Son sinyal</th>
        </tr>
      </thead>
      <tbody>
        {bots.map((b) => {
          const sig = byBot[b.id]?.[0];
          const sigCount = resolveSignalCount(b, byBot[b.id]);
          return (
            <tr key={b.id} style={{ borderBottom: "1px solid var(--border-1)" }}>
              <td>
                <strong>{b.symbol}</strong>
                {b.permission_revoked && <PermRevokedBadge />}
              </td>
              <td align="center">{b.timeframe}</td>
              <td align="center"><ModePill mode={b.mode} enabled={b.enabled} /></td>
              <td
                align="right"
                title={sigCount.tooltip}
                data-testid={`bots-signal-count-${b.id}`}
              >
                {sigCount.value}
              </td>
              <td>
                {sig ? (
                  <span>
                    {sig.kind} @ {formatPrice(sig.price)} ({sig.action})
                    <span style={{ color: "var(--fg-2)" }}>
                      {" · " + formatLocalTimestamp(sig.timestamp ?? sig.bar_time)}
                    </span>
                  </span>
                ) : (
                  <span style={{ color: "var(--fg-2)" }}>(no signals)</span>
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
    return <div style={{ padding: 16, color: "var(--fg-2)" }}>Henüz sinyal yok.</div>;
  }
  return (
    <table style={{ width: "100%", fontSize: 11, marginTop: 8 }}>
      <thead>
        <tr style={{ color: "var(--fg-2)" }}>
          <th align="left">Time</th>
          <th align="left">Bot</th>
          <th>Kind</th>
          <th align="right">Price</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        {feed.map((s, i) => (
          <tr key={`${s.bot_id}-${s.bar_index}-${i}`}>
            <td>{formatLocalTimestamp(s.timestamp ?? s.bar_time)}</td>
            <td>
              <span style={{ background: "var(--surface-2)", padding: "1px 4px", borderRadius: 3 }}>
                {s.bot_symbol}
              </span>
            </td>
            <td align="center" style={{
              color: s.kind === "entry" ? "var(--accent-ok)" : "var(--accent-warn)",
            }}>
              {s.kind}
            </td>
            <td align="right">{formatPrice(s.price)}</td>
            <td align="center">{s.action}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function BOTSPane() {
  const loadAll = useBotsSupervisionStore((s) => s.loadAll);
  const error = useBotsSupervisionStore((s) => s.error);

  // BUG #10 — unified polling.  PERF mounts the same hook; once is enough,
  // but mounting it in both panes is safe (each install owns its own
  // interval handle).
  useBotEcosystemPolling();

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <KPIStrip />
      <div style={{ overflowY: "auto", padding: "0 16px" }}>
        {/* BUG #11 — refresh control sits next to the table heading; the
            label spells out that it refreshes the WHOLE supervisor view. */}
        <div style={{ display: "flex", alignItems: "center", margin: "12px 0 4px" }}>
          <h4 style={{ margin: 0 }}>Botlar</h4>
          <button
            data-testid="bots-refresh-all"
            onClick={() => loadAll()}
            style={{ marginLeft: "auto" }}
          >
            Tümünü yenile
          </button>
        </div>
        <BotTable />
        <h4 style={{ margin: "16px 0 4px" }}>Sinyal akışı</h4>
        <SignalFeed />
        {error && <div style={{ color: "var(--accent-err)", padding: 8 }}>{error}</div>}
      </div>
    </div>
  );
}

export default BOTSPane;
