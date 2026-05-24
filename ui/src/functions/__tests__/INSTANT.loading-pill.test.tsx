/**
 * Bug #10d — INSTANT default-state red pill regression.
 *
 * Before the fix the header showed `UNAVAILABLE` (negative tone) during the
 * initial fetch even though the backend returns ~100 events within ~150ms.
 * Now the first paint must use a neutral `loading` pill, and the negative
 * `unavailable` pill is only allowed AFTER the first fetch resolves with no
 * usable transport.
 */
import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { INSTANTPane } from "../INSTANT";
import * as instant from "@/lib/instant";
import * as xai from "@/lib/xai";

vi.mock("@/lib/timezone", () => ({
  readTimezone: () => "UTC",
}));

vi.mock("@/lib/xinject", () => ({
  useXInjectStore: {
    getState: () => ({ consumeInjection: () => null }),
  },
}));

beforeEach(() => {
  // X-inject merge fetch isn't relevant — short-circuit it.
  vi.spyOn(xai, "fetchXInstantEvents").mockResolvedValue({ events: [] } as never);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function pillLabels(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll(".ds-pill__label")).map(
    (el) => el.textContent?.trim() ?? "",
  );
}

describe("INSTANT pre-fetch pill — Bug #10d", () => {
  it("paints a neutral 'loading' pill before the first fetch resolves", () => {
    // Never-resolving promises simulate the initial-fetch window.
    vi.spyOn(instant, "fetchInstantStatus").mockReturnValue(new Promise(() => {}));
    vi.spyOn(instant, "fetchInstantEvents").mockReturnValue(new Promise(() => {}));

    const { container } = render(<INSTANTPane code="INSTANT" symbol={undefined} />);
    const labels = pillLabels(container);

    expect(labels).toContain("loading");
    expect(labels).not.toContain("unavailable");
  });

  it("flips to 'live' once a healthy status resolves", async () => {
    vi.spyOn(instant, "fetchInstantStatus").mockResolvedValue({
      ok: true,
      mode: "secondary",
      primary: false,
      transport: "http",
      health: {
        metrics: { total_events: 50, newest_fetched_at: new Date().toISOString() },
        sources: [],
      },
    } as never);
    vi.spyOn(instant, "fetchInstantEvents").mockResolvedValue({
      events: [],
    } as never);

    const { container } = render(<INSTANTPane code="INSTANT" symbol={undefined} />);

    await waitFor(() => {
      expect(pillLabels(container)).toContain("live");
    });
    expect(pillLabels(container)).not.toContain("loading");
  });

  it("only paints 'unavailable' AFTER the first fetch resolves with no transport", async () => {
    vi.spyOn(instant, "fetchInstantStatus").mockResolvedValue({
      ok: false,
      mode: "secondary",
      primary: false,
      transport: "unavailable",
      health: { metrics: {}, sources: [] },
    } as never);
    vi.spyOn(instant, "fetchInstantEvents").mockResolvedValue({
      events: [],
    } as never);

    const { container } = render(<INSTANTPane code="INSTANT" symbol={undefined} />);

    await waitFor(() => {
      expect(pillLabels(container)).toContain("unavailable");
    });
    expect(pillLabels(container)).not.toContain("loading");
  });
});
