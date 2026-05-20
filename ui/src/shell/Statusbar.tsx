import { useEffect, useState } from "react";
import { useAppStore } from "@/lib/store";
import { StatusSection, StatusDivider } from "@/design-system";
import { PRESET_LABELS, readState, THEME_CHANGE_EVENT, type ThemeState } from "@/lib/theme";
import { formatTime, timezoneOffsetLabel, useTimezone } from "@/lib/timezone";

export function Statusbar() {
  const status = useAppStore((s) => s.sidecarStatus);
  const port = useAppStore((s) => s.sidecarPort);
  const engineRoot = useAppStore((s) => s.engineRoot);
  const total = useAppStore((s) => s.functionIndex.length);
  const tz = useTimezone();
  const [now, setNow] = useState(() => new Date());
  const [themeLabel, setThemeLabel] = useState(() => PRESET_LABELS[readState().preset]);

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const update = (event: Event) => {
      const detail = (event as CustomEvent<ThemeState>).detail;
      setThemeLabel(PRESET_LABELS[detail?.preset ?? readState().preset]);
    };
    window.addEventListener(THEME_CHANGE_EVENT, update);
    return () => window.removeEventListener(THEME_CHANGE_EVENT, update);
  }, []);

  const tzShort = timezoneOffsetLabel(tz, now);
  const clock = `${formatTime(now, { tz, seconds: true })} ${tzShort}`;
  const dataRoot = engineRoot ? shortenPath(engineRoot) : "—";

  const tone =
    status === "healthy" ? "positive" : status === "crashed" ? "negative" : "warn";

  // Heuristic market session — UTC hours 13-21 ≈ NYSE, otherwise pre/after.
  const utcHour = now.getUTCHours();
  const marketState =
    utcHour >= 13 && utcHour < 20 ? "open" : utcHour >= 20 && utcHour < 22 ? "after" : "pre-open";
  const marketTone =
    marketState === "open" ? "positive" : marketState === "after" ? "warn" : "muted";

  return (
    // A11Y-05 P1: drop the footer-wide role="status" so the 1Hz clock no
    // longer makes screen readers announce the entire bar every second.
    // Only the runtime status section gets aria-live.
    <footer className="statusbar" aria-label="App status">
      <span className="u-inline-flex u-items-center u-h-full">
        <StatusSection
          label="theme"
          value={themeLabel}
          tone="muted"
        />
        <StatusDivider />
        <span role="status" aria-live="polite">
          <StatusSection
            label="runtime"
            value={
              <>
                {status}
                {port && <span className="u-text-mute statusbar__port-suffix">:{port}</span>}
              </>
            }
            tone={tone}
            withDot
          />
        </span>
        <StatusDivider />
        <StatusSection label="fn" value={total} />
      </span>
      <span className="u-inline-flex u-items-center u-h-full statusbar__market">
        <StatusSection label="market" value={marketState} tone={marketTone} withDot />
      </span>
      <span className="u-inline-flex u-items-center u-h-full">
        <StatusSection
          label="data"
          value={
            <span
              title={engineRoot ?? ""}
              className="statusbar__data-value"
            >
              {dataRoot}
            </span>
          }
        />
        <StatusDivider />
        {/* aria-hidden on the clock — sighted users see the time, but a
            screen reader doesn't need it announced once per second. */}
        <span aria-hidden>
          <StatusSection value={clock} tone="accent" />
        </span>
      </span>
    </footer>
  );
}

function shortenPath(path: string): string {
  const home = "/Users/nazmi/";
  if (path.startsWith(home)) return `~/${path.slice(home.length)}`;
  return path;
}
