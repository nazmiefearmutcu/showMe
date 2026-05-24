/**
 * Faz 4 — STRA pane new regression fixes.
 *
 *  - H-UI-3 unknown timeframe surfaced as option + inline error
 *  - H-UI-4 alias collision flagged inline
 *  - H-UI-8 literal:<x> missing prefix flagged
 *  - H-UI-9 preview disabled hint
 *  - LOW removing flag disables Sil
 *  - LOW Pydantic detail surfaced
 */
import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { STRAPane } from "./STRA";
import { useStrategyStore } from "@/lib/strategy-store";
import { useIndicatorStore } from "@/lib/indicator-store";

const BASE_DRAFT = {
  id: "abc", name: "Existing", description: "", timeframe: "1h",
  version: 1, asset_filter: {},
  indicators: [
    { alias: "rsi_1", id: "rsi", params: {} },
    { alias: "rsi_1", id: "rsi", params: {} },  // duplicate alias for H-UI-4
  ],
  entry_rules: [
    { kind: "greater_than", left: "rsi_1", right: "30" },  // missing literal: prefix
  ],
  exit_rules: [],
  entry_logic: "all", exit_logic: "any",
  position: { side: "long", sizing_kind: "fixed_quote", sizing_value: 100 },
  created_at: "", updated_at: "",
};

beforeEach(() => {
  useStrategyStore.setState({
    strategies: [{ id: "abc", name: "Existing", description: "", timeframe: "1h",
                   created_at: "", updated_at: "" }],
    draft: BASE_DRAFT as never,
    draftIsNew: false, dirty: false, loading: false, removing: false,
    error: null, lastPreview: null,
    loadList: vi.fn(async () => {}),
  });
  useIndicatorStore.setState({
    entries: [
      { id: "rsi", display_name: "RSI", family: "momentum", short_description: "",
        long_description: "", formula: "", parameters: [], confidence: 9,
        confidence_rationale: "", suggested_strategy: {}, references: [] },
    ],
    loading: false, error: null, selectedId: null,
    loadCatalog: vi.fn(async () => {}),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("STRA pane fixes2", () => {
  // ─── H-UI-3 ──────────────────────────────────────────────────────────
  it("unknown_timeframe_surfaces", () => {
    useStrategyStore.setState({
      draft: { ...BASE_DRAFT, timeframe: "30m" } as never,
      dirty: false,
    });
    render(<STRAPane />);
    expect(screen.getByTestId("stra-timeframe-unknown-option")).toBeInTheDocument();
    expect(screen.getByTestId("stra-field-err-timeframe")).toBeInTheDocument();
  });

  it("unknown_timeframe_disables_save_even_when_dirty", () => {
    useStrategyStore.setState({
      draft: { ...BASE_DRAFT, timeframe: "30m" } as never,
      dirty: true,
    });
    render(<STRAPane />);
    const kaydet = screen.getByRole("button", { name: /^kaydet$/i }) as HTMLButtonElement;
    expect(kaydet.disabled).toBe(true);
  });

  // ─── H-UI-4 ──────────────────────────────────────────────────────────
  it("duplicate_alias_flagged_inline", () => {
    render(<STRAPane />);
    expect(screen.getByTestId("stra-field-err-alias-dup")).toBeInTheDocument();
    expect(screen.getByTestId("stra-indicator-alias-0").getAttribute("data-dup")).toBe("1");
    expect(screen.getByTestId("stra-indicator-alias-1").getAttribute("data-dup")).toBe("1");
  });

  it("duplicate_alias_blocks_save", () => {
    useStrategyStore.setState({ dirty: true });
    render(<STRAPane />);
    const kaydet = screen.getByRole("button", { name: /^kaydet$/i }) as HTMLButtonElement;
    expect(kaydet.disabled).toBe(true);
  });

  // ─── H-UI-8 ──────────────────────────────────────────────────────────
  it("operand_missing_literal_prefix_flagged", () => {
    render(<STRAPane />);
    // The entry rule's right input is "30" with no literal: prefix.
    const rightInput = screen.getByTestId("stra-entry-rule-0-right");
    expect(rightInput.getAttribute("title")).toMatch(/literal/);
    expect(screen.getByTestId("stra-entry-operand-hint")).toBeInTheDocument();
  });

  // ─── H-UI-9 ──────────────────────────────────────────────────────────
  it("preview_button_disabled_when_dirty_with_hint", () => {
    useStrategyStore.setState({ dirty: true });
    render(<STRAPane />);
    const preview = screen.getByTestId("stra-preview-button") as HTMLButtonElement;
    expect(preview.disabled).toBe(true);
    expect(screen.getByTestId("stra-preview-hint").textContent).toMatch(/kaydet/i);
  });

  it("preview_button_disabled_when_no_id_with_hint", () => {
    useStrategyStore.setState({
      draft: { ...BASE_DRAFT, id: undefined } as never,
      dirty: false,
    });
    render(<STRAPane />);
    const preview = screen.getByTestId("stra-preview-button") as HTMLButtonElement;
    expect(preview.disabled).toBe(true);
    expect(screen.getByTestId("stra-preview-hint")).toBeInTheDocument();
  });

  // ─── LOW removing flag ───────────────────────────────────────────────
  it("sil_disabled_while_removing", () => {
    useStrategyStore.setState({ removing: true });
    render(<STRAPane />);
    const sil = screen.getByTestId("stra-sil-button") as HTMLButtonElement;
    expect(sil.disabled).toBe(true);
    expect(sil.textContent).toMatch(/Siliniyor/i);
  });

  // ─── LOW Pydantic detail ─────────────────────────────────────────────
  it("pydantic_detail_array_renders_field_msg", () => {
    useStrategyStore.setState({
      error: 'PUT failed: 422 Unprocessable Entity {"detail":[{"loc":["body","timeframe"],"msg":"unknown"}]}',
    });
    render(<STRAPane />);
    expect(screen.getByTestId("stra-pane-error").textContent).toMatch(/body\.timeframe/);
    expect(screen.getByTestId("stra-pane-error").textContent).toMatch(/unknown/);
  });

  it("pydantic_detail_string_passes_through", () => {
    useStrategyStore.setState({
      error: 'GET /api/foo: 500 Internal Server Error',
    });
    render(<STRAPane />);
    expect(screen.getByTestId("stra-pane-error").textContent).toMatch(/500/);
  });

  // ─── H-UI-10 dirty switch ────────────────────────────────────────────
  it("dirty_switch_prompts_confirm", () => {
    useStrategyStore.setState({
      strategies: [
        { id: "abc", name: "Existing", description: "", timeframe: "1h",
          created_at: "", updated_at: "" },
        { id: "def", name: "Other", description: "", timeframe: "4h",
          created_at: "", updated_at: "" },
      ],
      dirty: true,
    });
    const openSpy = vi.fn(async () => {});
    useStrategyStore.setState({ openExisting: openSpy as never });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<STRAPane />);
    const allButtons = screen.getAllByRole("button");
    const other = allButtons.find((b) => b.textContent?.includes("Other"));
    fireEvent.click(other!);
    expect(confirmSpy).toHaveBeenCalled();
    expect(openSpy).not.toHaveBeenCalled();
  });
});
