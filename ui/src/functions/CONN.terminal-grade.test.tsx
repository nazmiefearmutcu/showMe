/**
 * CONN — terminal-grade upgrade coverage (F1–F6).
 *
 * Drives the store via setState (mirrors CONN.test.tsx) and asserts the
 * a11y / UX / display upgrades:
 *   - secret field show/hide toggle flips input type (F1)
 *   - account_label + secret field + upgrade re-confirm have bound labels (F2)
 *   - add-form error region is role=status (F2/F3)
 *   - Test / Bağlan expose aria-busy when their in-flight flag is set (F3)
 *   - per-credential status Pill renders ok/failed/untested + last_verified
 *     relative text shows when present (F4)
 *   - permission renders as a Pill (F6)
 *   - Empty shown when no credentials (F6)
 *   - delete uses the in-app ConfirmDialog (F5)
 *   - guard: CONN.tsx contains NO `--fg-1` token.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { CONNPane } from "./CONN";
import { useExchangeStore } from "@/lib/exchange-store";

const ORIGINAL_FETCH = global.fetch;

function baseCatalog() {
  return [
    {
      id: "binance", display_name: "Binance", aliases: ["binance.com"],
      asset_classes: ["spot", "futures"], regions: ["global"],
      adapter: "ccxt", requires: ["api_key", "api_secret"], optional: [],
      capabilities: { fetch_balance: true }, ccxt_id: "binance", notes: "",
    },
    {
      id: "okx", display_name: "OKX", aliases: [],
      asset_classes: ["spot"], regions: ["global"],
      adapter: "ccxt", requires: ["api_key", "api_secret", "passphrase"],
      optional: [], capabilities: { fetch_balance: true }, ccxt_id: "okx", notes: "",
    },
  ];
}

beforeEach(() => {
  useExchangeStore.setState({
    catalog: baseCatalog(),
    credentials: [],
    selectedExchangeId: null,
    catalogLoading: false,
    credentialsLoading: false,
    saving: false,
    deleting: new Set<string>(),
    testing: new Set<string>(),
    upgrading: new Set<string>(),
    error: null,
  });
});

afterEach(() => {
  global.fetch = ORIGINAL_FETCH;
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("CONN terminal-grade — F1 secret show/hide", () => {
  it("toggles the secret input between password and text", () => {
    render(<CONNPane />);
    fireEvent.click(screen.getByText("Binance"));
    const secret = screen.getByLabelText(/api_secret/i, { selector: "input" }) as HTMLInputElement;
    expect(secret.type).toBe("password");
    const toggle = screen.getByRole("button", { name: /göster: api_secret/i });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    expect((screen.getByLabelText(/api_secret/i, { selector: "input" }) as HTMLInputElement).type).toBe("text");
    expect(
      screen.getByRole("button", { name: /gizle: api_secret/i }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("non-secret api_key has no show/hide toggle and stays text", () => {
    render(<CONNPane />);
    fireEvent.click(screen.getByText("Binance"));
    const key = screen.getByLabelText(/^api_key$/i) as HTMLInputElement;
    expect(key.type).toBe("text");
    expect(screen.queryByRole("button", { name: /göster: api_key/i })).toBeNull();
  });
});

describe("CONN terminal-grade — F2 form a11y", () => {
  it("account_label + secret field have bound labels", () => {
    render(<CONNPane />);
    fireEvent.click(screen.getByText("Binance"));
    // getByLabelText only matches when label htmlFor/id (or wrapping) binds.
    expect(screen.getByLabelText(/account label/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/api_secret/i, { selector: "input" })).toBeInTheDocument();
  });

  it("the upgrade re-confirm input has a bound label", () => {
    useExchangeStore.setState({
      credentials: [{
        id: "abc", exchange_id: "binance", account_label: "main",
        permissions: ["read"], created_at: "2026-05-21T10:00:00Z",
      }],
      selectedExchangeId: "binance",
    });
    render(<CONNPane />);
    expect(screen.getByLabelText(/yeniden yaz/i)).toBeInTheDocument();
  });

  it("the add-form error region is role=status and shows store error", async () => {
    // loadCatalog/loadCredentials run on mount and reset error to null, so set
    // the error AFTER mount to assert the live region surfaces it.
    useExchangeStore.setState({ selectedExchangeId: "binance" });
    render(<CONNPane />);
    await act(async () => {
      useExchangeStore.setState({ error: "boom" });
    });
    const region = await screen.findByText("boom");
    expect(region).toHaveAttribute("role", "status");
    expect(region).toHaveAttribute("aria-live", "polite");
  });

  it("Bağlan is disabled with a title reason until required fields are filled", () => {
    render(<CONNPane />);
    fireEvent.click(screen.getByText("Binance"));
    const submit = screen.getByRole("button", { name: /bağlan/i });
    expect(submit).toBeDisabled();
    expect(submit.getAttribute("title")).toMatch(/etiket/i);
  });
});

describe("CONN terminal-grade — F3 async signaling", () => {
  it("Test button exposes aria-busy when its in-flight flag is set", () => {
    useExchangeStore.setState({
      credentials: [{
        id: "abc", exchange_id: "binance", account_label: "main",
        permissions: ["read"], created_at: "2026-05-21T10:00:00Z",
      }],
      selectedExchangeId: "binance",
      testing: new Set<string>(["abc"]),
    });
    render(<CONNPane />);
    const testBtn = screen.getByRole("button", { name: /^\.\.\.$|^test$/i });
    expect(testBtn).toHaveAttribute("aria-busy", "true");
    expect(testBtn).toBeDisabled();
  });

  it("Bağlan exposes aria-busy when saving is set", () => {
    useExchangeStore.setState({ selectedExchangeId: "binance", saving: true });
    render(<CONNPane />);
    const submit = screen.getByRole("button", { name: /bağlan|\.\.\./i });
    expect(submit).toHaveAttribute("aria-busy", "true");
    expect(submit).toBeDisabled();
  });
});

describe("CONN terminal-grade — F4 status Pill + last_verified", () => {
  it("renders 'Denenmedi' status when never verified", () => {
    useExchangeStore.setState({
      credentials: [{
        id: "abc", exchange_id: "binance", account_label: "main",
        permissions: ["read"], created_at: "2026-05-21T10:00:00Z",
        last_verified: null,
      }],
      selectedExchangeId: "binance",
    });
    render(<CONNPane />);
    const statusRegion = screen.getByRole("status", { name: /durum: denenmedi/i });
    expect(statusRegion).toBeInTheDocument();
    expect(screen.getByText(/son doğrulama: —/i)).toBeInTheDocument();
  });

  it("P2-2: only last_verified (no in-session test) → muted 'Daha önce doğrulandı', NOT green", () => {
    const tenMinAgo = new Date(Date.now() - 10 * 60_000).toISOString();
    useExchangeStore.setState({
      credentials: [{
        id: "abc", exchange_id: "binance", account_label: "main",
        permissions: ["read"], created_at: "2026-05-21T10:00:00Z",
        last_verified: tenMinAgo,
      }],
      selectedExchangeId: "binance",
    });
    render(<CONNPane />);
    // Honest: a stale prior-session verification does NOT claim live "Doğrulandı".
    expect(
      screen.getByRole("status", { name: /durum: daha önce doğrulandı/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: /^durum: doğrulandı$/i }),
    ).toBeNull();
    // The relative-time context line still shows.
    expect(screen.getByText(/son doğrulama:.*önce/i)).toBeInTheDocument();
  });

  it("P2-2: an in-session successful test flips to green 'Doğrulandı'", async () => {
    const tenMinAgo = new Date(Date.now() - 10 * 60_000).toISOString();
    useExchangeStore.setState({
      credentials: [{
        id: "abc", exchange_id: "binance", account_label: "main",
        permissions: ["read"], created_at: "2026-05-21T10:00:00Z",
        last_verified: tenMinAgo,
      }],
      selectedExchangeId: "binance",
    });
    vi.spyOn(useExchangeStore.getState(), "testCredential")
      .mockResolvedValue({ ok: true });
    render(<CONNPane />);
    // Before the test it is muted/stale.
    expect(
      screen.getByRole("status", { name: /durum: daha önce doğrulandı/i }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^test$/i }));
    await waitFor(() =>
      expect(
        screen.getByRole("status", { name: /durum: doğrulandı/i }),
      ).toBeInTheDocument(),
    );
  });

  it("a failed test flips the status Pill to 'Başarısız'", async () => {
    useExchangeStore.setState({
      credentials: [{
        id: "abc", exchange_id: "binance", account_label: "main",
        permissions: ["read"], created_at: "2026-05-21T10:00:00Z",
      }],
      selectedExchangeId: "binance",
    });
    vi.spyOn(useExchangeStore.getState(), "testCredential")
      .mockResolvedValue({ ok: false, error: "nope" });
    render(<CONNPane />);
    fireEvent.click(screen.getByRole("button", { name: /^test$/i }));
    await waitFor(() =>
      expect(screen.getByRole("status", { name: /durum: başarısız/i })).toBeInTheDocument(),
    );
  });
});

describe("CONN terminal-grade — F6 Pill / Empty", () => {
  it("renders permission as a Pill (salt okuma / okuma + işlem)", () => {
    useExchangeStore.setState({
      credentials: [
        {
          id: "ro", exchange_id: "binance", account_label: "read-acct",
          permissions: ["read"], created_at: "2026-05-21T10:00:00Z",
        },
        {
          id: "tr", exchange_id: "binance", account_label: "trade-acct",
          permissions: ["read", "trade"], created_at: "2026-05-21T10:00:00Z",
        },
      ],
      selectedExchangeId: "binance",
    });
    const { container } = render(<CONNPane />);
    expect(screen.getByText("salt okuma").closest(".ds-pill")).not.toBeNull();
    expect(screen.getByText("okuma + işlem").closest(".ds-pill")).not.toBeNull();
    // Both rendered as design-system pills.
    expect(container.querySelectorAll(".ds-pill").length).toBeGreaterThanOrEqual(2);
  });

  it("shows the Empty state when the selected exchange has no credentials", () => {
    useExchangeStore.setState({ selectedExchangeId: "binance", credentials: [] });
    render(<CONNPane />);
    expect(screen.getByText(/henüz bağlantı yok/i)).toBeInTheDocument();
  });
});

describe("CONN terminal-grade — F5 in-app delete dialog", () => {
  it("Sil opens the in-app ConfirmDialog and confirm triggers delete", async () => {
    useExchangeStore.setState({
      credentials: [{
        id: "abc", exchange_id: "binance", account_label: "main",
        permissions: ["read"], created_at: "2026-05-21T10:00:00Z",
      }],
      selectedExchangeId: "binance",
    });
    vi.spyOn(useExchangeStore.getState(), "dependentBots")
      .mockResolvedValue({ credential_id: "abc", bot_count: 0, bot_ids: [] });
    const del = vi
      .spyOn(useExchangeStore.getState(), "deleteCredential")
      .mockResolvedValue(true);

    render(<CONNPane />);
    fireEvent.click(screen.getByTestId("conn-sil-abc"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    fireEvent.click(within(dialog).getByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(del).toHaveBeenCalledWith("abc", { force: false }));
  });
});

describe("CONN terminal-grade — P2-1 single dependents fetch per Sil click", () => {
  function seedOne() {
    useExchangeStore.setState({
      credentials: [{
        id: "abc", exchange_id: "binance", account_label: "main",
        permissions: ["read"], created_at: "2026-05-21T10:00:00Z",
      }],
      selectedExchangeId: "binance",
    });
  }

  it("no-bots: dependentBots called EXACTLY ONCE, dialog confirms force=false", async () => {
    seedOne();
    const depsSpy = vi
      .spyOn(useExchangeStore.getState(), "dependentBots")
      .mockResolvedValue({ credential_id: "abc", bot_count: 0, bot_ids: [] });
    const del = vi
      .spyOn(useExchangeStore.getState(), "deleteCredential")
      .mockResolvedValue(true);

    render(<CONNPane />);
    fireEvent.click(screen.getByTestId("conn-sil-abc"));
    const dialog = await screen.findByRole("dialog");
    expect(depsSpy).toHaveBeenCalledTimes(1);
    fireEvent.click(within(dialog).getByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(del).toHaveBeenCalledWith("abc", { force: false }));
    // Still exactly one fetch — resolveDeletePlan did NOT re-fetch.
    expect(depsSpy).toHaveBeenCalledTimes(1);
  });

  it("has-bots: dependentBots called EXACTLY ONCE, dialog confirms force=true", async () => {
    seedOne();
    const depsSpy = vi
      .spyOn(useExchangeStore.getState(), "dependentBots")
      .mockResolvedValue({ credential_id: "abc", bot_count: 2, bot_ids: ["b1", "b2"] });
    const del = vi
      .spyOn(useExchangeStore.getState(), "deleteCredential")
      .mockResolvedValue(true);

    render(<CONNPane />);
    fireEvent.click(screen.getByTestId("conn-sil-abc"));
    const dialog = await screen.findByRole("dialog");
    expect(depsSpy).toHaveBeenCalledTimes(1);
    fireEvent.click(within(dialog).getByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(del).toHaveBeenCalledWith("abc", { force: true }));
    expect(depsSpy).toHaveBeenCalledTimes(1);
  });

  it("bots-unknown: ONE fetch, row banner + dialog force=true derive from the SAME fetch", async () => {
    seedOne();
    const depsSpy = vi
      .spyOn(useExchangeStore.getState(), "dependentBots")
      .mockResolvedValue({
        credential_id: "abc", bot_count: 0, bot_ids: [], bots_unknown: true,
      });
    const del = vi
      .spyOn(useExchangeStore.getState(), "deleteCredential")
      .mockResolvedValue(true);

    render(<CONNPane />);
    fireEvent.click(screen.getByTestId("conn-sil-abc"));
    const dialog = await screen.findByRole("dialog");
    expect(depsSpy).toHaveBeenCalledTimes(1);
    // Row-level banner derives from the same single fetch.
    expect(screen.getByTestId("conn-bots-unknown-abc")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(del).toHaveBeenCalledWith("abc", { force: true }));
    expect(depsSpy).toHaveBeenCalledTimes(1);
  });
});

describe("CONN terminal-grade — token guard", () => {
  it("CONN.tsx contains no undefined --fg-1 token", () => {
    const path = resolve(process.cwd(), "src/functions/CONN.tsx");
    const src = readFileSync(path, "utf8");
    expect(src).not.toContain("--fg-1");
  });
});
