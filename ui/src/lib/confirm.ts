/**
 * NSAlert-style confirm() replacement.
 *
 * Replaces the browser-default `confirm()` (forbidden by ui_standards
 * §6) with `tauri-plugin-dialog`'s native modal. Outside the Tauri
 * shell we fall back to an in-app overlay rendered through the toast
 * host's z-index space so designers can prototype in `npm run dev`.
 *
 * Usage:
 *
 *   if (await confirmAction({
 *     title: "Submit live order",
 *     body: "Buy 100 AAPL @ market — ~$15,000",
 *     primary: "Submit",
 *     destructive: false,
 *   })) {
 *     emsx.placeOrder(payload);
 *   }
 */
import { isInTauri } from "./tauri";

export interface ConfirmOptions {
  title: string;
  body?: string;
  primary?: string;
  cancel?: string;
  destructive?: boolean;
}

export async function confirmAction(opts: ConfirmOptions): Promise<boolean> {
  if (isInTauri()) {
    try {
      const dlg = await import("@tauri-apps/plugin-dialog");
      const ok = await dlg.ask(opts.body ?? "", {
        title: opts.title,
        kind: opts.destructive ? "warning" : "info",
        okLabel: opts.primary ?? "Confirm",
        cancelLabel: opts.cancel ?? "Cancel",
      });
      return Boolean(ok);
    } catch (err) {
      console.warn("confirmAction Tauri dialog failed", err);
    }
  }
  // Browser fallback — render a portal-style dialog and resolve on click.
  return browserConfirm(opts);
}

function browserConfirm(opts: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    if (typeof document === "undefined") {
      resolve(false);
      return;
    }
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const root = document.createElement("div");
    // UX-09 P3: scrim token instead of hardcoded rgba.
    root.style.cssText =
      "position:fixed;inset:0;display:flex;align-items:center;justify-content:center;background:var(--scrim-modal);z-index:var(--z-confirm);backdrop-filter:blur(4px);";
    const card = document.createElement("div");
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-modal", "true");
    card.id = `showme-confirm-${Date.now()}`;
    const titleId = `${card.id}-title`;
    card.setAttribute("aria-labelledby", titleId);
    card.style.cssText = [
      "min-width:320px",
      "max-width:420px",
      "background:var(--bg-elev-2)",
      "border:1px solid var(--border-strong)",
      "border-radius:var(--radius-md)",
      "box-shadow:var(--shadow-elev)",
      "padding:18px",
      "display:flex;flex-direction:column;gap:10px",
      "font-family:var(--font-text)",
      "color:var(--text-primary)",
    ].join(";");
    const h = document.createElement("strong");
    h.id = titleId;
    h.textContent = opts.title;
    h.style.cssText = "font-size:var(--font-size-lg);letter-spacing:var(--tracking-tight)";
    const b = document.createElement("p");
    b.textContent = opts.body ?? "";
    b.style.cssText =
      "margin:0;font-size:var(--font-size-md);color:var(--text-secondary);line-height:var(--line-height-normal)";
    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:8px;justify-content:flex-end;margin-top:6px";
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.textContent = opts.cancel ?? "Cancel";
    cancelBtn.style.cssText =
      "background:var(--bg-elev-3);border:1px solid var(--border-strong);color:var(--text-primary);padding:var(--space-3) var(--space-5);border-radius:var(--radius-sm);font-size:var(--font-size-md);cursor:pointer";
    const okBtn = document.createElement("button");
    okBtn.type = "button";
    okBtn.textContent = opts.primary ?? "Confirm";
    okBtn.style.cssText =
      "background:" +
      (opts.destructive ? "var(--negative)" : "var(--accent)") +
      ";color:var(--accent-on);border:none;padding:var(--space-3) var(--space-5);border-radius:var(--radius-sm);font-size:var(--font-size-md);cursor:pointer;font-weight:var(--font-weight-semibold)";
    const cleanup = () => {
      root.remove();
      window.removeEventListener("keydown", onKey);
      // A11Y-03 P1: restore focus to the previously focused element.
      previouslyFocused?.focus?.();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        cleanup();
        resolve(false);
      } else if (event.key === "Tab") {
        // Simple two-button focus trap.
        event.preventDefault();
        const next = document.activeElement === okBtn ? cancelBtn : okBtn;
        next.focus();
      } else if (event.key === "Enter") {
        event.preventDefault();
        cleanup();
        resolve(true);
      }
    };
    cancelBtn.onclick = () => {
      cleanup();
      resolve(false);
    };
    okBtn.onclick = () => {
      cleanup();
      resolve(true);
    };
    root.onclick = (e) => {
      if (e.target === root) {
        cleanup();
        resolve(false);
      }
    };
    row.appendChild(cancelBtn);
    row.appendChild(okBtn);
    card.appendChild(h);
    if (opts.body) card.appendChild(b);
    card.appendChild(row);
    root.appendChild(card);
    document.body.appendChild(root);
    window.addEventListener("keydown", onKey);
    requestAnimationFrame(() => okBtn.focus());
  });
}
