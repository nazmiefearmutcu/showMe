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
import { ConfirmDialog, Empty, Pill, SkeletonRow } from "@/design-system";
import { formatPrice } from "@/lib/format";

// Sentinel the backend stamps onto a SignalEntry whose live order was sized
// on the fallback equity ($10k) rather than real broker equity.
const FALLBACK_EQUITY_SOURCE = "fallback_10k";

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
  // name so screen readers announce "Durum: LIVE/SHADOW/OFF".
  return (
    <span role="status" aria-label={`Durum: ${label}`}>
      <Pill tone={tone} variant="soft" withDot>
        {label}
      </Pill>
    </span>
  );
}

function SignalLog({ entries }: { entries: SignalEntry[] }) {
  if (entries.length === 0) return <div className="u-text-secondary">(no signals yet)</div>;
  return (
    <table
      className="terminal-grid-numeric"
      aria-label="Sinyal kayıtları"
      style={{ width: "100%", fontSize: 11 }}
    >
      <caption className="u-sr-only">
        Botun ürettiği sinyaller — zaman, tür, fiyat, aksiyon ve detay.
      </caption>
      <thead>
        <tr className="u-text-secondary">
          <th scope="col" align="left">Time</th>
          <th scope="col">Kind</th>
          <th scope="col" align="right">Price</th>
          <th scope="col">Action</th>
          <th scope="col" align="left">Detail</th>
        </tr>
      </thead>
      <tbody>
        {entries.slice(-20).reverse().map((e, i) => {
          const isFallback = e.equity_source === FALLBACK_EQUITY_SOURCE;
          // P2b — stable composite key from entry identity so a new signal
          // arriving doesn't remount every row (index keys on a reversed
          // slice shift every row). bar_index disambiguates same-bar_time
          // entry/exit pairs; `i` is a final tiebreaker against any residual
          // collision (e.g. legacy rows with empty bar_time).
          const rowKey = `${e.bar_time}-${e.kind}-${e.bar_index}-${i}`;
          return (
            <tr key={rowKey}>
              <td>{e.bar_time.slice(0, 19)}</td>
              <td className={e.kind === "entry" ? "u-text-positive" : "u-text-warn"}>
                {e.kind}
              </td>
              <td align="right">{formatPrice(e.price)}</td>
              <td>{e.action}</td>
              <td>
                {e.error || e.order_id || ""}
                {isFallback && (
                  <span
                    data-testid="bot-signal-fallback-equity"
                    title="Bu canlı emir gerçek broker bakiyesi yerine yedek ($10k) bakiye ile boyutlandırıldı."
                    style={{ marginLeft: 6, display: "inline-block" }}
                  >
                    <Pill tone="warn" variant="soft" withDot={false}>
                      ≈$10k
                    </Pill>
                  </span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
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

  // F6 — explain *why* Save is disabled (same validation that disables it).
  // Returns undefined when Save is enabled so the button has no stale title.
  const saveDisabledReason: string | undefined = (() => {
    if (!saveDisabled && !liveConfirmMissing) return undefined;
    if (saving) return "Kaydediliyor…";
    if (missingStrategy) return "Strateji seçilmeli.";
    if (missingCredential) return "Bağlantı seçilmeli.";
    if (missingSymbol) return "Geçerli bir sembol gerekli.";
    if (timeframeUnknown) return "Geçerli bir timeframe seç.";
    if (liveConfirmMissing) return "Live moda geçiş için account_label onayı gerekli.";
    if (!dirty) return "Değişiklik yok.";
    return "Strateji, bağlantı ve sembol gerekli.";
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
          + Yeni bot
        </button>
        {list.map((b) => (
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
              <div><strong>{b.symbol}</strong></div>
              <div className="u-text-secondary" style={{ fontSize: 10 }}>
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
            <Empty title="Henüz bot yok" body="Bir strateji + bağlantı seçip yeni bot oluştur." />
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
            Soldan bir bot seç ya da <strong>+ Yeni bot</strong>.
          </div>
        )}
        {draft && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <h3 style={{ margin: 0 }}>
              {draft.symbol || "(yeni bot)"} {dirty && <em className="u-text-warn">*</em>}
              {draft.id && <span style={{ marginLeft: 8 }}><StatusPill rec={draft as BotRecord} /></span>}
            </h3>
            <label htmlFor="bot-strategy-select">
              Strateji
              <select id="bot-strategy-select"
                      aria-describedby={
                        strategyOrphan ? "bot-field-err-strategy-orphan"
                        : missingStrategy ? "bot-field-err-strategy"
                        : undefined
                      }
                      value={draft.strategy_id ?? ""}
                      onChange={(e) => setField("strategy_id", e.target.value)}>
                <option value="">— seç —</option>
                {/* C-UI-1 — keep orphan id in dropdown so user knows what's wrong. */}
                {strategyOrphan && draft.strategy_id && (
                  <option value={draft.strategy_id}
                          data-testid="bot-strategy-orphan-option">
                    [silinmiş] {draft.strategy_id.slice(0, 8)}
                  </option>
                )}
                {strategies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </label>
            {strategyOrphan && (
              <div id="bot-field-err-strategy-orphan"
                   data-testid="bot-field-err-strategy-orphan"
                   className="u-text-negative" style={{ fontSize: 11 }}>
                Seçili strateji silinmiş. Listeden başka bir strateji seç.
              </div>
            )}
            {missingStrategy && !strategyOrphan && (
              <div id="bot-field-err-strategy"
                   data-testid="bot-field-err-strategy"
                   className="u-text-negative" style={{ fontSize: 11 }}>
                Bir strateji seçmelisin.
              </div>
            )}
            <label htmlFor="bot-credential-select">
              Bağlantı
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
                <option value="">— seç —</option>
                {/* C-UI-1 — keep orphan id in dropdown. */}
                {credentialOrphan && draft.credential_id && (
                  <option value={draft.credential_id}
                          data-testid="bot-credential-orphan-option">
                    [silinmiş] {draft.credential_id.slice(0, 8)}
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
                   className="u-text-negative" style={{ fontSize: 11 }}>
                Seçili bağlantı silinmiş. Listeden başka bir bağlantı seç.
              </div>
            )}
            {missingCredential && !credentialOrphan && (
              <div id="bot-field-err-credential"
                   data-testid="bot-field-err-credential"
                   className="u-text-negative" style={{ fontSize: 11 }}>
                Bir bağlantı seçmelisin.
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
                   className="u-text-negative" style={{ fontSize: 11 }}>
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
                    [bilinmeyen] {draft.timeframe}
                  </option>
                )}
                {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            {timeframeUnknown && (
              <div id="bot-field-err-timeframe"
                   data-testid="bot-field-err-timeframe"
                   className="u-text-negative" style={{ fontSize: 11 }}>
                Bilinmeyen timeframe: "{draft.timeframe}". Listeden seç.
              </div>
            )}
            <label htmlFor="bot-tick-input">
              Tick interval (saniye)
              <input id="bot-tick-input" type="number" min={5} max={3600}
                     value={tickInputRaw}
                     onChange={(e) => setTickInputRaw(e.target.value)}
                     onBlur={commitTickInterval} />
            </label>

            <fieldset style={{ borderColor: "var(--border-card)", padding: 8 }}>
              <legend>Mod</legend>
              <label htmlFor="bot-mode-shadow">
                <input id="bot-mode-shadow" type="radio" checked={draft.mode === "shadow"}
                       onChange={() => setField("mode", "shadow")} />
                Shadow (sadece signal log)
              </label>
              <br />
              <label htmlFor="bot-mode-live" className="u-text-negative">
                <input id="bot-mode-live" type="radio" checked={draft.mode === "live"}
                       onChange={() => setField("mode", "live")} />
                Live (gerçek emir)
              </label>
            </fieldset>

            {/* B-C3 / F6 — shadow→live save needs confirm_account_label. Only
                render the re-type input while actually transitioning to live;
                never permanently visible in shadow mode. */}
            {transitioningToLive && (
              <label htmlFor="bot-save-confirm-label">
                Live moda geçiş onayı — account_label tekrar yaz
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
                       className="u-text-negative" style={{ fontSize: 11 }}>
                    account_label "{credential?.account_label ?? "?"}" ile eşleşmeli.
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
                {saving ? "Kaydediliyor..." : "Kaydet"}
              </button>
              {draft.id && !draft.enabled && (
                <>
                  {draft.mode === "live" && !transitioningToLive && (
                    <input placeholder={`account_label tekrar yaz`}
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
                  }>
                    {toggling ? "..." : "Etkinleştir"}
                  </button>
                </>
              )}
              {draft.id && draft.enabled && (
                <button
                  data-testid="bot-durdur-button"
                  onClick={() => setPendingDisableId(draft.id!)}
                  disabled={toggling || pendingDisableId !== null}>
                  {toggling ? "..." : "Durdur"}
                </button>
              )}
            {draft.id && (
              <button
                data-testid="bot-sil-button"
                onClick={() => setPendingDeleteBotId(draft.id!)}
                disabled={loading || pendingDeleteBotId !== null}
                className="u-text-negative"
                style={{ marginLeft: "auto" }}>
                Sil
              </button>
            )}
            </div>

            <h4>Signal log ({(draft.signal_log ?? []).length})</h4>
            <SignalLog entries={draft.signal_log ?? []} />
            {(draft.signal_log ?? []).length > 20 && (
              <div className="u-text-secondary" style={{ fontSize: 11 }}>
                Son 20 sinyal gösteriliyor — toplam {(draft.signal_log ?? []).length}.
              </div>
            )}
          </div>
        )}
      </div>

      {/* Round 24 — non-blocking dirty-switch confirm. Single dialog because
          only one switch can be pending at a time. */}
      <ConfirmDialog
        open={dirtySwitchTarget !== null}
        title="Kaydedilmemiş değişiklikler"
        body="Kaydetmediğin değişiklikler kaybolacak. Devam mı?"
        confirmLabel="Devam et"
        onConfirm={() => {
          if (dirtySwitchTarget === "new") openNew();
          else if (dirtySwitchTarget) openExisting(dirtySwitchTarget);
          setDirtySwitchTarget(null);
        }}
        onCancel={() => setDirtySwitchTarget(null)}
      />

      <ConfirmDialog
        open={pendingDeleteBotId !== null}
        title="Botu sil"
        body="Botu silmek istediğine emin misin? Bu işlem geri alınamaz."
        confirmLabel="Sil"
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
        title="Botu durdur"
        body="Bu bot çalışıyor (canlı modda gerçek emir verebilir). Durdurmak istediğine emin misin?"
        confirmLabel="Durdur"
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
