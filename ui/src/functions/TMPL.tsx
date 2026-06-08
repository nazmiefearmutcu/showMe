/**
 * TMPL — Template bot library browser. Sub-system G.
 *
 * Left: grid of template cards. Right: detail with NL explanation,
 * math, applicability, "Use" button → modal that creates a strategy.
 */
import { useEffect, useRef, useState } from "react";
import { useTemplateStore } from "@/lib/template-store";
import { useFocusTrap } from "@/lib/a11y";
import { ConfirmDialog, Empty, SkeletonRow } from "@/design-system";

export function TMPLPane() {
  const entries = useTemplateStore((s) => s.entries);
  const selectedId = useTemplateStore((s) => s.selectedId);
  const loadCatalog = useTemplateStore((s) => s.loadCatalog);
  const setSelected = useTemplateStore((s) => s.setSelected);
  const instantiate = useTemplateStore((s) => s.instantiate);
  const error = useTemplateStore((s) => s.error);
  const loading = useTemplateStore((s) => s.loading);

  const [useModal, setUseModal] = useState<string | null>(null);
  const [nameOverride, setNameOverride] = useState("");
  const [symbolOverride, setSymbolOverride] = useState("");
  const [creating, setCreating] = useState(false);
  const [createdId, setCreatedId] = useState<string | null>(null);
  // Round 24 HIGH 12 — once an instantiate attempt fails we keep `creating`
  // true (and the button disabled) until the user explicitly clicks Retry.
  // The old flow set `creating=false` on every catch, so a double-click
  // pattern of (success→error) or (error→error) bypassed the guard.
  const [instantiateError, setInstantiateError] = useState<string | null>(null);
  // Round 24 HIGH 11 — track which override fields the user has touched
  // so backdrop-click warns "you'll lose your overrides" iff any field
  // diverges from the template defaults.
  const [overridesDirty, setOverridesDirty] = useState(false);
  // H-UI-5 — auto-dismiss timer for the success state.
  const [autoDismissAt, setAutoDismissAt] = useState<number | null>(null);
  // Round 24 HIGH — secondary unsaved-warning confirm dialog within the
  // modal. Lives outside `useModal` because both can be visible at once
  // (the warning sits on top of the template modal).
  const [pendingClose, setPendingClose] = useState(false);
  // A11Y: trap Tab inside the open modal, restore focus to the trigger
  // (the "Bu template'i kullan" button) on close. Reuses the shared
  // `useFocusTrap` primitive that ShortcutsHelp + Palette already use.
  const modalRef = useRef<HTMLDivElement>(null);
  // Round 24 CRITICAL 4 — read store-level guard so a double-click
  // Oluştur can't queue two POSTs even if the local React state lags.
  const instantiatingInFlight = useTemplateStore((s) => s.instantiating);

  useEffect(() => { if (entries.length === 0) loadCatalog(); }, [entries.length, loadCatalog]);

  const closeModal = () => {
    setUseModal(null);
    setCreatedId(null);
    setAutoDismissAt(null);
    setInstantiateError(null);
    setOverridesDirty(false);
    setPendingClose(false);
  };

  /**
   * Round 24 HIGH 11 — guarded close. If the user has typed overrides AND
   * we haven't yet created the strategy, ask before discarding. Skip the
   * warning when:
   *   - `creating=true` → fall through to the success-or-fail path, never
   *     close mid-flight.
   *   - `createdId` is set → the success indicator is showing and the user
   *     just wants to dismiss.
   *   - No fields are dirty (default name + default symbol).
   */
  const requestClose = () => {
    if (creating || instantiatingInFlight) return;
    if (createdId) {
      closeModal();
      return;
    }
    if (overridesDirty) {
      setPendingClose(true);
      return;
    }
    closeModal();
  };

  // MEDIUM — Escape key dismiss when modal is open and not creating.
  // Round 24 — route through requestClose() so the unsaved-warning
  // confirmation fires for dirty overrides.
  useEffect(() => {
    if (!useModal) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !creating && !instantiatingInFlight) {
        requestClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [useModal, creating, instantiatingInFlight, overridesDirty, createdId]);

  // A11Y — trap Tab focus inside modal while open.
  useFocusTrap(modalRef, useModal !== null);

  // H-UI-5 — auto-close after success so the user lands back on TMPL list
  // (and the cross-store invalidation already refreshed STRA/BOT).
  useEffect(() => {
    if (autoDismissAt == null) return;
    const ms = Math.max(0, autoDismissAt - Date.now());
    const handle = window.setTimeout(closeModal, ms);
    return () => window.clearTimeout(handle);
  }, [autoDismissAt]);

  const selected = selectedId ? entries.find((e) => e.id === selectedId) ?? null : null;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", height: "100%",
                  overflow: "hidden" }}>
      <div style={{ borderRight: "1px solid var(--border-card)", padding: 8, overflowY: "auto" }}>
        <h4>Template kütüphanesi ({entries.length})</h4>
        {/* P5 — loading skeleton while the catalog is still in flight and we
            have nothing to show yet. */}
        {loading && entries.length === 0 && (
          <div data-testid="tmpl-list-loading" aria-busy="true">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonRow key={i} columns={1} />
            ))}
          </div>
        )}
        {/* P5 — empty catalog (load finished, nothing came back). */}
        {!loading && entries.length === 0 && (
          <Empty title="Template yok" body="Katalog boş ya da yüklenemedi." />
        )}
        {entries.map((e) => {
          const isSelected = selectedId === e.id;
          return (
          <button key={e.id} onClick={() => setSelected(e.id)}
                  // A11Y — announce the active selection to assistive tech.
                  aria-current={isSelected ? "true" : undefined}
                  style={{
                    display: "block", width: "100%", textAlign: "left",
                    padding: "8px 10px", borderBottom: "1px solid var(--border-row)",
                    background: isSelected ? "var(--surface-2)" : "transparent",
                    border: "none", cursor: "pointer",
                  }}>
            <div><strong>{e.name}</strong></div>
            <div style={{ fontSize: 10, color: "var(--text-secondary)" }}>
              {e.family} · {e.uses_indicators.join(", ")}
            </div>
          </button>
          );
        })}
      </div>

      <div style={{ overflowY: "auto", padding: 16 }}>
        {/* P5 — use the design-system Empty for the no-selection state. */}
        {!selected && (
          <Empty title="Template seçilmedi" body="Soldan bir template seç." />
        )}
        {selected && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              <h2 style={{ margin: 0 }}>{selected.name}</h2>
              <div style={{ color: "var(--text-secondary)" }}>{selected.family} · {selected.uses_indicators.join(", ")}</div>
              <p>{selected.description}</p>
            </div>
            <div>
              <h4>Açıklama</h4>
              <p style={{ whiteSpace: "pre-wrap" }}>{selected.natural_language_explanation}</p>
            </div>
            <details>
              <summary>Math</summary>
              <pre style={{ background: "var(--surface-2)", padding: 8, fontSize: 11,
                            whiteSpace: "pre-wrap" }}>{selected.math}</pre>
            </details>
            <div>
              <h4>Uygulanabilirlik</h4>
              <p style={{ color: "var(--text-secondary)" }}>{selected.applicability}</p>
            </div>
            <div>
              <h4>Önerilen ayarlar</h4>
              <p>Timeframe: <code>{selected.recommended_timeframe}</code></p>
              <p>Semboller: {selected.recommended_symbols.join(", ") || "(serbest)"}</p>
            </div>
            <button onClick={() => {
              setUseModal(selected.id);
              setNameOverride(selected.name);
              setSymbolOverride(selected.recommended_symbols[0] ?? "");
              setCreatedId(null);
              setAutoDismissAt(null);
              setInstantiateError(null);
              setOverridesDirty(false);
            }}>Bu template'i kullan</button>
            {/* A11Y — store-level errors are announced as an alert. */}
            {error && (
              <div role="alert" aria-live="assertive"
                   style={{ color: "var(--negative)" }}>{error}</div>
            )}
          </div>
        )}

        {useModal && (
          <div role="dialog" aria-modal="true"
               aria-labelledby="tmpl-modal-title"
               data-testid="tmpl-modal-backdrop"
               onClick={(e) => {
                 // Round 24 HIGH 11 — route backdrop click through
                 // requestClose() so the unsaved-warning fires when the
                 // user has typed overrides; clicks inside the body are
                 // still ignored via target===currentTarget.
                 if (e.target === e.currentTarget) {
                   requestClose();
                 }
               }}
               style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        zIndex: 1000 }}>
            <div ref={modalRef}
                 onClick={(e) => e.stopPropagation()}
                 data-testid="tmpl-modal-body"
                 style={{ background: "var(--surface-1)", padding: 16, minWidth: 360,
                          border: "1px solid var(--border-card)" }}>
              <h3 id="tmpl-modal-title" style={{ marginTop: 0 }}>Strateji oluştur</h3>
              <label htmlFor="tmpl-name-input">
                Ad
                <input
                  id="tmpl-name-input"
                  type="text"
                  value={nameOverride}
                  onChange={(e) => { setNameOverride(e.target.value); setOverridesDirty(true); }}
                />
              </label>
              <br />
              <label htmlFor="tmpl-symbol-input">
                Sembol (opsiyonel)
                <input
                  id="tmpl-symbol-input"
                  type="text"
                  value={symbolOverride}
                  onChange={(e) => { setSymbolOverride(e.target.value); setOverridesDirty(true); }}
                />
              </label>
              {/* A11Y — transient creating/created/error status messages are
                  wrapped in a polite live region so screen readers announce
                  them. The error sub-message additionally carries role=alert
                  for assertive announcement. */}
              <div aria-live="polite" data-testid="tmpl-status-region">
                {creating && (
                  <div data-testid="tmpl-creating-indicator"
                       style={{ color: "var(--warn)", marginTop: 8 }}>
                    Oluşturuluyor...
                  </div>
                )}
                {createdId && (
                  <div data-testid="tmpl-created-indicator"
                       style={{ color: "var(--positive)", marginTop: 8 }}>
                    Oluşturuldu (id: {createdId.slice(0, 8)}). STRA paneline gidip düzenleyebilirsin.
                  </div>
                )}
                {instantiateError && !creating && (
                  <div data-testid="tmpl-error-indicator"
                       role="alert"
                       style={{ color: "var(--negative)", marginTop: 8 }}>
                    Hata: {instantiateError}
                  </div>
                )}
              </div>
              <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 8 }}>
                {instantiateError && !creating && (
                  <button
                    data-testid="tmpl-retry-button"
                    onClick={() => setInstantiateError(null)}
                    style={{ marginRight: "auto" }}>
                    Yeniden dene
                  </button>
                )}
                <button
                  data-testid="tmpl-kapat-button"
                  disabled={creating || instantiatingInFlight}
                  onClick={requestClose}>
                  Kapat
                </button>
                <button
                  data-testid="tmpl-olustur-button"
                  disabled={
                    // Round 24 CRITICAL 4 + HIGH 12 — disable while creating
                    // OR while store-level instantiating is true OR while we
                    // are in an unresolved error state (user must hit Retry
                    // explicitly to clear `instantiateError` before retrying).
                    creating ||
                    instantiatingInFlight ||
                    !nameOverride ||
                    createdId !== null ||
                    instantiateError !== null
                  }
                  onClick={async () => {
                    // Local + store short-circuit — three layers deep.
                    if (creating || instantiatingInFlight) return;
                    setCreating(true);
                    setInstantiateError(null);
                    const r = await instantiate(useModal, nameOverride, symbolOverride || undefined);
                    setCreating(false);
                    if (r) {
                      // H-UI-5 — record success then schedule auto-close.
                      // Cross-store invalidation already done in template-store.
                      setCreatedId(r.strategy.id);
                      setAutoDismissAt(Date.now() + 1500);
                    } else {
                      // Round 24 HIGH 12 — failure leaves the button locked
                      // until the user clicks Retry; otherwise a frustrated
                      // double-tap would race a recovered backend into two
                      // strategies on the second success.
                      setInstantiateError(error ?? "instantiate_failed");
                    }
                  }}>
                  {creating ? "..." : "Oluştur"}
                </button>
              </div>
            </div>
            {/* Round 24 HIGH 11 — unsaved-overrides secondary confirm. */}
            <ConfirmDialog
              open={pendingClose}
              title="Değişiklikler kaybolacak"
              body="Yaptığın override'lar (ad / sembol) kaybolacak. Yine de kapatılsın mı?"
              confirmLabel="Kapat"
              destructive
              onConfirm={closeModal}
              onCancel={() => setPendingClose(false)}
            />
          </div>
        )}
      </div>
    </div>
  );
}

export default TMPLPane;
