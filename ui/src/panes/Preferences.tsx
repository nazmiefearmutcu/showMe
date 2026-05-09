import { useEffect, useMemo, useState } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  DataGrid,
  type DataGridColumn,
  Field,
  FieldRow,
  Pill,
  Tabs,
} from "@/design-system";
import {
  applyAccent,
  applyDensity,
  applyTheme,
  readAccent,
  readDensity,
  readTheme,
  type Accent,
  type Density,
  type Theme,
} from "@/lib/theme";
import { listLocales, locale, setLocale, t, type Locale } from "@/i18n";
import { invoke, isInTauri } from "@/lib/tauri";
import { toast } from "@/lib/toast";
import { useAppStore } from "@/lib/store";
import {
  fetchSidecarInfo,
  fetchStreamStats,
  type StreamChannelStats,
} from "@/lib/sidecar";
import {
  deleteSecret,
  listSecrets,
  secretsBackend,
  setSecret,
  type KeychainEntry,
  type SecretsBackend,
} from "@/lib/secrets";
import { capabilities, type BiometricCapabilities } from "@/lib/biometric";
import {
  applyUpdate,
  checkForUpdates,
  type UpdateInfo,
} from "@/lib/updater";

const SECTIONS = [
  "appearance",
  "data",
  "streams",
  "secrets",
  "migration",
  "llm",
  "about",
] as const;

const LOCALE_LABELS: Record<Locale, string> = {
  en: "English",
  tr: "Türkçe",
  de: "Deutsch",
  fr: "Français",
  es: "Español",
  it: "Italiano",
  ja: "日本語",
  zh: "中文",
  ko: "한국어",
  ar: "العربية",
  pt: "Português",
  ru: "Русский",
};

