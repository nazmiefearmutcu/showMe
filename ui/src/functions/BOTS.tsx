/**
 * BOTS — Bot supervisor pane (plural; distinct from D's per-bot BOT pane).
 *
 * Three sections: aggregate KPI strip, per-bot table, unified signal feed.
 * Auto-refresh every 10 seconds.
 */
import { useEffect } from "react";
import {
  useBotsSupervisionStore,
  type FeedSignal,
} from "@/lib/bots-supervision-store";

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

function KPIStrip() {
  const stats = useBotsSupervisionStore((s) => s.stats);
  const generatedAt = useBotsSupervisionStore((s) => s.generatedAt);
  const load = useBotsSupervisionStore((s) => s.loadAll);
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
      <button onClick={() => load()}>Yenile</button>
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
          return (
            <tr key={b.id} style={{ borderBottom: "1px solid var(--border-1)" }}>
              <td><strong>{b.symbol}</strong></td>
              <td align="center">{b.timeframe}</td>
              <td align="center"><ModePill mode={b.mode} enabled={b.enabled} /></td>
              <td align="right">{byBot[b.id]?.length ?? 0}</td>
              <td>
                {sig ? (
                  <span>
                    {sig.kind} @ {sig.price.toFixed(2)} ({sig.action})
                    <span style={{ color: "var(--fg-2)" }}>
                      {" · " + (sig.timestamp ?? sig.bar_time).slice(0, 19)}
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
            <td>{(s.timestamp ?? s.bar_time).slice(0, 19)}</td>
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
            <td align="right">{s.price.toFixed(2)}</td>
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

  useEffect(() => {
    loadAll();
    const t = setInterval(() => loadAll(), 10_000);
    return () => clearInterval(t);
  }, [loadAll]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <KPIStrip />
      <div style={{ overflowY: "auto", padding: "0 16px" }}>
        <h4 style={{ margin: "12px 0 4px" }}>Botlar</h4>
        <BotTable />
        <h4 style={{ margin: "16px 0 4px" }}>Sinyal akışı</h4>
        <SignalFeed />
        {error && <div style={{ color: "var(--accent-err)", padding: 8 }}>{error}</div>}
      </div>
    </div>
  );
}

export default BOTSPane;
