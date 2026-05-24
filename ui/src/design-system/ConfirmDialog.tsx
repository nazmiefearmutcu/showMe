/**
 * ConfirmDialog — non-blocking React replacement for `window.confirm()`.
 *
 * Why: Round 24 fix list (STRA / BOT / dirty-switch) flagged the use of
 * the native `window.confirm()` as both a blocking dialog (locks the JS
 * thread until the user clicks) and an a11y dead-end (focus escapes to
 * the OS shell, no Esc/backdrop semantics consistent with our other
 * modals). The `lib/confirm.ts::confirmAction()` helper is for *destructive
 * shell* (Tauri-native NSAlert) operations — fine for irreversible deletes,
 * but overkill for dirty-draft "are you sure?" prompts on the form path
 * because it spawns a native OS dialog that yanks focus out of the app.
 *
 * This component is the in-window, focus-trapped, Esc/backdrop-aware
 * dialog you compose into a pane when you want a confirm without leaving
 * the UI. It is intentionally lower-level than `confirmAction()` so the
 * caller renders it conditionally; we expose `<ConfirmDialog open=... />`
 * + an imperative `useConfirmDialog()` hook for the common case.
 *
 * Contract:
 *   - `open=false` renders nothing (no portal cost).
 *   - First focusable element receives autofocus on mount.
 *   - Tab cycles between Cancel + Confirm only (focus trap).
 *   - Esc fires onCancel().
 *   - Clicking the backdrop fires onCancel().
 *   - Confirm button styled `destructive` red when `destructive=true`.
 */
import { useEffect, useRef } from "react";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  body?: string | React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Onayla",
  cancelLabel = "İptal",
  destructive = false,
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const confirmBtnRef = useRef<HTMLButtonElement>(null);
  const cancelBtnRef = useRef<HTMLButtonElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    // Autofocus the confirm button so Enter is the affirmative default.
    // For destructive actions we focus Cancel instead — the user must
    // explicitly Tab to Confirm. This mirrors macOS HIG.
    const target = destructive ? cancelBtnRef.current : confirmBtnRef.current;
    queueMicrotask(() => target?.focus());

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) {
        e.preventDefault();
        onCancel();
      } else if (e.key === "Tab") {
        // Two-button focus trap.
        e.preventDefault();
        const next = document.activeElement === confirmBtnRef.current
          ? cancelBtnRef.current
          : confirmBtnRef.current;
        next?.focus();
      } else if (e.key === "Enter" && !busy && !destructive) {
        // Only auto-fire on non-destructive; destructive requires explicit click.
        e.preventDefault();
        onConfirm();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      // Restore focus to whatever the user was on before the dialog opened
      // (the trigger button is the common case). Skip when busy because the
      // dialog is mid-async and we'll restore in the onConfirm/onCancel
      // success path instead.
      if (!busy) {
        try { previouslyFocused.current?.focus(); } catch { /* noop */ }
      }
    };
  }, [open, busy, destructive, onCancel, onConfirm]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      data-testid="confirm-dialog-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onCancel();
      }}
      style={{
        position: "fixed", inset: 0,
        display: "flex", alignItems: "center", justifyContent: "center",
        background: "var(--scrim-modal, rgba(0,0,0,0.5))",
        zIndex: 1000,
      }}
    >
      <div
        data-testid="confirm-dialog-body"
        style={{
          background: "var(--surface-1)",
          border: "1px solid var(--border-1)",
          borderRadius: "var(--radius-md, 8px)",
          padding: 18,
          minWidth: 320,
          maxWidth: 480,
          boxShadow: "var(--shadow-elev, 0 10px 30px rgba(0,0,0,0.35))",
          display: "flex", flexDirection: "column", gap: 12,
        }}
      >
        <strong id="confirm-dialog-title" style={{ fontSize: 14 }}>{title}</strong>
        {body && (
          <div
            data-testid="confirm-dialog-body-text"
            style={{ fontSize: 12, color: "var(--fg-2)", lineHeight: 1.5 }}
          >
            {body}
          </div>
        )}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 4 }}>
          <button
            ref={cancelBtnRef}
            type="button"
            data-testid="confirm-dialog-cancel"
            disabled={busy}
            onClick={onCancel}
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmBtnRef}
            type="button"
            data-testid="confirm-dialog-confirm"
            disabled={busy}
            onClick={onConfirm}
            style={destructive ? {
              background: "var(--accent-err, #d32f2f)",
              color: "white",
              border: "none",
            } : undefined}
          >
            {busy ? "..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export default ConfirmDialog;