export function Preferences({ section }: { section?: string }) {
  const initial = useMemo<typeof SECTIONS[number]>(
    () =>
      section && (SECTIONS as readonly string[]).includes(section)
        ? (section as typeof SECTIONS[number])
        : "appearance",
    [section],
  );
  const [active, setActive] = useState(initial);
  const [theme, setThemeState] = useState<Theme>(readTheme());
  const [accent, setAccentState] = useState<Accent>(readAccent());
  const [density, setDensityState] = useState<Density>(readDensity());
  const [loc, setLocState] = useState<Locale>(locale());
  const [info, setInfo] = useState<Awaited<ReturnType<typeof fetchSidecarInfo>> | null>(null);
  const engineRoot = useAppStore((s) => s.engineRoot);
  const port = useAppStore((s) => s.sidecarPort);
  const status = useAppStore((s) => s.sidecarStatus);

  useEffect(() => {
    fetchSidecarInfo().then(setInfo).catch(() => setInfo(null));
  }, [port]);

  const applyThemeChoice = (next: Theme) => {
    applyTheme(next);
    setThemeState(next);
    toast.info(`Theme: ${next}`);
  };
  const applyAccentChoice = (next: Accent) => {
    applyAccent(next);
    setAccentState(next);
    toast.info(`Accent: ${next}`);
  };
  const applyDensityChoice = (next: Density) => {
    applyDensity(next);
    setDensityState(next);
    toast.info(`Density: ${next}`);
  };
  const applyLocale = (next: Locale) => {
    setLocale(next);
    setLocState(next);
    toast.info(`Language → ${LOCALE_LABELS[next]}`);
  };

  return (
    <main
      style={{
        padding: 18,
        display: "flex",
        flexDirection: "column",
        gap: 12,
        overflowY: "auto",
      }}
    >
      <header style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <h1
          style={{
            margin: 0,
            fontSize: 22,
            fontFamily: "Inter, SF Pro Text, system-ui",
            letterSpacing: 0,
          }}
        >
          {t("preferences.title")}
        </h1>
        <Pill tone={status === "healthy" ? "positive" : "muted"}>{status}</Pill>
      </header>

      <Tabs
        items={SECTIONS.map((s) => ({ id: s, label: t(`preferences.${s}`) }))}
        active={active}
        onChange={(id) => setActive(id as typeof SECTIONS[number])}
      />

      {active === "appearance" && (
        <Card>
          <CardHeader>{t("preferences.appearance")}</CardHeader>
          <CardBody>
            <FieldRow>
              <label
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 4,
                  width: "100%",
                }}
              >
                <span
                  style={{
                    fontSize: 10,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    color: "var(--text-mute)",
                  }}
                >
                  {t("preferences.appearance.theme")}
                </span>
                <select
                  value={theme}
                  onChange={(e) => applyThemeChoice(e.target.value as Theme)}
                  style={selectStyle}
                >
                  <option value="dark">Dark</option>
                  <option value="light">Light</option>
                </select>
              </label>
              <label
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 4,
                  width: "100%",
                }}
              >
                <span
                  style={{
                    fontSize: 10,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    color: "var(--text-mute)",
                  }}
                >
                  {t("preferences.appearance.language")}
                </span>
                <select
                  value={loc}
                  onChange={(e) => applyLocale(e.target.value as Locale)}
                  style={selectStyle}
                >
                  {listLocales().map((l) => (
                    <option value={l} key={l}>
                      {LOCALE_LABELS[l]}
                    </option>
                  ))}
                </select>
              </label>
            </FieldRow>
            <FieldRow>
              <label
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 4,
                  width: "100%",
                }}
              >
                <span
                  style={{
                    fontSize: 10,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    color: "var(--text-mute)",
                  }}
                >
                  {t("preferences.appearance.accent")}
                </span>
                <select
                  value={accent}
                  onChange={(e) => applyAccentChoice(e.target.value as Accent)}
                  style={selectStyle}
                >
                  <option value="cyan">Cyan</option>
                  <option value="amber">Amber</option>
                  <option value="violet">Violet</option>
                  <option value="lime">Lime</option>
                </select>
              </label>
              <label
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 4,
                  width: "100%",
                }}
              >
                <span
                  style={{
                    fontSize: 10,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    color: "var(--text-mute)",
                  }}
                >
                  {t("preferences.appearance.density")}
                </span>
                <select
                  value={density}
                  onChange={(e) => applyDensityChoice(e.target.value as Density)}
                  style={selectStyle}
                >
                  <option value="compact">Compact</option>
                  <option value="comfortable">Comfortable</option>
                </select>
              </label>
            </FieldRow>
          </CardBody>
        </Card>
      )}

      {active === "data" && (
        <Card>
          <CardHeader>{t("preferences.data")}</CardHeader>
          <CardBody>
            <FieldRow>
              <Field
                label={t("preferences.data.engine_root")}
                value={engineRoot ?? ""}
                placeholder="/path/to/ShowMe"
                readOnly
              />
              <Field
                label={t("preferences.data.app_data")}
                value="~/Library/Application Support/showMe"
                readOnly
                trailing={
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await invoke("open_data_folder");
                      } catch (err) {
                        toast.error("Reveal failed", String(err));
                      }
                    }}
                    style={btnStyle}
                  >
                    {t("preferences.data.reveal")}
                  </button>
                }
              />
            </FieldRow>
          </CardBody>
        </Card>
      )}

      {active === "streams" && <StreamsSection />}

      {active === "secrets" && <SecretsSection />}

      {active === "migration" && <MigrationSection />}

      {active === "llm" && <LlmSection />}

      {active === "about" && <AboutSection info={info} />}
    </main>
  );
}

const selectStyle = {
  background: "var(--bg-elev-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  color: "var(--text-primary)",
  font: "inherit",
  fontSize: 12,
  height: 28,
  padding: "0 8px",
  appearance: "none",
} as const;

const btnStyle = {
  background: "var(--bg-elev-3)",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  font: "inherit",
  fontSize: 11,
  padding: "2px 8px",
  cursor: "default",
};

// ── Secrets section (Round 20) ───────────────────────────────────────────

