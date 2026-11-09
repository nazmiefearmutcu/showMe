import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { TermStructureChart, nearTermAboveSpot } from "./TermStructureChart";

describe("TermStructureChart", () => {
  it("labels the three VIX points with their values", () => {
    const { getByRole, container } = render(
      <TermStructureChart vix9d={18.2} vix={17.1} vix3m={18.2} />,
    );
    expect(getByRole("img").getAttribute("aria-label")).toBe(
      "VIX term structure: VIX9D 18.20, VIX 17.10, VIX3M 18.20",
    );
    const texts = Array.from(container.querySelectorAll("text")).map((t) => t.textContent);
    expect(texts).toContain("17.10");
    expect(texts).toContain("VIX3M");
  });

  it("colours the VIX9D dot as a warning when it sits above spot", () => {
    const { container } = render(<TermStructureChart vix9d={21} vix={17} vix3m={19} />);
    expect(container.querySelector('circle[data-warn="true"]')).not.toBeNull();
    expect(nearTermAboveSpot(21, 17)).toBe(true);
    expect(nearTermAboveSpot(15, 17)).toBe(false);
  });

  it("omits missing points and never invents one", () => {
    const { container } = render(<TermStructureChart vix9d={null} vix={17} vix3m={19} />);
    expect(container.querySelectorAll("circle")).toHaveLength(2);
    expect(container.textContent).not.toContain("VIX9D");
  });

  it("shows a note instead of a chart when fewer than two points exist", () => {
    const { getByRole, container } = render(
      <TermStructureChart vix9d={null} vix={17} vix3m={undefined} />,
    );
    expect(getByRole("note").textContent).toMatch(/Not enough VIX points/);
    expect(container.querySelector("svg")).toBeNull();
  });
});
