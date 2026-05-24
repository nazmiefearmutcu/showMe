/**
 * QA-2026-05-24 fix — the Appearance theme-preview mock must NOT ship
 * hand-authored figures that look like real portfolio data. The
 * pre-fix preview rendered `DOGEUSDT $86,617` and a `$590,397`
 * portfolio total verbatim, which leaked into demo screenshots and
 * fooled QA into thinking the bot had taken positions.
 *
 * The replacement uses neutral, clearly-labeled placeholders
 * (`EXAMPLE ASSET-1` etc.) with round mock totals.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { AppearanceSection } from "../preferences_pane/appearance";
import type { ThemeState } from "@/lib/theme";

vi.mock("@/i18n", () => ({
  t: (key: string) => key,
  listLocales: () => ["en"],
}));

vi.mock("@/lib/timezone", async () => {
  const actual = await vi.importActual<typeof import("@/lib/timezone")>(
    "@/lib/timezone",
  );
  return {
    ...actual,
    useTimezone: () => "UTC",
    useTimezoneMode: () => "auto",
    listAllTimezones: () => ["UTC"],
    getSystemTimezone: () => "UTC",
    readManualTimezone: () => "UTC",
  };
});

vi.mock("@/lib/theme", async () => {
  const actual = await vi.importActual<typeof import("@/lib/theme")>(
    "@/lib/theme",
  );
  return actual;
});

const baseState: ThemeState = {
  preset: "midnight",
  custom: { bg: "#0a0d12", surface: "#101620", accent: "#42d6a4" },
  density: "comfortable",
};

const noop = () => {};

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  localStorage.clear();
});

describe("AppearanceSection — theme preview mock cleanliness", () => {
  it("never renders the legacy DOGEUSDT $86,617 / $590,397 / 51-positions strings", () => {
    const { container } = render(
      <AppearanceSection
        state={baseState}
        density="comfortable"
        locale="en"
        onPreset={noop}
        onCustom={noop}
        onDensity={noop}
        onLocale={noop}
      />,
    );
    const text = container.textContent ?? "";
    expect(text).not.toContain("DOGEUSDT");
    expect(text).not.toContain("$86,617");
    expect(text).not.toContain("$590,397");
    expect(text).not.toContain("-$704");
    expect(text).not.toContain("-$211");
    // The replacement values that ARE expected:
    expect(text).toContain("EXAMPLE ASSET-1");
    expect(text).toContain("EXAMPLE ASSET-2");
    expect(text).toContain("$10,000");
  });

  it("marks the preview strip with data-preview='mock' for screenshot audits", () => {
    const { container } = render(
      <AppearanceSection
        state={baseState}
        density="comfortable"
        locale="en"
        onPreset={noop}
        onCustom={noop}
        onDensity={noop}
        onLocale={noop}
      />,
    );
    const preview = container.querySelector(
      '[data-preview="mock"]',
    ) as HTMLElement | null;
    expect(preview, "preview strip annotated with data-preview='mock'").toBeTruthy();
  });
});
