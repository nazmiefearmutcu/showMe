/**
 * AppErrorBoundary — top-level React error boundary (REL-04 P5).
 *
 * Wraps the entire `<App />` tree so a render error in the titlebar,
 * sidebar, statusbar, or workspace can't drop the whole shell to a
 * blank-screen state. The per-pane `PaneErrorBoundary` still catches
 * pane-local crashes; this is the outer net for everything *around* a
 * pane (titlebar drag, sidebar drag, command palette).
 *
 * On error we render a full-screen "Something went wrong" surface with
 * two affordances:
 *   - **Reload** — full window reload to recover.
 *   - **Send Logs / Open Logs** — invokes the `open_data_folder` Tauri
 *     command so the user can attach the log directory to a bug
 *     report. In a browser test environment the invoke is missing, so
 *     the button degrades gracefully to a console hint.
 *
 * Always render a *self-contained* DOM tree (no design-system imports)
 * so the boundary survives even when those modules are themselves the
 * source of the crash.
 */
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
  componentStack: string | null;
}

async function openLogsFolder(): Promise<void> {
  // Lazy import so that test environments without Tauri can stub a
  // simple console fallback.
  try {
    const mod = await import("@/lib/tauri");
    const inv = (mod as { invoke?: (cmd: string, args?: unknown) => Promise<unknown> }).invoke;
    if (typeof inv === "function") {
      await inv("open_data_folder");
      return;
    }
  } catch (err) {
    console.warn("[showMe] openLogsFolder: invoke unavailable", err);
  }
  console.info("[showMe] openLogsFolder: no Tauri runtime; check ~/Library/Application Support/showMe/logs");
}

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null, componentStack: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    this.setState({ componentStack: info.componentStack ?? null });
    // Always console.error so the dev tools surface the full stack.
    console.error("[showMe] AppErrorBoundary caught render error", error, info);
    try {
      window.localStorage?.setItem(
        "showme.last_app_error",
        JSON.stringify({
          message: error.message,
          stack: error.stack,
          componentStack: info.componentStack,
          ts: new Date().toISOString(),
        }),
      );
    } catch {
      /* localStorage unavailable */
    }
  }

  private handleReload = (): void => {
    try {
      window.location.reload();
    } catch {
      /* JSDOM lacks reload in some setups */
    }
  };

  private handleOpenLogs = (): void => {
    void openLogsFolder();
  };

  render(): ReactNode {
    const { error, componentStack } = this.state;
    if (!error) return this.props.children;

    // Bundle D / THEME-01. Hard-coded hex used to pin this surface to the
    // legacy dark palette even when the user picked the iced/papyrus/amber
    // theme. Route through design-system tokens so the boundary inherits
    // whatever theme the body sits on. Fallbacks live in tokens.css.
    return (
      <div
        role="alert"
        data-testid="app-error-boundary"
        style={{
          position: "fixed",
          inset: 0,
          background: "var(--bg-1)",
          color: "var(--fg-1)",
          display: "grid",
          placeItems: "center",
          padding: 24,
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif",
          zIndex: 99999,
        }}
      >
        <div style={{ maxWidth: 640, width: "100%", display: "grid", gap: 16 }}>
          <div style={{ display: "grid", gap: 4 }}>
            <strong style={{ fontSize: 20, color: "var(--accent-err)" }}>
              Something went wrong
            </strong>
            <span style={{ fontSize: 13, color: "var(--fg-2)" }}>
              showMe hit an unrecoverable render error. Your data is safe — the
              Python sidecar keeps running in the background.
            </span>
          </div>
          <div
            style={{
              background: "var(--surface-1)",
              border: "1px solid var(--border-1)",
              borderRadius: 8,
              padding: 12,
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
              fontSize: 12,
              maxHeight: 140,
              overflow: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {error.message || error.name || "Unknown render error"}
            {error.stack ? "\n\n" + error.stack : ""}
            {componentStack ? "\n\nComponent stack:" + componentStack : ""}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              data-testid="app-error-reload"
              onClick={this.handleReload}
              style={{
                appearance: "none",
                background: "var(--accent)",
                color: "var(--bg-1)",
                border: "0",
                borderRadius: 6,
                padding: "8px 14px",
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Reload
            </button>
            <button
              type="button"
              data-testid="app-error-open-logs"
              onClick={this.handleOpenLogs}
              style={{
                appearance: "none",
                background: "transparent",
                color: "var(--fg-1)",
                border: "1px solid var(--border-1)",
                borderRadius: 6,
                padding: "8px 14px",
                fontSize: 13,
                cursor: "pointer",
              }}
            >
              Open Logs Folder
            </button>
          </div>
        </div>
      </div>
    );
  }
}
