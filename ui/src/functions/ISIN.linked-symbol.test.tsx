/**
 * UI-7: the ISIN pane follows the linked symbol.
 *
 * The lookup and search box were seeded only in useState initialisers, so a
 * link change from AAPL to MSFT left the previous lookup and results in place.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { ISINPane } from "./ISIN";

vi.mock("@/lib/useFunction", () => ({
  useFunction: vi.fn(),
}));

import { useFunction } from "@/lib/useFunction";

beforeEach(() => {
  vi.mocked(useFunction).mockReturnValue({
    state: "idle",
    data: undefined,
    error: null,
    refetch: () => {},
  } as unknown as ReturnType<typeof useFunction>);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function lastParams(): { ids?: unknown } {
  const calls = vi.mocked(useFunction).mock.calls;
  return (calls[calls.length - 1][0] as { params: { ids?: unknown } }).params;
}

describe("ISINPane linked symbol", () => {
  it("looks up the new symbol and shows it in the search box after the link changes", () => {
    const { rerender, container } = render(<ISINPane code="ISIN" symbol="AAPL" />);
    expect(lastParams().ids).toBe("AAPL");

    rerender(<ISINPane code="ISIN" symbol="MSFT" />);

    expect(lastParams().ids).toBe("MSFT");
    expect((container.querySelector("input") as HTMLInputElement).value).toBe("MSFT");
  });
});
