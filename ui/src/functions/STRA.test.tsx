import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { STRAPane } from "./STRA";
import { useStrategyStore } from "@/lib/strategy-store";
import { useIndicatorStore } from "@/lib/indicator-store";

beforeEach(() => {
  useStrategyStore.setState({
    strategies: [], draft: null, draftIsNew: false, dirty: false,
    loading: false, error: null, lastPreview: null,
  });
  useIndicatorStore.setState({
    entries: [
      { id: "rsi", display_name: "RSI", family: "momentum", short_description: "",
        long_description: "", formula: "", parameters: [], confidence: 9,
        confidence_rationale: "", suggested_strategy: {}, references: [] },
    ],
    loading: false, error: null, selectedId: null,
  });
});

describe("STRA pane", () => {
  it("shows empty-state copy when no draft", () => {
    render(<STRAPane />);
    // "Yeni strateji" appears in BOTH the left-pane button and the
    // right-pane empty-state copy (<strong> inside the helper text).
    expect(screen.getAllByText(/new strategy/i).length).toBeGreaterThanOrEqual(2);
  });

  it("Yeni strateji opens a blank draft", () => {
    render(<STRAPane />);
    fireEvent.click(screen.getByRole("button", { name: /^\+ new strategy$/i }));
    expect(useStrategyStore.getState().draft).not.toBeNull();
    expect(screen.getByLabelText(/^name$/i)).toBeInTheDocument();
  });

  it("setting name marks dirty + reflects in title", () => {
    render(<STRAPane />);
    fireEvent.click(screen.getByRole("button", { name: /^\+ new strategy$/i }));
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "MyStrat" } });
    expect(useStrategyStore.getState().dirty).toBe(true);
    expect(screen.getByText(/MyStrat/)).toBeInTheDocument();
  });

  it("Add indicator appends an entry", () => {
    render(<STRAPane />);
    fireEvent.click(screen.getByRole("button", { name: /^\+ new strategy$/i }));
    fireEvent.click(screen.getByRole("button", { name: /add indicator/i }));
    expect((useStrategyStore.getState().draft?.indicators ?? []).length).toBe(1);
  });

  it("Add rule in entry rules appends a rule", () => {
    render(<STRAPane />);
    fireEvent.click(screen.getByRole("button", { name: /^\+ new strategy$/i }));
    const allAddRuleButtons = screen.getAllByRole("button", { name: /add rule/i });
    fireEvent.click(allAddRuleButtons[0]);
    expect((useStrategyStore.getState().draft?.entry_rules ?? []).length).toBe(1);
  });

  it("rule operand placeholder is English (i18n regression)", () => {
    render(<STRAPane />);
    fireEvent.click(screen.getByRole("button", { name: /^\+ new strategy$/i }));
    // A blank draft has no rules yet — add one so the operand input exists.
    fireEvent.click(screen.getAllByRole("button", { name: /add rule/i })[0]);
    expect(
      screen.getByPlaceholderText("literal:30 or alias"),
    ).toBeInTheDocument();
  });

  it("renders saved strategy in left list", () => {
    useStrategyStore.setState({
      strategies: [{ id: "abc", name: "Existing", description: "", timeframe: "1h",
                     created_at: "", updated_at: "" }],
    });
    render(<STRAPane />);
    expect(screen.getByText("Existing")).toBeInTheDocument();
  });
});
