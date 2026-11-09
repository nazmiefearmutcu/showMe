import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { SentimentBars } from "./SentimentBars";

const series = [
  { ts: "2026-11-05", mean: 0.4 },
  { ts: "2026-11-06", mean: -0.2 },
  { ts: "2026-11-07", mean: null },
  { ts: "2026-11-08", mean: 0 },
];

describe("SentimentBars", () => {
  it("draws up bars for positive means and down bars for negative ones", () => {
    const { container } = render(
      <SentimentBars series={series} ariaLabel="NVDA news sentiment" />,
    );
    const bars = container.querySelectorAll("rect");
    expect(bars).toHaveLength(3);
    expect(bars[0].getAttribute("data-direction")).toBe("up");
    expect(bars[1].getAttribute("data-direction")).toBe("down");
    expect(bars[2].getAttribute("data-direction")).toBe("flat");
  });

  it("leaves a null bucket blank rather than drawing it as zero", () => {
    const { container } = render(
      <SentimentBars
        series={[
          { ts: "a", mean: null },
          { ts: "b", mean: null },
        ]}
        ariaLabel="x"
      />,
    );
    expect(container.querySelectorAll("rect")).toHaveLength(0);
  });

  it("sizes bars against the largest absolute mean in view", () => {
    const { container } = render(<SentimentBars series={series} ariaLabel="x" />);
    const [first] = Array.from(container.querySelectorAll("rect"));
    expect(Number(first.getAttribute("height"))).toBeGreaterThan(0);
  });

  it("places tone samples by timestamp on the bucket axis, not by sample index", () => {
    // Three hourly buckets, five tone samples: the counts differ on purpose.
    const hourly = [
      { ts: "2026-11-08T00:00:00Z", mean: 0.4 },
      { ts: "2026-11-08T01:00:00Z", mean: -0.2 },
      { ts: "2026-11-08T02:00:00Z", mean: 0.1 },
    ];
    const tone = [
      { ts: "2026-11-08T00:00:00Z", value: 1 },
      { ts: "2026-11-08T00:30:00Z", value: 2 },
      { ts: "2026-11-08T01:00:00Z", value: 3 },
      { ts: "2026-11-08T01:30:00Z", value: 4 },
      { ts: "2026-11-08T02:00:00Z", value: 5 },
    ];
    const { container, getByTestId } = render(
      <SentimentBars series={hourly} tone={tone} ariaLabel="x" />,
    );
    // Axis runs from -30 min to +2.5 h (3 h span over 400 units): x = (t + 0.5 h) / 3 h * 400.
    const xs = getByTestId("gdelt-tone-line")
      .getAttribute("points")!
      .split(" ")
      .map((p) => Number(p.split(",")[0]));
    expect(xs).toHaveLength(5);
    expect(xs[0]).toBeCloseTo(66.7, 1);
    expect(xs[1]).toBeCloseTo(133.3, 1);
    expect(xs[2]).toBeCloseTo(200.0, 1);
    expect(xs[3]).toBeCloseTo(266.7, 1);
    expect(xs[4]).toBeCloseTo(333.3, 1);

    // A tone sample at a bucket's own time sits on that bar's centre.
    const bars = Array.from(container.querySelectorAll("rect"));
    const centre =
      Number(bars[1].getAttribute("x")) + Number(bars[1].getAttribute("width")) / 2;
    expect(xs[2]).toBeCloseTo(centre, 1);
  });

  it("does not show the tone legend when no tone point can be drawn", () => {
    const { container } = render(
      <SentimentBars series={series} tone={[{ ts: "bad", value: 1 }]} ariaLabel="x" />,
    );
    expect(container.querySelector("[data-testid='gdelt-tone-line']")).toBeNull();
    expect(container.textContent).not.toContain("GDELT tone");
  });

  it("draws the GDELT tone line and legend only when tone is supplied", () => {
    const without = render(<SentimentBars series={series} ariaLabel="x" />);
    expect(without.queryByTestId("gdelt-tone-line")).toBeNull();
    without.unmount();

    const withTone = render(
      <SentimentBars
        series={series}
        ariaLabel="x"
        tone={[
          { ts: "2026-11-05", value: -2 },
          { ts: "2026-11-08", value: 3 },
        ]}
      />,
    );
    expect(withTone.getByTestId("gdelt-tone-line")).toBeTruthy();
    expect(withTone.container.textContent).toContain("GDELT tone");
  });
});
