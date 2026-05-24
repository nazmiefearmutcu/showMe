/**
 * Faz 3 — TMPL pane regression fixes.
 *
 * B-C5 — Kapat must be disabled while creating=true to prevent orphan strategy.
 */
import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TMPLPane } from "./TMPL";
import { useTemplateStore } from "@/lib/template-store";

const FIX = [
  { id: "rsi-mean-revert", name: "RSI MR", description: "RSI desc",
    uses_indicators: ["rsi"], recommended_timeframe: "1h",
    recommended_symbols: ["BTC/USDT"], applicability: "appl",
    natural_language_explanation: "NL", math: "M", spec_template: {}, family: "momentum" },
];

beforeEach(() => {
  useTemplateStore.setState({ entries: FIX, selectedId: null, loading: false, error: null });
});

describe("TMPL pane fixes", () => {
  it("kapat_disabled_while_creating — Kapat button disabled when creating=true", async () => {
    // Hold the instantiate promise unresolved so creating stays true.
    let resolveCreate: (v: unknown) => void = () => {};
    const pending = new Promise((res) => { resolveCreate = res; });
    const fakeInstantiate = (() => pending) as unknown as
      ReturnType<typeof useTemplateStore.getState>["instantiate"];
    vi.spyOn(useTemplateStore.getState(), "instantiate")
      .mockImplementation(fakeInstantiate);

    render(<TMPLPane />);
    fireEvent.click(screen.getByText("RSI MR"));
    fireEvent.click(screen.getByRole("button", { name: /kullan/i }));
    fireEvent.click(screen.getByRole("button", { name: /oluştur/i }));

    // While in-flight, Kapat must be disabled.
    const kapat = screen.getByTestId("tmpl-kapat-button") as HTMLButtonElement;
    expect(kapat.disabled).toBe(true);
    expect(screen.getByTestId("tmpl-creating-indicator")).toBeInTheDocument();

    // Resolve and re-check Kapat re-enables.
    resolveCreate({ template_id: "rsi-mean-revert", strategy: { id: "abc" } });
    await pending;
    // Allow React to commit the post-await setCreating(false).
    await new Promise((r) => setTimeout(r, 0));
    expect(kapat.disabled).toBe(false);
  });

  it("kapat_enabled_pre_create — Kapat enabled before user hits Oluştur", () => {
    render(<TMPLPane />);
    fireEvent.click(screen.getByText("RSI MR"));
    fireEvent.click(screen.getByRole("button", { name: /kullan/i }));
    const kapat = screen.getByTestId("tmpl-kapat-button") as HTMLButtonElement;
    expect(kapat.disabled).toBe(false);
  });
});
