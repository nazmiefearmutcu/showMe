/**
 * BTMM smoke test — Agent J test-coverage initiative.
 *
 * Catches import/render regressions in `<BTMMPane/>`. Mocks
 * `useFunction` so the BIS CBPOL probe doesn't fire on mount. Pins:
 * mounting renders without throwing.
 */
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: "idle",
    data: undefined,
    error: undefined,
    refetch: vi.fn(),
  }),
}));

import { BTMMPane } from "./BTMM";

afterEach(() => cleanup());

describe("BTMM smoke", () => {
  it("mounts without throwing", () => {
    const { container } = render(<BTMMPane code="BTMM" />);
    expect(container.firstChild).not.toBeNull();
  });
});
