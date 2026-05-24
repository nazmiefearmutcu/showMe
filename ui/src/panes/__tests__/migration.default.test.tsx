/**
 * QA-2026-05-24 fix — MigrationSection must not prefill a hardcoded
 * developer-machine path. Pre-fix default was
 * `/Users/nazmi/Desktop/Projeler/proje/showMe/engine`, which silently
 * leaked Nazmi's home directory into demo screenshots and was an
 * unusable no-op on every other machine. Default now starts empty
 * and the placeholder reads `~/path/to/legacy/data`; the canonical
 * `engineRoot` from the app store fills in once the sidecar boots.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, waitFor } from "@testing-library/react";
import { MigrationSection } from "../preferences_pane/migration";
import { useAppStore } from "@/lib/store";

vi.mock("@/lib/tauri", () => ({
  invoke: vi.fn(async () => ({
    positions_imported: 0,
    trades_imported: 0,
  })),
  isInTauri: () => false,
}));

beforeEach(() => {
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

describe("MigrationSection — engine-path default is not a hardcoded /Users/nazmi/ value", () => {
  it("renders an empty engine-path field by default", () => {
    const { container } = render(<MigrationSection />);
    const field = container.querySelector(
      'input[placeholder="~/path/to/legacy/data"]',
    ) as HTMLInputElement | null;
    expect(field, "engine path input present with new placeholder").toBeTruthy();
    expect(field!.value).toBe("");
  });

  it("placeholder is the generic `~/path/to/legacy/data` prompt, never a real Mac home", () => {
    const { container } = render(<MigrationSection />);
    const input = container.querySelector(
      "input",
    ) as HTMLInputElement | null;
    expect(input!.placeholder).toBe("~/path/to/legacy/data");
    expect(input!.placeholder).not.toContain("/Users/");
    expect(input!.value).not.toContain("/Users/nazmi");
  });

  it("populates from the app store's engineRoot once the sidecar reports one", async () => {
    const { container } = render(<MigrationSection />);
    useAppStore.setState({ engineRoot: "/opt/showme/engine" });
    await waitFor(() => {
      const input = container.querySelector("input") as HTMLInputElement;
      expect(input.value).toBe("/opt/showme/engine");
    });
  });
});
