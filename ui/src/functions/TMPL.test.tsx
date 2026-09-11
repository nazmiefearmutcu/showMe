import { render, screen, fireEvent, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TMPLPane } from "./TMPL";
import { useTemplateStore } from "@/lib/template-store";

const FIX = [
  { id: "rsi-mean-revert", name: "RSI MR", description: "RSI desc",
    uses_indicators: ["rsi"], recommended_timeframe: "1h",
    recommended_symbols: ["BTC/USDT"], applicability: "appl",
    natural_language_explanation: "NL", math: "M", spec_template: {}, family: "momentum" },
  { id: "ema-crossover", name: "EMA X", description: "EMA desc",
    uses_indicators: ["ema"], recommended_timeframe: "1h", recommended_symbols: [],
    applicability: "", natural_language_explanation: "", math: "", spec_template: {}, family: "trend" },
];

beforeEach(() => {
  useTemplateStore.setState({ entries: FIX, selectedId: null, loading: false, error: null });
});

describe("TMPL pane", () => {
  it("renders both templates in list", () => {
    render(<TMPLPane />);
    expect(screen.getByText("RSI MR")).toBeInTheDocument();
    expect(screen.getByText("EMA X")).toBeInTheDocument();
  });

  it("selecting renders detail view", () => {
    render(<TMPLPane />);
    fireEvent.click(screen.getByText("RSI MR"));
    expect(screen.getByText(/RSI desc/)).toBeInTheDocument();
    expect(screen.getByText(/NL/)).toBeInTheDocument();
  });

  it("Use button opens modal with default name", () => {
    render(<TMPLPane />);
    fireEvent.click(screen.getByText("RSI MR"));
    fireEvent.click(screen.getByRole("button", { name: /use this template/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    const nameInput = screen.getByLabelText(/^name$/i) as HTMLInputElement;
    expect(nameInput.value).toBe("RSI MR");
  });

  it("Create button calls instantiate", async () => {
    const spy = vi.spyOn(useTemplateStore.getState(), "instantiate")
      .mockResolvedValue({ template_id: "rsi-mean-revert", strategy: { id: "abc" } as never });
    render(<TMPLPane />);
    fireEvent.click(screen.getByText("RSI MR"));
    fireEvent.click(screen.getByRole("button", { name: /use this template/i }));
    fireEvent.click(screen.getByRole("button", { name: /create/i }));
    // Wait a tick for the promise to resolve
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(spy).toHaveBeenCalled();
    expect(spy.mock.calls[0][0]).toBe("rsi-mean-revert");
  });

  it("Close button closes modal", () => {
    render(<TMPLPane />);
    fireEvent.click(screen.getByText("RSI MR"));
    fireEvent.click(screen.getByRole("button", { name: /use this template/i }));
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("surfaces a catalog load error at the list level with Retry (audit A10 M)", () => {
    const loadCatalog = vi.fn(async () => {});
    useTemplateStore.setState({
      entries: [],
      selectedId: null,
      loading: false,
      error: "catalog exploded",
      loadCatalog,
    });
    render(<TMPLPane />);
    const box = screen.getByTestId("tmpl-catalog-error");
    expect(box.textContent).toContain("catalog exploded");
    // Mount effect already triggered one load; the Retry button adds one more.
    const before = loadCatalog.mock.calls.length;
    fireEvent.click(within(box).getByRole("button", { name: /retry/i }));
    expect(loadCatalog.mock.calls.length).toBe(before + 1);
  });

  it("shows the instantiate error, not a stale catalog error (audit A10 L)", async () => {
    // A stale catalog error from an earlier load must not leak into the modal.
    useTemplateStore.setState({ error: "stale catalog failure" });
    vi.spyOn(useTemplateStore.getState(), "instantiate").mockImplementation(async () => {
      useTemplateStore.setState({ instantiateError: "instantiate exploded" });
      return null;
    });
    render(<TMPLPane />);
    fireEvent.click(screen.getByText("RSI MR"));
    fireEvent.click(screen.getByRole("button", { name: /use this template/i }));
    fireEvent.click(screen.getByRole("button", { name: /create/i }));
    const indicator = await screen.findByTestId("tmpl-error-indicator");
    expect(indicator.textContent).toContain("instantiate exploded");
    expect(indicator.textContent).not.toContain("stale catalog failure");
  });
});
