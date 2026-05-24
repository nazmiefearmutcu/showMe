import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { AppErrorBoundary } from "./shell/AppErrorBoundary";
import { toast } from "./lib/toast";
import { listen } from "./lib/tauri";
import "./styles/index.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root missing in index.html");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </React.StrictMode>,
);

/**
 * REL-04 P7 — global error handlers.
 *
 * React's error boundary only catches *render* errors. Async errors,
 * unhandled promise rejections, and event-handler throws fall through
 * to the window. Catch them, route to a single toast, and dedupe within
 * a 5s window so a recurring failure doesn't spam the UI with the same
 * notification 60 times a second.
 *
 * Module-level singleton — runs exactly once per page load.
 */
const recentlySeen = new Map<string, number>();
const DEDUPE_MS = 5_000;

function dedupedReport(kind: "error" | "rejection", message: string, detail?: unknown): void {
  console.error(`[showMe] window.${kind === "error" ? "onerror" : "onunhandledrejection"}`, message, detail);
  const key = `${kind}:${message}`;
  const now = Date.now();
  // Trim stale entries lazily.
  for (const [k, ts] of recentlySeen) {
    if (now - ts > DEDUPE_MS) recentlySeen.delete(k);
  }
  if (recentlySeen.has(key)) return;
  recentlySeen.set(key, now);
  try {
    toast.error("Unexpected error", "Check logs for details.");
  } catch {
    /* toast store may not have hydrated yet on a very early boot crash */
  }
}

window.addEventListener("error", (e) => {
  // Some browsers fire `error` events with no message (e.g. cross-origin
  // script errors). Skip those to avoid empty-string spam.
  if (!e || !e.message) return;
  dedupedReport("error", e.message, e.error);
});

window.addEventListener("unhandledrejection", (e) => {
  const reason = e?.reason;
  const message =
    reason instanceof Error
      ? reason.message
      : typeof reason === "string"
        ? reason
        : "Unhandled promise rejection";
  dedupedReport("rejection", message, reason);
});

/**
 * REL-04 P5 — bridge the Rust panic hook into the UI.
 *
 * `tauri/src/lib.rs::install_panic_hook` already emits an `app:panic`
 * event with a one-line summary on every Rust panic. Until this listener
 * was added the UI silently ignored the event — the user got a frozen
 * window and no toast.
 */
listen<string | { payload?: string }>("app:panic", (event) => {
  const detail =
    typeof event.payload === "string"
      ? event.payload
      : (event.payload as { payload?: string } | undefined)?.payload ??
        JSON.stringify(event.payload ?? null);
  console.error("[showMe] Rust panic", detail);
  try {
    toast.error("App encountered a panic", "Please restart showMe.");
  } catch {
    /* toast store unavailable */
  }
}).catch((err) => {
  console.warn("[showMe] failed to attach app:panic listener", err);
});

/**
 * Disable browser context menu — we ship our own NSMenu-style menu later.
 *
 * Trade-off: module-load listener with no cleanup. The window is an
 * app singleton (Tauri webview) so attaching the listener at module
 * scope leaks at most one entry across the entire process lifetime —
 * not a real leak. Wrapping this inside a `useEffect` in `App` would
 * also defer the protection past the first paint, during which a
 * stray right-click could leak the default browser menu and break the
 * cockpit feel. Keeping it here is the deliberate trade.
 */
window.addEventListener("contextmenu", (e) => e.preventDefault());
