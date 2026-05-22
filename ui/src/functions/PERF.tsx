/**
 * PERF — Cumulative performance pane. Sub-system I.
 *
 * Top: total PnL across all bots + best/worst pills.
 * Middle: sortable leaderboard table.
 * Right (when bot selected): equity curve <svg> (no external chart lib).
 */
import { useEffect } from "react";
import {
  usePerformanceStore,
} from "@/lib/performance-store";

function _color(n: number): string {
  if (n > 0) return "var(--accent-ok)";
  if (n < 0) return "var(--accent-err)";
  return "var(--fg-2)";
}

function KPI({ label, value, fmt = (v) => v.toFixed(2) }: {
  label: string; value: number; fmt?: (v: number) => string;
}) {
  return (
    <div>
      <div style={{ fontSize: 10, color: "var(--fg-2)" }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 600, color: _color(value) }}>
        {fmt(value)}
      </div>
    </div>
  );
}

function EquityCurve({ points, width = 480, height = 160 }: {
  points: { t: string; equity: number }[]; width?: number; height?: number;
}) {
  if (points.length < 2) {
    return <div style={{ color: "var(--fg-2)" }}>Yeterli trade verisi yok.</div>;
  }
  const equities = points.map((p) => p.equity);
  const min = Math.min(...equities);
  const max = Math.max(...equities);
  const range = max - min || 1;
  const stepX = width / (points.length - 1);
  const pathD = points.map((p, i) => {
    const x = i * stepX;
    const y = height - ((p.equity - min) / range) * height;
    return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg width={width} height={height} style={{ border: "1px solid var(--border-1)" }}>
      <path d={pathD} stroke="var(--accent-ok)" fill="none" strokeWidth={1.5} />
      <text x={4} y={12} fill="var(--fg-2)" fontSize="9">
        min: {min.toFixed(2)} · max: {max.toFixed(2)}
      </text>
    </svg>
  );
}

export function PERFPane() {
  const leaderboard = usePerformanceStore((s) => s.leaderboard);
  const selected = usePerformanceStore((s) => s.selected);
  const loadLeaderboard = usePerformanceStore((s) => s.loadLeaderboard);
  const loadBot = usePerformanceStore((s) => s.loadBot);
  const clearSelected = usePerformanceStore((s) => s.clearSelected);
  const error = usePerformanceStore((s) => s.error);

  useEffect(() => {
    loadLeaderboard();
    const t = setInterval(() => loadLeaderboard(), 15_000);
    return () => clearInterval(t);
  }, [loadLeaderboard]);

  const totalPnL = leaderboard.reduce((acc, e) => acc + e.total_pnl, 0);
  const best = leaderboard[0]; // already sorted desc by total_pnl
  const worst = leaderboard[leaderboard.length - 1];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <div style={{ display: "flex", gap: 24, alignItems: "center", padding: "8px 16px",
                    borderBottom: "1px solid var(--border-1)" }}>
        <KPI label="Toplam PnL" value={totalPnL} />
        <KPI label="Bot sayısı" value={leaderboard.length} fmt={(v) => v.toFixed(0)} />
        {best && best.total_pnl > 0 && (
          <div>
            <div style={{ fontSize: 10, color: "var(--fg-2)" }}>En iyi</div>
            <div style={{ color: "var(--accent-ok)" }}>{best.symbol}: +{best.total_pnl.toFixed(2)}</div>
          </div>
        )}
        {worst && worst.total_pnl < 0 && (
          <div>
            <div style={{ fontSize: 10, color: "var(--fg-2)" }}>En kötü</div>
            <div style={{ color: "var(--accent-err)" }}>{worst.symbol}: {worst.total_pnl.toFixed(2)}</div>
          </div>
        )}
        <button style={{ marginLeft: "auto" }} onClick={() => loadLeaderboard()}>Yenile</button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: selected ? "1fr 1fr" : "1fr",
                    flex: 1, overflow: "hidden" }}>
        <div style={{ overflowY: "auto", padding: 8 }}>
          <h4>Leaderboard</h4>
          {leaderboard.length === 0 ? (
            <div style={{ color: "var(--fg-2)" }}>Henüz performans verisi yok.</div>
          ) : (
            <table style={{ width: "100%", fontSize: 12 }}>
              <thead>
                <tr style={{ color: "var(--fg-2)" }}>
                  <th align="left">Symbol</th>
                  <th align="right">Trades</th>
                  <th align="right">Win %</th>
                  <th align="right">Total PnL</th>
                  <th align="right">Max DD</th>
                </tr>
              </thead>
              <tbody>
                {leaderboard.map((e) => (
                  <tr key={e.bot_id}
                      onClick={() => loadBot(e.bot_id)}
                      style={{
                        cursor: "pointer",
                        background: selected?.bot_id === e.bot_id ? "var(--surface-2)" : "transparent",
                        borderBottom: "1px solid var(--border-1)",
                      }}>
                    <td>{e.symbol}</td>
                    <td align="right">{e.trade_count}</td>
                    <td align="right">{(e.win_rate * 100).toFixed(0)}%</td>
                    <td align="right" style={{ color: _color(e.total_pnl) }}>
                      {e.total_pnl.toFixed(2)}
                    </td>
                    <td align="right" style={{ color: e.max_drawdown > 0 ? "var(--accent-warn)" : undefined }}>
                      {e.max_drawdown.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {selected && (
          <div style={{ overflowY: "auto", padding: 8, borderLeft: "1px solid var(--border-1)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <h4 style={{ margin: 0 }}>{selected.symbol}</h4>
              <button onClick={clearSelected} style={{ marginLeft: "auto" }}>Kapat</button>
            </div>
            <div style={{ display: "flex", gap: 16, margin: "8px 0" }}>
              <KPI label="Trades" value={selected.metrics.trade_count} fmt={(v) => v.toFixed(0)} />
              <KPI label="Win %" value={selected.metrics.win_rate * 100} fmt={(v) => v.toFixed(0) + "%"} />
              <KPI label="Total PnL" value={selected.metrics.total_pnl} />
              <KPI label="Avg PnL" value={selected.metrics.avg_pnl} />
              <KPI label="Max DD" value={selected.metrics.max_drawdown} />
            </div>
            <h4>Equity curve</h4>
            <EquityCurve points={selected.equity_curve} />
            <h4>Trades ({selected.trades.length})</h4>
            <table style={{ width: "100%", fontSize: 11 }}>
              <thead>
                <tr style={{ color: "var(--fg-2)" }}>
                  <th align="left">Entry</th>
                  <th align="right">@</th>
                  <th align="left">Exit</th>
                  <th align="right">@</th>
                  <th align="right">PnL</th>
                  <th align="right">%</th>
                </tr>
              </thead>
              <tbody>
                {selected.trades.slice(-50).reverse().map((t, i) => (
                  <tr key={i}>
                    <td>{t.entry_time.slice(0, 16)}</td>
                    <td align="right">{t.entry_price.toFixed(2)}</td>
                    <td>{t.exit_time.slice(0, 16)}</td>
                    <td align="right">{t.exit_price.toFixed(2)}</td>
                    <td align="right" style={{ color: _color(t.pnl) }}>
                      {t.pnl.toFixed(2)}
                    </td>
                    <td align="right" style={{ color: _color(t.pnl_pct) }}>
                      {t.pnl_pct.toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {error && <div style={{ color: "var(--accent-err)", padding: 8 }}>{error}</div>}
    </div>
  );
}

export default PERFPane;
