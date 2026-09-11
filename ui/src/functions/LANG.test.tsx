/**
 * LANG pane — data-honesty + render-contract tests.
 *
 * Pins the LANG language-switch contract:
 *  - the load states render (loading / error / ok);
 *  - the switcher lists the terminal's real locales from @/i18n
 *    `listLocales()` (12 entries), NOT a hardcoded subset;
 *  - coverage pills are honest: computed with `isLocaleComplete()`, and
 *    the coverage note says function panes hardcode English;
 *  - the sidecar persisted value is surfaced separately from the active
 *    UI locale (two different things — never conflated);
 *  - one interaction: clicking a locale APPLIES it through the real i18n
 *    mechanism (document lang attr flips, aria-pressed moves).
 *
 * `useFunction` is mocked; the real @/i18n module is exercised (jsdom)
 * and reset to "en" after every test.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { LANGPane } from "./LANG";
import { isLocaleComplete, listLocales, locale, setLocale } from "@/i18n";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: {
    data?: unknown;
    warnings?: string[];
    sources?: string[];
    elapsed_ms?: number;
  } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

// SymbolBar pulls router/symbol-resolver side effects we don't need here.
vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function registryPayload(persisted: string) {
  return {
    warnings: [],
    sources: ["showme_i18n_registry"],
    elapsed_ms: 12,
    data: {
      status: "ready",
      lang: persisted,
      rows: listLocales().map((loc) => ({
        lang: loc,
        label:
          loc === "en"
            ? "English"
            : loc === "tr"
              ? "Turkish"
              : loc === "de"
                ? "German"
                : loc,
        selected: loc === persisted,
        coverage: "core_labels",
        requires_reload: loc === persisted,
      })),
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  setLocale("en");
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
  setLocale("en");
});

describe("LANG pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<LANGPane code="LANG" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the registry call fails", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<LANGPane code="LANG" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the locale grid when the registry answers", () => {
    setMockFn({ state: "ok", data: registryPayload("en") });
    const { container } = render(<LANGPane code="LANG" />);
    const grid = screen.getByRole("grid", { name: /locale options/i });
    expect(grid).toBeTruthy();
    expect(container.querySelectorAll("tbody tr").length).toBe(listLocales().length);
    expect(container.textContent).toContain("Turkish");
    expect(container.textContent).toContain("German");
  });
});

describe("LANG pane — honesty", () => {
  it("lists exactly the terminal locales from @/i18n (12, no invented ones)", () => {
    setMockFn({ state: "ok", data: registryPayload("en") });
    render(<LANGPane code="LANG" />);
    for (const loc of listLocales()) {
      expect(
        screen.getAllByText(loc.toUpperCase()).length,
      ).toBeGreaterThan(0);
    }
  });

  it("surfaces the sidecar-persisted value separately from the active UI locale", () => {
    setMockFn({ state: "ok", data: registryPayload("tr") });
    render(<LANGPane code="LANG" />);
    const kpis = screen.getByRole("region", { name: /LANG KPI ribbon/i });
    expect(kpis.textContent).toContain("TR");
    expect(kpis.textContent).toContain("runtime/lang.txt");
  });

  it("states the translation-coverage truth (function panes stay English)", () => {
    setMockFn({ state: "ok", data: registryPayload("en") });
    render(<LANGPane code="LANG" />);
    expect(
      screen.getByRole("status", { name: /translation coverage note/i }),
    ).toHaveTextContent(/function panes hardcode English/i);
  });
});

describe("LANG pane — interaction (applies through @/i18n)", () => {
  it("switches the UI locale when a locale row is clicked", () => {
    setMockFn({ state: "ok", data: registryPayload("en") });
    render(<LANGPane code="LANG" />);
    expect(locale()).toBe("en");
    // The locale code cell carries the actionable title; the click bubbles
    // to the row's onRowClick.
    fireEvent.click(screen.getByTitle("Switch UI language to German"));
    // The real i18n module applied the change to the document.
    expect(locale()).toBe("de");
    expect(document.documentElement.getAttribute("lang")).toBe("de");
    // The active column now marks German.
    expect(
      within(screen.getByRole("grid", { name: /locale options/i })).getByText("active"),
    ).toBeInTheDocument();
  });
});

describe("LANG pane — grid upgrade (L7)", () => {
  it("filters the locale grid from the search box", () => {
    setMockFn({ state: "ok", data: registryPayload("en") });
    const { container } = render(<LANGPane code="LANG" />);
    fireEvent.change(screen.getByLabelText("Filter locales"), {
      target: { value: "german" },
    });
    expect(container.querySelectorAll("tbody tr").length).toBe(1);
    expect(container.textContent).toContain("German");
    // Clearing restores the full set.
    fireEvent.change(screen.getByLabelText("Filter locales"), {
      target: { value: "" },
    });
    expect(container.querySelectorAll("tbody tr").length).toBe(listLocales().length);
  });

  it("sorts the coverage matrix from the header", () => {
    setMockFn({ state: "ok", data: registryPayload("en") });
    const { container } = render(<LANGPane code="LANG" />);
    const complete = listLocales().find((l) => isLocaleComplete(l));
    expect(complete).toBeTruthy();
    fireEvent.click(screen.getByRole("columnheader", { name: /Coverage/i }));
    // Shell-complete locales rank above shell-labels-only locales.
    expect(container.querySelector("tbody tr")?.textContent).toContain(
      String(complete).toUpperCase(),
    );
  });

  it("shows the honest empty state when the filter matches nothing", () => {
    setMockFn({ state: "ok", data: registryPayload("en") });
    render(<LANGPane code="LANG" />);
    fireEvent.change(screen.getByLabelText("Filter locales"), {
      target: { value: "zzzz" },
    });
    expect(screen.getByText(/No locales match/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filter" }));
    expect(screen.queryByText(/No locales match/i)).toBeNull();
  });
});
