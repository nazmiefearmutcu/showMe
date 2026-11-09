/**
 * UI-15 — HeatCell null contract.
 *
 * A missing matrix cell is `value = null`. It must not be presented as a zero
 * correlation: no zero value in the default aria-label, no tint, and the
 * caller's label is shown as-is.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { HeatCell } from "./HeatCell";

afterEach(() => {
  cleanup();
});

describe("HeatCell missing value", () => {
  it("does not announce a missing cell as value 0.00 when no ariaLabel is given", () => {
    render(<HeatCell value={null} label="—" />);
    const cell = screen.getByRole("button");
    expect(cell.getAttribute("aria-label")).toBe("no value");
    expect(cell.getAttribute("aria-label")).not.toContain("0.00");
  });

  it("renders no heat tint for a missing value", () => {
    render(<HeatCell value={null} label="—" />);
    const cell = screen.getByRole("button");
    expect(cell.style.background).toBe("transparent");
    expect(cell.textContent).toBe("—");
  });

  it("still renders a real zero as value 0.00", () => {
    render(<HeatCell value={0} />);
    expect(screen.getByRole("button").getAttribute("aria-label")).toBe("value 0.00");
  });
});
