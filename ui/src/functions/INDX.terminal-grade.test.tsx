/**
 * INDX — terminal-grade upgrade tests.
 *
 * Covers:
 *  H1 — confidence subjective-disclosure text is present (list + detail) and the
 *       confidence element carries a meter role + aria-valuenow + a subjective title.
 *  H2 — suggested-strategy section is labelled illustrative / "doğrulanmamış".
 *  D1 — INDX.tsx source contains NO dead `--fg-1` token (readFileSync guard).
 *  D2 — confidence renders with role="meter" semantics (not color-only).
 *  S1 — loading + empty list → Skeleton (data-testid="indx-loading").
 *  S2 — error → error state (data-testid="indx-error") with the message.
 *  S3 — no search results → Empty (data-testid="indx-empty").
 *  A1 — search input has a bound label.
 *  A2 — family filter buttons have aria-labels.
 *  A3 — parameter table has a caption + scope="col" on every <th>.
 *  A5 — result count is a role="status" with the right count.
 *
 * Additive; existing INDX + indicator-store suites stay green.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { INDXPane } from "./INDX";
import { useIndicatorStore } from "@/lib/indicator-store";

// Stub the network loader so the empty-list useEffect doesn't run the real
// loadCatalog and clobber the loading/error state we set up per test.
const noopLoad = vi.fn(async () => {});

const __dir = dirname(fileURLToPath(import.meta.url));

const FIXTURES = [
  { id: "rsi", display_name: "RSI", family: "momentum", short_description: "OB/OS",
    long_description: "Wilder", formula: "RSI=100-100/(1+RS)",
    parameters: [{ name: "period", type: "int", default: 14, min: 2, max: 100, effect: "düşür → hızlı" }],
    confidence: 9, confidence_rationale: "range güvenilir",
    suggested_strategy: { name: "MR", summary: "Mean reversion", rules: ["entry", "exit"] },
    references: ["Wilder 1978"] },
  { id: "ema", display_name: "EMA", family: "trend", short_description: "MA",
    long_description: "", formula: "", parameters: [], confidence: 8,
    confidence_rationale: "", suggested_strategy: {}, references: [] },
];

beforeEach(() => {
  useIndicatorStore.setState({
    entries: FIXTURES, loading: false, error: null, selectedId: null, loadCatalog: noopLoad,
  });
});

describe("INDX H1 — subjective confidence disclosure", () => {
  it("shows a list-level subjective-confidence legend (backtest değil)", () => {
    render(<INDXPane />);
    expect(screen.getByText(/öznel editör değerlendirmesi \(backtest değil\)/i)).toBeInTheDocument();
  });

  it("confidence element has a subjective title tooltip", () => {
    render(<INDXPane />);
    const meters = screen.getAllByRole("meter");
    expect(meters.length).toBeGreaterThanOrEqual(1);
    expect(meters[0].getAttribute("title")).toMatch(/öznel/i);
  });

  it("detail rationale heading reads honestly (öznel)", () => {
    render(<INDXPane />);
    fireEvent.click(screen.getByText("RSI"));
    expect(screen.getByText(/Değerlendirme gerekçesi \(öznel\)/i)).toBeInTheDocument();
  });
});

describe("INDX H2 — suggested strategy labelled illustrative", () => {
  it("suggested-strategy heading says doğrulanmamış / illustrative", () => {
    render(<INDXPane />);
    fireEvent.click(screen.getByText("RSI"));
    expect(screen.getByText(/Örnek strateji \(illüstratif — doğrulanmamış\)/i)).toBeInTheDocument();
    expect(screen.getByText(/backtest edilmemiş, doğrulanmamıştır/i)).toBeInTheDocument();
  });
});

describe("INDX D1 — no dead CSS token", () => {
  it("INDX.tsx references no nonexistent --fg-1 token", () => {
    const src = readFileSync(join(__dir, "INDX.tsx"), "utf8");
    expect(src).not.toMatch(/--fg-1\b/);
  });
});

describe("INDX D2 — accessible confidence meter (not color-only)", () => {
  it("confidence has role=meter with aria-valuenow / min / max and visible text", () => {
    render(<INDXPane />);
    fireEvent.click(screen.getByText("RSI"));
    const meters = screen.getAllByRole("meter");
    const detailMeter = meters.find((m) => m.getAttribute("aria-valuenow") === "9");
    expect(detailMeter).toBeTruthy();
    expect(detailMeter!.getAttribute("aria-valuemin")).toBe("0");
    expect(detailMeter!.getAttribute("aria-valuemax")).toBe("10");
    expect(detailMeter!.getAttribute("aria-label")).toMatch(/öznel/i);
    expect(detailMeter!.textContent).toMatch(/9\/10/);
  });
});

describe("INDX S1 — loading state", () => {
  it("shows a Skeleton placeholder while loading + empty", () => {
    useIndicatorStore.setState({ entries: [], loading: true, error: null, selectedId: null });
    render(<INDXPane />);
    expect(screen.getByTestId("indx-loading")).toBeInTheDocument();
  });
});

describe("INDX S2 — error state", () => {
  it("shows an error block with the message instead of a blank pane", () => {
    useIndicatorStore.setState({ entries: [], loading: false, error: "503 boom", selectedId: null });
    render(<INDXPane />);
    const err = screen.getByTestId("indx-error");
    expect(err).toBeInTheDocument();
    expect(err.textContent).toMatch(/503 boom/);
  });
});

describe("INDX S3 — no-results empty state", () => {
  it("renders design-system Empty when search has no matches", () => {
    render(<INDXPane />);
    fireEvent.change(screen.getByLabelText("Indikatör ara"), { target: { value: "xyzzy" } });
    expect(screen.getByTestId("indx-empty")).toBeInTheDocument();
  });
});

describe("INDX A1/A2 — input + family a11y", () => {
  it("search input is reachable by its bound label", () => {
    render(<INDXPane />);
    const input = screen.getByLabelText("Indikatör ara");
    expect(input).toBeInTheDocument();
    expect(input.tagName).toBe("INPUT");
  });

  it("family filter buttons have aria-labels", () => {
    render(<INDXPane />);
    expect(screen.getByLabelText("Aile: momentum")).toBeInTheDocument();
    expect(screen.getByLabelText("Aile: trend")).toBeInTheDocument();
  });
});

describe("INDX A3 — parameter table semantics", () => {
  it("param table has a caption and scope=col on every th", () => {
    render(<INDXPane />);
    fireEvent.click(screen.getByText("RSI"));
    const table = screen.getByText(/period/i).closest("table")!;
    expect(within(table).getByText(/İndikatör parametreleri/i)).toBeInTheDocument();
    const ths = table.querySelectorAll("th");
    expect(ths.length).toBeGreaterThanOrEqual(1);
    ths.forEach((th) => expect(th.getAttribute("scope")).toBe("col"));
  });
});

describe("INDX A5 — result count is role=status", () => {
  it("announces the count and updates on search", () => {
    render(<INDXPane />);
    const status = screen.getByText(/^2 indikatör$/);
    expect(status.getAttribute("role")).toBe("status");
    fireEvent.change(screen.getByLabelText("Indikatör ara"), { target: { value: "rsi" } });
    expect(screen.getByText(/^1 indikatör$/)).toBeInTheDocument();
  });
});
