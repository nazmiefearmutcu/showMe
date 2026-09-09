import { useEffect, useState } from "react";
import { useAppStore } from "@/lib/store";
import { StatusSection, StatusDivider } from "@/design-system";
import { PRESET_LABELS, readState, THEME_CHANGE_EVENT, type ThemeState } from "@/lib/theme";
import { formatTime, timezoneOffsetLabel, useTimezone } from "@/lib/timezone";
import { describeNyseMarketState, getNyseMarketState } from "@/lib/market-state";
import { useTapeHealth, TAPE_LABEL, formatTickAge } from "@/lib/tape-health";

/**
 * TapeHealthSection — the one honest "is my tape alive" pill (campaign
 * 2026-09-08, Lane B / U3). Aggregates the EXISTING quote-layer transport
 * registry (lib/tape-health.ts, fed by the multiplexer in market-data.ts)
 * into `LIVE · N sym · <age>` / RECONNECTING / DOWN. No polling loops and no
 * sockets here: state changes arrive via useSyncExternalStore, and the
 * staleness figure rides the Statusbar's existing 1 Hz clock re-render.
 * Hidden entirely when the desk has zero quote subscriptions — no tape, no
 * claim. Labels + age format are single-sourced in lib/tape-health.ts so
 * this pill and the Titlebar mini-tape can never drift (R3 L-2).
 */

function TapeHealthSection() {
  const health = useTapeHealth();
  if (health.totalSymbols === 0) return null;
  // Visible value: when the tape is down/reconnecting the desk still sees
  // how many symbols it WANTS ticks for; the tooltip must not call them
  // "streaming" though — only liveSymbols are actually streaming.
  const subscribed = health.totalSymbols;
  const streaming = health.state === "live" ? health.liveSymbols : 0;
  const ageMs =
    health.lastTickAt != null ? Math.max(0, Date.now() - health.lastTickAt) : null;
  const ageLabel = ageMs == null ? "—" : formatTickAge(ageMs);
  const tone =
    health.state === "live"
      ? "positive"
      : health.state === "reconnecting"
        ? "warn"
        : "negative";
  return (
    <>
      <StatusDivider />
      <span data-testid="tape-health" data-tape-state={health.state}>
        <StatusSection
          label="tape"
          value={`${TAPE_LABEL[health.state]} · ${subscribed} sym · ${ageLabel}`}
          tone={tone}
          withDot
          title={`Market data tape: ${TAPE_LABEL[health.state]} — ${streaming} streaming of ${subscribed} subscribed symbol${subscribed === 1 ? "" : "s"}, freshest tick ${ageLabel} ago`}
        />
      </span>
    </>
  );
}

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
        <TapeHealthSection />
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
          {/* Law 4 (accent discipline): the clock is data, not chrome —
              full-contrast display ink instead of accent. */}
          <StatusSection value={clock} />
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
