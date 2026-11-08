/**
 * AV pane — request shape.
 *
 * The pane must send an explicit `limit` so the shared agent default of 6
 * does not silently cap the archive list (AV#3). Kept in its own file so
 * the existing AV.test.tsx stays unchanged.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { AVPane } from "./AV";

const calls: Array<{ code: string; params?: Record<string, unknown> }> = [];

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { code: string; params?: Record<string, unknown> }) => {
    calls.push(args);
    return {
      state: "ok",
      data: { data: { status: "empty", symbol: "AAPL", count: 0, rows: [] } },
      error: null,
      refetch: vi.fn(),
    };
  },
}));

afterEach(() => {
  cleanup();
  calls.length = 0;
});

describe("AV pane — request shape", () => {
  it("asks for an explicit limit so the agent default of 6 does not cap the archive", () => {
    render(<AVPane code="AV" symbol="AAPL" />);
    const last = calls[calls.length - 1];
    expect(last.code).toBe("AV");
    expect(last.params?.limit).toBe(25);
  });
});
