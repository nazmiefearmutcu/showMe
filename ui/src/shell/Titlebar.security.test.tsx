/**
 * L3 (campaign 2026-09-11) — titlebar truth.
 *
 * H2: the "active security" chip was hardcoded `AAPL / US Equity` and never
 * followed the focused pane. M1: the session pill was a static NYSE-only
 * "MK" string. These tests pin the focused-pane binding, the security
 * context push, and the per-venue session pill.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, renderHook, screen } from "@testing-library/react";
import { Titlebar } from "./Titlebar";
import { useAppStore } from "@/lib/store";
import { leaf, useWorkspace } from "@/lib/workspace";
import { setActiveSecurity, useSecurityContext } from "@/lib/security-context";
import { setLocale } from "@/i18n";

// Tauri invoke is a no-op in jsdom.
vi.mock("@/lib/tauri", () => ({
  invoke: vi.fn(async () => undefined),
  listen: vi.fn(async () => () => undefined),
}));

function focusLeaf(code: string, symbol?: string): void {
  const node = { ...leaf(code, symbol), id: "L1" };
  useWorkspace.setState({ tree: node, focusedId: "L1" });
}

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
  setActiveSecurity(null);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Titlebar — active security chip (H2)", () => {
  it("follows the focused pane symbol and asset class", () => {
    focusLeaf("DES", "AAPL");
    render(<Titlebar />);
    expect(screen.getByTestId("titlebar-security-symbol").textContent).toBe("AAPL");
    expect(screen.getByTestId("titlebar-security-class").textContent).toBe("US Equity");
  });

  it("pushes the focused security into the desk-wide security context", () => {
    focusLeaf("DES", "AAPL");
    render(<Titlebar />);
    const { result } = renderHook(() => useSecurityContext());
    expect(result.current.active).toEqual({
      symbol: "AAPL",
      label: "US Equity",
      assetClass: "EQUITY",
    });
  });

  it("updates live when the focused pane's symbol changes", () => {
    focusLeaf("DES", "AAPL");
    render(<Titlebar />);
    act(() => {
      useWorkspace.getState().setFocusedTarget("DES", "BTCUSDT");
    });
    expect(screen.getByTestId("titlebar-security-symbol").textContent).toBe("BTCUSDT");
    expect(screen.getByTestId("titlebar-security-class").textContent).toBe("Crypto");
    const { result } = renderHook(() => useSecurityContext());
    expect(result.current.active?.assetClass).toBe("CRYPTO");
  });

  it("clears to a neutral placeholder when the focused pane has no symbol", () => {
    focusLeaf("HOME");
    render(<Titlebar />);
    expect(screen.getByTestId("titlebar-security-symbol").textContent).toBe("—");
    const { result } = renderHook(() => useSecurityContext());
    expect(result.current.active).toBeNull();
  });

  it("hint text points at the command line, not the retired '/ to focus'", () => {
    focusLeaf("HOME");
    render(<Titlebar />);
    const chip = screen.getByTestId("titlebar-security-chip");
    expect(chip.textContent).toContain("/ command");
    expect(chip.textContent).not.toContain("/ to focus");
  });
});

describe("Titlebar — market session pill (M1)", () => {
  it("crypto security shows the 24/7 pill", () => {
    focusLeaf("MICRO", "BTCUSDT");
    render(<Titlebar />);
    const pill = screen.getByTestId("titlebar-market-pill");
    expect(pill.getAttribute("data-session-kind")).toBe("crypto");
    expect(pill.textContent).toBe("24/7");
  });

  it("equity security uses the NYSE calendar (Friday RTH → open)", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-22T13:35:00Z"));
    focusLeaf("DES", "AAPL");
    render(<Titlebar />);
    const pill = screen.getByTestId("titlebar-market-pill");
    expect(pill.getAttribute("data-session-kind")).toBe("equity");
    expect(pill.textContent).toBe("open");
  });

  it("FX security shows the 24/5 week (Saturday → closed)", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-23T12:00:00Z"));
    focusLeaf("FX", "EURUSD");
    render(<Titlebar />);
    const pill = screen.getByTestId("titlebar-market-pill");
    expect(pill.getAttribute("data-session-kind")).toBe("fx");
    expect(pill.textContent).toBe("closed · 24/5");
  });

  it("no active security defaults the pill to the equity calendar", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-22T13:35:00Z"));
    focusLeaf("HOME");
    render(<Titlebar />);
    const pill = screen.getByTestId("titlebar-market-pill");
    expect(pill.getAttribute("data-session-kind")).toBe("equity");
    expect(pill.textContent).toBe("open");
  });
});
