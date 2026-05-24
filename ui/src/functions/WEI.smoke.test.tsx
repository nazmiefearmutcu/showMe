/**
 * WEI smoke test — Agent J test-coverage initiative.
 *
 * Catches import/render regressions in `<WEIPane/>`. Mocks
 * `useFunction` so the indices fetch doesn't fire on mount. Pins:
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

import { WEIPane } from "./WEI";

afterEach(() => cleanup());

describe("WEI smoke", () => {
  it("mounts without throwing", () => {
    const { container } = render(<WEIPane code="WEI" />);
    expect(container.firstChild).not.toBeNull();
  });
});
