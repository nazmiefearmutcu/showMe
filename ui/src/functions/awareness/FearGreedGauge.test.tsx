import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import {
  FearGreedGauge,
  fearGreedZone,
  formatSignedDelta,
  formatUtcStamp,
  needleAngle,
  ratingLabel,
} from "./FearGreedGauge";

describe("fearGreedZone", () => {
  it("maps the design zones, with their boundaries on the upper side", () => {
    expect(fearGreedZone(0).key).toBe("extreme-fear");
    expect(fearGreedZone(24.9).key).toBe("extreme-fear");
    expect(fearGreedZone(25).key).toBe("fear");
    expect(fearGreedZone(45).key).toBe("neutral");
    expect(fearGreedZone(55).key).toBe("greed");
    expect(fearGreedZone(75).key).toBe("extreme-greed");
    expect(fearGreedZone(100).key).toBe("extreme-greed");
  });

  it("uses the negative token for extreme fear and positive for greed", () => {
    expect(fearGreedZone(10).color).toBe("var(--negative)");
    expect(fearGreedZone(60).color).toBe("var(--positive)");
    expect(fearGreedZone(60).opacity).toBe(0.55);
  });
});

describe("needleAngle", () => {
  it("is pi at 0, pi/2 at 50 and 0 at 100", () => {
    expect(needleAngle(0)).toBeCloseTo(Math.PI, 10);
    expect(needleAngle(50)).toBeCloseTo(Math.PI / 2, 10);
    expect(needleAngle(100)).toBeCloseTo(0, 10);
  });
});

describe("formatSignedDelta", () => {
  it("uses a real minus sign and a plus for gains", () => {
    expect(formatSignedDelta(-2.2)).toBe("−2.2");
    expect(formatSignedDelta(2.24)).toBe("+2.2");
    expect(formatSignedDelta(0.01)).toBe("0.0");
  });
});

describe("formatUtcStamp", () => {
  it("formats an ISO instant as day, month, HH:MM UTC", () => {
    expect(formatUtcStamp("2026-11-06T23:59:00Z")).toBe("6 Nov 23:59 UTC");
  });

  it("returns an empty string when the timestamp does not parse", () => {
    expect(formatUtcStamp("not a date")).toBe("");
    expect(formatUtcStamp(null)).toBe("");
  });
});

describe("FearGreedGauge", () => {
  it("exposes a sentence label with the rounded score and zone", () => {
    const { getByRole } = render(<FearGreedGauge score={22.4} />);
    expect(getByRole("img").getAttribute("aria-label")).toBe(
      "Fear and Greed gauge at 22, extreme fear",
    );
  });

  it("clamps out-of-range scores for drawing and labelling", () => {
    const { getByRole } = render(<FearGreedGauge score={140} />);
    expect(getByRole("img").getAttribute("aria-label")).toBe(
      "Fear and Greed gauge at 100, extreme greed",
    );
  });

  it("points the needle left for 0 and right for 100", () => {
    const low = render(<FearGreedGauge score={0} />);
    const needleLow = low.getByTestId("fear-greed-needle");
    expect(Number(needleLow.getAttribute("x2"))).toBeLessThan(100);
    expect(Number(needleLow.getAttribute("y2"))).toBeCloseTo(100, 1);
    low.unmount();

    const high = render(<FearGreedGauge score={100} />);
    const needleHigh = high.getByTestId("fear-greed-needle");
    expect(Number(needleHigh.getAttribute("x2"))).toBeGreaterThan(100);
    expect(Number(needleHigh.getAttribute("y2"))).toBeCloseTo(100, 1);
  });

  it("draws five zone arcs, with tick labels only in the hero size", () => {
    const compact = render(<FearGreedGauge score={50} />);
    expect(compact.container.querySelectorAll("path[data-zone]")).toHaveLength(5);
    expect(compact.container.querySelectorAll("text")).toHaveLength(0);
    compact.unmount();

    const hero = render(<FearGreedGauge score={50} size="hero" />);
    expect(hero.container.querySelectorAll("text").length).toBe(3);
    expect(hero.container.querySelector("svg")?.getAttribute("width")).toBe("240");
  });
});

describe("ratingLabel and the crypto gauge size (F6 M-4, M-7)", () => {
  it("sentence-cases awareness ratings and returns null for blank input", () => {
    expect(ratingLabel("extreme fear")).toBe("Extreme fear");
    expect(ratingLabel("Extreme Fear")).toBe("Extreme fear");
    expect(ratingLabel("  ")).toBeNull();
    expect(ratingLabel(null)).toBeNull();
  });

  it("draws the crypto size at 160 x 88", () => {
    const { container } = render(<FearGreedGauge score={28} size="crypto" testId="g" />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("160");
    expect(svg?.getAttribute("height")).toBe("88");
  });
});
