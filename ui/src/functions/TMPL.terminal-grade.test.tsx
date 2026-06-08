/**
 * TMPL terminal-grade close-out — P1 (dead-token purge), P3 (a11y states),
 * P5 (loading skeleton + Empty states).
 *
 * Mix of source-scan assertions (cheap, regression-proof against silent
 * token/aria drops) and behavioral render assertions.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TMPLPane } from "./TMPL";
import { useTemplateStore } from "@/lib/template-store";

const __dirname = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(__dirname, "TMPL.tsx"), "utf-8");

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
    instantiating: false,
    error: null,
  });
});

describe("TMPL P1 — dead CSS token purge", () => {
  it("references ZERO of the 5 dead tokens", () => {
    for (const dead of [
      "var(--border-1)",
      "var(--fg-2)",
      "var(--accent-err)",
      "var(--accent-warn)",
      "var(--accent-ok)",
    ]) {
      expect(src.includes(dead), `still references ${dead}`).toBe(false);
    }
  });

  it("uses canonical tokens instead", () => {
    expect(src).toMatch(/var\(--border-card\)/);
    expect(src).toMatch(/var\(--text-secondary\)/);
    expect(src).toMatch(/var\(--negative\)/);
    expect(src).toMatch(/var\(--warn\)/);
    expect(src).toMatch(/var\(--positive\)/);
  });
});

describe("TMPL P3 — a11y on modal + status + list", () => {
  function openModal() {
    render(<TMPLPane />);
    fireEvent.click(screen.getByText("RSI MR"));
    fireEvent.click(screen.getByRole("button", { name: /kullan/i }));
  }

  it("status region has aria-live polite and an alert role for errors", () => {
    expect(src).toMatch(/aria-live=["']polite["']/);
    expect(src).toMatch(/role=["']alert["']/);
  });

  it("modal points aria-labelledby at its titled heading", () => {
    openModal();
    const dialog = screen.getByRole("dialog");
    const labelledby = dialog.getAttribute("aria-labelledby");
    expect(labelledby).toBeTruthy();
    const title = document.getElementById(labelledby as string);
    expect(title).not.toBeNull();
    expect(title?.tagName.toLowerCase()).toBe("h3");
  });

  it("selected template button carries aria-current", () => {
    render(<TMPLPane />);
    const btn = screen.getByRole("button", { name: /RSI MR/ });
    expect(btn.getAttribute("aria-current")).toBeNull();
    fireEvent.click(btn);
    const selectedBtn = screen.getByRole("button", { name: /RSI MR/ });
    expect(selectedBtn.getAttribute("aria-current")).toBe("true");
  });

  it("name + symbol inputs are label-associated text inputs", () => {
    openModal();
    const adInput = screen.getByLabelText(/^ad$/i) as HTMLInputElement;
    expect(adInput.type).toBe("text");
    const symInput = screen.getByLabelText(/sembol/i) as HTMLInputElement;
    expect(symInput.type).toBe("text");
  });
});

describe("TMPL P5 — loading skeleton + Empty states", () => {
  it("renders a loading skeleton while loading with no entries", () => {
    useTemplateStore.setState({
      entries: [], loading: true, loadCatalog: async () => {},
    });
    render(<TMPLPane />);
    expect(screen.getByTestId("tmpl-list-loading")).toBeInTheDocument();
  });

  it("renders the Empty component for no-template-selected", () => {
    useTemplateStore.setState({ entries: FIX, loading: false, selectedId: null });
    render(<TMPLPane />);
    // design-system Empty renders a .ds-empty container.
    expect(document.querySelector(".ds-empty")).not.toBeNull();
  });

  it("renders the Empty component when the catalog is empty (not loading)", () => {
    useTemplateStore.setState({
      entries: [], loading: false, loadCatalog: async () => {},
    });
    render(<TMPLPane />);
    expect(document.querySelectorAll(".ds-empty").length).toBeGreaterThan(0);
  });
});