function SecretsSection() {
  const [entries, setEntries] = useState<KeychainEntry[]>([]);
  const [account, setAccount] = useState("");
  const [value, setValue] = useState("");
  const [caps, setCaps] = useState<BiometricCapabilities | null>(null);
  const [backend, setBackend] = useState<SecretsBackend>("browser");
  const writable = backend === "keychain";

  useEffect(() => {
    listSecrets().then(setEntries).catch(() => setEntries([]));
    capabilities().then(setCaps).catch(() => setCaps(null));
    secretsBackend().then(setBackend).catch(() => setBackend("unsupported"));
  }, []);

  const refresh = () => {
    listSecrets().then(setEntries).catch(() => setEntries([]));
  };

  const onSave = async () => {
    if (!account.trim() || !value) return;
    try {
      await setSecret(account.trim(), value);
      setValue("");
      setAccount("");
      refresh();
      toast.success("Secret stored", account.trim());
    } catch (err) {
      toast.error("Save failed", String(err));
    }
  };

  const onDelete = async (acct: string) => {
    try {
      const ok = await deleteSecret(acct);
      if (ok) {
        toast.warn("Secret removed", acct);
        refresh();
      }
    } catch (err) {
      toast.error("Delete failed", String(err));
    }
  };

  const backendNote = (() => {
    if (backend === "browser")
      return "Keychain is only available inside the native app. In browser preview this surface is read-only.";
    if (backend === "unsupported")
      return "This OS doesn't expose the macOS Keychain. Use environment variables until a local fallback vault is configured.";
    return null;
  })();

  return (
    <Card>
      <CardHeader
        trailing={
          <span style={{ display: "flex", gap: 6 }}>
            <Pill
              tone={
                backend === "keychain"
                  ? "positive"
                  : backend === "browser"
                    ? "muted"
                    : "warn"
              }
              withDot={false}
            >
              {backend === "keychain"
                ? "Keychain"
                : backend === "browser"
                  ? "Browser"
                  : "Unsupported"}
            </Pill>
            {caps && (
              <Pill
                tone={caps.biometry_available ? "positive" : "muted"}
                withDot={false}
              >
                {caps.biometry_available
                  ? caps.biometry_kind === "face_id"
                    ? "Face ID"
                    : "Touch ID"
                  : "no biometry"}
              </Pill>
            )}
          </span>
        }
      >
        Secrets
      </CardHeader>
      <CardBody>
        {backendNote && (
          <p
            style={{
              fontSize: 11,
              color: "var(--text-mute)",
              margin: "0 0 8px",
            }}
          >
            {backendNote}
          </p>
        )}
        <FieldRow>
          <Field
            label="Account"
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            placeholder="e.g. finnhub, openai"
          />
          <Field
            label="Secret"
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="paste API key"
            trailing={
              <button
                type="button"
                onClick={onSave}
                disabled={!writable || !account.trim() || !value}
                className="btn btn--accent"
                style={{ height: 22, fontSize: 10 }}
              >
                Save
              </button>
            }
          />
        </FieldRow>

        <div
          style={{
            marginTop: 12,
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          {entries.length === 0 && (
            <span style={{ color: "var(--text-mute)", fontSize: 11 }}>
              no stored secrets
            </span>
          )}
          {entries.map((e) => (
            <div
              key={e.account}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 100px auto",
                gap: 6,
                padding: "4px 6px",
                background: "var(--bg-elev-2)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-sm)",
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 11,
                alignItems: "center",
              }}
            >
              <span>{e.account}</span>
              <span style={{ color: "var(--text-mute)", fontSize: 10 }}>
                {e.service.split(".").slice(-2).join(".")}
              </span>
              <button
                type="button"
                onClick={() => onDelete(e.account)}
                className="btn btn--ghost"
                style={{ height: 18, fontSize: 10 }}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  );
}

// ── Migration section ────────────────────────────────────────────────────

interface MigrationSummary {
  source: string;
  target: string;
  positions_imported: number;
  positions_skipped: number;
  trades_imported: number;
  trades_skipped: number;
  daily_pnl?: number | null;
  paper_balance?: number | null;
  bot_start_time?: string | null;
  mode: string;
  warnings: string[];
}

function MigrationSection() {
  const inTauri = isInTauri();
  const [enginePath, setEnginePathLocal] = useState(
    "/Users/nazmi/Desktop/Projeler/proje/showMe/engine",
  );
  const [writable, setWritable] = useState(false);
  const [running, setRunning] = useState(false);
  const [last, setLast] = useState<MigrationSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const engineRoot = useAppStore((s) => s.engineRoot);

  useEffect(() => {
    if (engineRoot) setEnginePathLocal(engineRoot);
  }, [engineRoot]);

  const onRun = async () => {
    if (!inTauri) {
      toast.warn("Native app required", "Use the CLI in browser preview.");
      return;
    }
    setRunning(true);
    setError(null);
    try {
      const res = await invoke<MigrationSummary>("run_migration", {
        enginePath,
        writable,
      });
      setLast(res);
      toast.success(
        "Migration done",
        `${res.positions_imported} positions · ${res.trades_imported} trades`,
      );
    } catch (err) {
      setError(String(err));
      toast.error("Migration failed", String(err));
    } finally {
      setRunning(false);
    }
  };

  return (
    <Card>
      <CardHeader
        trailing={
          <Pill tone={writable ? "warn" : "muted"} withDot={false}>
            {writable ? "writable" : "read-only mirror"}
          </Pill>
        }
      >
        State importer
      </CardHeader>
      <CardBody>
        <p
          style={{
            margin: "0 0 8px",
            fontSize: 12,
            color: "var(--text-secondary)",
            lineHeight: 1.5,
          }}
        >
          One-shot copy of a source <code>runtime/state.json</code> into the
          showMe portfolio database at{" "}
          <code>~/Library/Application Support/showMe/data/portfolio.db</code>.
          Idempotent — re-running upserts on (symbol, side, opened_at).
        </p>

        <FieldRow>
          <Field
            label="ShowMe engine path"
            value={enginePath}
            onChange={(e) => setEnginePathLocal(e.target.value)}
            placeholder="/path/to/ShowMe"
            hint="Defaults to the bundled ShowMe engine"
          />
          <label
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 4,
              width: "100%",
            }}
          >
            <span
              style={{
                fontSize: 10,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                color: "var(--text-mute)",
              }}
            >
              Mode
            </span>
            <div style={{ display: "flex", gap: 6, height: 28, alignItems: "center" }}>
              <button
                type="button"
                onClick={() => setWritable(false)}
                style={{
                  ...modeBtn,
                  background: !writable ? "var(--accent-soft)" : "var(--bg-elev-2)",
                  color: !writable ? "var(--accent)" : "var(--text-secondary)",
                  borderColor: !writable ? "var(--accent)" : "var(--border-subtle)",
                }}
              >
                Read-only mirror
              </button>
              <button
                type="button"
                onClick={() => setWritable(true)}
                style={{
                  ...modeBtn,
                  background: writable ? "var(--accent-soft)" : "var(--bg-elev-2)",
                  color: writable ? "var(--accent)" : "var(--text-secondary)",
                  borderColor: writable ? "var(--accent)" : "var(--border-subtle)",
                }}
              >
                Writable copy
              </button>
            </div>
          </label>
        </FieldRow>

        <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}>
          <button
            type="button"
            className="btn btn--accent"
            onClick={onRun}
            disabled={running || !enginePath.trim()}
            style={{ height: 26 }}
          >
            {running ? "Running…" : "Run import"}
          </button>
          {!inTauri && (
            <span style={{ fontSize: 11, color: "var(--text-mute)" }}>
              CLI: <code>python3 -m showme.migration</code>
            </span>
          )}
        </div>

        {error && (
          <div
            style={{
              marginTop: 12,
              padding: 8,
              background: "var(--bg-elev-2)",
              border: "1px solid var(--negative)",
              borderRadius: "var(--radius-sm)",
              color: "var(--negative)",
              fontSize: 11,
              fontFamily: "JetBrains Mono, monospace",
            }}
          >
            {error}
          </div>
        )}

        {last && (
          <div
            style={{
              marginTop: 12,
              padding: 12,
              background: "var(--bg-elev-2)",
              border: "1px solid var(--border-subtle)",
              borderRadius: "var(--radius-md)",
            }}
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                gap: 10,
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 12,
              }}
            >
              <SummaryStat label="positions" value={last.positions_imported} />
              <SummaryStat label="trades" value={last.trades_imported} />
              <SummaryStat
                label="paper $"
                value={
                  last.paper_balance != null
                    ? `$${last.paper_balance.toLocaleString(undefined, {
                        maximumFractionDigits: 2,
                      })}`
                    : "—"
                }
              />
              <SummaryStat
                label="daily P&L"
                value={
                  last.daily_pnl != null
                    ? last.daily_pnl.toLocaleString(undefined, {
                        maximumFractionDigits: 2,
                      })
                    : "—"
                }
              />
              <SummaryStat
                label="skipped"
                value={last.positions_skipped + last.trades_skipped}
              />
              <SummaryStat label="mode" value={last.mode} />
            </div>
            {last.warnings.length > 0 && (
              <ul
                style={{
                  margin: "10px 0 0",
                  paddingLeft: 16,
                  fontSize: 11,
                  color: "var(--text-secondary)",
                }}
              >
                {last.warnings.slice(0, 5).map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function SummaryStat({
  label,
  value,
}: {
  label: string;
  value: number | string;
}) {
  return (
    <div>
      <div
        style={{
          fontSize: 10,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          color: "var(--text-mute)",
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 15, color: "var(--text-primary)" }}>{value}</div>
    </div>
  );
}

const modeBtn: React.CSSProperties = {
  height: 24,
  padding: "0 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  cursor: "default",
};

// ── Streams diagnostics ──────────────────────────────────────────────────

function StreamsSection() {
  const port = useAppStore((s) => s.sidecarPort);
  const [stats, setStats] = useState<Awaited<ReturnType<typeof fetchStreamStats>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchStreamStats()
      .then((res) => !cancelled && setStats(res))
      .catch((err) => !cancelled && setError(String(err)));
    return () => {
      cancelled = true;
    };
  }, [port, tick]);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 2500);
    return () => clearInterval(id);
  }, []);

  const rows = stats?.channels ?? [];
  const subscribers = rows.reduce((sum, row) => sum + row.subscribers, 0);
  const cols = useMemo<DataGridColumn<StreamChannelStats>[]>(
    () => [
      { key: "symbol", header: "Symbol", width: 120 },
      {
        key: "subscribers",
        header: "Subs",
        numeric: true,
        width: 80,
      },
      {
        key: "last_price",
        header: "Last",
        numeric: true,
        width: 120,
        render: (row) =>
          row.last_price == null
            ? "-"
            : row.last_price.toLocaleString(undefined, {
                maximumFractionDigits: 6,
              }),
      },
      {
        key: "source",
        header: "Source",
        width: 100,
        render: (row) => row.source ?? "-",
      },
    ],
    [],
  );

  return (
    <Card>
      <CardHeader
        trailing={
          <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <Pill tone={subscribers > 0 ? "positive" : "muted"} withDot={subscribers > 0}>
              {subscribers} subs
            </Pill>
            <button
              type="button"
              onClick={() => setTick((t) => t + 1)}
              className="btn btn--ghost"
              style={{ height: 24 }}
            >
              Refresh
            </button>
          </span>
        }
      >
        {t("preferences.streams")}
      </CardHeader>
      <CardBody>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
            gap: 10,
            marginBottom: 12,
          }}
        >
          <SummaryStat label="channels" value={rows.length} />
          <SummaryStat label="subscribers" value={subscribers} />
          <SummaryStat
            label="status"
            value={error ? "error" : subscribers > 0 ? "live" : "idle"}
          />
        </div>

        {error ? (
          <pre
            style={{
              margin: 0,
              padding: 8,
              background: "var(--bg-elev-2)",
              border: "1px solid var(--negative)",
              borderRadius: "var(--radius-sm)",
              color: "var(--negative)",
              fontSize: 11,
              whiteSpace: "pre-wrap",
            }}
          >
            {error}
          </pre>
        ) : rows.length === 0 ? (
          <div style={{ color: "var(--text-mute)", fontSize: 12 }}>
            no active stream channels
          </div>
        ) : (
          <DataGrid
            columns={cols}
            rows={rows}
            rowKey={(row) => row.symbol}
            density="compact"
          />
        )}
      </CardBody>
    </Card>
  );
}

