import { useMemo } from "react";
import { useAppStore } from "@/lib/store";
import {
  Card,
  CardBody,
  CardHeader,
  DataGrid,
  type DataGridColumn,
  Pill,
  Skeleton,
} from "@/design-system";
import type { FunctionEntry } from "@/lib/sidecar";
import { navigate } from "@/lib/router";
import { t } from "@/i18n";
import { BUILTIN_PRESETS, loadBuiltinPreset } from "@/lib/builtinPresets";
import { useFunction } from "@/lib/useFunction";
import { listNativeCodes } from "@/functions/registry";

interface CategoryRow {
  category: string;
  count: number;
  share: number;
}

interface PortfolioPosition {
  symbol: string;
  asset_class?: string;
  market_value?: number;
  unrealized_pnl?: number;
  weight_pct?: number;
}

interface PortfolioData {
  status?: string;
  positions?: PortfolioPosition[];
  totals?: {
    market_value?: number;
    unrealized_pnl?: number;
    n_positions?: number;
  };
  by_asset_class?: Record<string, number>;
}

const CATEGORY_COLUMNS: DataGridColumn<CategoryRow>[] = [
  { key: "category", header: "Category", width: "1fr" },
  { key: "count", header: "n", numeric: true, width: 52 },
  {
    key: "share",
    header: "%",
    numeric: true,
    width: 64,
    render: (r) => `${(r.share * 100).toFixed(1)}%`,
  },
];

const POSITION_COLUMNS: DataGridColumn<PortfolioPosition>[] = [
  {
    key: "symbol",
    header: "Symbol",
    width: "1fr",
    render: (row) => (
      <button
        type="button"
        onClick={() => navigate(`/symbol/${row.symbol}/DES`)}
        style={{
          background: "transparent",
          border: 0,
          color: "var(--accent)",
          cursor: "default",
          font: "inherit",
          padding: 0,
        }}
      >
        {row.symbol}
      </button>
    ),
  },
  { key: "asset_class", header: "Asset", width: 76 },
  {
    key: "market_value",
    header: "MV",
    numeric: true,
    width: 92,
    render: (row) => money(row.market_value),
  },
  {
    key: "unrealized_pnl",
    header: "P&L",
    numeric: true,
    width: 92,
    render: (row) => signedMoney(row.unrealized_pnl),
  },
  {
    key: "weight_pct",
    header: "Wt",
    numeric: true,
    width: 64,
    render: (row) => (row.weight_pct == null ? "-" : `${row.weight_pct.toFixed(1)}%`),
  },
];

const PRIMARY_CODES = [
  "PORT",
  "WATCH",
  "CN",
  "ANR",
  "MOST",
  "WEI",
  "GLCO",
  "BTMM",
  "ASK",
  "AGENT",
];

