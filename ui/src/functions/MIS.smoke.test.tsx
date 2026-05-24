/**
 * MIS smoke test — Agent J test-coverage initiative.
 *
 * Catches import/render regressions in `<MISPane/>`. Mocks the
 * `@/lib/mis` boot fetches so the component reaches its initial
 * "results" tab without hitting the network. The contract this file
 * pins: mounting renders the Sonuçlar (Results) tab header.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/mis", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/mis")>();
  return {
    ...actual,
    fetchMisMarkets: vi.fn(async () => ({ markets: [] })),
    fetchMisIndicators: vi.fn(async () => []),
    fetchMisConfig: vi.fn(async () => null),
    fetchMisScanProgress: vi.fn(async () => null),
    runMisScan: vi.fn(),
    saveMisConfig: vi.fn(),
  };
});

import { MISPane } from "./MIS";

afterEach(() => cleanup());

describe("MIS smoke", () => {
  it("mounts and renders the Sonuçlar (Results) tab", () => {
    render(<MISPane code="MIS" />);
    // The tab strip ships "Sonuçlar" + "Ayarlar"; either confirms mount.
    expect(screen.getAllByText(/Sonu[çc]lar/i).length).toBeGreaterThanOrEqual(1);
  });
});
