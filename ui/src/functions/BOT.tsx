/**
 * BOT — Bot manager pane (sub-system D).
 *
 * Left: list of bots with status pills. Right: form with strategy
 * picker (from strategy-store), credential picker (from exchange-store),
 * symbol/timeframe/tick inputs, mode toggle, signal log viewer.
 */
import { useEffect, useRef, useState } from "react";
import {
  useBotStore, type BotRecord, type SignalEntry,
} from "@/lib/bot-store";
import { useStrategyStore } from "@/lib/strategy-store";
import { useExchangeStore } from "@/lib/exchange-store";
import {
  clampTickInterval,
  isKnownTimeframe,
  normalizeSymbol,
  TIMEFRAMES,
  validateSymbol,
} from "@/lib/validators";
import {
  buildGridCsv,
  ConfirmDialog,
  DataGrid,
  downloadGridCsv,
  Empty,
  gridCsvFilename,
  Pill,
  SkeletonRow,
  type DataGridColumn,
  type GridCsvColumn,
} from "@/design-system";
import { formatPrice } from "@/lib/format";
import { isKaosRecord } from "@/lib/kaos-venues";
import { KaosEngineBadge, KaosLaneBanner, VenueBadges } from "@/functions/KaosBadges";

// Sentinel the backend stamps onto a SignalEntry whose live order was sized
// on the fallback equity ($10k) rather than real broker equity.
const FALLBACK_EQUITY_SOURCE = "fallback_10k";

// The signal log renders the newest SIGNAL_LOG_WINDOW entries; the CSV export
// always covers the FULL `signal_log` array (the wire payload is not windowed).
const SIGNAL_LOG_WINDOW = 20;

// F1 — map a bot's (enabled, mode) state to a design-system Pill tone and
// an accessible status label.
function statusToneAndLabel(rec: { mode: string; enabled: boolean }):
  { tone: "negative" | "warn" | "muted"; label: string } {
  if (!rec.enabled) return { tone: "muted", label: "OFF" };
  return rec.mode === "live"
    ? { tone: "negative", label: "LIVE" }
    : { tone: "warn", label: "SHADOW" };
}

function StatusPill({ rec }: { rec: { mode: string; enabled: boolean } }) {
  const { tone, label } = statusToneAndLabel(rec);
  // F1 — Pill carries the visible label; the wrapper gives it an accessible
  // name so screen readers announce "Status: LIVE/SHADOW/OFF".
  return (
    <span role="status" aria-label={`Status: ${label}`}>
      <Pill tone={tone} variant="soft" withDot>
        {label}
      </Pill>
    </span>
  );
}

function fallbackEquityBadge(entry: SignalEntry) {
  if (entry.equity_source !== FALLBACK_EQUITY_SOURCE) return null;
  return (
    <span
      data-testid="bot-signal-fallback-equity"
      title="This live order was sized with the fallback ($10k) balance instead of the real broker balance."
      style={{ marginLeft: 6, display: "inline-block" }}
    >
      <Pill tone="warn" variant="soft" withDot={false}>
        ≈$10k
      </Pill>
    </span>
  );
}

