import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { BDAPane } from "./BDA";
import { useAssistantStore } from "@/lib/assistant-store";
import { useStrategyStore } from "@/lib/strategy-store";

beforeEach(() => {
  useAssistantStore.setState({
    text: "", result: null, explanation: null, loading: false, error: null,
  });
  useStrategyStore.setState({
    strategies: [
      { id: "s1", name: "RSI MR", description: "", timeframe: "1h",
        created_at: "", updated_at: "" },
    ],
    draft: null, draftIsNew: false, dirty: false, loading: false, error: null,
    lastPreview: null,
  });
});

describe("BDA pane", () => {
  it("renders textarea + buttons", () => {
    render(<BDAPane />);
    expect(screen.getByLabelText(/strateji isteği/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^strateji öner$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /öner.*kaydet/i })).toBeInTheDocument();
  });

  it("textarea updates store text", () => {
    render(<BDAPane />);
    fireEvent.change(screen.getByLabelText(/strateji isteği/i), {
      target: { value: "RSI 30 altında" },
    });
    expect(useAssistantStore.getState().text).toBe("RSI 30 altında");
  });

  it("renders strategy dropdown with available strategies", () => {
    render(<BDAPane />);
    expect(screen.getByText("RSI MR")).toBeInTheDocument();
  });

  it("shows notes when result populated", () => {
    useAssistantStore.setState({
      result: { spec: { name: "X" } as never, notes: ["sample note"], saved_id: null },
    });
    render(<BDAPane />);
    expect(screen.getByText(/sample note/i)).toBeInTheDocument();
  });

  it("shows explanation when populated", () => {
    useAssistantStore.setState({ explanation: "RSI strateji TR özet" });
    render(<BDAPane />);
    expect(screen.getByText(/RSI strateji TR özet/)).toBeInTheDocument();
  });
});
