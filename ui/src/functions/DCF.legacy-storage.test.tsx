/**
 * DCF pane — legacy persisted placeholders must not become overrides.
 *
 * The pre-fix pane wrote its placeholder defaults (FCFE 10000, shares 15000)
 * to `showme.dcf.fcfe` / `showme.dcf.shares` on mount. Those values were never
 * typed by the user, so a profile holding them must send no FCFE or shares and
 * let the provider supply the base (FCFE/shares overrides now use
 * `showme.dcf.fcfe_override` / `showme.dcf.shares_override`).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { DCFPane } from "./DCF";

let lastParams: Record<string, unknown> | undefined;

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { params?: Record<string, unknown> }) => {
    lastParams = args.params;
    return { state: "idle", data: undefined, error: null, refetch: vi.fn() };
  },
}));

beforeEach(() => {
  localStorage.clear();
  lastParams = undefined;
});
afterEach(() => {
  cleanup();
});

describe("DCF pane — legacy storage", () => {
  it("does not send the legacy placeholder FCFE and shares as overrides", () => {
    localStorage.setItem("showme.dcf.fcfe", "10000");
    localStorage.setItem("showme.dcf.shares", "15000");
    render(<DCFPane code="DCF" symbol="AAPL" />);
    expect(lastParams).not.toHaveProperty("fcfe");
    expect(lastParams).not.toHaveProperty("shares_outstanding");
  });

  it("still sends an override the user typed under the new key", () => {
    localStorage.setItem("showme.dcf.fcfe", "10000");
    localStorage.setItem("showme.dcf.fcfe_override", "12000");
    render(<DCFPane code="DCF" symbol="AAPL" />);
    expect(lastParams?.fcfe).toBe(12e9);
    expect(lastParams).not.toHaveProperty("shares_outstanding");
  });
});
