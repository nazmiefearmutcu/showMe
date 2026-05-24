/**
 * NI smoke test — Agent J test-coverage initiative.
 *
 * Catches import/render regressions in `<NIPane/>`. Mocks the network
 * surface (`runFunction`, `useAppStore`, veryfinder) so the news
 * effect can short-circuit on mount. Pins: mounting renders without
 * throwing.
 */
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/functions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/functions")>();
  return {
    ...actual,
    runFunction: vi.fn(async () => ({ status: "ok", data: { articles: [] }, sources: [] })),
  };
});

vi.mock("@/lib/store", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/store")>();
  return {
    ...actual,
    useAppStore: ((selector: (s: { sidecarPort: number | null; sidecarStatus: string; functionIndex: unknown[] }) => unknown) =>
      selector({ sidecarPort: 8421, sidecarStatus: "healthy", functionIndex: [] })) as never,
  };
});

vi.mock("@/lib/tauri", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/tauri")>();
  return {
    ...actual,
    isInTauri: () => false,
    invoke: vi.fn(),
  };
});

vi.mock("@/lib/veryfinder", () => ({
  fetchVeryfinderBatch: vi.fn(async () => ({})),
  recommendedVeryfinderSampleForNews: () => [],
}));

import { NIPane } from "./NI";

afterEach(() => cleanup());

describe("NI smoke", () => {
  it("mounts without throwing", () => {
    const { container } = render(<NIPane code="NI" />);
    expect(container.firstChild).not.toBeNull();
  });
});
