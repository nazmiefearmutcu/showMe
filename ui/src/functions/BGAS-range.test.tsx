/**
 * BGAS pane — request-shape tests for the history window.
 *
 * The backend reads the advertised `range` (1M/3M/6M/1Y) and prefers it over
 * the router-injected `days` default. The pane therefore must send `range`
 * (and no `days`) for BGAS, and keep the legacy `days` window for BOIL.
 *
 * `useFunction` is mocked so the test can read the params the pane sends.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { BGASPane } from "./BGAS";
import { BOILPane } from "./BOIL";

const calls: Array<{ code: string; params: Record<string, unknown> }> = [];

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { code: string; params: Record<string, unknown> }) => {
    calls.push({ code: args.code, params: args.params });
    return { state: "idle", data: undefined, error: null, refetch: vi.fn() };
  },
}));

beforeEach(() => {
  localStorage.clear();
  calls.length = 0;
});
afterEach(() => {
  cleanup();
});

describe("BGAS pane — history window request", () => {
  it("sends range (not days) with the 1Y default", () => {
    render(<BGASPane code="BGAS" symbol="NG=F" />);
    const last = calls[calls.length - 1];
    expect(last.code).toBe("BGAS");
    expect(last.params.range).toBe("1Y");
    expect(last.params).not.toHaveProperty("days");
    expect(last.params.live).toBe(true);
  });

  it("re-requests with the selected range when the user picks 3m", () => {
    render(<BGASPane code="BGAS" symbol="NG=F" />);
    const group = screen.getByLabelText("HISTORY");
    const opt3m = group.querySelector('button[title="HISTORY 3m"]');
    expect(opt3m).not.toBeNull();
    fireEvent.click(opt3m as Element);
    const last = calls[calls.length - 1];
    expect(last.params.range).toBe("3M");
    expect(last.params).not.toHaveProperty("days");
  });
});

describe("BOIL pane — legacy days window is unchanged", () => {
  it("still sends days for BOIL", () => {
    render(<BOILPane code="BOIL" symbol="CL=F" />);
    const last = calls[calls.length - 1];
    expect(last.code).toBe("BOIL");
    expect(last.params.days).toBe(365);
    expect(last.params).not.toHaveProperty("range");
  });
});
