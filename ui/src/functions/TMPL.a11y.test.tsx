/**
 * TMPL a11y regression — Agent F close-out.
 *
 * Pins the three a11y guarantees the modal must hold:
 *  1. Esc closes the modal (already shipped, kept as a guard).
 *  2. `data-testid="tmpl-modal-body"` is the focus-trap container.
 *  3. The source imports `useFocusTrap` from `@/lib/a11y` (the same
 *     hook ShortcutsHelp + Palette use). A regression that strips the
 *     trap would slip past behavioral tests because focus-trap relies
 *     on DOM focus order that jsdom approximates loosely.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TMPLPane } from "./TMPL";
import { useTemplateStore } from "@/lib/template-store";

const __dirname = dirname(fileURLToPath(import.meta.url));
const tmplSourceRaw = readFileSync(resolve(__dirname, "TMPL.tsx"), "utf-8");

const FIX = [
  {
    id: "rsi-mean-revert",
    name: "RSI MR",
    description: "RSI desc",
    uses_indicators: ["rsi"],
    recommended_timeframe: "1h",
    recommended_symbols: ["BTC/USDT"],
    applicability: "appl",
    natural_language_explanation: "NL",
    math: "M",
    spec_template: {},
    family: "momentum",
  },
];

beforeEach(() => {
  useTemplateStore.setState({
    entries: FIX,
    selectedId: null,
    loading: false,
    error: null,
  });
});

describe("TMPL modal a11y (focus trap + Esc)", () => {
  it("source imports useFocusTrap from @/lib/a11y", () => {
    expect(tmplSourceRaw).toMatch(
      /import\s+\{[^}]*useFocusTrap[^}]*\}\s+from\s+["']@\/lib\/a11y["']/,
    );
    // And actually invokes it with the modal ref + open flag.
    expect(tmplSourceRaw).toMatch(/useFocusTrap\(modalRef,\s*useModal\s*!==\s*null\)/);
  });

  it("modal body element exists and carries the trap-container testid", () => {
    render(<TMPLPane />);
    fireEvent.click(screen.getByText("RSI MR"));
    fireEvent.click(screen.getByRole("button", { name: /kullan/i }));
    const body = screen.getByTestId("tmpl-modal-body");
    expect(body).toBeInTheDocument();
    // role="dialog" + aria-modal still on the backdrop wrapper.
    expect(screen.getByTestId("tmpl-modal-backdrop")).toHaveAttribute(
      "aria-modal",
      "true",
    );
  });

  it("Esc closes the modal (was already shipped, kept as regression guard)", () => {
    render(<TMPLPane />);
    fireEvent.click(screen.getByText("RSI MR"));
    fireEvent.click(screen.getByRole("button", { name: /kullan/i }));
    expect(screen.getByTestId("tmpl-modal-backdrop")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("tmpl-modal-backdrop")).toBeNull();
  });
});
