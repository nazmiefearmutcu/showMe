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
 */

import { useEffect, useState } from "react";
import {
  THEME_TRANSITION_END,
  THEME_TRANSITION_START,
} from "@/lib/theme-transition";

export function ThemeTransitionOverlay() {
  const [active, setActive] = useState(false);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    let depth = 0;
    let leaveTimer: number | null = null;

    function onStart() {
      depth += 1;
      if (leaveTimer != null) {
        window.clearTimeout(leaveTimer);
        leaveTimer = null;
      }
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
      }, 140);
    }

    window.addEventListener(THEME_TRANSITION_START, onStart);
    window.addEventListener(THEME_TRANSITION_END, onEnd);
    return () => {
      window.removeEventListener(THEME_TRANSITION_START, onStart);
      window.removeEventListener(THEME_TRANSITION_END, onEnd);
      if (leaveTimer != null) window.clearTimeout(leaveTimer);
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
