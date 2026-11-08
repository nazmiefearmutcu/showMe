/**
 * DEBT pane — country filter (P2A-G07 DEBT#4).
 *
 * The backend accepts a `countries` input (ISO-2, comma separated). The pane
 * must expose it: a valid filter is sent, an invalid code is refused without
 * a request, and "All" clears the filter back to the backend default.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DEBTPane } from "./DEBT";

const hoisted = vi.hoisted(() => ({
  calls: [] as Array<{ params?: Record<string, unknown> }>,
}));

vi.mock("@/lib/useFunction", () => ({
  useFunction: (opts: { params?: Record<string, unknown> }) => {
    hoisted.calls.push(opts);
    return { state: "idle", data: undefined, error: null, refetch: vi.fn() };
  },
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => 0,
}));

beforeEach(() => {
  hoisted.calls.length = 0;
});

afterEach(() => {
  cleanup();
});

function lastParams(): Record<string, unknown> | undefined {
  return hoisted.calls[hoisted.calls.length - 1]?.params;
}

function filterInput(): HTMLInputElement {
  return screen.getByLabelText("Country filter (ISO-2 codes)") as HTMLInputElement;
}

describe("DEBT pane — country filter", () => {
  it("sends no countries param until a filter is applied", () => {
    render(<DEBTPane code="DEBT" />);
    expect(lastParams()?.countries).toBeUndefined();
  });

  it("sends normalised ISO-2 codes for a valid filter", () => {
    render(<DEBTPane code="DEBT" />);
    fireEvent.change(filterInput(), { target: { value: "us, de  us" } });
    fireEvent.submit(filterInput().closest("form") as HTMLFormElement);
    expect(lastParams()).toEqual({ countries: "US,DE" });
  });

  it("refuses an invalid code and does not change the request", () => {
    render(<DEBTPane code="DEBT" />);
    fireEvent.change(filterInput(), { target: { value: "USA1" } });
    fireEvent.submit(filterInput().closest("form") as HTMLFormElement);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Not valid: USA1");
    expect(lastParams()?.countries).toBeUndefined();
  });

  it("clears back to all countries", () => {
    render(<DEBTPane code="DEBT" />);
    fireEvent.change(filterInput(), { target: { value: "JP" } });
    fireEvent.submit(filterInput().closest("form") as HTMLFormElement);
    expect(lastParams()).toEqual({ countries: "JP" });
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(lastParams()?.countries).toBeUndefined();
    expect(filterInput().value).toBe("");
  });
});
