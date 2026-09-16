/**
 * Owner report (2026-09-16): "settings nerede" — the utility segment (the
 * only visible /preferences link) hides on narrow windows, so the titlebar
 * must carry an always-visible settings entry point next to the palette.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Titlebar } from "./Titlebar";
import { useAppStore } from "@/lib/store";
import { useWorkspace, leaf } from "@/lib/workspace";
import { setActiveSecurity } from "@/lib/security-context";
import { setLocale } from "@/i18n";

vi.mock("@/lib/tauri", () => ({
  invoke: vi.fn(async () => undefined),
  listen: vi.fn(async () => () => undefined),
}));

beforeEach(() => {
  window.location.hash = "#/";
  setLocale("en");
  useAppStore.setState({
    paletteOpen: false,
    shortcutsOpen: false,
    sidebarVisible: false,
    functionIndex: [],
    sidecarStatus: "healthy",
  });
  useWorkspace.setState({ tree: { ...leaf("HOME"), id: "L1" }, focusedId: "L1" });
  setActiveSecurity(null);
});

afterEach(() => {
  cleanup();
});

describe("Titlebar settings entry point", () => {
  it("renders a settings button in the palette segment and routes to /preferences", () => {
    render(<Titlebar />);
    const settings = screen.getByTestId("titlebar-settings");
    expect(settings).toBeInTheDocument();
    fireEvent.click(settings);
    expect(window.location.hash).toBe("#/preferences");
  });
});
