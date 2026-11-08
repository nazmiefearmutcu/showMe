import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ImportanceDots, importanceLevel } from "./ImportanceDots";
import { SurpriseCell, formatSignedValue } from "./SurpriseCell";
import { ProvenanceButton } from "./ProvenanceButton";

afterEach(() => cleanup());

describe("ImportanceDots", () => {
  it("maps 1-3 to low / medium / high with an accessible name", () => {
    const { unmount } = render(<ImportanceDots importance={3} />);
    expect(screen.getByRole("img", { name: "High importance" })).toBeTruthy();
    expect(document.querySelectorAll(".aw-imp__dot--high")).toHaveLength(3);
    unmount();
    render(<ImportanceDots importance="2" />);
    expect(screen.getByRole("img", { name: "Medium importance" })).toBeTruthy();
    expect(document.querySelectorAll(".aw-imp__dot--on")).toHaveLength(2);
  });

  it("reports an unknown importance instead of inventing a level", () => {
    render(<ImportanceDots importance={null} />);
    expect(screen.getByRole("img", { name: "Importance not reported" })).toBeTruthy();
    expect(document.querySelectorAll(".aw-imp__dot--off")).toHaveLength(3);
  });

  it("clamps out-of-range values and rejects blank strings", () => {
    expect(importanceLevel(7)).toBe(3);
    expect(importanceLevel(0)).toBe(1);
    expect(importanceLevel("")).toBeNull();
    expect(importanceLevel("n/a")).toBeNull();
  });
});

describe("SurpriseCell", () => {
  it("shows above with a glyph and a signed value", () => {
    render(<SurpriseCell surprise={0.1} unit="%" direction="above" released />);
    const cell = screen.getByLabelText("Above consensus by +0.10%");
    expect(cell.textContent).toContain("▲");
    expect(cell.textContent).toContain("+0.10%");
  });

  it("uses the real minus sign for below", () => {
    render(<SurpriseCell surprise={-0.3} unit="K" direction="below" released />);
    const cell = screen.getByLabelText("Below consensus by −0.30K");
    expect(cell.textContent).toContain("▼");
    expect(cell.textContent).toContain("−0.30K");
  });

  it("renders inline prints with an equals glyph", () => {
    render(<SurpriseCell surprise={0} unit="%" direction="inline" released />);
    expect(screen.getByLabelText("Inline with consensus").textContent).toBe("= 0.00%");
  });

  it("renders nothing for unreleased prints or missing surprise", () => {
    const { container, rerender } = render(
      <SurpriseCell surprise={0.4} direction="above" released={false} />,
    );
    expect(container.textContent).toBe("");
    rerender(<SurpriseCell surprise={null} released />);
    expect(container.textContent).toBe("");
  });

  it("formats signed values with two decimals", () => {
    expect(formatSignedValue(1.234)).toBe("+1.23");
    expect(formatSignedValue(-0.5)).toBe("−0.50");
  });
});

describe("ProvenanceButton", () => {
  const sources = [
    { provider: "econ.nasdaq", basis: "consensus", fetched_at: "2026-06-09T11:55:00.000Z" },
    { provider: "econ.forexfactory", basis: "impact" },
  ];

  it("lists each provider behind the row when expanded", () => {
    render(<ProvenanceButton sources={sources} subject="CPI" />);
    const btn = screen.getByRole("button", { name: "Sources for CPI: 2" });
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("econ.nasdaq")).toBeTruthy();
    expect(screen.getByText("econ.forexfactory")).toBeTruthy();
    expect(screen.getByText("11:55 UTC")).toBeTruthy();
  });

  it("closes on Escape and returns focus to the button", () => {
    render(<ProvenanceButton sources={sources} subject="CPI" />);
    const btn = screen.getByRole("button", { name: "Sources for CPI: 2" });
    fireEvent.click(btn);
    fireEvent.keyDown(screen.getByRole("region", { name: "Sources for CPI" }), {
      key: "Escape",
    });
    expect(screen.queryByRole("region", { name: "Sources for CPI" })).toBeNull();
    expect(document.activeElement).toBe(btn);
  });

  it("renders a dash and no button when no source is recorded", () => {
    render(<ProvenanceButton sources={[]} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByLabelText("No source recorded").textContent).toBe("—");
  });
});
