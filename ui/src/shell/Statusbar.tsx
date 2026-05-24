import { useEffect, useState } from "react";
import { useAppStore } from "@/lib/store";
import { StatusSection, StatusDivider } from "@/design-system";
import { PRESET_LABELS, readState, THEME_CHANGE_EVENT, type ThemeState } from "@/lib/theme";
import { formatTime, timezoneOffsetLabel, useTimezone } from "@/lib/timezone";
import { describeNyseMarketState, getNyseMarketState } from "@/lib/market-state";

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

  // Canonical NYSE state machine (lib/market-state). Replaces the heuristic
  // "UTC hours 13-21 ≈ NYSE" rule that lit MARKET / open on Saturday.
  const nyseState = getNyseMarketState(now);
  const marketDisplay = describeNyseMarketState(nyseState);

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
      <span
        className="u-inline-flex u-items-center u-h-full statusbar__market"
        data-testid="market-state"
        data-market-state={nyseState}
      >
        <StatusSection
          label="market"
          value={marketDisplay.label}
          tone={marketDisplay.tone}
          withDot={marketDisplay.withDot}
        />
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

/**
 * Replace any `/Users/<account>/` prefix with `~/` so the bar never leaks a
 * developer's macOS short-name into screenshots, demos, or screen-share
 * sessions. Prior implementation hard-coded `/Users/nazmi/`, which silently
 * no-op'd on every other machine and exposed Nazmi's home folder.
 */
export function shortenPath(path: string): string {
  const match = path.match(/^\/Users\/[^/]+\//);
  if (match) return `~/${path.slice(match[0].length)}`;
  return path;
}
