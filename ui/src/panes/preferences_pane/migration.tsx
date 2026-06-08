import { useEffect, useState } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  Field,
  FieldRow,
  Pill,
} from "@/design-system";
import { invoke, isInTauri } from "@/lib/tauri";
import { toast } from "@/lib/toast";
import { useAppStore } from "@/lib/store";
import {
  readMigrationPath,
  readMigrationWritable,
  writeMigrationPath,
  writeMigrationWritable,
} from "@/lib/migration-prefs";
import { modeBtn, type MigrationSummary } from "./_types";

export function MigrationSection() {
  const inTauri = isInTauri();
  // Never prefill a real developer path here — the field used to ship the
  // hardcoded `/Users/nazmi/Desktop/Projeler/proje/showMe/engine` value which
  // leaked into every demo screenshot and silently no-op'd on other machines.
  // A persisted user value (set last session) takes precedence; otherwise we
  // start empty so the placeholder prompts, and the effect below fills in the
  // canonical `engineRoot` from the app store once the engine boots.
  const [enginePath, setEnginePathLocal] = useState(() => readMigrationPath() ?? "");
  const [writable, setWritableLocal] = useState(() => readMigrationWritable() ?? false);
  const [running, setRunning] = useState(false);
  const [last, setLast] = useState<MigrationSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const engineRoot = useAppStore((s) => s.engineRoot);

  useEffect(() => {
    // Only auto-fill from the store when the user has neither persisted nor
    // typed a path — a persisted/typed value must win over the auto-fill.
    if (engineRoot && !enginePath && !readMigrationPath()) {
      setEnginePathLocal(engineRoot);
    }
  }, [engineRoot, enginePath]);

  const setEnginePath = (next: string) => {
    setEnginePathLocal(next);
    writeMigrationPath(next);
  };
  const setWritable = (next: boolean) => {
    setWritableLocal(next);
    writeMigrationWritable(next);
  };

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
        <p className="prefs-lede u-mb-0">
          One-shot copy of a source <code>runtime/state.json</code> into the
          showMe portfolio database at{" "}
          <code>~/Library/Application Support/showMe/data/portfolio.db</code>.
          Idempotent — re-running upserts on (symbol, side, opened_at).
        </p>

        <FieldRow>
          <Field
            label="ShowMe engine path"
            value={enginePath}
            onChange={(e) => setEnginePath(e.target.value)}
            placeholder="~/path/to/legacy/data"
            hint="Defaults to the bundled ShowMe engine"
          />
          <label className="migration-mode-label">
            <span className="migration-mode-caption">Mode</span>
            <div
              role="radiogroup"
              aria-label="Migration mode"
              className="u-flex u-gap-6 prefs-h-28 u-items-center"
            >
              <button
                type="button"
                role="radio"
                aria-checked={!writable}
                onClick={() => setWritable(false)}
                style={modeBtn}
                className={`migration-mode-btn${!writable ? " migration-mode-btn--active" : ""}`}
              >
                Read-only mirror
              </button>
              <button
                type="button"
                role="radio"
                aria-checked={writable}
                onClick={() => setWritable(true)}
                style={modeBtn}
                className={`migration-mode-btn${writable ? " migration-mode-btn--active" : ""}`}
              >
                Writable copy
              </button>
            </div>
          </label>
        </FieldRow>

        <div className="u-mt-12 u-flex u-gap-8 u-items-center">
          <button
            type="button"
            className="btn btn--accent u-btn-26"
            onClick={onRun}
            disabled={running || !enginePath.trim()}
            aria-busy={running}
          >
            {running ? "Running…" : "Run import"}
          </button>
          {running && (
            <span role="status" aria-live="polite" className="u-text-11 u-text-mute">
              Importing state…
            </span>
          )}
          {!inTauri && (
            <span className="u-text-11 u-text-mute">
              CLI: <code>python3 -m showme.migration</code>
            </span>
          )}
        </div>

        {error && (
          <div role="alert" className="migration-error">{error}</div>
        )}

        {last && (
          <div className="migration-result">
            <div className="about-llm-stat-grid">
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
              <ul className="migration-warnings">
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

export function SummaryStat({
  label,
  value,
}: {
  label: string;
  value: number | string;
}) {
  return (
    <div>
      <div className="migration-mode-caption">{label}</div>
      <div className="u-text-15 u-text-primary">{value}</div>
    </div>
  );
}
