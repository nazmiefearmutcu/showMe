/**
 * Stress tests for UI Cascade, Dropdowns, timeframe mapping, and orphan references.
 * Implements verification for multiple concurrent orphan references, empty lists,
 * multiple invalid inputs at once, and timeframe mapping mismatches.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BOTPane } from "./BOT";
import { STRAPane } from "./STRA";
import { useBotStore } from "@/lib/bot-store";
import { useStrategyStore } from "@/lib/strategy-store";
import { useExchangeStore } from "@/lib/exchange-store";
import { useIndicatorStore } from "@/lib/indicator-store";

const PERSISTED_DRAFT = {
  id: "b1",
  strategy_id: "s1",
  credential_id: "c1",
  exchange_id: "binance",
  symbol: "BTC/USDT",
  timeframe: "1h",
  tick_interval_seconds: 60,
  mode: "shadow",
  enabled: false,
  signal_log: [],
  last_processed_event: null,
  created_at: "",
  updated_at: "",
};

const BASE_STRA_DRAFT = {
  id: "abc",
  name: "Existing",
  description: "",
  timeframe: "1h",
  version: 1,
  asset_filter: {},
  indicators: [],
  entry_rules: [],
  exit_rules: [],
  entry_logic: "all",
  exit_logic: "any",
  position: { side: "long", sizing_kind: "fixed_quote", sizing_value: 100 },
  created_at: "",
  updated_at: "",
};

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("UI Stress Tests — BOT and STRA Panes", () => {
  describe("BOT Pane — Concurrent and Boundary Failures", () => {
    it("handles multiple concurrent orphan references and disables saving", () => {
      // Both strategy and credential IDs are orphaned (ghost-id and ghost-c)
      useBotStore.setState({
        bots: [],
        draft: {
          ...PERSISTED_DRAFT,
          strategy_id: "ghost-id",
          credential_id: "ghost-c",
        } as any,
        draftIsNew: false,
        dirty: true,
        loading: false,
        saving: false,
        toggling: false,
        error: null,
        loadList: vi.fn(async () => {}),
      });

      useStrategyStore.setState({
        strategies: [], // empty list
        draft: null,
        draftIsNew: false,
        dirty: false,
        loading: false,
        removing: false,
        error: null,
        lastPreview: null,
        loadList: vi.fn(async () => {}),
      });

      useExchangeStore.setState({
        catalog: [],
        credentials: [], // empty list
        selectedExchangeId: null,
        catalogLoading: false,
        credentialsLoading: false,
        error: null,
        loadCredentials: vi.fn(async () => {}),
      });

      // Render the component
      const { unmount } = render(<BOTPane />);

      // Verify no crash occurred and orphan options are rendered
      expect(screen.getByTestId("bot-strategy-orphan-option")).toBeInTheDocument();
      expect(screen.getByTestId("bot-credential-orphan-option")).toBeInTheDocument();

      // Verify inline error elements are in the document
      expect(screen.getByTestId("bot-field-err-strategy-orphan")).toBeInTheDocument();
      expect(screen.getByTestId("bot-field-err-credential-orphan")).toBeInTheDocument();

      // Save button must be disabled
      const saveBtn = screen.getByRole("button", { name: /^kaydet$/i }) as HTMLButtonElement;
      expect(saveBtn.disabled).toBe(true);

      unmount();
    });

    it("handles empty lists gracefully (empty bot, strategy, and credential stores)", () => {
      useBotStore.setState({
        bots: [],
        draft: null,
        draftIsNew: false,
        dirty: false,
        loading: false,
        saving: false,
        toggling: false,
        error: null,
        loadList: vi.fn(async () => {}),
      });

      useStrategyStore.setState({
        strategies: [],
        draft: null,
        draftIsNew: false,
        dirty: false,
        loading: false,
        removing: false,
        error: null,
        loadList: vi.fn(async () => {}),
      });

      useExchangeStore.setState({
        catalog: [],
        credentials: [],
        selectedExchangeId: null,
        catalogLoading: false,
        credentialsLoading: false,
        error: null,
        loadCredentials: vi.fn(async () => {}),
      });

      const { unmount } = render(<BOTPane />);

      // Verify list empty state is displayed instead of crashing
      expect(screen.getByTestId("bot-list-empty")).toBeInTheDocument();
      expect(screen.getByText(/soldan bir bot seç ya da/i)).toBeInTheDocument();

      unmount();
    });

    it("handles multiple invalid inputs at once (orphaned references, empty symbol, unknown timeframe)", () => {
      useBotStore.setState({
        bots: [],
        draft: {
          ...PERSISTED_DRAFT,
          strategy_id: "ghost-id",
          credential_id: "ghost-c",
          symbol: "   ", // whitespace only
          timeframe: "30m", // unknown/unsupported timeframe
        } as any,
        draftIsNew: false,
        dirty: true,
        loading: false,
        saving: false,
        toggling: false,
        error: null,
        loadList: vi.fn(async () => {}),
      });

      useStrategyStore.setState({
        strategies: [],
        draft: null,
        draftIsNew: false,
        dirty: false,
        loading: false,
        removing: false,
        error: null,
        loadList: vi.fn(async () => {}),
      });

      useExchangeStore.setState({
        catalog: [],
        credentials: [],
        selectedExchangeId: null,
        catalogLoading: false,
        credentialsLoading: false,
        error: null,
        loadCredentials: vi.fn(async () => {}),
      });

      const { unmount } = render(<BOTPane />);

      // Verify UI renders options and flags all errors
      expect(screen.getByTestId("bot-strategy-orphan-option")).toBeInTheDocument();
      expect(screen.getByTestId("bot-credential-orphan-option")).toBeInTheDocument();
      expect(screen.getByTestId("bot-timeframe-unknown-option")).toBeInTheDocument();

      expect(screen.getByTestId("bot-field-err-strategy-orphan")).toBeInTheDocument();
      expect(screen.getByTestId("bot-field-err-credential-orphan")).toBeInTheDocument();
      expect(screen.getByTestId("bot-field-err-symbol")).toBeInTheDocument();
      expect(screen.getByTestId("bot-field-err-timeframe")).toBeInTheDocument();

      // Save must be disabled
      const saveBtn = screen.getByRole("button", { name: /^kaydet$/i }) as HTMLButtonElement;
      expect(saveBtn.disabled).toBe(true);

      unmount();
    });
  });

  describe("STRA Pane — Timeframe Mismatches and Boundary Failures", () => {
    it("handles unknown timeframe in strategy draft and blocks saving", () => {
      useStrategyStore.setState({
        strategies: [],
        draft: {
          ...BASE_STRA_DRAFT,
          timeframe: "45m", // unknown/unsupported timeframe
        } as any,
        draftIsNew: false,
        dirty: true,
        loading: false,
        removing: false,
        error: null,
        loadList: vi.fn(async () => {}),
      });

      useIndicatorStore.setState({
        entries: [],
        loading: false,
        error: null,
        selectedId: null,
        loadCatalog: vi.fn(async () => {}),
      });

      const { unmount } = render(<STRAPane />);

      // Verify the unknown option is rendered
      expect(screen.getByTestId("stra-timeframe-unknown-option")).toBeInTheDocument();
      expect(screen.getByTestId("stra-field-err-timeframe")).toBeInTheDocument();

      // Save button must be disabled
      const saveBtn = screen.getByTestId("stra-save-button") as HTMLButtonElement;
      expect(saveBtn.disabled).toBe(true);

      unmount();
    });
  });
});
