/**
 * Faz 5 — sentiment panel binding.
 *
 * Pins the contract that the Welcome dashboard's sentiment gauge consumes
 * `useSentimentStore` instead of literal "Cautiously Bullish" / "+32%" /
 * static `rotate(-58deg)` styling.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { Welcome, sentimentNeedleAngle, formatSentimentPct } from "./Welcome";
import { useAppStore } from "@/lib/store";
import { useSentimentStore } from "@/lib/sentiment-store";

// Welcome's useFunction calls would otherwise try to hit the sidecar in jsdom;
// stub them. Returning `idle` keeps the loading/skeleton paths benign.
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({ state: "idle", data: null, error: null, refetch: () => {} }),
}));

// Stub the sentiment refresh action so we can verify it's called and so the
// real fan-out doesn't escape jsdom.
const refreshSpy = vi.fn();

beforeEach(() => {
  cleanup();
  localStorage.clear();
  // Force "booting" so the auto-refresh effect bails (status guard) and our
  // tests fully control what's in the store.
  useAppStore.setState({
    sidecarStatus: "booting",
    sidecarPort: null,
    engineRoot: null,
    functionIndex: [],
  });
  useSentimentStore.setState({
    score: 0,
    label: "Neutral",
    mentions: 0,
    loading: false,
    error: null,
    lastUpdated: null,
    _inflight: null,
    refresh: refreshSpy,
  });
  refreshSpy.mockReset();
});

describe("Welcome sentiment panel — pure helpers", () => {
  it("sentimentNeedleAngle maps [-1,+1] to [-90deg,+90deg]", () => {
    expect(sentimentNeedleAngle(-1)).toBe(-90);
    expect(sentimentNeedleAngle(0)).toBe(0);
    expect(sentimentNeedleAngle(1)).toBe(90);
    // mid-band sanity
    expect(sentimentNeedleAngle(0.5)).toBeCloseTo(45, 5);
    expect(sentimentNeedleAngle(-0.5)).toBeCloseTo(-45, 5);
  });

  it("sentimentNeedleAngle clamps out-of-range input", () => {
    expect(sentimentNeedleAngle(2)).toBe(90);
    expect(sentimentNeedleAngle(-2)).toBe(-90);
  });

  it("formatSentimentPct adds + prefix for positive, plain for negative/zero", () => {
    expect(formatSentimentPct(0.33)).toBe("+33%");
    expect(formatSentimentPct(0)).toBe("0%");
    expect(formatSentimentPct(-0.32)).toBe("-32%");
  });
});

describe("Welcome sentiment panel — DOM binding", () => {
  it("first-mount (no lastUpdated, loading=true) renders 'loading…' eyebrow", () => {
    useSentimentStore.setState({
      loading: true,
      score: 0,
      label: "Neutral",
      mentions: 0,
      lastUpdated: null,
      error: null,
    });
    const { getByTestId } = render(<Welcome />);
    const gauge = getByTestId("sentiment-gauge");
    expect(gauge).toBeTruthy();
    // The meta line shows the loading prefix.
    expect(gauge.parentElement?.textContent).toContain("loading…");
    // Bullish label hidden until first load completes (or load aborts via
    // lastUpdated being set on error path).
    expect(getByTestId("sentiment-label").textContent).toMatch(/Loading…/);
    // No real percentage yet.
    expect(getByTestId("sentiment-change").textContent).toBe("0%");
  });

  it("first-mount idle (no lastUpdated, loading=false) renders em-dash placeholder", () => {
    useSentimentStore.setState({
      loading: false,
      score: 0,
      label: "Neutral",
      mentions: 0,
      lastUpdated: null,
      error: null,
    });
    const { getByTestId } = render(<Welcome />);
    expect(getByTestId("sentiment-change").textContent).toBe("—");
  });

  it("after populate (score=0.33, label='Cautiously Bullish') renders bound DOM", () => {
    useSentimentStore.setState({
      loading: false,
      score: 0.33,
      label: "Cautiously Bullish",
      mentions: 540,
      lastUpdated: new Date("2026-05-23T12:00:00Z"),
      error: null,
    });
    const { getByTestId, container } = render(<Welcome />);
    // <strong> binding
    expect(getByTestId("sentiment-label").textContent).toBe("Cautiously Bullish");
    // +33% chip with positive tone class
    const change = getByTestId("sentiment-change");
    expect(change.textContent).toBe("+33%");
    expect(change.className).toContain("terminal-change--positive");
    // aria-label reflects label
    const gauge = getByTestId("sentiment-gauge");
    expect(gauge.getAttribute("aria-label")).toBe("Sentiment cautiously bullish");
    // gauge holds the raw score for downstream introspection
    expect(gauge.getAttribute("data-score")).toBe("0.330");
    // eyebrow shows mention count
    expect(container.textContent).toContain("540 mentions");
  });

  it("negative score: needle rotates to negative angle and chip class is --negative", () => {
    useSentimentStore.setState({
      loading: false,
      score: -0.5,
      label: "Cautiously Bearish",
      mentions: 90,
      lastUpdated: new Date(),
      error: null,
    });
    const { getByTestId } = render(<Welcome />);
    const needle = getByTestId("sentiment-needle") as HTMLElement;
    // -0.5 should map to -45deg
    expect(needle.style.transform).toBe("rotate(-45deg)");
    const change = getByTestId("sentiment-change");
    expect(change.textContent).toBe("-50%");
    expect(change.className).toContain("terminal-change--negative");
    expect(getByTestId("sentiment-gauge").getAttribute("aria-label")).toBe(
      "Sentiment cautiously bearish",
    );
  });

  it("score=0 → needle straight up (0deg)", () => {
    useSentimentStore.setState({
      loading: false,
      score: 0,
      label: "Neutral",
      mentions: 10,
      lastUpdated: new Date(),
      error: null,
    });
    const { getByTestId } = render(<Welcome />);
    const needle = getByTestId("sentiment-needle") as HTMLElement;
    expect(needle.style.transform).toBe("rotate(0deg)");
  });

  it("score=+1 → needle at +90deg", () => {
    useSentimentStore.setState({
      loading: false,
      score: 1,
      label: "Strongly Bullish",
      mentions: 999,
      lastUpdated: new Date(),
      error: null,
    });
    const { getByTestId } = render(<Welcome />);
    const needle = getByTestId("sentiment-needle") as HTMLElement;
    expect(needle.style.transform).toBe("rotate(90deg)");
  });

  it("error with no last value → 'unavailable' eyebrow + em-dash placeholder", () => {
    useSentimentStore.setState({
      loading: false,
      score: 0,
      label: "Neutral",
      mentions: 0,
      lastUpdated: null,
      error: "503 Service Unavailable",
    });
    const { getByTestId } = render(<Welcome />);
    expect(getByTestId("sentiment-gauge").parentElement?.textContent).toContain(
      "unavailable",
    );
    expect(getByTestId("sentiment-change").textContent).toBe("—");
  });

  it("auto-refresh fires once sidecar becomes healthy", () => {
    // Status was "booting" in beforeEach — effect bails.
    const { rerender } = render(<Welcome />);
    expect(refreshSpy).not.toHaveBeenCalled();

    // Flip status to healthy → effect should re-run and fire refresh.
    act(() => {
      useAppStore.setState({ sidecarStatus: "healthy" });
    });
    rerender(<Welcome />);
    expect(refreshSpy).toHaveBeenCalled();
    // First call should hand over the fallback list (watchRows are empty when
    // there's no portfolio + the default sample deck IS the watchRows now).
    const firstCallSymbols = refreshSpy.mock.calls[0]![0] as string[];
    expect(Array.isArray(firstCallSymbols)).toBe(true);
    expect(firstCallSymbols.length).toBeGreaterThan(0);
  });
});

describe("Welcome — demo data banners on BRIEF + MOVERS", () => {
  it("renders 'Demo data' banner on the BRIEF panel", () => {
    const { getByTestId } = render(<Welcome />);
    expect(getByTestId("brief-demo-banner").textContent).toMatch(/Demo data/i);
  });

  it("renders 'Demo data' badge on the MOVERS panel header", () => {
    const { getByTestId } = render(<Welcome />);
    expect(getByTestId("movers-demo-banner").textContent).toMatch(/Demo data/i);
  });
});
