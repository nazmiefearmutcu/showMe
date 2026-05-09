import { useEffect, useRef, useState, type AnimationEvent, type TransitionEvent } from "react";

type IntroPhase = "standby" | "expanding" | "leaving";

interface IntroSplashProps {
  ready: boolean;
  onDone: () => void;
}

export function IntroSplash({ ready, onDone }: IntroSplashProps) {
  const [phase, setPhase] = useState<IntroPhase>("standby");
  const readyRef = useRef(ready);
  const doneRef = useRef(false);

  useEffect(() => {
    readyRef.current = ready;
  }, [ready]);

  function beginExpand() {
    setPhase((current) => (current === "standby" ? "expanding" : current));
  }

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
    if (event.target !== event.currentTarget || phase !== "leaving" || doneRef.current) return;
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
            phase === "standby" ? "showme-intro__circle--standby" : "showme-intro__circle--expand"
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
