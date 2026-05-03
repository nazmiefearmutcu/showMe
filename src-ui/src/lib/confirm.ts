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
    const root = document.createElement("div");
    root.style.cssText =
      "position:fixed;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.55);z-index:9500;backdrop-filter:blur(4px);";
    const card = document.createElement("div");
    card.style.cssText = [
      "min-width:320px",
      "max-width:420px",
      "background:var(--bg-elev-2)",
      "border:1px solid var(--border-strong)",
      "border-radius:var(--radius-md)",
      "box-shadow:var(--shadow-elev)",
      "padding:18px",
      "display:flex;flex-direction:column;gap:10px",
      "font-family:system-ui,-apple-system,sans-serif",
      "color:var(--text-primary)",
    ].join(";");
    const h = document.createElement("strong");
    h.textContent = opts.title;
    h.style.cssText = "font-size:14px;letter-spacing:-0.01em";
    const b = document.createElement("p");
    b.textContent = opts.body ?? "";
    b.style.cssText = "margin:0;font-size:12px;color:var(--text-secondary);line-height:1.5";
    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:8px;justify-content:flex-end;margin-top:6px";
    const cancelBtn = document.createElement("button");
    cancelBtn.textContent = opts.cancel ?? "Cancel";
    cancelBtn.style.cssText =
      "background:var(--bg-elev-3);border:1px solid var(--border-strong);color:var(--text-primary);padding:6px 12px;border-radius:var(--radius-sm);font-size:12px;cursor:default";
    const okBtn = document.createElement("button");
    okBtn.textContent = opts.primary ?? "Confirm";
    okBtn.style.cssText =
      "background:" +
      (opts.destructive ? "var(--negative)" : "var(--accent)") +
      ";color:#000;border:none;padding:6px 12px;border-radius:var(--radius-sm);font-size:12px;cursor:default;font-weight:600";
    const cleanup = () => root.remove();
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
    requestAnimationFrame(() => okBtn.focus());
  });
}
