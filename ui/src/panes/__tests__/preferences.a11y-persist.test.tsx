/**
 * PREF a11y + persistence (UI-INT-PREF) — guards three things:
 *  1. mutually-exclusive button groups expose proper radiogroup/radio +
 *     aria-checked semantics (density + migration mode covered here);
 *  2. icon/symbol-only buttons carry an aria-label (secrets delete,
 *     copy-hex, llm/streams refresh);
 *  3. MigrationSection persists the engine path + mode to localStorage and
 *     restores them on remount, and the custom-colors Reset resets to the
 *     HOME preset (papyrus) — not always midnight.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { AppearanceSection } from "../preferences_pane/appearance";
import { MigrationSection } from "../preferences_pane/migration";
import { useAppStore } from "@/lib/store";
import type { Preset, ThemeState } from "@/lib/theme";

vi.mock("@/i18n", () => ({
  t: (key: string) => key,
  listLocales: () => ["en", "tr"],
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

vi.mock("@/lib/tauri", () => ({
  invoke: vi.fn(async () => ({
    source: "src",
    target: "dst",
    positions_imported: 0,
    positions_skipped: 0,
    trades_imported: 0,
    trades_skipped: 0,
    mode: "read-only",
    warnings: [],
  })),
  isInTauri: () => false,
}));

const baseState: ThemeState = {
  preset: "papyrus",
  custom: { bg: "#ece6d6", surface: "#faf5e3", accent: "#8a5a1f" },
  density: "comfortable",
};

const noop = () => {};

beforeEach(() => {
  localStorage.clear();
  useAppStore.setState({
    sidecarStatus: "booting",
    sidecarPort: null,
    engineRoot: null,
    functionIndex: [],
  });
});

afterEach(() => {
  cleanup();
});

function renderAppearance(overrides: Partial<Parameters<typeof AppearanceSection>[0]> = {}) {
  return render(
    <AppearanceSection
      state={baseState}
      density="comfortable"
      locale="en"
      onPreset={noop}
      onCustom={noop}
      onDensity={noop}
      onLocale={noop}
      {...overrides}
    />,
  );
}

describe("PREF a11y — radiogroup/radio semantics", () => {
  it("density group exposes role=radiogroup with role=radio + aria-checked", () => {
    const { getByRole } = renderAppearance();
    const group = getByRole("radiogroup", { name: /density/i });
    const radios = group.querySelectorAll('[role="radio"]');
    expect(radios.length).toBe(2);
    // comfortable is selected here
    const checked = group.querySelectorAll('[role="radio"][aria-checked="true"]');
    expect(checked.length).toBe(1);
  });

  it("language picker is a radiogroup of radios", () => {
    const { getByRole } = renderAppearance();
    const group = getByRole("radiogroup", { name: /language/i });
    expect(group.querySelectorAll('[role="radio"]').length).toBeGreaterThanOrEqual(2);
    expect(
      group.querySelectorAll('[role="radio"][aria-checked="true"]').length,
    ).toBe(1);
  });

  it("preset thumbnails expose aria-pressed and an accessible name", () => {
    const { container } = renderAppearance();
    const thumbs = container.querySelectorAll(
      ".prefs-preset-grid button[aria-pressed]",
    );
    expect(thumbs.length).toBeGreaterThanOrEqual(6);
    // Each thumb has a non-empty accessible name (visible label text).
    thumbs.forEach((t) => expect((t.textContent ?? "").trim().length).toBeGreaterThan(0));
  });

  it("copy-hex buttons have an aria-label", () => {
    const { getAllByLabelText } = renderAppearance();
    expect(getAllByLabelText(/copy hex/i).length).toBeGreaterThanOrEqual(1);
  });

  it("migration mode group exposes radiogroup/radio + aria-checked", () => {
    const { getByRole } = render(<MigrationSection />);
    const group = getByRole("radiogroup", { name: /mode/i });
    const radios = group.querySelectorAll('[role="radio"]');
    expect(radios.length).toBe(2);
    // read-only mirror is the default-selected option
    const checked = group.querySelector('[role="radio"][aria-checked="true"]');
    expect(checked).toBeTruthy();
    expect(checked!.textContent).toMatch(/read-only/i);
  });
});

describe("PREF bug — custom-colors Reset returns to the HOME preset, not midnight", () => {
  it("resets to the current non-custom preset (papyrus)", () => {
    const onPreset = vi.fn();
    renderAppearance({
      state: { ...baseState, preset: "papyrus" },
      onPreset,
    });
    // The reset button is the trailing ghost button in the custom-colors card.
    const resetBtn = document.querySelector(
      ".prefs-reset-btn",
    ) as HTMLButtonElement;
    expect(resetBtn).toBeTruthy();
    fireEvent.click(resetBtn);
    expect(onPreset).toHaveBeenCalledWith("papyrus");
    expect(onPreset).not.toHaveBeenCalledWith("midnight");
  });

  it("falls back to papyrus when current preset is custom", () => {
    const onPreset = vi.fn();
    renderAppearance({
      state: {
        ...baseState,
        preset: "custom" as Preset,
      },
      onPreset,
    });
    const resetBtn = document.querySelector(
      ".prefs-reset-btn",
    ) as HTMLButtonElement;
    fireEvent.click(resetBtn);
    expect(onPreset).toHaveBeenCalledWith("papyrus");
  });
});

describe("PREF persistence — migration path + mode round-trip localStorage", () => {
  it("persists the typed engine path and restores it on remount", async () => {
    const first = render(<MigrationSection />);
    const input = first.container.querySelector("input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "/opt/custom/engine" } });
    await waitFor(() => {
      expect(localStorage.getItem("showme.migration.lastPath.v1")).toBe(
        "/opt/custom/engine",
      );
    });
    first.unmount();

    const second = render(<MigrationSection />);
    const input2 = second.container.querySelector("input") as HTMLInputElement;
    expect(input2.value).toBe("/opt/custom/engine");
  });

  it("persists the writable mode toggle and restores it on remount", async () => {
    const first = render(<MigrationSection />);
    const writableBtn = [...first.container.querySelectorAll("[role=radio]")].find(
      (b) => /writable/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement;
    fireEvent.click(writableBtn);
    await waitFor(() => {
      expect(localStorage.getItem("showme.migration.mode.v1")).toBe("writable");
    });
    first.unmount();

    const second = render(<MigrationSection />);
    const checked = second.container.querySelector(
      '[role="radio"][aria-checked="true"]',
    );
    expect(checked!.textContent).toMatch(/writable/i);
  });

  it("a persisted path takes precedence over engineRoot auto-fill", async () => {
    localStorage.setItem("showme.migration.lastPath.v1", "/persisted/path");
    const { container } = render(<MigrationSection />);
    // engineRoot arrives after mount; persisted value should win
    useAppStore.setState({ engineRoot: "/opt/showme/engine" });
    await waitFor(() => {
      const input = container.querySelector("input") as HTMLInputElement;
      expect(input.value).toBe("/persisted/path");
    });
  });
});