// ── About + auto-update ────────────────────────────────────────────────

function AboutSection({
  info,
}: {
  info: Awaited<ReturnType<typeof fetchSidecarInfo>> | null;
}) {
  const [check, setCheck] = useState<UpdateInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [applying, setApplying] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [installResult, setInstallResult] = useState<InstallResult | null>(null);
  const inTauri = isInTauri();

  const onCheck = async () => {
    setBusy(true);
    try {
      const res = await checkForUpdates();
      setCheck(res);
      if (res.error) toast.warn("Updater error", res.error);
      else if (res.available)
        toast.info(
          "Update available",
          `${res.current_version} → ${res.latest_version}`,
        );
      else toast.info("Up to date", res.current_version);
    } catch (err) {
      toast.error("Updater failed", String(err));
    } finally {
      setBusy(false);
    }
  };

  const onApply = async () => {
    setApplying(true);
    try {
      await applyUpdate();
    } catch (err) {
      toast.error("Update failed", String(err));
      setApplying(false);
    }
  };

  const onInstall = async () => {
    if (!inTauri) {
      toast.warn("Native app required", "Build the app first, then install.");
      return;
    }
    setInstalling(true);
    try {
      const res = await invoke<InstallResult>("install_to_applications");
      setInstallResult(res);
      toast.success(
        res.already_installed ? "Already in Applications" : "Installed",
        res.target,
      );
    } catch (err) {
      toast.error("Install failed", String(err));
    } finally {
      setInstalling(false);
    }
  };

  return (
    <Card>
      <CardHeader
        trailing={
          <button
            type="button"
            onClick={onCheck}
            disabled={busy}
            className="btn btn--accent"
            style={{ height: 24 }}
          >
            {busy ? "Checking…" : "Check for updates"}
          </button>
        }
      >
        {t("preferences.about")}
      </CardHeader>
      <CardBody>
        <dl
          style={{
            display: "grid",
            gridTemplateColumns: "180px 1fr",
            gap: "6px 16px",
            fontSize: 12,
          }}
        >
          <dt style={{ color: "var(--text-mute)" }}>
            {t("preferences.about.version")}
          </dt>
          <dd style={{ margin: 0 }}>{info?.version ?? "—"}</dd>
          <dt style={{ color: "var(--text-mute)" }}>
            {t("preferences.about.python")}
          </dt>
          <dd
            style={{
              margin: 0,
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 11,
            }}
          >
            {info?.python?.split(" ")[0] ?? "—"}
          </dd>
          <dt style={{ color: "var(--text-mute)" }}>
            {t("preferences.about.tauri")}
          </dt>
          <dd style={{ margin: 0 }}>2.x</dd>
          <dt style={{ color: "var(--text-mute)" }}>engine attached</dt>
          <dd style={{ margin: 0 }}>
            {info?.engine?.engine_attached ? "yes" : "no"}
          </dd>
        </dl>

        <div
          style={{
            marginTop: 14,
            padding: 10,
            background: "var(--bg-elev-2)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-md)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <div>
            <div style={{ fontWeight: 700 }}>Applications install</div>
            <div style={{ color: "var(--text-mute)", fontSize: 11 }}>
              {inTauri
                ? "Copy this signed app bundle into /Applications."
                : "Available after running the native app build."}
            </div>
            {installResult && (
              <div
                style={{
                  marginTop: 4,
                  color: "var(--positive)",
                  fontSize: 11,
                  fontFamily: "JetBrains Mono, monospace",
                }}
              >
                {installResult.target}
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onInstall}
            disabled={installing || !inTauri}
            className="btn btn--accent"
            style={{ height: 26 }}
          >
            {installing ? "Installing..." : "Install to Applications"}
          </button>
        </div>

        {check && (
          <div
            style={{
              marginTop: 14,
              padding: 10,
              background: "var(--bg-elev-2)",
              border: "1px solid var(--border-subtle)",
              borderRadius: "var(--radius-md)",
              fontSize: 12,
            }}
          >
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <Pill
                tone={
                  check.error
                    ? "warn"
                    : check.available
                      ? "positive"
                      : "muted"
                }
                withDot={false}
              >
                {check.error
                  ? "error"
                  : check.available
                    ? "update available"
                    : "up to date"}
              </Pill>
              <span style={{ color: "var(--text-mute)" }}>
                current {check.current_version}
                {check.latest_version
                  ? ` · latest ${check.latest_version}`
                  : ""}
              </span>
            </div>
            {check.release_notes && (
              <pre
                style={{
                  marginTop: 8,
                  padding: 8,
                  background: "var(--bg-elev-3)",
                  borderRadius: "var(--radius-sm)",
                  fontSize: 11,
                  whiteSpace: "pre-wrap",
                  overflow: "auto",
                  maxHeight: 200,
                }}
              >
                {check.release_notes}
              </pre>
            )}
            {check.available && !check.error && (
              <div style={{ marginTop: 10 }}>
                <button
                  type="button"
                  onClick={onApply}
                  disabled={applying}
                  className="btn btn--accent"
                  style={{ height: 26 }}
                >
                  {applying ? "Downloading…" : "Download & restart"}
                </button>
              </div>
            )}
            {check.error && (
              <pre
                style={{
                  marginTop: 8,
                  fontSize: 11,
                  color: "var(--negative)",
                }}
              >
                {check.error}
              </pre>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

// ── LLM cost ledger section ────────────────────────────────────────────

interface LlmCost {
  today_usd: number;
  cap_usd: number;
  remaining_usd: number;
  exhausted: boolean;
  providers: Array<{ name: string; model: string }>;
  entries: Array<{
    ts: string;
    provider: string;
    model: string;
    input_tokens: number;
    output_tokens: number;
    usd: number;
    purpose: string;
  }>;
}

interface InstallResult {
  ok: boolean;
  source: string;
  target: string;
  already_installed: boolean;
}

function LlmSection() {
  const port = useAppStore((s) => s.sidecarPort);
  const [data, setData] = useState<LlmCost | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!port) return;
    let cancelled = false;
    setError(null);
    fetch(`http://127.0.0.1:${port}/api/llm/cost`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: LlmCost) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(String(err)));
    return () => {
      cancelled = true;
    };
  }, [port, tick]);

  return (
    <Card>
      <CardHeader
        trailing={
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => setTick((t) => t + 1)}
          >
            ⟳
          </button>
        }
      >
        LLM planner cost ledger
      </CardHeader>
      <CardBody>
        <p
          style={{
            margin: "0 0 8px",
            fontSize: 12,
            color: "var(--text-secondary)",
            lineHeight: 1.5,
          }}
        >
          Planner providers are used only when their keys are configured.
          Today's spend is capped at{" "}
          <code>${data?.cap_usd?.toFixed(2) ?? "1.00"}</code> — override
          via the <code>SHOWME_LLM_DAILY_USD</code> env var.
        </p>

        {error && (
          <div
            style={{
              padding: 8,
              background: "var(--bg-elev-2)",
              border: "1px solid var(--negative)",
              borderRadius: "var(--radius-sm)",
              color: "var(--negative)",
              fontSize: 11,
            }}
          >
            {error}
          </div>
        )}

        {data && (
          <>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                gap: 10,
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 12,
              }}
            >
              <SummaryStat
                label="today $"
                value={`$${data.today_usd.toFixed(4)}`}
              />
              <SummaryStat
                label="remaining"
                value={`$${data.remaining_usd.toFixed(4)}`}
              />
              <SummaryStat label="cap" value={`$${data.cap_usd.toFixed(2)}`} />
              <SummaryStat label="entries" value={data.entries.length} />
              <SummaryStat
                label="state"
                value={data.exhausted ? "capped" : "open"}
              />
              <SummaryStat
                label="providers"
                value={data.providers.length || "fallback only"}
              />
            </div>
            <div style={{ marginTop: 12 }}>
              <div
                style={{
                  fontSize: 10,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  color: "var(--text-mute)",
                  marginBottom: 6,
                }}
              >
                Configured providers
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {data.providers.length === 0 ? (
                  <span style={{ fontSize: 11, color: "var(--text-mute)" }}>
                    No API keys configured — deterministic planner only.
                  </span>
                ) : (
                  data.providers.map((p) => (
                    <Pill key={p.name} tone="accent" withDot={false}>
                      {p.name} · {p.model}
                    </Pill>
                  ))
                )}
              </div>
            </div>
            {data.entries.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <div
                  style={{
                    fontSize: 10,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    color: "var(--text-mute)",
                    marginBottom: 6,
                  }}
                >
                  Recent calls (last 50)
                </div>
                <div
                  style={{
                    border: "1px solid var(--border-subtle)",
                    borderRadius: "var(--radius-sm)",
                    overflow: "hidden",
                    maxHeight: 220,
                    overflowY: "auto",
                    fontSize: 11,
                    fontFamily: "JetBrains Mono, monospace",
                  }}
                >
                  {data.entries
                    .slice()
                    .reverse()
                    .map((e, i) => (
                      <div
                        key={i}
                        style={{
                          display: "grid",
                          gridTemplateColumns: "150px 1fr 70px 70px 80px",
                          padding: "4px 8px",
                          gap: 8,
                          borderBottom:
                            i === data.entries.length - 1
                              ? undefined
                              : "1px solid var(--border-subtle)",
                          color: "var(--text-secondary)",
                        }}
                      >
                        <span>{e.ts.slice(0, 19).replace("T", " ")}</span>
                        <span style={{ color: "var(--accent)" }}>
                          {e.provider} · {e.model}
                        </span>
                        <span>{e.input_tokens}↓</span>
                        <span>{e.output_tokens}↑</span>
                        <span
                          style={{
                            color:
                              e.usd >= 0.01
                                ? "var(--warn)"
                                : "var(--text-primary)",
                          }}
                        >
                          ${e.usd.toFixed(5)}
                        </span>
                      </div>
                    ))}
                </div>
              </div>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}