export function Welcome() {
  const status = useAppStore((s) => s.sidecarStatus);
  const engine = useAppStore((s) => s.engineRoot);
  const port = useAppStore((s) => s.sidecarPort);
  const idx = useAppStore((s) => s.functionIndex);
  const total = idx.length;
  const nativeCodes = useMemo(() => new Set(listNativeCodes()), []);
  const portfolio = useFunction<PortfolioData>({
    code: "PORT",
    enabled: status === "healthy" && total > 0,
  });

  const rows = useMemo<CategoryRow[]>(() => {
    if (!total) return [];
    const counts = new Map<string, number>();
    for (const fn of idx) counts.set(fn.category, (counts.get(fn.category) ?? 0) + 1);
    return [...counts.entries()]
      .map(([category, count]) => ({ category, count, share: count / total }))
      .sort((a, b) => b.count - a.count);
  }, [idx, total]);

  const commandDeck = useMemo(() => {
    const byCode = new Map(idx.map((entry) => [entry.code, entry]));
    return PRIMARY_CODES.map((code) => byCode.get(code) ?? fallbackEntry(code)).filter(Boolean);
  }, [idx]);

  const positions = useMemo(
    () => portfolio.data?.data?.positions ?? [],
    [portfolio.data?.data?.positions],
  );
  const totals = portfolio.data?.data?.totals;
  const topPositions = useMemo(
    () =>
      [...positions]
        .sort((a, b) => (b.market_value ?? 0) - (a.market_value ?? 0))
        .slice(0, 10),
    [positions],
  );
  const classRows = useMemo(
    () =>
      Object.entries(portfolio.data?.data?.by_asset_class ?? {})
        .sort(([, a], [, b]) => b - a)
        .slice(0, 6),
    [portfolio.data?.data?.by_asset_class],
  );

  return (
    <main
      className="showme-home"
      style={{
        padding: 18,
        display: "grid",
        gridTemplateColumns: "minmax(0, 1.8fr) minmax(330px, 0.9fr)",
        gridTemplateRows: "auto auto minmax(0, 1fr)",
        gap: 14,
        height: "100%",
        minHeight: 0,
        overflow: "auto",
      }}
    >
      <header
        className="showme-home__section showme-home__section--0"
        style={{
          gridColumn: "1 / -1",
          display: "grid",
          gridTemplateColumns: "1fr auto",
          alignItems: "end",
          gap: 14,
        }}
      >
        <div>
          <h1
            style={{
              fontFamily: "Inter, SF Pro Text, system-ui",
              fontSize: 22,
              margin: 0,
              letterSpacing: 0,
              color: "var(--text-primary)",
            }}
          >
            {t("shell.welcome.title")}
          </h1>
          <div
            style={{
              marginTop: 4,
              color: "var(--text-secondary)",
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 11,
            }}
          >
            {shortPath(engine) || "engine attaching"}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <Pill tone={status === "healthy" ? "positive" : "warn"}>{status}</Pill>
          <Pill tone="muted" withDot={false}>{port ? `:${port}` : "no port"}</Pill>
          <Pill tone="accent" withDot={false}>{total || "--"} fn</Pill>
        </div>
      </header>

      <section
        className="showme-home__section showme-home__section--1"
        style={{
          gridColumn: "1 / -1",
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
          gap: 10,
        }}
      >
        <MetricCard label="Market value" value={money(totals?.market_value)} order={0} />
        <MetricCard label="Unrealized P&L" value={signedMoney(totals?.unrealized_pnl)} order={1} />
        <MetricCard label="Positions" value={String(totals?.n_positions ?? positions.length)} order={2} />
        <MetricCard label="Native panes" value={`${nativeCodes.size}/${total || "--"}`} order={3} />
      </section>

      <Card className="showme-home__section showme-home__section--2" variant="elev-2" style={{ minHeight: 0 }}>
        <CardHeader trailing={portfolio.data?.status ?? portfolio.state}>
          Portfolio board
        </CardHeader>
        <CardBody>
          {portfolio.state === "loading" ? (
            <div style={{ display: "grid", gap: 8 }}>
              <Skeleton height={22} />
              <Skeleton height={22} />
              <Skeleton height={22} />
            </div>
          ) : topPositions.length ? (
            <DataGrid
              columns={POSITION_COLUMNS}
              rows={topPositions}
              rowKey={(row) => row.symbol}
              density="compact"
            />
          ) : (
            <div style={emptyPanelStyle}>
              <strong>No attached portfolio state</strong>
              <span>PORT is ready, but this runtime has no local positions.</span>
              <button
                type="button"
                className="btn btn--accent"
                onClick={() => navigate("/fn/PORT")}
                style={{ width: "fit-content" }}
              >
                Open PORT
              </button>
            </div>
          )}
        </CardBody>
      </Card>

      <aside className="showme-home__section showme-home__section--3" style={{ display: "grid", gap: 14, minHeight: 0 }}>
        <Card variant="elev-2">
          <CardHeader>Command deck</CardHeader>
          <CardBody>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              {commandDeck.map((fn) => (
                <button
                  key={fn.code}
                  type="button"
                  className="showme-home__command"
                  onClick={() => navigate(`/fn/${fn.code}`)}
                  style={commandButtonStyle}
                >
                  <strong>{fn.code}</strong>
                  <span>{fn.name}</span>
                </button>
              ))}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>Function inventory</CardHeader>
          <CardBody>
            <DataGrid columns={CATEGORY_COLUMNS} rows={rows} rowKey={(r) => r.category} density="compact" />
          </CardBody>
        </Card>
      </aside>

      <Card className="showme-home__section showme-home__section--4" style={{ minHeight: 0 }}>
        <CardHeader trailing={`${classRows.length} classes`}>
          Exposure
        </CardHeader>
        <CardBody>
          {classRows.length ? (
            <div style={{ display: "grid", gap: 8 }}>
              {classRows.map(([cls, mv]) => (
                <ExposureBar
                  key={cls}
                  label={cls}
                  value={mv}
                  total={totals?.market_value ?? 0}
                />
              ))}
            </div>
          ) : (
            <div style={emptyPanelStyle}>No exposure rows</div>
          )}
        </CardBody>
      </Card>

      <Card className="showme-home__section showme-home__section--5">
        <CardHeader>Workspace presets</CardHeader>
        <CardBody>
          <div style={{ display: "grid", gap: 6 }}>
            {BUILTIN_PRESETS.map((p) => (
              <button
                key={p.id}
                type="button"
                className="showme-home__preset"
                onClick={() => {
                  loadBuiltinPreset(p.id);
                  navigate(`/${p.id === "macro" ? "fn/WEI" : "fn/PORT"}`);
                }}
                style={presetButtonStyle}
              >
                <strong>{p.label}</strong>
                <span>{p.description}</span>
              </button>
            ))}
          </div>
        </CardBody>
      </Card>
    </main>
  );
}

