/**
 * SCAN — Scanner Agent (Phase A + Phase B).
 *
 * Lets the trader phrase a coarse intent ("crypto opportunities", "energy
 * pull-back", "EUR/USD overextended") and runs the ZAK-weighted scan
 * server-side. Results are clickable — clicking a row pushes the symbol
 * into a DES pane (or, in linked mode, into all sibling panes).
 */
import { useEffect, useMemo, useState } from "react";
import {
  ChangeText,
  DataGrid,
  type DataGridColumn,
  Empty,
  FieldRow,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
} from "@/design-system";
import {
  listUniverses,
  runScan,
  type ScanResult,
  type ScanRow,
  type UniverseSummary,
} from "@/lib/scanner";
import { navigate } from "@/lib/router";
import { useWorkspace } from "@/lib/workspace";
import {
  FunctionControlGroup,
  LoadStatePill,
  RowLimitControl,
} from "./function-controls";
import {
  TOP_N_LIMITS,
  type TopNLimit,
  usePersistentOption,
} from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

const SAMPLE_INTENTS = [
  "crypto opportunities high conviction",
  "S&P 500 pullbacks near 200-day MA",
  "EUR/USD overextended",
  "energy commodities trending up",
];

type SortKey = "score" | "confidence" | "change_pct";

function sortableHeader(
  label: string,
  key: SortKey,
  active: SortKey,
  setActive: (k: SortKey) => void,
) {
  const isActive = key === active;
  return (
    <button
      type="button"
      onClick={() => setActive(key)}
      style={{
        all: "unset",
        cursor: "default",
        color: isActive ? "var(--accent)" : "inherit",
        fontWeight: isActive ? 700 : 500,
      }}
      title={`Sort by ${label}`}
    >
      {label}
      {isActive && <span style={{ marginLeft: 4 }}>↓</span>}
    </button>
  );
}

function buildColumns(
  sortKey: SortKey,
  setSortKey: (k: SortKey) => void,
): DataGridColumn<ScanRow>[] {
  return [
    { key: "rank", header: "#", width: 40, render: (_r, idx) => idx + 1, numeric: true },
    {
      key: "symbol",
      header: "Symbol",
      width: 100,
      render: (r) => (
        <span style={{ color: "var(--accent)", fontWeight: 700 }}>{r.symbol}</span>
      ),
    },
    { key: "asset_class", header: "Class", width: 90 },
    {
      key: "direction",
      header: "Dir",
      width: 70,
      render: (r) => {
        const tone =
          r.direction === "LONG"
            ? "positive"
            : r.direction === "SHORT"
              ? "negative"
              : "muted";
        return r.direction ? <Pill tone={tone} withDot={false}>{r.direction}</Pill> : "—";
      },
    },
    {
      key: "confidence",
      header: sortableHeader("Conf %", "confidence", sortKey, setSortKey),
      numeric: true,
      width: 80,
      render: (r) => (r.confidence != null ? r.confidence.toFixed(1) : "—"),
    },
    {
      key: "score",
      header: sortableHeader("Score", "score", sortKey, setSortKey),
      numeric: true,
      width: 90,
      render: (r) => <ChangeText value={r.score ?? 0} digits={3} />,
    },
    {
      key: "change_pct",
      header: sortableHeader("Δ today", "change_pct", sortKey, setSortKey),
      numeric: true,
      width: 90,
      render: (r) => {
        const v = r.fine?.quote?.change_pct;
        return v == null ? (
          <span style={{ color: "var(--text-mute)" }}>—</span>
        ) : (
          <ChangeText value={v} digits={2} suffix="%" />
        );
      },
    },
    {
      key: "timeframes",
      header: "TFs",
      render: (r) => (r.timeframes ?? []).join(" · ") || (r.skipped ?? "—"),
    },
  ];
}

function sortRows(rows: ScanRow[], key: SortKey): ScanRow[] {
  const score = (r: ScanRow): number => {
    if (key === "confidence") return r.confidence ?? -Infinity;
    if (key === "change_pct") {
      const v = r.fine?.quote?.change_pct;
      return v == null ? -Infinity : Math.abs(v);
    }
    return Math.abs(r.score ?? 0);
  };
  return [...rows].sort((a, b) => score(b) - score(a));
}

