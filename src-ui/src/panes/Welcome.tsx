import { useMemo } from "react";
import { useAppStore } from "@/lib/store";
import {
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  ChangeText,
  DataGrid,
  type DataGridColumn,
  Pill,
  Skeleton,
} from "@/design-system";
import type { FunctionEntry } from "@/lib/sidecar";
import { navigate } from "@/lib/router";
import { t } from "@/i18n";
import { BUILTIN_PRESETS, loadBuiltinPreset } from "@/lib/builtinPresets";

interface CategoryRow {
  category: string;
  count: number;
  share: number;
}

const COLUMNS: DataGridColumn<CategoryRow>[] = [
  { key: "category", header: "Category", width: "1fr" },
  { key: "count", header: "n", numeric: true, width: 60 },
  {
    key: "share",
    header: "Share",
    numeric: true,
    width: 90,
    render: (r) => `${(r.share * 100).toFixed(1)}%`,
  },
];

export function Welcome() {
  const status = useAppStore((s) => s.sidecarStatus);
  const engine = useAppStore((s) => s.engineRoot);
  const port = useAppStore((s) => s.sidecarPort);
  const idx = useAppStore((s) => s.functionIndex);
  const total = idx.length;

  const rows = useMemo<CategoryRow[]>(() => {
    if (!total) return [];
    const counts = new Map<string, number>();
    for (const fn of idx) counts.set(fn.category, (counts.get(fn.category) ?? 0) + 1);
    return [...counts.entries()]
      .map(([category, count]) => ({ category, count, share: count / total }))
      .sort((a, b) => b.count - a.count);
  }, [idx, total]);

  const recent: FunctionEntry[] = idx.slice(0, 6);

  return (
    <main
      style={{
        padding: 18,
        display: "grid",
        gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)",
        gap: 18,
        overflowY: "auto",
      }}
    >
      <header
        style={{
          gridColumn: "1 / -1",
          display: "flex",
          alignItems: "baseline",
          gap: 12,
        }}
      >
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
        <Pill tone={status === "healthy" ? "positive" : status === "stub" ? "muted" : "warn"}>
          {status}
        </Pill>
        {port && (
          <span style={{ fontSize: 11, color: "var(--text-mute)" }}>
            runtime :{port}
          </span>
        )}
      </header>

      <Card>
        <CardHeader trailing={<ChangeText value={total || null} digits={0} signed={false} />}>
          Function inventory
        </CardHeader>
        <CardBody>
          {total === 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <Skeleton height={14} />
              <Skeleton height={14} width="80%" />
              <Skeleton height={14} width="64%" />
            </div>
          ) : (
            <DataGrid columns={COLUMNS} rows={rows} rowKey={(r) => r.category} density="compact" />
          )}
        </CardBody>
        <CardFooter>
          Live from the Python runtime at <code>{port ? `127.0.0.1:${port}` : "—"}</code>
        </CardFooter>
      </Card>

      <Card>
        <CardHeader>Workspace presets</CardHeader>
        <CardBody>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {BUILTIN_PRESETS.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => {
                  loadBuiltinPreset(p.id);
                  navigate(`/fn/${
                    p.id === "trading-desk" ? "DES" :
                    p.id === "macro" ? "WEI" : "DES"
                  }`);
                }}
                style={{
                  background: "transparent",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--text-primary)",
                  textAlign: "left",
                  padding: "8px 10px",
                  cursor: "default",
                  display: "grid",
                  gridTemplateColumns: "1fr auto",
                  gap: 8,
                  fontSize: 12,
                  transition: "background var(--motion-fast)",
                }}
                onMouseEnter={(e) =>
                  ((e.currentTarget as HTMLElement).style.background =
                    "var(--bg-elev-2)")
                }
                onMouseLeave={(e) =>
                  ((e.currentTarget as HTMLElement).style.background =
                    "transparent")
                }
              >
                <span>
                  <strong style={{ fontWeight: 600 }}>{p.label}</strong>
                  <div style={{ color: "var(--text-mute)", fontSize: 10 }}>
                    {p.description}
                  </div>
                </span>
                <span
                  style={{
                    color: "var(--accent)",
                    fontFamily: "JetBrains Mono, monospace",
                    fontSize: 10,
                  }}
                >
                  Open ↗
                </span>
              </button>
            ))}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>Quick launch</CardHeader>
        <CardBody>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {recent.map((fn) => (
              <button
                key={fn.code}
                type="button"
                onClick={() => navigate(`/fn/${fn.code}`)}
                style={{
                  background: "transparent",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "var(--radius-sm)",
                  color: "var(--text-primary)",
                  textAlign: "left",
                  padding: "6px 10px",
                  cursor: "default",
                  display: "grid",
                  gridTemplateColumns: "60px 1fr auto",
                  gap: 10,
                  fontFamily: "JetBrains Mono, monospace",
                  fontSize: 11,
                  transition: "background var(--motion-fast)",
                }}
                onMouseEnter={(e) =>
                  ((e.currentTarget as HTMLElement).style.background =
                    "var(--bg-elev-2)")
                }
                onMouseLeave={(e) =>
                  ((e.currentTarget as HTMLElement).style.background =
                    "transparent")
                }
              >
                <span style={{ color: "var(--accent)", fontWeight: 700 }}>
                  {fn.code}
                </span>
                <span style={{ color: "var(--text-primary)" }}>{fn.name}</span>
                <span style={{ color: "var(--text-mute)", fontSize: 10 }}>
                  {fn.category}
                </span>
              </button>
            ))}
            {!recent.length && <Skeleton height={120} />}
          </div>
        </CardBody>
      </Card>

      <Card style={{ gridColumn: "1 / -1" }}>
        <CardHeader>Quality standard</CardHeader>
        <CardBody>
          <ul
            style={{
              color: "var(--text-secondary)",
              fontSize: 12,
              paddingLeft: 16,
              margin: "4px 0",
            }}
          >
            <li>Every function must run with a compatible asset class and documented input profile.</li>
            <li>Live provider failures are shown as actionable data requirements, not silent placeholder output.</li>
            <li>News surfaces expose relevance, importance, severity, and alert flags.</li>
            <li>Portfolio functions read local Application Support state and support explicit Advanced overrides.</li>
          </ul>
        </CardBody>
        <CardFooter>
          Open Preferences for theme, color, density, language, streams, secrets, migration, and installation controls.
        </CardFooter>
      </Card>

      <Card>
        <CardHeader>Runtime</CardHeader>
        <CardBody>
          <dl
            style={{
              display: "grid",
              gridTemplateColumns: "120px 1fr",
              gap: "6px 16px",
              fontSize: 12,
            }}
          >
            <dt style={{ color: "var(--text-mute)" }}>{t("shell.status.sidecar")}</dt>
            <dd style={{ margin: 0 }}>{status}</dd>
            <dt style={{ color: "var(--text-mute)" }}>{t("shell.status.functions")}</dt>
            <dd style={{ margin: 0 }}>{total}</dd>
            <dt style={{ color: "var(--text-mute)" }}>data root</dt>
            <dd
              style={{
                margin: 0,
                fontFamily: "JetBrains Mono, monospace",
                color: "var(--text-secondary)",
              }}
            >
              {engine ?? "(not attached)"}
            </dd>
          </dl>
        </CardBody>
      </Card>
    </main>
  );
}
