/**
 * ISIN pane — ID type selector (P2A-G07 ISIN#5).
 *
 * The backend reads `id_type` to force the identifier flavour. The pane must
 * expose that choice and send it; AUTO sends nothing so detection stays on.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ISINPane } from "./ISIN";

const hoisted = vi.hoisted(() => ({
  calls: [] as Array<{ params?: Record<string, unknown> }>,
}));

vi.mock("@/lib/useFunction", () => ({
  useFunction: (opts: { params?: Record<string, unknown> }) => {
    hoisted.calls.push(opts);
    return { state: "idle", data: undefined, error: null, refetch: vi.fn() };
  },
}));

beforeEach(() => {
  hoisted.calls.length = 0;
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  localStorage.clear();
});

function lastParams(): Record<string, unknown> | undefined {
  return hoisted.calls[hoisted.calls.length - 1]?.params;
}

describe("ISIN pane — ID type selector", () => {
  it("offers Auto plus each forced identifier type", () => {
    render(<ISINPane code="ISIN" symbol="US0378331005" />);
    const select = screen.getByLabelText("Identifier type") as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(["AUTO", "ID_ISIN", "ID_CUSIP", "ID_SEDOL", "TICKER"]);
    expect(select.value).toBe("AUTO");
  });

  it("sends only ids while the type is AUTO so detection stays on", () => {
    render(<ISINPane code="ISIN" symbol="US0378331005" />);
    expect(lastParams()).toEqual({ ids: "US0378331005" });
  });

  it("sends the chosen id_type to the backend", () => {
    render(<ISINPane code="ISIN" symbol="037833100" />);
    const select = screen.getByLabelText("Identifier type");
    fireEvent.change(select, { target: { value: "ID_CUSIP" } });
    expect(lastParams()).toEqual({ ids: "037833100", id_type: "ID_CUSIP" });
  });

  it("returns to auto detection when Auto is selected again", () => {
    render(<ISINPane code="ISIN" symbol="AAPL" />);
    const select = screen.getByLabelText("Identifier type");
    fireEvent.change(select, { target: { value: "TICKER" } });
    fireEvent.change(select, { target: { value: "AUTO" } });
    expect(lastParams()).toEqual({ ids: "AAPL" });
  });
});
