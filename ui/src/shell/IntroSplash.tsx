import { useEffect, useRef, useState, type TransitionEvent } from "react";
import { useReducedMotion } from "@/lib/a11y";

type IntroPhase = "standby" | "expanding" | "leaving";

interface IntroSplashProps {
  ready: boolean;
  onDone: () => void;
}

/**
 * IntroSplash — boot splash, DESIGN-BRIEF minimal treatment:
 * logo mark + progress hairline, no glow wash, no pulse rings, no
 * entrance animations. The phase machine is unchanged (standby →
 * expanding → leaving) and is driven purely by timeouts + the overlay
 * opacity `transitionend`, so it no longer depends on keyframe events.
 *
 * A11Y-06 P1: when reduced-motion is set the global media query clamps
 * keyframes/transitions to 0.01ms — `transitionend` would never fire and
 * the boot would deadlock, so we skip the phases entirely.
 */
export function IntroSplash({ ready, onDone }: IntroSplashProps) {
  const [phase, setPhase] = useState<IntroPhase>("standby");
  const doneRef = useRef(false);
  const reducedMotion = useReducedMotion();

  // Reduced motion: announce-and-release immediately (see doc comment).
  useEffect(() => {
    if (!reducedMotion) return;
    if (ready && !doneRef.current) {
      doneRef.current = true;
      onDone();
    }
  }, [reducedMotion, ready, onDone]);

  useEffect(() => {
    if (!ready || reducedMotion || doneRef.current) return;
    const id = window.setTimeout(
      () => setPhase((current) => (current === "standby" ? "expanding" : current)),
      350,
    );
    return () => window.clearTimeout(id);
  }, [ready, reducedMotion]);

  useEffect(() => {
    if (phase !== "expanding" || doneRef.current) return;
    const id = window.setTimeout(() => setPhase("leaving"), 1_900);
    return () => window.clearTimeout(id);
  }, [phase]);

  useEffect(() => {
    if (phase !== "leaving" || doneRef.current) return;
    const id = window.setTimeout(() => {
      if (doneRef.current) return;
      doneRef.current = true;
      onDone();
    }, 420);
    return () => window.clearTimeout(id);
  }, [phase, onDone]);

  function handleOverlayTransitionEnd(event: TransitionEvent<HTMLDivElement>) {
    if (event.target !== event.currentTarget || phase !== "leaving" || doneRef.current)
      return;
    doneRef.current = true;
    onDone();
  }

  return (
    <div
      className={`showme-intro showme-intro--${phase}`}
      aria-label="showMe loading"
      aria-busy={phase !== "leaving"}
      onTransitionEnd={handleOverlayTransitionEnd}
    >
      <div className="showme-intro__container">
        <div className="showme-intro__mark">
          <span className="showme-intro__mark-block" aria-hidden />
          <span className="showme-intro__logo-show">show</span>
          <span className="showme-intro__logo-me">Me</span>
        </div>
        <div
          className="showme-intro__progress"
          role="progressbar"
          aria-label="Loading showMe"
        >
          <span className="showme-intro__progress-bar" />
        </div>
      </div>
    </div>
  );
}
