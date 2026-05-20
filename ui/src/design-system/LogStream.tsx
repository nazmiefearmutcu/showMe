/**
 * LogStream — auto-scroll, level-tinted, monospace event tail.
 *
 * Used by INSTANT/AGENT/ASK/SYS panes. Levels tint the leading badge,
 * not the row, so the eye still reads the message text first.
 */

import { memo, useEffect, useRef } from "react";

export type LogLevel = "info" | "warn" | "error" | "debug";

export interface LogEntry {
  ts: string;
  level: LogLevel;
  message: string;
  source?: string;
}

function LogStreamImpl({
  entries,
  maxHeight = 240,
  follow = true,
  monoFontSize = 11,
}: {
  entries: LogEntry[];
  maxHeight?: number;
  follow?: boolean;
  monoFontSize?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!follow) return;
    const el = ref.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [entries, follow]);

  return (
    <div
      ref={ref}
      className="ds-logstream"
      style={{
        maxHeight,
        fontSize: monoFontSize,
      }}
    >
      {entries.length === 0 ? (
        <div className="ds-logstream__empty">no events</div>
      ) : (
        entries.map((e, i) => (
          <div key={i} className="ds-logstream__row">
            <span className="u-text-mute">{e.ts.slice(11, 19)}</span>
            <span className={`ds-logstream__level ds-logstream__level--${e.level}`}>
              {e.level}
            </span>
            <span className="ds-logstream__msg">
              {e.source && (
                <span className="ds-logstream__source">[{e.source}]</span>
              )}
              {e.message}
            </span>
          </div>
        ))
      )}
    </div>
  );
}

export const LogStream = memo(LogStreamImpl);
