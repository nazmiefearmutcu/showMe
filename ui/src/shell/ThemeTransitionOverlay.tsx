/**
 * Theme transition overlay — covers the workspace during a preset/density
 * change so the user sees the showMe logo + pulse instead of a layout freeze.
 *
 * Listens for `THEME_TRANSITION_START` / `THEME_TRANSITION_END` from
 * `lib/theme-transition.ts`. Reuses the boot intro's CSS identity
 * (`.showme-intro` + `.showme-intro__container`) so the brief overlay
 * matches the visual brand without re-implementing keyframes.
 *
 * Multi-trigger safety: a counter tracks overlapping starts so rapid
 * preset toggles don't tear the overlay down mid-transition.
 *
 * Recovery S01 hardening (2026-05-20): a self-watchdog forces the overlay
 * to clear after `MAX_OVERLAY_LIFETIME_MS` from the first start, even if
 * no END event ever arrives. A `THEME_TRANSITION_FORCE_END` listener
 * provides an external emergency-clear hook. Combined with the producer-
 * side guarantee in `runThemeTransition`, the overlay can never become a
 * permanent input-blocker.
 */

import { useEffect, useState } from "react";
import {
  THEME_TRANSITION_END,
  THEME_TRANSITION_FORCE_END,
  THEME_TRANSITION_START,
} from "@/lib/theme-transition";

/**
 * Self-watchdog ceiling. Even if every guarantee on the producer side
 * fails, the overlay clears itself this many ms after the first START.
 * Sized comfortably above the producer-side watchdog (1200ms) so this
 * only fires in catastrophic cases.
 */
export const MAX_OVERLAY_LIFETIME_MS = 1500;

/** Leave-phase keyframe duration, kept in sync with `.showme-intro--brief`. */
const LEAVE_DURATION_MS = 140;

export function ThemeTransitionOverlay() {
  const [active, setActive] = useState(false);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    let depth = 0;
    let leaveTimer: number | null = null;
    let watchdog: number | null = null;

    const clearLeaveTimer = () => {
      if (leaveTimer != null) {
        window.clearTimeout(leaveTimer);
        leaveTimer = null;
      }
    };
    const clearWatchdog = () => {
      if (watchdog != null) {
        window.clearTimeout(watchdog);
        watchdog = null;
      }
    };

    /** Hard reset — depth back to 0, all timers cleared, overlay hidden. */
    const hardClear = () => {
      depth = 0;
      clearLeaveTimer();
      clearWatchdog();
      setLeaving(false);
      setActive(false);
    };

    function onStart() {
      depth += 1;
      clearLeaveTimer();
      // (Re)arm the self-watchdog from the latest start so a chain of
      // rapid presses still gets ~MAX_OVERLAY_LIFETIME_MS of grace.
      clearWatchdog();
      watchdog = window.setTimeout(hardClear, MAX_OVERLAY_LIFETIME_MS);
      setLeaving(false);
      setActive(true);
    }

    function onEnd() {
      depth = Math.max(0, depth - 1);
      if (depth > 0) return;
      // Start fade-out; unmount after the leaving keyframe completes.
      setLeaving(true);
      leaveTimer = window.setTimeout(() => {
        setActive(false);
        setLeaving(false);
        leaveTimer = null;
        clearWatchdog();
      }, LEAVE_DURATION_MS);
    }

    function onForceEnd() {
      hardClear();
    }

    window.addEventListener(THEME_TRANSITION_START, onStart);
    window.addEventListener(THEME_TRANSITION_END, onEnd);
    window.addEventListener(THEME_TRANSITION_FORCE_END, onForceEnd);
    return () => {
      window.removeEventListener(THEME_TRANSITION_START, onStart);
      window.removeEventListener(THEME_TRANSITION_END, onEnd);
      window.removeEventListener(THEME_TRANSITION_FORCE_END, onForceEnd);
      clearLeaveTimer();
      clearWatchdog();
    };
  }, []);

  if (!active) return null;

  const phaseClass = leaving
    ? "showme-intro--leaving"
    : "showme-intro--expanding";

  return (
    <div
      className={`showme-intro showme-intro--brief ${phaseClass}`}
      aria-hidden="true"
      data-testid="theme-transition-overlay"
      data-phase={leaving ? "leaving" : "expanding"}
    >
      <div className="showme-intro__container">
        <div className="showme-intro__pulse-ring showme-intro__pulse-ring--one" />
        <div className="showme-intro__pulse-ring showme-intro__pulse-ring--two" />
        <div className="showme-intro__circle showme-intro__circle--expand" />
        <div className="showme-intro__logo showme-intro__logo--reveal">
          <span className="showme-intro__logo-show">show</span>
          <span className="showme-intro__logo-me">Me</span>
        </div>
      </div>
    </div>
  );
}