const SIGNAL_COLUMNS: DataGridColumn<SignalEntry>[] = [
  {
    key: "bar_time",
    header: "Time",
    width: 150,
    sortable: true,
    sortValue: (e) => e.bar_time ?? "",
    render: (e) => e.bar_time.slice(0, 19),
  },
  {
    key: "kind",
    header: "Kind",
    width: 80,
    sortable: true,
    sortValue: (e) => e.kind,
    render: (e) => (
      <span className={e.kind === "entry" ? "u-text-positive" : "u-text-warn"}>
        {e.kind}
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
    sortValue: (e) => e.price,
    render: (e) => formatPrice(e.price),
  },
  {
    key: "action",
    header: "Action",
    width: 90,
    sortable: true,
    sortValue: (e) => e.action,
    render: (e) => e.action,
  },
  {
    key: "detail",
    header: "Detail",
    sortable: true,
    sortValue: (e) => e.error || e.order_id || "",
    render: (e) => (
      <>
        {e.error || e.order_id || ""}
        {fallbackEquityBadge(e)}
      </>
    ),
  },
];

const SIGNAL_CSV_COLUMNS: GridCsvColumn<SignalEntry>[] = [
  { key: "bar_time", header: "Time", value: (e) => e.bar_time },
  { key: "kind", header: "Kind", value: (e) => e.kind },
  { key: "price", header: "Price", value: (e) => e.price },
  { key: "action", header: "Action", value: (e) => e.action },
  { key: "detail", header: "Detail", value: (e) => e.error || e.order_id || "" },
  { key: "equity_source", header: "Equity source", value: (e) => e.equity_source ?? "" },
];

/** Export the FULL signal_log (not just the 20-row view window) as CSV. */
export function buildSignalLogCsv(entries: SignalEntry[]): string {
  return buildGridCsv(SIGNAL_CSV_COLUMNS, [...entries].reverse());
}

function SignalLog({ entries }: { entries: SignalEntry[] }) {
  if (entries.length === 0) return <div className="u-text-secondary">(no signals yet)</div>;
  const rows = entries.slice(-SIGNAL_LOG_WINDOW).reverse();
  return (
    <DataGrid
      columns={SIGNAL_COLUMNS}
      rows={rows}
      density="compact"
      ariaLabel="Signal log"
      // Keep the existing newest-first presentation by default; the built-in
      // sorter takes over on header click (asc → desc → none).
      defaultSortKey="bar_time"
      defaultSortDir="none"
      rowKey={(e, i) => `${e.bar_time}-${e.kind}-${e.bar_index}-${i}`}
    />
  );
}

export function BOTPane() {
  const list = useBotStore((s) => s.bots);
  const draft = useBotStore((s) => s.draft);
  const dirty = useBotStore((s) => s.dirty);
  const loading = useBotStore((s) => s.loading);
  const saving = useBotStore((s) => s.saving);
  const toggling = useBotStore((s) => s.toggling);
  const error = useBotStore((s) => s.error);
  const loadList = useBotStore((s) => s.loadList);
  const openNew = useBotStore((s) => s.openNew);
  const openExisting = useBotStore((s) => s.openExisting);
  const setField = useBotStore((s) => s.setDraftField);
  const save = useBotStore((s) => s.save);
  const remove = useBotStore((s) => s.remove);
  const enable = useBotStore((s) => s.enable);
  const disable = useBotStore((s) => s.disable);

  const strategies = useStrategyStore((s) => s.strategies);
  const loadStrategies = useStrategyStore((s) => s.loadList);
  const credentials = useExchangeStore((s) => s.credentials);
  const loadCredentials = useExchangeStore((s) => s.loadCredentials);

  const [confirmLabel, setConfirmLabel] = useState("");
  // B-C3 — track original mode at draft load to detect shadow→live transition.
  const [originalMode, setOriginalMode] = useState<"shadow" | "live" | null>(null);
  // C-UI-3 — keep the raw input string for tick interval so the user can
  // delete digits without immediately resetting to 60.
  const [tickInputRaw, setTickInputRaw] = useState<string>("");
  // C-UI-2 — local input mirror so we don't clobber a half-typed symbol.
  const [symbolRaw, setSymbolRaw] = useState<string>("");
  // Track the loaded record id separately so we can re-capture originalMode
  // on save success without forgetting it on mode toggles.
  const lastDraftIdRef = useRef<string | null>(null);
  const [pendingDeleteBotId, setPendingDeleteBotId] = useState<string | null>(null);
  // F6 — confirm before disabling a (possibly live) running bot.
  const [pendingDisableId, setPendingDisableId] = useState<string | null>(null);

  useEffect(() => {
    // C-UI-5 — always refresh strategies/credentials on mount so that
    // BDA/TMPL-created strategies and CONN-created credentials surface
    // even if a list was previously cached non-empty.
    loadList();
    loadStrategies();
    loadCredentials();
  }, [loadList, loadStrategies, loadCredentials]);

  // C-UI-4 — capture originalMode whenever a draft identity changes OR
  // when the saved mode shifts (e.g. successful shadow→live save). The
  // ref guards us from over-triggering on plain mode-toggle keystrokes.
  // UA-CRITICAL-03: previously deps array was missing → the effect ran on
  // every render (typing in any input triggered the identity check). Only
  // the draft identity + persisted tick/symbol/mode are read, so deps narrow
  // to those four fields.
  useEffect(() => {
    const did = draft?.id ?? null;
    if (did !== lastDraftIdRef.current) {
      lastDraftIdRef.current = did;
      setConfirmLabel("");
      setTickInputRaw(
        draft?.tick_interval_seconds != null
          ? String(draft.tick_interval_seconds)
          : "",
      );
      setSymbolRaw(draft?.symbol ?? "");
      if (did) {
        setOriginalMode((draft?.mode as "shadow" | "live") ?? "shadow");
      } else {
        setOriginalMode(null);
      }
    }
  }, [draft?.id, draft?.tick_interval_seconds, draft?.symbol, draft?.mode]);

  // When the persisted draft mode shifts AND the draft is not dirty, the
  // backend has acknowledged the new mode (post-save) — re-capture so a
  // second toggle starts from the new baseline. This is the C-UI-4 fix.
  useEffect(() => {
    if (draft?.id && !dirty) {
      setOriginalMode((draft.mode as "shadow" | "live") ?? "shadow");
    }
  }, [draft?.id, draft?.mode, dirty]);

  const credential = credentials.find((c) => c.id === draft?.credential_id);

  // C-UI-1 — detect orphan IDs (strategy/credential present on the draft
  // but not in the current list because something was deleted elsewhere).
  const strategyOrphan = Boolean(
    draft?.strategy_id && !strategies.some((s) => s.id === draft.strategy_id),
  );
  const credentialOrphan = Boolean(
    draft?.credential_id && !credentials.some((c) => c.id === draft.credential_id),
  );

  // H-UI-3 — guard against persisted timeframe values that are no longer
  // in the canonical TIMEFRAMES list (e.g. a future migration shrunk it).
  const timeframeUnknown = Boolean(draft && !isKnownTimeframe(draft.timeframe));

  // B-C2 + C-UI-2 — required-field gating (whitespace-only symbol now
  // counts as missing).
  const symbolError = draft
    ? validateSymbol(symbolRaw || draft.symbol || "")
    : null;
  const missingStrategy = !draft?.strategy_id || strategyOrphan;
  const missingCredential = !draft?.credential_id || credentialOrphan;
  const missingSymbol = !!symbolError;

  // B-C3 — detect shadow→live transition (existing bot only; new bots default to shadow).
  const transitioningToLive =
    Boolean(draft?.id) && originalMode === "shadow" && draft?.mode === "live";
  const liveConfirmMissing =
    transitioningToLive &&
    (confirmLabel.length === 0 || confirmLabel !== credential?.account_label);

  const saveDisabled =
    !dirty || saving || missingStrategy || missingCredential || missingSymbol ||
    timeframeUnknown;

  // Safe-L fix (audit A9): explain why Enable is disabled. In live mode the
  // button requires the re-typed account_label; when the credential is
  // orphaned/unavailable the old markup left it disabled with NO reason.
  const enableDisabledReason: string | undefined = (() => {
    if (!draft?.id || draft.enabled) return undefined;
    if (dirty) return "Save or discard changes before enabling this bot.";
    if (toggling) return "Enable is already in progress…";
    if (draft.mode === "live" && confirmLabel !== credential?.account_label) {
      return credential
        ? `Re-type account_label "${credential.account_label}" to enable live mode.`
        : "No connection is available for this bot. Re-select a connection before enabling live mode.";
    }
    return undefined;
  })();

  // F6 — explain *why* Save is disabled (same validation that disables it).
  // Returns undefined when Save is enabled so the button has no stale title.
  const saveDisabledReason: string | undefined = (() => {
    if (!saveDisabled && !liveConfirmMissing) return undefined;
    if (saving) return "Saving…";
    if (missingStrategy) return "A strategy must be selected.";
    if (missingCredential) return "A connection must be selected.";
    if (missingSymbol) return "A valid symbol is required.";
    if (timeframeUnknown) return "Select a valid timeframe.";
    if (liveConfirmMissing) return "Account_label confirmation is required to switch to live mode.";
    if (!dirty) return "No changes.";
    return "Strategy, connection and symbol are required.";
  })();

  // Round 24 — replace blocking window.confirm with ConfirmDialog.
  // `dirtySwitchTarget = "new" | botId | null` carries the intent across
  // the async confirm. Only one modal at a time.
  const [dirtySwitchTarget, setDirtySwitchTarget] = useState<string | "new" | null>(null);

  // H-UI-10 — protect a dirty draft when the user clicks another bot in
  // the rail.
  const handleSidebarClick = (id: string) => {
    if (dirty) {
      setDirtySwitchTarget(id);
      return;
    }
    openExisting(id);
  };

  // C-UI-3 — commit clamp on blur or when user submits.
  const commitTickInterval = () => {
    const clamped = clampTickInterval(tickInputRaw, draft?.tick_interval_seconds ?? 60);
    if (clamped !== draft?.tick_interval_seconds) {
      setField("tick_interval_seconds", clamped);
    }
    setTickInputRaw(String(clamped));
  };

  // H-UI-1 — wrap save so confirmLabel is cleared on success.
  const handleSave = async () => {
    // C-UI-3 — make sure tick is committed before save.
    commitTickInterval();
    let saved: BotRecord | null;
    if (transitioningToLive) {
      saved = await save(confirmLabel);
    } else {
      saved = await save();
    }
    if (saved) {
      setConfirmLabel("");
      setOriginalMode((saved.mode as "shadow" | "live") ?? "shadow");
    }
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", height: "100%",
                  overflow: "hidden" }}>
      <div style={{ borderRight: "1px solid var(--border-card)", padding: 8, overflowY: "auto" }}>
        <button onClick={() => {
          if (dirty) {
            setDirtySwitchTarget("new");
            return;
          }
          openNew();
        }} style={{ width: "100%", marginBottom: 8 }}>
          + New bot
        </button>
        {/* KAOS Multibot pinned first (stable) — the default bot leads the
            rail; everything else keeps its updated_at order. */}
        {[...list]
          .sort((a, b) => Number(isKaosRecord(b)) - Number(isKaosRecord(a)))
          .map((b) => (
          <button key={b.id} onClick={() => handleSidebarClick(b.id)}
                  style={{
                    display: "grid", gridTemplateColumns: "1fr auto",
                    gap: 6, alignItems: "center", padding: "6px 8px",
                    width: "100%", textAlign: "left",
                    background: draft?.id === b.id ? "var(--surface-2)" : "transparent",
                    border: "none", borderBottom: "1px solid var(--border-card)",
                    cursor: "pointer",
                  }}>
            <div>
              <div>
                <strong>{b.symbol}</strong>
                {isKaosRecord(b) && <KaosEngineBadge />}
              </div>
              <div className="u-text-secondary" style={{ fontSize: "var(--font-size-2xs)" }}>
                {b.exchange_id} · {b.timeframe}
              </div>
            </div>
            <StatusPill rec={b} />
          </button>
        ))}
        {/* F5 — Skeleton while the first load is in flight and we have
            nothing to show yet. */}
        {loading && list.length === 0 && (
          <div data-testid="bot-list-loading" aria-busy="true">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonRow key={i} columns={1} />
            ))}
          </div>
        )}
        {/* F5 — design-system Empty when the load finished with no bots. */}
        {!loading && list.length === 0 && (
          <div data-testid="bot-list-empty">
            <Empty title="No bots yet" body="Pick a strategy + connection and create a new bot." />
          </div>
        )}
      </div>

      <div style={{ overflowY: "auto", padding: 16 }}>
        {/* F4 — async error is an announced live region. Rendered at the pane
            root (not inside the {draft && …} block) so a loadList/store error
            that occurs while no bot is selected (draft === null) is still
            visible. Single instance → never shown twice. */}
        {error && (
          <div data-testid="bot-pane-error"
               role="status" aria-live="polite"
               className="u-text-negative"
               style={{ marginBottom: 8 }}>
            {error}
          </div>
        )}
        {!draft && (
          <div className="u-text-secondary">
            Select a bot on the left or <strong>+ New bot</strong>.
          </div>
        )}
        {draft && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <h3 style={{ margin: 0 }}>
              {draft.symbol || "(new bot)"} {dirty && <em className="u-text-warn">*</em>}
              {isKaosRecord(draft) && <KaosEngineBadge />}
              {/* KAOS Multibot venue chips — only from payload data; hidden
                  for spec bots and older payloads (hide, never fake). */}
              <VenueBadges venues={draft.venues} />
              {draft.id && <span style={{ marginLeft: 8 }}><StatusPill rec={draft as BotRecord} /></span>}
            </h3>
            {/* KAOS Multibot lane honesty: the backend's own venue_rows
                lane_status, verbatim, only when it proves the NASDAQ lane
                is paper. Hidden entirely otherwise (never faked). */}
            <KaosLaneBanner venueRows={draft.venue_rows} />
            <label htmlFor="bot-strategy-select">
              Strategy
              <select id="bot-strategy-select"
                      aria-describedby={
                        strategyOrphan ? "bot-field-err-strategy-orphan"
                        : missingStrategy ? "bot-field-err-strategy"
                        : undefined
                      }
                      value={draft.strategy_id ?? ""}
                      onChange={(e) => setField("strategy_id", e.target.value)}>
                <option value="">— select —</option>
                {/* C-UI-1 — keep orphan id in dropdown so user knows what's wrong. */}
                {strategyOrphan && draft.strategy_id && (
                  <option value={draft.strategy_id}
                          data-testid="bot-strategy-orphan-option">
                    [deleted] {draft.strategy_id.slice(0, 8)}
                  </option>
                )}
                {strategies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </label>
            {strategyOrphan && (
              <div id="bot-field-err-strategy-orphan"
                   data-testid="bot-field-err-strategy-orphan"
                   className="u-text-negative" style={{ fontSize: "var(--font-size-sm)" }}>
                The selected strategy was deleted. Pick another one from the list.
              </div>
            )}
            {missingStrategy && !strategyOrphan && (
              <div id="bot-field-err-strategy"
                   data-testid="bot-field-err-strategy"
                   className="u-text-negative" style={{ fontSize: "var(--font-size-sm)" }}>
                You must select a strategy.
              </div>
            )}
            <label htmlFor="bot-credential-select">
              Connection
              <select id="bot-credential-select"
                      aria-describedby={
                        credentialOrphan ? "bot-field-err-credential-orphan"
                        : missingCredential ? "bot-field-err-credential"
                        : undefined
                      }
                      value={draft.credential_id ?? ""}
                      onChange={(e) => {
                        const id = e.target.value;
                        const c = credentials.find((x) => x.id === id);
                        setField("credential_id", id);
                        // H-1 — when credential cleared, also clear exchange_id +
                        // account-label echo; when picking another, sync exchange_id.
                        if (c) {
                          setField("exchange_id", c.exchange_id);
                        } else {
                          setField("exchange_id", "");
                        }
                      }}>
                <option value="">— select —</option>
                {/* C-UI-1 — keep orphan id in dropdown. */}
                {credentialOrphan && draft.credential_id && (
                  <option value={draft.credential_id}
                          data-testid="bot-credential-orphan-option">
                    [deleted] {draft.credential_id.slice(0, 8)}
                  </option>
                )}
                {credentials.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.exchange_id}:{c.account_label} ({c.permissions.join("+")})
                  </option>
                ))}
              </select>
            </label>
            {credentialOrphan && (
              <div id="bot-field-err-credential-orphan"
                   data-testid="bot-field-err-credential-orphan"
                   className="u-text-negative" style={{ fontSize: "var(--font-size-sm)" }}>
                The selected connection was deleted. Pick another one from the list.
              </div>
            )}
            {missingCredential && !credentialOrphan && (
              <div id="bot-field-err-credential"
                   data-testid="bot-field-err-credential"
                   className="u-text-negative" style={{ fontSize: "var(--font-size-sm)" }}>
                You must select a connection.
              </div>
            )}
            <label htmlFor="bot-symbol-input">
              Symbol
              <input
                id="bot-symbol-input"
                aria-describedby={symbolError ? "bot-field-err-symbol" : undefined}
                value={symbolRaw}
                onChange={(e) => {
                  // C-UI-2 — normalize for state but keep the raw locally so
                  // user can still see in-progress edits (trim happens on
                  // submit, not per-keystroke).
                  const next = normalizeSymbol(e.target.value);
                  setSymbolRaw(next);
                  setField("symbol", next.trim());
                }}
                placeholder="BTC/USDT" />
            </label>
            {symbolError && (
              <div id="bot-field-err-symbol"
                   data-testid="bot-field-err-symbol"
                   className="u-text-negative" style={{ fontSize: "var(--font-size-sm)" }}>
                {symbolError}
              </div>
            )}
            <label htmlFor="bot-timeframe-select">
              Timeframe
              <select id="bot-timeframe-select"
                      aria-describedby={timeframeUnknown ? "bot-field-err-timeframe" : undefined}
                      value={draft.timeframe ?? "1h"}
                      onChange={(e) => setField("timeframe", e.target.value as BotRecord["timeframe"])}>
                {/* H-UI-3 — surface unknown values so the user sees them. */}
                {timeframeUnknown && draft.timeframe && (
                  <option value={draft.timeframe}
                          data-testid="bot-timeframe-unknown-option">
                    [unknown] {draft.timeframe}
                  </option>
                )}
                {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            {timeframeUnknown && (
              <div id="bot-field-err-timeframe"
                   data-testid="bot-field-err-timeframe"
                   className="u-text-negative" style={{ fontSize: "var(--font-size-sm)" }}>
                Unknown timeframe: "{draft.timeframe}". Pick one from the list.
              </div>
            )}
            <label htmlFor="bot-tick-input">
              Tick interval (seconds)
              <input id="bot-tick-input" type="number" min={5} max={3600}
                     value={tickInputRaw}
                     onChange={(e) => setTickInputRaw(e.target.value)}
                     onBlur={commitTickInterval} />
            </label>

            <fieldset style={{ borderColor: "var(--border-card)", padding: 8 }}>
              <legend>Mode</legend>
              <label htmlFor="bot-mode-shadow">
                <input id="bot-mode-shadow" type="radio" checked={draft.mode === "shadow"}
                       onChange={() => setField("mode", "shadow")} />
                Shadow (signal log only)
              </label>
              <br />
              <label htmlFor="bot-mode-live" className="u-text-negative">
                <input id="bot-mode-live" type="radio" checked={draft.mode === "live"}
                       onChange={() => setField("mode", "live")} />
                Live (real orders)
              </label>
            </fieldset>

            {/* B-C3 / F6 — shadow→live save needs confirm_account_label. Only
                render the re-type input while actually transitioning to live;
                never permanently visible in shadow mode. */}
            {transitioningToLive && (
              <label htmlFor="bot-save-confirm-label">
                Live mode switch confirmation — re-type account_label
                <input
                  id="bot-save-confirm-label"
                  data-testid="bot-save-confirm-label"
                  aria-describedby={liveConfirmMissing ? "bot-field-err-confirm-label" : undefined}
                  placeholder={credential?.account_label ?? "account_label"}
                  value={confirmLabel}
                  onChange={(e) => setConfirmLabel(e.target.value)}
                  style={{ width: 200 }}
                />
                {liveConfirmMissing && (
                  <div id="bot-field-err-confirm-label"
                       data-testid="bot-field-err-confirm-label"
                       className="u-text-negative" style={{ fontSize: "var(--font-size-sm)" }}>
                    Must match account_label "{credential?.account_label ?? "?"}".
                  </div>
                )}
              </label>
            )}

            <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
              {/* B-C2 + B-C3 + B-C4 — gate save until valid + not already saving */}
              <button
                onClick={handleSave}
                disabled={saveDisabled || liveConfirmMissing}
                title={saveDisabledReason}
              >
                {saving ? "Saving..." : "Save"}
              </button>
              {draft.id && !draft.enabled && (
                <>
                  {draft.mode === "live" && !transitioningToLive && (
                    <input placeholder={`re-type account_label`}
                           value={confirmLabel}
                           onChange={(e) => setConfirmLabel(e.target.value)}
                           style={{ width: 160 }} />
                  )}
                  <button onClick={async () => {
                    if (draft.mode === "live") {
                      const rec = await enable(draft.id!, confirmLabel);
                      if (rec) setConfirmLabel("");
                    } else {
                      const rec = await enable(draft.id!);
                      if (rec) setConfirmLabel("");
                    }
                  }} disabled={
                    dirty || toggling ||
                    (draft.mode === "live" && confirmLabel !== credential?.account_label)
                  } title={enableDisabledReason}>
                    {toggling ? "..." : "Enable"}
                  </button>
                </>
              )}
              {draft.id && draft.enabled && (
                <button
                  data-testid="bot-stop-button"
                  onClick={() => setPendingDisableId(draft.id!)}
                  disabled={toggling || pendingDisableId !== null}>
                  {toggling ? "..." : "Stop"}
                </button>
              )}
            {draft.id && (
              <button
                data-testid="bot-delete-button"
                onClick={() => setPendingDeleteBotId(draft.id!)}
                disabled={loading || pendingDeleteBotId !== null}
                className="u-text-negative"
                style={{ marginLeft: "auto" }}>
                Delete
              </button>
            )}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <h4 style={{ margin: 0 }}>Signal log ({(draft.signal_log ?? []).length})</h4>
              <button
                data-testid="bot-signal-log-csv"
                type="button"
                onClick={() => {
                  const entries = draft.signal_log ?? [];
                  downloadGridCsv(
                    gridCsvFilename(
                      `bot-signals-${(draft.symbol || draft.id || "bot").replace(/[^A-Za-z0-9_-]+/g, "-")}`,
                    ),
                    buildSignalLogCsv(entries),
                  );
                }}
                disabled={(draft.signal_log ?? []).length === 0}
                title="Download CSV"
                aria-label={`Download all ${(draft.signal_log ?? []).length} signals as CSV`}
                style={{ marginLeft: "auto" }}
              >
                CSV
              </button>
            </div>
            <SignalLog entries={draft.signal_log ?? []} />
            {(draft.signal_log ?? []).length > SIGNAL_LOG_WINDOW && (
              <div className="u-text-secondary" style={{ fontSize: "var(--font-size-sm)" }}>
                Showing the last {SIGNAL_LOG_WINDOW} signals — {(draft.signal_log ?? []).length} total;
                the CSV export covers the full log.
              </div>
            )}
          </div>
        )}
      </div>

      {/* Round 24 — non-blocking dirty-switch confirm. Single dialog because
          only one switch can be pending at a time. */}
      <ConfirmDialog
        open={dirtySwitchTarget !== null}
        title="Unsaved changes"
        body="Unsaved changes will be lost. Continue?"
        confirmLabel="Continue"
        cancelLabel="Cancel"
        onConfirm={() => {
          if (dirtySwitchTarget === "new") openNew();
          else if (dirtySwitchTarget) openExisting(dirtySwitchTarget);
          setDirtySwitchTarget(null);
        }}
        onCancel={() => setDirtySwitchTarget(null)}
      />

      <ConfirmDialog
        open={pendingDeleteBotId !== null}
        title="Delete bot"
        body="Are you sure you want to delete this bot? This cannot be undone."
        confirmLabel="Delete"
        cancelLabel="Cancel"
        destructive
        busy={loading}
        onConfirm={() => {
          if (!pendingDeleteBotId) return;
          const id = pendingDeleteBotId;
          setPendingDeleteBotId(null);
          void remove(id);
        }}
        onCancel={() => setPendingDeleteBotId(null)}
      />

      {/* F6 — confirm before stopping a (possibly live) running bot. */}
      <ConfirmDialog
        open={pendingDisableId !== null}
        title="Stop bot"
        body="This bot is running (live mode can place real orders). Are you sure you want to stop it?"
        confirmLabel="Stop"
        cancelLabel="Cancel"
        destructive
        busy={toggling}
        onConfirm={() => {
          if (!pendingDisableId) return;
          const id = pendingDisableId;
          setPendingDisableId(null);
          void disable(id);
        }}
        onCancel={() => setPendingDisableId(null)}
      />
    </div>
  );
}

export default BOTPane;
