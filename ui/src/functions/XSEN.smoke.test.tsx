/**
 * XSEN smoke test — Agent J test-coverage initiative.
 *
 * Catches import/render regressions in `<XSENPane/>`. Mocks the
 * `@/lib/xai` health probe so the component doesn't reach for the
 * network on mount. Contract: mounting renders without throwing AND
 * the default query "AAPL" is wired into the search input.
 */
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/xai", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/xai")>();
  return {
    ...actual,
    fetchXHealth: vi.fn(async () => ({
      ok: false,
      model_loaded: false,
      model_dir: null,
      load_error: "test-mode",
      scraper: {
        backends: { guest_token: false, nitter_pool_size: 0, jina_proxy: false },
        guest_token_present: false,
        nitter_mirrors_active: [],
      },
    })),
    analyzeXTopic: vi.fn(),
  };
});

import { XSENPane } from "./XSEN";

afterEach(() => cleanup());

describe("XSEN smoke", () => {
  it("mounts and seeds the default AAPL query", () => {
    const { container } = render(<XSENPane code="XSEN" />);
    expect(container.firstChild).not.toBeNull();
    // Initial draftQuery default is "AAPL"; surfaced via a text input.
    const aaplInput = container.querySelector('input[value="AAPL"]');
    expect(aaplInput).not.toBeNull();
  });
});
