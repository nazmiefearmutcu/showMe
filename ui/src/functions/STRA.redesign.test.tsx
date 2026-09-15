/**
 * STRA — editor redesign behaviour pins.
 *
 * These run the pane against the REAL strategy store with a mocked sidecar:
 *  - Save round-trip: New → name → Save → POST /api/strategies → clean draft.
 *  - "+ Add rule" appends a rule row (entry group).
 *  - Empty name is flagged inline and blocks Save (mirrors backend min_length).
 *  - Position sizing commits on blur and marks the draft dirty.
 *  - Pane chrome (header code chip + provenance footer) renders.
 */
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { STRAPane } from "./STRA";
import { useStrategyStore } from "@/lib/strategy-store";
import { useIndicatorStore } from "@/lib/indicator-store";

vi.mock("@/lib/sidecar", () => ({ sidecarFetch: vi.fn() }));
import { sidecarFetch } from "@/lib/sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

const RSI_ENTRY = {
  id: "rsi", display_name: "RSI", family: "momentum", short_description: "",
  long_description: "", formula: "", parameters: [], confidence: 9,
  confidence_rationale: "", suggested_strategy: {}, references: [],
};

beforeEach(() => {
  useStrategyStore.setState({
    strategies: [], draft: null, draftIsNew: false, dirty: false,
    loading: false, saving: false, previewing: false, removing: false,
    error: null, lastPreview: null,
  });
  useIndicatorStore.setState({
    entries: [RSI_ENTRY], loading: false, error: null, selectedId: null,
  });
  mock.mockReset();
  mock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === "/api/strategies" && !init?.method) return { records: [] };
    if (url === "/api/strategies" && init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      return { ...body, id: "s-new", created_at: "x", updated_at: "y" };
    }
    if (url === "/api/indicators/catalog") return [];
    return {};
  });
});

describe("STRA redesign — save round-trip", () => {
  it("New → name → Save POSTs the draft and clears dirty", async () => {
    render(<STRAPane />);
    fireEvent.click(screen.getByRole("button", { name: /^\+ new strategy$/i }));
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "RSI v1" } });

    const save = screen.getByTestId("stra-save-button") as HTMLButtonElement;
    expect(save.disabled).toBe(false);
    fireEvent.click(save);

    await waitFor(() =>
      expect(useStrategyStore.getState().draft?.id).toBe("s-new"));
    expect(useStrategyStore.getState().dirty).toBe(false);

    const post = mock.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === "POST");
    expect(post).toBeTruthy();
    expect(JSON.parse(String((post![1] as RequestInit).body)).name).toBe("RSI v1");
  });
});

describe("STRA redesign — rule builder", () => {
  it("+ Add rule appends an entry rule row", () => {
    render(<STRAPane />);
    fireEvent.click(screen.getByRole("button", { name: /^\+ new strategy$/i }));
    const entryGroup = screen.getByTestId("stra-entry-group");
    fireEvent.click(within(entryGroup).getByRole("button", { name: /add rule/i }));

    expect(useStrategyStore.getState().draft?.entry_rules?.length).toBe(1);
    expect(screen.getByTestId("stra-entry-rule-0-right")).toBeInTheDocument();
  });
});

describe("STRA redesign — name validation", () => {
  it("empty name is flagged inline and blocks Save", () => {
    render(<STRAPane />);
    fireEvent.click(screen.getByRole("button", { name: /^\+ new strategy$/i }));

    expect(screen.getByTestId("stra-field-err-name")).toBeInTheDocument();
    const save = screen.getByTestId("stra-save-button") as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    expect(save.getAttribute("title")).toMatch(/name is required/i);
  });

  it("typing a name clears the inline error", () => {
    render(<STRAPane />);
    fireEvent.click(screen.getByRole("button", { name: /^\+ new strategy$/i }));
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "X" } });
    expect(screen.queryByTestId("stra-field-err-name")).toBeNull();
  });
});

describe("STRA redesign — position sizing", () => {
  it("sizing value commits on blur and marks the draft dirty", () => {
    render(<STRAPane />);
    fireEvent.click(screen.getByRole("button", { name: /^\+ new strategy$/i }));

    const sizing = screen.getByTestId("stra-position-sizing") as HTMLInputElement;
    fireEvent.change(sizing, { target: { value: "250" } });
    fireEvent.blur(sizing);

    const pos = useStrategyStore.getState().draft?.position as { sizing_value: number };
    expect(pos.sizing_value).toBe(250);
    expect(useStrategyStore.getState().dirty).toBe(true);
  });
});

describe("STRA redesign — pane chrome", () => {
  it("renders the code chip and the provenance footer", () => {
    render(<STRAPane />);
    expect(screen.getByText("STRA")).toBeInTheDocument();
    expect(screen.getByText("/api/strategies")).toBeInTheDocument();
  });
});
