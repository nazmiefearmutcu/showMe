import {
  useEffect,
  useRef,
  useState,
  type AnimationEvent,
  type TransitionEvent,
} from "react";
import { useReducedMotion } from "@/lib/a11y";

type IntroPhase = "standby" | "expanding" | "leaving";

interface IntroSplashProps {
  ready: boolean;
  onDone: () => void;
}

export function IntroSplash({ ready, onDone }: IntroSplashProps) {
  const [phase, setPhase] = useState<IntroPhase>("standby");
  const readyRef = useRef(ready);
  const doneRef = useRef(false);
  const reducedMotion = useReducedMotion();

  useEffect(() => {
    readyRef.current = ready;
  }, [ready]);

  // A11Y-06 P1: when reduced-motion is set, the keyframes are clamped to
  // 0.01ms by the global media query — the `animationiteration` /
  // `animationend` events that normally drive `setPhase` will not fire,
  // deadlocking the boot. Skip the animation phases entirely.
  useEffect(() => {
    if (!reducedMotion) return;
    if (ready && !doneRef.current) {
      doneRef.current = true;
      onDone();
    }
  }, [reducedMotion, ready, onDone]);

  function beginExpand() {
    setPhase((current) => (current === "standby" ? "expanding" : current));
  }

  useEffect(() => {
    if (!ready || reducedMotion || doneRef.current) return;
    const id = window.setTimeout(beginExpand, 350);
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

  function handleDotIteration(event: AnimationEvent<HTMLDivElement>) {
    if (event.animationName === "showmeIntroPulseLoop" && readyRef.current) {
      beginExpand();
    }
  }

  function handleLogoAnimationEnd(event: AnimationEvent<HTMLDivElement>) {
    if (event.animationName === "showmeIntroTextReveal") {
      setPhase("leaving");
    }
  }

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
        <div className="showme-intro__pulse-ring showme-intro__pulse-ring--one" />
        <div className="showme-intro__pulse-ring showme-intro__pulse-ring--two" />
        <div className="showme-intro__orbit">
          <span />
        </div>
        <div
          className={`showme-intro__circle ${
            phase === "standby"
              ? "showme-intro__circle--standby"
              : "showme-intro__circle--expand"
          }`}
          onAnimationIteration={handleDotIteration}
        />
        <div
          className={`showme-intro__logo ${
            phase !== "standby" ? "showme-intro__logo--reveal" : ""
          }`}
          onAnimationEnd={handleLogoAnimationEnd}
        >
          <span className="showme-intro__logo-show">show</span>
          <span className="showme-intro__logo-me">Me</span>
        </div>
      </div>
    </div>
  );
}
