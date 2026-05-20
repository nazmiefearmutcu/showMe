import type { ReactNode } from "react";

interface EmptyProps {
  title: string;
  body?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}

export function Empty({ title, body, action, icon = "∅" }: EmptyProps) {
  return (
    <div className="ds-empty">
      <div className="ds-empty__icon">{icon}</div>
      <strong className="ds-empty__title">{title}</strong>
      {body && <div className="ds-empty__body">{body}</div>}
      {action && <div className="u-mt-8">{action}</div>}
    </div>
  );
}
