/**
 * Bundle D / AUDIO-01 — INSTANT speech-synthesis fix.
 *
 * Regression test for the bug where every 30 s poll cycle's cleanup called
 * `window.speechSynthesis.cancel()`, wiping any utterance that had just
 * been queued for a fresh high-priority event. The pane now splits the
 * speak loop from the cancel-on-unmount/off path, so queued utterances
 * survive incremental refreshes.
 *
 * We test the contract directly without rendering the full INSTANT pane:
 * the audio effect's behaviour is the contract we need pinned.
 */
import { render, act } from "@testing-library/react";
import { useEffect, useRef, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

interface SpeechStub {
  speak: ReturnType<typeof vi.fn>;
  cancel: ReturnType<typeof vi.fn>;
}

let speechStub: SpeechStub;

beforeEach(() => {
  speechStub = {
    speak: vi.fn(),
    cancel: vi.fn(),
  };
  Object.defineProperty(window, "speechSynthesis", {
    configurable: true,
    value: speechStub,
  });
  // SpeechSynthesisUtterance constructor minimal stub.
  (window as unknown as { SpeechSynthesisUtterance: unknown }).SpeechSynthesisUtterance =
    class {
      constructor(public text: string) {}
      rate = 1;
    };
});

afterEach(() => {
  vi.restoreAllMocks();
});

interface Event {
  dedupe_key?: string;
  priority_score?: number;
  priority_label?: string;
  source_name?: string;
  title?: string;
  generated_summary?: string;
}

/**
 * Mirror of the post-fix INSTANT audio effect shape. The test asserts that
 * the *cleanup* path no longer cancels queued utterances when the events
 * array prop changes (i.e. a poll cycle).
 */
function AudioHarness({ audio, events, audioThreshold }: { audio: boolean; events: Event[]; audioThreshold: number }) {
  const [, setBump] = useState(0);
  const spokenRef = useRef<Set<string>>(new Set());
  const audioEventsRef = useRef(events);
  const audioThresholdRef = useRef(audioThreshold);
  useEffect(() => {
    audioEventsRef.current = events;
  }, [events]);
  useEffect(() => {
    audioThresholdRef.current = audioThreshold;
  }, [audioThreshold]);

  // Speak loop — runs whenever inputs change. No cancel in cleanup.
  useEffect(() => {
    if (!audio || !("speechSynthesis" in window)) return;
    const seen = spokenRef.current;
    for (const event of audioEventsRef.current) {
      const score = Number(event.priority_score ?? 0);
      const key = event.dedupe_key ?? event.title ?? "";
      if (!key || seen.has(key) || score < audioThresholdRef.current) continue;
      seen.add(key);
      const u = new (window as unknown as { SpeechSynthesisUtterance: new (text: string) => unknown }).SpeechSynthesisUtterance(
        `${event.priority_label ?? "update"}. ${event.source_name ?? "instant"}. Score ${score}. ${event.title ?? ""}. ${event.generated_summary ?? ""}`,
      );
      (window.speechSynthesis as unknown as { speak: (u: unknown) => void }).speak(u);
    }
    // Intentionally no cancel here.
  }, [audio, events]);

  // Cancel only when audio flips off.
  useEffect(() => {
    if (audio) return;
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
  }, [audio]);

  // Cancel only on unmount.
  useEffect(() => {
    return () => {
      if ("speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  return <button onClick={() => setBump((b) => b + 1)}>bump</button>;
}

describe("INSTANT audio queue preservation", () => {
  it("does not cancel queued utterances when the events array updates", () => {
    const events1: Event[] = [
      { dedupe_key: "k1", priority_score: 90, title: "first" },
    ];
    const events2: Event[] = [
      ...events1,
      { dedupe_key: "k2", priority_score: 91, title: "second" },
    ];
    const { rerender } = render(
      <AudioHarness audio events={events1} audioThreshold={72} />,
    );
    expect(speechStub.speak).toHaveBeenCalledTimes(1);
    // Cancel must not have been called yet — audio is still on, no unmount.
    expect(speechStub.cancel).not.toHaveBeenCalled();

    // Simulate a poll cycle that appends a new event.
    rerender(<AudioHarness audio events={events2} audioThreshold={72} />);
    expect(speechStub.speak).toHaveBeenCalledTimes(2);
    expect(speechStub.cancel).not.toHaveBeenCalled();
  });

  it("cancels when audio toggles off", () => {
    const events: Event[] = [{ dedupe_key: "k1", priority_score: 90, title: "x" }];
    const { rerender } = render(
      <AudioHarness audio events={events} audioThreshold={72} />,
    );
    expect(speechStub.cancel).not.toHaveBeenCalled();
    rerender(<AudioHarness audio={false} events={events} audioThreshold={72} />);
    expect(speechStub.cancel).toHaveBeenCalled();
  });

  it("cancels on unmount", () => {
    const events: Event[] = [{ dedupe_key: "k1", priority_score: 90, title: "x" }];
    const { unmount } = render(
      <AudioHarness audio events={events} audioThreshold={72} />,
    );
    expect(speechStub.cancel).not.toHaveBeenCalled();
    act(() => unmount());
    expect(speechStub.cancel).toHaveBeenCalled();
  });

  it("does not respeak events whose key was already added to the seen set", () => {
    const events: Event[] = [{ dedupe_key: "k1", priority_score: 90, title: "x" }];
    const { rerender } = render(
      <AudioHarness audio events={events} audioThreshold={72} />,
    );
    expect(speechStub.speak).toHaveBeenCalledTimes(1);
    // Re-rerender with same event — should not respeak.
    rerender(<AudioHarness audio events={[...events]} audioThreshold={72} />);
    expect(speechStub.speak).toHaveBeenCalledTimes(1);
  });
});
