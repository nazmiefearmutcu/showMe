/**
 * BRIEF pane — only the route's own timeout reason is warming (BRIEF#4 follow-up).
 *
 * A provider exception that merely contains the words "timed out" (for example an
 * httpx ReadTimeout escaping BRIEF.execute) is a real failure: the pane shows the
 * honest empty state and never auto-retries. Only "function timed out after <N>s"
 * from the route, and an explicit warming reason, count as warming.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { BRIEFPane } from "./BRIEF";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
  refetch: ReturnType<typeof vi.fn>;
}

const mockFn: MockFnState = {
  state: "idle",
  data: undefined,
  error: null,
  refetch: vi.fn(),
};

function setMockFn(next: Partial<MockFnState>) {
  mockFn.state = next.state ?? "idle";
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
  mockFn.refetch = next.refetch ?? vi.fn();
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: mockFn.refetch,
  }),
}));

vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

/** The useFunction envelope: the pane reads `data.data` as the BRIEF payload. */
function envelope(inner: Record<string, unknown>) {
  return { sources: [], elapsed_ms: 1070, data: inner };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe("BRIEF pane — timeout reasons (BRIEF#4 follow-up)", () => {
  it("does not treat a provider exception that says 'timed out' as warming", () => {
    vi.useFakeTimers();
    const refetch = vi.fn();
    setMockFn({
      state: "ok",
      refetch,
      data: envelope({
        status: "provider_unavailable",
        articles: [],
        reason: "The read operation timed out",
      }),
    });
    render(<BRIEFPane code="BRIEF" />);
    expect(screen.queryByText(/Briefing is warming up/i)).toBeNull();
    expect(screen.getByText(/No briefing returned/i)).toBeInTheDocument();
    vi.advanceTimersByTime(30000);
    expect(refetch).not.toHaveBeenCalled();
  });

  it("treats the route's own timeout reason as warming", () => {
    vi.useFakeTimers();
    const refetch = vi.fn();
    setMockFn({
      state: "ok",
      refetch,
      data: envelope({
        status: "provider_unavailable",
        articles: [],
        reason: "function timed out after 25s",
      }),
    });
    render(<BRIEFPane code="BRIEF" />);
    expect(screen.getByText(/Briefing is warming up/i)).toBeInTheDocument();
  });
});
