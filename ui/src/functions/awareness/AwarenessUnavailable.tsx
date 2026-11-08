import { useState } from "react";

/**
 * Honest "service down" state for every Awareness-backed pane.
 *
 * Shown when the backend returns `status === "provider_unavailable"`. It never
 * renders rows or sample data — only the backend's verbatim reason and two
 * actions (retry, copy the start command).
 */
export interface AwarenessUnavailableProps {
  reason?: string | null;
  onRetry?: () => void;
  /** Which pane is affected, e.g. "news" or "economic calendar". */
  subject?: string;
}

export const AWARENESS_START_COMMAND = "awareness-markets";

export function AwarenessUnavailable({ reason, onRetry, subject = "data" }: AwarenessUnavailableProps) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard?.writeText(AWARENESS_START_COMMAND);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="aw-unavailable" role="alert">
      <div className="aw-unavailable__title">Awareness service is not running</div>
      <p className="aw-unavailable__body">
        No {subject} is shown and no sample data is substituted. Start the awareness-markets service
        (it autostarts when SHOWME_AWARENESS_HOME points at an awareness checkout) and retry.
      </p>
      {reason ? <pre className="aw-unavailable__reason">{reason}</pre> : null}
      <div className="aw-unavailable__actions">
        {onRetry ? (
          <button type="button" className="aw-btn" onClick={onRetry}>
            Retry
          </button>
        ) : null}
        <button type="button" className="aw-btn aw-btn--ghost" onClick={copy}>
          {copied ? "Copied" : "Copy start command"}
        </button>
      </div>
    </div>
  );
}
