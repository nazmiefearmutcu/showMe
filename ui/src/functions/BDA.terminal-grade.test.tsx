/**
 * BDA — terminal-grade / honesty-first upgrade tests.
 *
 * Covers:
 *  F1 — de-overclaim help caption (keyword, not NLP) + supported-indicator list.
 *       severity-coded notes: an "ignored" note renders with the warn testid.
 *  F2 — a11y: textarea bound label + aria-describedby; error region role=status;
 *       result region is a labelled live region; generate button aria-busy.
 *  F3 — Skeleton while loadingGenerate+no result; Empty initial state;
 *       Cmd/Ctrl+Enter triggers generate.
 *  F4 — explanation rendered monospace.
 *
 * Additive; the existing BDA suites stay green.
 */
import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BDAPane } from "./BDA";
import { useAssistantStore } from "@/lib/assistant-store";
import { useStrategyStore } from "@/lib/strategy-store";

beforeEach(() => {
  useAssistantStore.setState({
    text: "", result: null, explanation: null,
    loading: false, loadingGenerate: false, loadingExplain: false,
    error: null,
    generate: vi.fn(async () => null) as never,
    explainStrategy: vi.fn(async () => null) as never,
    setText: useAssistantStore.getState().setText,
  });
  useStrategyStore.setState({
    strategies: [
      { id: "s1", name: "RSI MR", description: "", timeframe: "1h",
        created_at: "", updated_at: "" },
    ],
    draft: null, draftIsNew: false, dirty: false,
    loading: false, removing: false, error: null, lastPreview: null,
    loadList: vi.fn(async () => {}),
  });
});

describe("BDA F1 — de-overclaim + supported indicators", () => {
  it("shows a help caption that says it is keyword-based, not real NLP", () => {
    render(<BDAPane />);
    const help = screen.getByTestId("bda-help");
    expect(help).toBeInTheDocument();
    expect(help.textContent).toMatch(/gerçek NLP değil/i);
  });

  it("help caption lists supported indicators", () => {
    render(<BDAPane />);
    const help = screen.getByTestId("bda-help");
    expect(help.textContent).toMatch(/RSI/);
    expect(help.textContent).toMatch(/MACD/);
    expect(help.textContent).toMatch(/Bollinger/);
    expect(help.textContent).toMatch(/Ichimoku/);
  });
});

describe("BDA F1 — severity-coded notes", () => {
  it("renders an ignored/warn note with the warn testid and tone class", () => {
    useAssistantStore.setState({
      result: {
        spec: { name: "X" } as never,
        notes: [
          "Tanınan indikatör: rsi (alias=rsi14)",
          "⚠ 'divergence' desteklenmiyor — yok sayıldı",
        ],
        saved_id: null,
      },
    });
    render(<BDAPane />);
    const warn = screen.getByTestId("bda-note-warn");
    expect(warn).toBeInTheDocument();
    expect(warn.textContent).toMatch(/yok sayıldı/);
    expect(warn.className).toMatch(/u-text-warn/);
  });

  it("renders a default-disclosure note as info (muted, not warn)", () => {
    useAssistantStore.setState({
      result: {
        spec: { name: "X" } as never,
        notes: ["Timeframe: 1h (varsayılan — belirtilmedi)"],
        saved_id: null,
      },
    });
    render(<BDAPane />);
    expect(screen.queryByTestId("bda-note-warn")).toBeNull();
    const note = screen.getByText(/varsayılan — belirtilmedi/);
    expect(note.className).toMatch(/u-text-mute/);
  });

  it("renders a catalog-failure note as negative", () => {
    useAssistantStore.setState({
      result: {
        spec: { name: "X" } as never,
        notes: ["katalog doğrulaması başarısız: unknown indicator id: foo"],
        saved_id: null,
      },
    });
    render(<BDAPane />);
    const warn = screen.getByTestId("bda-note-warn");
    expect(warn.className).toMatch(/u-text-negative/);
  });
});

describe("BDA F2 — accessibility", () => {
  it("textarea has a bound label and aria-describedby pointing at help", () => {
    render(<BDAPane />);
    const ta = document.getElementById("bda-text") as HTMLTextAreaElement;
    expect(ta).toBeTruthy();
    // label[for=bda-text] exists
    const label = document.querySelector('label[for="bda-text"]');
    expect(label).toBeTruthy();
    expect(ta.getAttribute("aria-describedby")).toContain("bda-help");
  });

  it("error region has role=status and negative styling", () => {
    useAssistantStore.setState({ error: "boom" });
    render(<BDAPane />);
    const err = screen.getByTestId("bda-error");
    expect(err.getAttribute("role")).toBe("status");
    expect(err.className).toMatch(/u-text-negative/);
  });

  it("result region is a labelled live region", () => {
    useAssistantStore.setState({
      result: { spec: { name: "X" } as never, notes: ["n"], saved_id: null },
    });
    render(<BDAPane />);
    const region = screen.getByTestId("bda-result");
    expect(region.getAttribute("role")).toBe("region");
    expect(region.getAttribute("aria-label")).toBeTruthy();
    expect(region.getAttribute("aria-live")).toBe("polite");
  });

  it("generate button exposes aria-busy when loadingGenerate", () => {
    useAssistantStore.setState({ text: "RSI", loadingGenerate: true });
    render(<BDAPane />);
    const gen = screen.getByTestId("bda-generate-button");
    expect(gen.getAttribute("aria-busy")).toBe("true");
  });
});

describe("BDA F3 — states + usability", () => {
  it("shows a Skeleton while loadingGenerate and no result yet", () => {
    useAssistantStore.setState({ text: "RSI", loadingGenerate: true, result: null });
    render(<BDAPane />);
    expect(screen.getByTestId("bda-generate-loading")).toBeInTheDocument();
  });

  it("shows the Empty initial state before the first parse", () => {
    render(<BDAPane />);
    expect(screen.getByTestId("bda-empty")).toBeInTheDocument();
  });

  it("Cmd/Ctrl+Enter in the textarea triggers generate", () => {
    const generateSpy = vi.fn(async () => null);
    useAssistantStore.setState({ text: "RSI 30 altında", generate: generateSpy as never });
    render(<BDAPane />);
    const ta = document.getElementById("bda-text") as HTMLTextAreaElement;
    fireEvent.keyDown(ta, { key: "Enter", metaKey: true });
    expect(generateSpy).toHaveBeenCalledWith(false);
  });
});

describe("BDA F4 — display", () => {
  it("renders the explanation in a monospace container", () => {
    useAssistantStore.setState({ explanation: "RSI strateji TR özet" });
    render(<BDAPane />);
    const exp = screen.getByTestId("bda-explanation");
    expect(exp.textContent).toMatch(/RSI strateji TR özet/);
    expect(exp.style.fontFamily).toMatch(/font-mono/);
  });
});
