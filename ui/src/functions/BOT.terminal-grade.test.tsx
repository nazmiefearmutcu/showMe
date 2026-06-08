/**
 * BOT — terminal-grade upgrade tests.
 *
 * Covers the NEW behaviours added in the terminal-grade pass:
 *  F1 — design-system Pill status with an accessible name.
 *  F2 — signal table caption + scope; price uses formatPrice; fallback-equity
 *       badge shown only when equity_source === "fallback_10k".
 *  F4 — pane error region is a polite live region (role=status).
 *  F5 — Empty when no bots; Skeleton when loading + empty.
 *  F6 — Disable triggers a ConfirmDialog; disabled Save has a title.
 *
 * These are additive; the existing BOT suites stay green. Follows the
 * store-setState render style of BOT.fixes2.test.tsx + STRA.terminal-grade.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BOTPane } from "./BOT";
import { useBotStore } from "@/lib/bot-store";
import { useStrategyStore } from "@/lib/strategy-store";
import { useExchangeStore } from "@/lib/exchange-store";

const __dir = dirname(fileURLToPath(import.meta.url));

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

beforeEach(() => {
  useBotStore.setState({
    bots: [
      { id: "b1", strategy_id: "s1", credential_id: "c1", exchange_id: "binance",
        symbol: "BTC/USDT", timeframe: "1h", mode: "shadow", enabled: false,
        created_at: "", updated_at: "" },
    ],
    draft: null, draftIsNew: false, dirty: false,
    loading: false, saving: false, toggling: false, error: null,
    loadList: vi.fn(async () => {}),
  });
  useStrategyStore.setState({
    strategies: [{ id: "s1", name: "RSI-rev", description: "", timeframe: "1h",
                   created_at: "", updated_at: "" }],
    draft: null, draftIsNew: false, dirty: false, loading: false, removing: false,
    error: null, lastPreview: null,
    loadList: vi.fn(async () => {}),
  });
  useExchangeStore.setState({
    catalog: [],
    credentials: [{ id: "c1", exchange_id: "binance", account_label: "main",
                    permissions: ["read", "trade"], created_at: "" }],
    selectedExchangeId: null, catalogLoading: false, credentialsLoading: false, error: null,
    loadCredentials: vi.fn(async () => {}),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("BOT F1 — Pill status with accessible name", () => {
  it("renders an OFF status with an accessible name for a disabled bot", () => {
    render(<BOTPane />);
    // The sidebar row carries the status pill; OFF for the disabled bot.
    const off = screen.getAllByRole("status", { name: /durum: off/i });
    expect(off.length).toBeGreaterThanOrEqual(1);
    expect(off[0].textContent).toMatch(/OFF/);
  });

  it("renders LIVE status (negative tone) for an enabled live bot", () => {
    useBotStore.setState({
      bots: [{ id: "b1", strategy_id: "s1", credential_id: "c1",
               exchange_id: "binance", symbol: "BTC/USDT", timeframe: "1h",
               mode: "live", enabled: true, created_at: "", updated_at: "" }],
    });
    render(<BOTPane />);
    const live = screen.getAllByRole("status", { name: /durum: live/i });
    expect(live.length).toBeGreaterThanOrEqual(1);
    // Pill tone-negative class present on the inner pill.
    expect(live[0].querySelector(".ds-pill--tone-negative")).not.toBeNull();
  });

  it("renders SHADOW status (warn tone) for an enabled shadow bot", () => {
    useBotStore.setState({
      bots: [{ id: "b1", strategy_id: "s1", credential_id: "c1",
               exchange_id: "binance", symbol: "BTC/USDT", timeframe: "1h",
               mode: "shadow", enabled: true, created_at: "", updated_at: "" }],
    });
    render(<BOTPane />);
    const shadow = screen.getAllByRole("status", { name: /durum: shadow/i });
    expect(shadow[0].querySelector(".ds-pill--tone-warn")).not.toBeNull();
  });
});

describe("BOT F2 — signal table semantics + display", () => {
  it("signal table has a caption and column scopes", () => {
    useBotStore.setState({
      draft: {
        ...PERSISTED_DRAFT,
        signal_log: [
          { bar_index: 0, bar_time: "2026-05-22T10:00:00Z", kind: "entry",
            price: 100.5, action: "shadow" },
        ],
      } as never,
    });
    render(<BOTPane />);
    const table = screen.getByRole("table", { name: /sinyal/i });
    expect(table.querySelector("caption")).not.toBeNull();
    const ths = table.querySelectorAll("th[scope='col']");
    expect(ths.length).toBe(5);
  });

  it("price cell uses formatPrice (sub-cent price not truncated to 2dp)", () => {
    useBotStore.setState({
      draft: {
        ...PERSISTED_DRAFT,
        signal_log: [
          { bar_index: 0, bar_time: "2026-05-22T10:00:00Z", kind: "entry",
            price: 0.00012345, action: "shadow" },
        ],
      } as never,
    });
    render(<BOTPane />);
    // formatPrice(0.00012345) keeps precision; the naive .toFixed(2) would
    // have collapsed it to "0.00".
    expect(screen.queryByText("0.00")).toBeNull();
    // 0.00012345 is in the [0.0001, 0.01) band → 6dp = "0.000123".
    expect(screen.getByText("0.000123")).toBeInTheDocument();
  });

  it("shows the fallback-equity badge when equity_source==='fallback_10k'", () => {
    useBotStore.setState({
      draft: {
        ...PERSISTED_DRAFT,
        signal_log: [
          { bar_index: 0, bar_time: "2026-05-22T10:00:00Z", kind: "entry",
            price: 100, action: "placed", order_id: "o1",
            equity_source: "fallback_10k" },
        ],
      } as never,
    });
    render(<BOTPane />);
    expect(screen.getByTestId("bot-signal-fallback-equity")).toBeInTheDocument();
  });

  it("hides the fallback-equity badge when equity_source is 'broker'", () => {
    useBotStore.setState({
      draft: {
        ...PERSISTED_DRAFT,
        signal_log: [
          { bar_index: 0, bar_time: "2026-05-22T10:00:00Z", kind: "entry",
            price: 100, action: "placed", order_id: "o1",
            equity_source: "broker" },
        ],
      } as never,
    });
    render(<BOTPane />);
    expect(screen.queryByTestId("bot-signal-fallback-equity")).toBeNull();
  });

  it("hides the fallback-equity badge when equity_source is absent", () => {
    useBotStore.setState({
      draft: {
        ...PERSISTED_DRAFT,
        signal_log: [
          { bar_index: 0, bar_time: "2026-05-22T10:00:00Z", kind: "entry",
            price: 100, action: "shadow" },
        ],
      } as never,
    });
    render(<BOTPane />);
    expect(screen.queryByTestId("bot-signal-fallback-equity")).toBeNull();
  });
});

describe("BOT F3 — form control labels", () => {
  it("binds strategy / credential / symbol / timeframe / tick labels", () => {
    useBotStore.setState({ draft: { ...PERSISTED_DRAFT } as never });
    render(<BOTPane />);
    expect(screen.getByLabelText(/strateji/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/bağlantı/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^symbol$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/timeframe/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/tick interval/i)).toBeInTheDocument();
  });
});

describe("BOT F4 — async error live region", () => {
  it("renders the pane error as a polite status live region", () => {
    useBotStore.setState({
      draft: { ...PERSISTED_DRAFT } as never,
      error: "Bir şeyler ters gitti",
    });
    render(<BOTPane />);
    const err = screen.getByTestId("bot-pane-error");
    expect(err.getAttribute("role")).toBe("status");
    expect(err.getAttribute("aria-live")).toBe("polite");
    expect(err.textContent).toMatch(/ters gitti/);
  });

  it("shows a store error even when no bot is selected (draft === null)", () => {
    // P2a — a loadList/store error with no draft must still surface; the
    // error region used to live inside the {draft && …} block and was
    // invisible while nothing was selected.
    useBotStore.setState({
      draft: null,
      error: "Liste yüklenemedi",
    });
    render(<BOTPane />);
    const err = screen.getByTestId("bot-pane-error");
    expect(err).toBeInTheDocument();
    expect(err.getAttribute("role")).toBe("status");
    expect(err.getAttribute("aria-live")).toBe("polite");
    expect(err.textContent).toMatch(/yüklenemedi/);
  });

  it("does not render the pane error twice when a draft is present", () => {
    // P2a — single instance guarantee: error region appears exactly once.
    useBotStore.setState({
      draft: { ...PERSISTED_DRAFT } as never,
      error: "tek sefer",
    });
    render(<BOTPane />);
    expect(screen.getAllByTestId("bot-pane-error")).toHaveLength(1);
  });
});

describe("BOT F5 — empty / loading sidebar states", () => {
  it("shows Empty when no bots and not loading", () => {
    useBotStore.setState({ bots: [], draft: null, loading: false });
    render(<BOTPane />);
    expect(screen.getByTestId("bot-list-empty")).toBeInTheDocument();
  });

  it("shows a skeleton while loading + empty", () => {
    useBotStore.setState({ bots: [], draft: null, loading: true });
    render(<BOTPane />);
    expect(screen.getByTestId("bot-list-loading")).toBeInTheDocument();
  });
});

describe("BOT F6 — disable confirm + disabled-Save title", () => {
  it("Durdur triggers a ConfirmDialog instead of disabling immediately", () => {
    const disableSpy = vi.fn(async () => null);
    useBotStore.setState({
      draft: { ...PERSISTED_DRAFT, enabled: true } as never,
      disable: disableSpy as never,
    });
    render(<BOTPane />);
    fireEvent.click(screen.getByTestId("bot-durdur-button"));
    // Dialog open, disable NOT yet called.
    expect(screen.getByTestId("confirm-dialog-body")).toBeInTheDocument();
    expect(disableSpy).not.toHaveBeenCalled();
    // Confirm → disable fires with the bot id.
    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    expect(disableSpy).toHaveBeenCalledWith("b1");
  });

  it("disabled Save button has an explanatory title", () => {
    // Not dirty → Save disabled and must explain why.
    useBotStore.setState({ draft: { ...PERSISTED_DRAFT } as never, dirty: false });
    render(<BOTPane />);
    const save = screen.getByRole("button", { name: /^kaydet$/i }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    expect(save.getAttribute("title")).toBeTruthy();
  });
});

describe("BOT — no dead CSS alias tokens in new code", () => {
  it("BOT.tsx references no nonexistent CSS alias tokens", () => {
    const src = readFileSync(join(__dir, "BOT.tsx"), "utf8");
    expect(src).not.toMatch(/var\(--accent-err\)/);
    expect(src).not.toMatch(/var\(--fg-2\)/);
    expect(src).not.toMatch(/var\(--border-1\)/);
    expect(src).not.toMatch(/var\(--accent-warn\)/);
    expect(src).not.toMatch(/var\(--accent-ok\)/);
  });
});