function MetricCard({ label, value, order }: { label: string; value: string; order: number }) {
  const negative = value.startsWith("-");
  return (
    <Card
      className="showme-home__metric"
      density="compact"
      variant="elev-2"
      style={{ animationDelay: `${80 + order * 48}ms` }}
    >
      <CardBody>
        <div style={{ color: "var(--text-mute)", fontSize: 10, textTransform: "uppercase" }}>
          {label}
        </div>
        <div
          className="showme-home__metric-value"
          style={{
            color: negative ? "var(--negative)" : "var(--text-primary)",
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 18,
            marginTop: 4,
          }}
        >
          {value}
        </div>
      </CardBody>
    </Card>
  );
}

function ExposureBar({
  label,
  value,
  total,
}: {
  label: string;
  value: number;
  total: number;
}) {
  const pct = total > 0 ? Math.max(0, Math.min(100, (value / total) * 100)) : 0;
  return (
    <div style={{ display: "grid", gap: 4 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 11 }}>
        <strong>{label}</strong>
        <span style={{ color: "var(--text-secondary)" }}>{money(value)}</span>
      </div>
      <div
        className="showme-exposure__track"
        style={{
          height: 6,
          background: "var(--bg-elev-3)",
          borderRadius: 999,
          overflow: "hidden",
        }}
      >
        <div
          key={`${label}-${value}-${pct.toFixed(2)}`}
          className="showme-exposure__fill"
          style={{
            width: `${pct}%`,
            height: "100%",
            background: "var(--accent)",
          }}
        />
      </div>
    </div>
  );
}

function fallbackEntry(code: string): FunctionEntry {
  return {
    code,
    name: code === "CN" ? "Company News" : code,
    category: "screen",
    description: "",
  };
}

function money(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "-";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  return `${sign}$${abs.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function signedMoney(value?: number | null): string {
  if (value == null || !Number.isFinite(value)) return "-";
  return `${value >= 0 ? "+" : "-"}${money(Math.abs(value))}`;
}

function shortPath(path: string | null): string {
  if (!path) return "";
  const home = "/Users/nazmi/";
  return path.startsWith(home) ? `~/${path.slice(home.length)}` : path;
}

const commandButtonStyle = {
  background: "var(--bg-elev-1)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  cursor: "default",
  display: "grid",
  gap: 3,
  minHeight: 48,
  padding: "8px 10px",
  textAlign: "left" as const,
};

const presetButtonStyle = {
  ...commandButtonStyle,
  gridTemplateColumns: "120px 1fr",
  minHeight: 40,
};

const emptyPanelStyle = {
  border: "1px dashed var(--border-strong)",
  borderRadius: "var(--radius-md)",
  color: "var(--text-secondary)",
  display: "grid",
  gap: 8,
  minHeight: 126,
  placeContent: "center",
  textAlign: "center" as const,
};
