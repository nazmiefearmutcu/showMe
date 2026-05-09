import { useState, type CSSProperties, type ReactNode } from "react";

/**
 * Pane — root container for a function surface (DES, FA, EQS, etc.).
 *
 * Round-15 GoldenLayout wraps `Pane` instances; Round-14 just renders one
 * pane filling the workspace.
 */
export function Pane({
  children,
  style,
}: {
  children: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <article
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: 0,
        background: "var(--bg-elev-1)",
        borderRadius: "var(--radius-md)",
        border: "1px solid var(--border-subtle)",
        overflow: "hidden",
        ...style,
      }}
    >
      {children}
    </article>
  );
}

export function PaneHeader({
  code,
  title,
  subtitle,
  trailing,
  help,
}: {
  code: string;
  title: string;
  subtitle?: string;
  trailing?: ReactNode;
  help?: ReactNode;
}) {
  const [helpOpen, setHelpOpen] = useState(false);
  const helpContent = help ?? (
    <DefaultPaneHelp code={code} title={title} subtitle={subtitle} />
  );
  return (
    <header
      style={{
        position: "relative",
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "8px 14px",
        borderBottom: "1px solid var(--border-subtle)",
        background:
          "linear-gradient(180deg, rgba(255,255,255,0.025), transparent)",
      }}
    >
      <span
        style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 11,
          letterSpacing: "0.06em",
          color: "var(--accent)",
          fontWeight: 700,
          padding: "2px 8px",
          background: "var(--accent-soft)",
          borderRadius: "var(--radius-sm)",
        }}
      >
        {code}
      </span>
      <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.1 }}>
        <strong
          style={{
            fontSize: 13,
            color: "var(--text-primary)",
            letterSpacing: 0,
          }}
        >
          {title}
        </strong>
        {subtitle && (
          <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>
            {subtitle}
          </span>
        )}
      </div>
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
        {trailing}
        <button
          type="button"
          aria-label={`${code} help`}
          title="How to use"
          onClick={() => setHelpOpen((open) => !open)}
          style={{
            width: 22,
            height: 22,
            borderRadius: "50%",
            border: "1px solid var(--border-subtle)",
            background: helpOpen ? "var(--accent-soft)" : "var(--bg-elev-2)",
            color: helpOpen ? "var(--accent)" : "var(--text-secondary)",
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 12,
            fontWeight: 800,
            lineHeight: "20px",
            padding: 0,
            cursor: "default",
          }}
        >
          i
        </button>
      </div>
      {helpOpen && (
        <div
          role="dialog"
          aria-label={`${code} usage`}
          style={{
            position: "absolute",
            right: 12,
            top: 40,
            zIndex: 50,
            width: "min(420px, calc(100vw - 48px))",
            border: "1px solid rgba(255,122,0,0.38)",
            background: "var(--bg-elev-3)",
            boxShadow: "0 18px 40px rgba(0,0,0,0.44)",
            borderRadius: "var(--radius-sm)",
            padding: 12,
            color: "var(--text-primary)",
            fontSize: 12,
            lineHeight: 1.5,
          }}
        >
          {helpContent}
        </div>
      )}
    </header>
  );
}

function DefaultPaneHelp({
  code,
  title,
  subtitle,
}: {
  code: string;
  title: string;
  subtitle?: string;
}) {
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <strong style={{ color: "var(--accent)", fontFamily: "JetBrains Mono, monospace" }}>
        {code} · {title}
      </strong>
      <span style={{ color: "var(--text-secondary)" }}>
        {subtitle
          ? `${subtitle} function. Change the visible controls, enter a symbol or parameters when shown, then run or refresh the pane.`
          : "Change the visible controls, enter a symbol or parameters when shown, then run or refresh the pane."}
      </span>
      <span style={{ color: "var(--text-mute)" }}>
        Live/degraded state, source names, warnings, and transport details are shown in the pane body or footer.
      </span>
    </div>
  );
}

export function PaneBody({
  children,
  style,
}: {
  children: ReactNode;
  style?: CSSProperties;
}) {
  return (
    <div
      tabIndex={0}
      style={{
        flex: "1 1 auto",
        minHeight: 0,
        padding: "12px 14px",
        overflow: "auto",
        outline: "none",
        fontSize: 12,
        color: "var(--text-primary)",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export function PaneFooter({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <footer
      style={{
        padding: "6px 14px",
        borderTop: "1px solid var(--border-subtle)",
        background: "rgba(0,0,0,0.18)",
        fontSize: 10,
        color: "var(--text-mute)",
        display: "flex",
        gap: 12,
        fontFamily: "JetBrains Mono, monospace",
      }}
    >
      {children}
    </footer>
  );
}