export function SCANPane({ code }: FunctionPaneProps) {
  const [intent, setIntent] = useState(SAMPLE_INTENTS[0]);
  const [universe, setUniverse] = useState<string>("");
  const [topN, setTopN] = usePersistentOption<TopNLimit>(
    "showme.scan-topn",
    TOP_N_LIMITS,
    20,
  );
  const [phaseC, setPhaseC] = useState(true);
  const [phaseD, setPhaseD] = useState(true);
  const [universes, setUniverses] = useState<UniverseSummary[]>([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openSymbol, setOpenSymbol] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const setFocusedTarget = useWorkspace((s) => s.setFocusedTarget);

  const sortedRows = useMemo(
    () => (result ? sortRows(result.rows, sortKey) : []),
    [result, sortKey],
  );
  const cols = useMemo(() => buildColumns(sortKey, setSortKey), [sortKey]);

  // Drawer keyboard navigation: ←/→ between rows, ⌘↩ Open DES, Esc close.
  useEffect(() => {
    if (!openSymbol || sortedRows.length === 0) return;
    const onKey = (e: KeyboardEvent) => {
      const idx = sortedRows.findIndex((r) => r.symbol === openSymbol);
      if (idx === -1) return;
      if (e.key === "Escape") {
        e.preventDefault();
        setOpenSymbol(null);
      } else if (e.key === "ArrowLeft" && idx > 0) {
        e.preventDefault();
        setOpenSymbol(sortedRows[idx - 1].symbol);
      } else if (e.key === "ArrowRight" && idx < sortedRows.length - 1) {
        e.preventDefault();
        setOpenSymbol(sortedRows[idx + 1].symbol);
      } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        jumpToDES(sortedRows[idx].symbol);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openSymbol, sortedRows]);

  useEffect(() => {
    listUniverses().then(setUniverses).catch(() => setUniverses([]));
  }, []);

  const run = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    setOpenSymbol(null);
    try {
      const phases = ["A", "B"];
      if (phaseC) phases.push("C");
      if (phaseD) phases.push("D");
      const r = await runScan({
        intent,
        universe: universe || undefined,
        top_n: topN,
        phases,
        fine_top_k: phaseC ? Math.min(topN, 8) : undefined,
      });
      setResult(r);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  };

  const onRowClick = (row: ScanRow) => {
    if (row.skipped || !row.symbol) return;
    // Open the per-symbol drawer first; double-click jumps to DES.
    setOpenSymbol(row.symbol === openSymbol ? null : row.symbol);
  };

  const jumpToDES = (sym: string) => {
    setFocusedTarget("DES", sym);
    navigate(`/symbol/${sym}/DES`);
  };

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="Scanner Agent"
          subtitle={result ? result.universe_key : "Phase A + Phase B"}
          trailing={
            <FunctionControlGroup>
              <RowLimitControl
                label="TOP"
                value={topN}
                onChange={(next) => setTopN(next as TopNLimit)}
                disabled={running}
              />
              <LoadStatePill state={running ? "loading" : error ? "error" : result ? "ok" : "idle"} />
              <button
                type="button"
                className="btn btn--accent"
                onClick={run}
                disabled={running || !intent.trim()}
                style={{ height: 24 }}
              >
                {running ? "Scanning..." : "Run scan"}
              </button>
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              <span
                style={{
                  fontSize: 10,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  color: "var(--text-mute)",
                  display: "block",
                  marginBottom: 4,
                }}
              >
                Intent (NL)
              </span>
              <textarea
                value={intent}
                onChange={(e) => setIntent(e.target.value)}
                rows={2}
                spellCheck={false}
                style={{
                  width: "100%",
                  resize: "vertical",
                  background: "var(--bg-elev-2)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "var(--radius-md)",
                  fontFamily: "JetBrains Mono, monospace",
                  fontSize: 12,
                  padding: 8,
                  outline: "none",
                }}
              />
              <div
                style={{
                  display: "flex",
                  gap: 6,
                  marginTop: 6,
                  flexWrap: "wrap",
                }}
              >
                {SAMPLE_INTENTS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="btn btn--ghost"
                    onClick={() => setIntent(s)}
                    style={{ fontSize: 10, fontFamily: "JetBrains Mono" }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>

            <FieldRow>
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span
                  style={{
                    fontSize: 10,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    color: "var(--text-mute)",
                  }}
                >
                  Universe (override)
                </span>
                <select
                  value={universe}
                  onChange={(e) => setUniverse(e.target.value)}
                  style={{
                    background: "var(--bg-elev-2)",
                    border: "1px solid var(--border-subtle)",
                    borderRadius: "var(--radius-md)",
                    color: "var(--text-primary)",
                    fontFamily: "JetBrains Mono, monospace",
                    fontSize: 12,
                    height: 28,
                    padding: "0 8px",
                  }}
                >
                  <option value="">(auto from intent)</option>
                  {universes.map((u) => (
                    <option key={u.key} value={u.key}>
                      {u.key} · {u.size}
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span
                  style={{
                    fontSize: 10,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    color: "var(--text-mute)",
                  }}
                >
                  Phases
                </span>
                <div
                  style={{
                    display: "flex",
                    gap: 6,
                    height: 28,
                    alignItems: "center",
                  }}
                >
                  <PhaseToggle label="A+B" checked disabled />
                  <PhaseToggle
                    label="C · fine"
                    checked={phaseC}
                    onChange={() => setPhaseC((c) => !c)}
                  />
                  <PhaseToggle
                    label="D · risk"
                    checked={phaseD}
                    onChange={() => setPhaseD((d) => !d)}
                  />
                </div>
              </label>
            </FieldRow>

            {error && <Empty title="Scan failed" body={error} icon="!" />}

            {running && (
              <div style={{ display: "grid", gap: 6 }}>
                <Skeleton height={14} />
                <Skeleton height={14} />
                <Skeleton height={14} width="80%" />
              </div>
            )}

            {result && !running && (
              <>
                <div
                  style={{
                    display: "flex",
                    gap: 8,
                    fontSize: 11,
                    color: "var(--text-secondary)",
                    flexWrap: "wrap",
                  }}
                >
                  <Pill tone="accent" withDot={false}>
                    {result.asset_class}
                  </Pill>
                  <Pill tone="muted" withDot={false}>
                    universe · {result.universe_key}
                  </Pill>
                  <Pill tone="muted" withDot={false}>
                    {result.timeframes.join(" · ")}
                  </Pill>
                  {result.phases.map((p) => (
                    <Pill key={p.name} tone="muted" withDot={false}>
                      {p.name} · {Math.round(p.elapsed_ms)}ms
                    </Pill>
                  ))}
                  {result.warnings.length > 0 && (
                    <Pill tone="warn" withDot={false}>
                      {result.warnings.length} warn
                    </Pill>
                  )}
                </div>
                {sortedRows.length === 0 ? (
                  <Empty title="Scan empty" body="Universe scanned but nothing produced a signal." />
                ) : (
                  <DataGrid
                    columns={cols}
                    rows={sortedRows}
                    rowKey={(r) => r.symbol}
                    density="compact"
                    onRowClick={onRowClick}
                    onRowDoubleClick={(r) => {
                      if (!r.skipped && r.symbol) jumpToDES(r.symbol);
                    }}
                  />
                )}
                {openSymbol && (
                  <Drawer
                    row={sortedRows.find((r) => r.symbol === openSymbol)}
                    onClose={() => setOpenSymbol(null)}
                    onJumpDES={jumpToDES}
                    hint={
                      sortedRows.length > 1
                        ? "← / → between rows · double-click row → DES · ⌘↵ Open DES · esc close"
                        : "double-click row → DES"
                    }
                  />
                )}
              </>
            )}
          </div>
        </PaneBody>
        <PaneFooter>
          <span>elapsed · {result ? Math.round(result.elapsed_ms) : "—"} ms</span>
          <span>rows · {result?.rows.length ?? 0}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function PhaseToggle({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange?: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onChange}
      disabled={disabled}
      style={{
        height: 24,
        padding: "0 8px",
        background: checked ? "var(--accent-soft)" : "var(--bg-elev-2)",
        color: checked ? "var(--accent)" : "var(--text-secondary)",
        border: `1px solid ${checked ? "var(--accent)" : "var(--border-subtle)"}`,
        borderRadius: "var(--radius-sm)",
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 10,
        cursor: disabled ? "not-allowed" : "default",
        opacity: disabled ? 0.65 : 1,
      }}
    >
      {label}
    </button>
  );
}

function Drawer({
  row,
  onClose,
  onJumpDES,
  hint,
}: {
  row?: ScanRow;
  onClose: () => void;
  onJumpDES: (sym: string) => void;
  hint?: string;
}) {
  if (!row) return null;
  const fine = row.fine;
  const overlap = row.position_overlap;
  return (
    <section
      style={{
        marginTop: 4,
        background: "var(--bg-elev-2)",
        border: "1px solid var(--border-strong)",
        borderRadius: "var(--radius-md)",
        padding: 12,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 10,
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 12,
        }}
      >
        <strong style={{ color: "var(--accent)" }}>{row.symbol}</strong>
        <span style={{ color: "var(--text-mute)" }}>{row.asset_class}</span>
        <Pill
          tone={
            row.direction === "LONG"
              ? "positive"
              : row.direction === "SHORT"
                ? "negative"
                : "muted"
          }
          withDot={false}
        >
          {row.direction ?? "—"} · {row.confidence?.toFixed(0) ?? "—"}%
        </Pill>
        {overlap?.held && <Pill tone="warn" withDot={false}>HELD</Pill>}
        {overlap?.high_concentration && (
          <Pill tone="warn" withDot={false}>HIGH CONC</Pill>
        )}
        {fine?.overextension?.deviation_label === "OVERBOUGHT" && (
          <Pill tone="negative" withDot={false}>OVERBOUGHT</Pill>
        )}
        {fine?.overextension?.deviation_label === "OVERSOLD" && (
          <Pill tone="positive" withDot={false}>OVERSOLD</Pill>
        )}
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <button
            type="button"
            className="btn btn--accent"
            onClick={() => onJumpDES(row.symbol)}
            style={{ height: 22, fontSize: 10 }}
          >
            Open DES
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={onClose}
            style={{ height: 22, fontSize: 10 }}
          >
            Close
          </button>
        </div>
      </header>

      {hint && (
        <div
          style={{
            fontSize: 10,
            color: "var(--text-mute)",
            marginBottom: 8,
            fontFamily: "JetBrains Mono, monospace",
          }}
        >
          {hint}
        </div>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
          gap: 14,
        }}
      >
        <div>
          <h4 style={H4}>Phase B contributions</h4>
          <ContribTable rows={row.contributions ?? []} />
        </div>
        <div>
          <h4 style={H4}>Phase C — fine scan</h4>
          {fine ? (
            <>
              {fine.quote && (
                <div style={{ marginBottom: 8, fontSize: 11, color: "var(--text-secondary)" }}>
                  last <strong style={{ color: "var(--text-primary)" }}>
                    {fine.quote.last ?? "—"}
                  </strong>
                  {fine.quote.change_pct != null && (
                    <span style={{ marginLeft: 8 }}>
                      <ChangeText
                        value={fine.quote.change_pct}
                        digits={2}
                        suffix="%"
                      />
                    </span>
                  )}
                </div>
              )}
              {fine.overextension && (
                <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 8 }}>
                  z(30d): <strong>{fine.overextension.z_score_30d.toFixed(2)}</strong>
                  {" · "}
                  <span
                    style={{
                      color:
                        fine.overextension.deviation_label === "OVERBOUGHT"
                          ? "var(--negative)"
                          : fine.overextension.deviation_label === "OVERSOLD"
                            ? "var(--positive)"
                            : "var(--text-secondary)",
                    }}
                  >
                    {fine.overextension.deviation_label}
                  </span>
                </div>
              )}
              <ContribTable rows={fine.contributions ?? []} />
            </>
          ) : (
            <div style={{ fontSize: 11, color: "var(--text-mute)" }}>
              Phase C disabled · enable the toggle and re-run.
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

const H4 = {
  margin: "0 0 6px 0",
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "uppercase" as const,
  color: "var(--text-mute)",
};

function ContribTable({
  rows,
}: {
  rows: NonNullable<ScanRow["contributions"]>;
}) {
  if (rows.length === 0) {
    return (
      <div style={{ fontSize: 11, color: "var(--text-mute)" }}>
        no contributions
      </div>
    );
  }
  return (
    <table
      style={{
        width: "100%",
        borderCollapse: "collapse",
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 11,
      }}
    >
      <thead>
        <tr style={{ color: "var(--text-mute)" }}>
          <th style={CTH}>TF</th>
          <th style={CTH}>Wt</th>
          <th style={CTH}>Dir</th>
          <th style={CTH}>Conf%</th>
          <th style={CTH}>Contrib</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => (
          <tr key={c.tf} style={{ borderTop: "1px solid var(--border-subtle)" }}>
            <td style={CTD}>{c.tf}</td>
            <td style={{ ...CTD, textAlign: "right" }}>{c.weight}</td>
            <td style={CTD}>
              <span
                style={{
                  color:
                    c.direction === "LONG"
                      ? "var(--positive)"
                      : c.direction === "SHORT"
                        ? "var(--negative)"
                        : "var(--text-mute)",
                }}
              >
                {c.direction}
              </span>
            </td>
            <td style={{ ...CTD, textAlign: "right" }}>
              {c.confidence.toFixed(0)}
            </td>
            <td style={{ ...CTD, textAlign: "right" }}>
              <ChangeText value={c.contribution} digits={3} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const CTH: React.CSSProperties = {
  padding: "4px 6px",
  textAlign: "left",
  fontSize: 9,
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  fontWeight: 500,
};
const CTD: React.CSSProperties = {
  padding: "3px 6px",
  color: "var(--text-primary)",
};
