/**
 * FLY pane — request-parameter honesty (FLY#1).
 *
 * The backend handler never reads a `live_flight` flag: aircraft come from the
 * OpenSky feed unless `reference=true`. The pane must not send, or claim, a
 * flag that does nothing, so its useFunction params carry only real inputs.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { FLYPane } from "./FLY";

const captured = vi.hoisted(() => ({
  params: undefined as Record<string, unknown> | undefined,
}));

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { params?: Record<string, unknown> }) => {
    captured.params = args.params;
    return { state: "idle", data: undefined, error: null, refetch: vi.fn() };
  },
}));

afterEach(() => {
  cleanup();
  captured.params = undefined;
});

describe("FLY request params", () => {
  it("does not send a live_flight flag the backend ignores", () => {
    render(<FLYPane code="FLY" />);
    expect(captured.params).toBeDefined();
    expect(captured.params).not.toHaveProperty("live_flight");
  });
});
