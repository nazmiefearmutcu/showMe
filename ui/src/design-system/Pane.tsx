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
  // A11Y-05: panes are landmarks. Keep `<article>` semantics — heading lives
  // inside via PaneHeader's <h2>.
  return (
    <article className="ds-pane" style={style}>
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
    <header className="ds-pane-header">
      <span className="ds-pane-header__code">{code}</span>
      <div className="ds-pane-header__title-host">
        <h2 className="ds-pane-header__title">{title}</h2>
        {subtitle && (
          <span className="ds-pane-header__subtitle">{subtitle}</span>
        )}
      </div>
      <div className="ds-pane-header__trailing">
        {trailing}
        <button
          type="button"
          aria-label={`${code} help`}
          title="How to use"
          onClick={() => setHelpOpen((open) => !open)}
          className={`ds-pane-header__help-btn${helpOpen ? " ds-pane-header__help-btn--open" : ""}`}
        >
          i
        </button>
      </div>
      {helpOpen && (
        <div
          role="dialog"
          aria-label={`${code} usage`}
          className="ds-pane-header__help-popup"
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
    <div className="ds-pane-help">
      <strong className="ds-pane-help__title">{code} · {title}</strong>
      <span className="u-text-secondary">
        {subtitle
          ? `${subtitle} function. Change the visible controls, enter a symbol or parameters when shown, then run or refresh the pane.`
          : "Change the visible controls, enter a symbol or parameters when shown, then run or refresh the pane."}
      </span>
      <span className="u-text-mute">
        Live/degraded state, source names, warnings, and transport details are shown in the pane body or footer.
      </span>
    </div>
  );
}

export function PaneBody({
  children,
  style,
  className,
}: {
  children: ReactNode;
  style?: CSSProperties;
  className?: string;
}) {
  return (
    <div tabIndex={0} className={`ds-pane-body${className ? ` ${className}` : ""}`} style={style}>
      {children}
    </div>
  );
}

export function PaneFooter({
  children,
}: {
  children: ReactNode;
}) {
  return <footer className="ds-pane-footer">{children}</footer>;
}
