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

  it("draws the GDELT tone line and legend only when tone is supplied", () => {
    const without = render(<SentimentBars series={series} ariaLabel="x" />);
    expect(without.queryByTestId("gdelt-tone-line")).toBeNull();
    without.unmount();

    const withTone = render(
      <SentimentBars
        series={series}
        ariaLabel="x"
        tone={[
          { ts: "a", value: -2 },
          { ts: "b", value: 3 },
        ]}
      />,
    );
    expect(withTone.getByTestId("gdelt-tone-line")).toBeTruthy();
    expect(withTone.container.textContent).toContain("GDELT tone");
  });
});
