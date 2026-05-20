import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  code: string;
  children: ReactNode;
}

interface State {
  error: Error | null;
  componentStack: string | null;
}

export class PaneErrorBoundary extends Component<Props, State> {
  state: State = { error: null, componentStack: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    this.setState({ componentStack: info.componentStack ?? null });
    console.error(`[showMe] Pane "${this.props.code}" render failed`, error, info);
    try {
      window.localStorage?.setItem(
        "showme.last_pane_error",
        JSON.stringify({
          code: this.props.code,
          message: error.message,
          stack: error.stack,
          componentStack: info.componentStack,
          ts: new Date().toISOString(),
        }),
      );
    } catch {
      // localStorage unavailable in some Tauri configurations; non-fatal.
    }
  }

  componentDidUpdate(prev: Props): void {
    if (prev.code !== this.props.code && this.state.error) {
      this.setState({ error: null, componentStack: null });
    }
  }

  private handleRetry = (): void => {
    this.setState({ error: null, componentStack: null });
  };

  render(): ReactNode {
    const { error, componentStack } = this.state;
    if (!error) return this.props.children;

    return (
      <div
        role="alert"
        data-testid="pane-error-boundary"
        style={{
          padding: 16,
          height: "100%",
          overflow: "auto",
          display: "grid",
          gap: 12,
          alignContent: "start",
          background: "var(--surface)",
          color: "var(--text-primary)",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <strong style={{ color: "var(--negative)" }}>
            {this.props.code} · pane render failed
          </strong>
          <button type="button" className="btn btn--ghost u-btn-mini" onClick={this.handleRetry}>
            Retry
          </button>
        </div>
        <div style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 12 }}>
          {error.message || error.name || "Unknown render error"}
        </div>
        {error.stack ? (
          <pre
            style={{
              fontFamily: "var(--font-mono, monospace)",
              fontSize: 11,
              color: "var(--text-mute)",
              whiteSpace: "pre-wrap",
              maxHeight: 220,
              overflow: "auto",
              margin: 0,
            }}
          >
            {error.stack}
          </pre>
        ) : null}
        {componentStack ? (
          <pre
            style={{
              fontFamily: "var(--font-mono, monospace)",
              fontSize: 11,
              color: "var(--text-mute)",
              whiteSpace: "pre-wrap",
              maxHeight: 200,
              overflow: "auto",
              margin: 0,
            }}
          >
            {componentStack}
          </pre>
        ) : null}
      </div>
    );
  }
}
