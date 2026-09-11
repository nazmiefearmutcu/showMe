/**
 * CN alias coverage (AUDIT A10 [M] / AUDIT A2 NI).
 *
 * CN renders the same NIPane component as NI but with distinct behavior that
 * previously had no direct coverage:
 *   - `code="CN"` requests the CN function (company news), not NI;
 *   - with no symbol it falls back to a default equity symbol (palette-cold
 *     renders must pull headlines immediately — 2026-05-11 hotfix);
 *   - a 404 from CN re-issues the query under NI with `topic = <symbol>`;
 *   - the news-limit preference persists under the `showme.cn-news-limit` key.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const runFunctionMock = vi.fn();
const fetchVeryfinderBatchMock = vi.fn();

vi.mock("@/lib/functions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/functions")>();
  return {
    ...actual,
    runFunction: (...args: unknown[]) => runFunctionMock(...args),
  };
});

vi.mock("@/lib/store", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/store")>();
  return {
    ...actual,
    useAppStore: ((selector: (s: { sidecarPort: number | null; sidecarStatus: string; functionIndex: unknown[] }) => unknown) =>
      selector({ sidecarPort: 8421, sidecarStatus: "healthy", functionIndex: [] })) as never,
  };
});

vi.mock("@/lib/tauri", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/tauri")>();
  return {
    ...actual,
    isInTauri: () => false,
    invoke: vi.fn(),
  };
});

vi.mock("@/lib/veryfinder", () => ({
  fetchVeryfinderBatch: (...args: unknown[]) => fetchVeryfinderBatchMock(...args),
  recommendedVeryfinderSampleForNews: () => 5,
}));

import { FunctionCallError } from "@/lib/functions";
import { defaultSymbolForFunction } from "@/lib/symbols";
import { NIPane } from "./NI";

beforeEach(() => {
  localStorage.clear();
  runFunctionMock.mockReset();
  fetchVeryfinderBatchMock.mockReset();
  fetchVeryfinderBatchMock.mockResolvedValue({ ok: true, items: [] });
});
afterEach(() => cleanup());

describe("CN alias (shares NIPane with NI)", () => {
  it("falls back to a default equity symbol when rendered cold without one", async () => {
    runFunctionMock.mockResolvedValue({ status: "ok", data: { articles: [] }, sources: [] });
    render(<NIPane code="CN" />);
    await screen.findByText(/No headlines yet/i);
    const [code, opts] = runFunctionMock.mock.calls[0] as [
      string,
      { symbol?: string; params?: Record<string, unknown> },
    ];
    expect(code).toBe("CN");
    expect(opts.symbol).toBe(defaultSymbolForFunction("CN", ["EQUITY"]));
    expect(opts.symbol).toBeTruthy();
  });

  it("requests CN (not NI) when a symbol is bound", async () => {
    runFunctionMock.mockResolvedValue({ status: "ok", data: { articles: [] }, sources: [] });
    render(<NIPane code="CN" symbol="ACME" />);
    await screen.findByText(/No headlines yet/i);
    const [code, opts] = runFunctionMock.mock.calls[0] as [
      string,
      { symbol?: string },
    ];
    expect(code).toBe("CN");
    expect(opts.symbol).toBe("ACME");
  });

  it("re-issues the query under NI when CN answers 404", async () => {
    runFunctionMock
      .mockRejectedValueOnce(new FunctionCallError("CN: 404 Not Found", 404, "not found"))
      .mockResolvedValueOnce({ status: "ok", data: { articles: [] }, sources: [] });
    render(<NIPane code="CN" symbol="ACME" />);
    await screen.findByText(/No headlines yet/i);
    expect(runFunctionMock).toHaveBeenCalledTimes(2);
    const [firstCode] = runFunctionMock.mock.calls[0] as [string];
    const [secondCode, secondOpts] = runFunctionMock.mock.calls[1] as [
      string,
      { symbol?: string; params?: Record<string, unknown> },
    ];
    expect(firstCode).toBe("CN");
    expect(secondCode).toBe("NI");
    expect(secondOpts.params?.topic).toBe("ACME");
  });

  it("persists the news limit under the CN-specific key", async () => {
    runFunctionMock.mockResolvedValue({ status: "ok", data: { articles: [] }, sources: [] });
    render(<NIPane code="CN" symbol="ACME" />);
    await screen.findByText(/No headlines yet/i);
    // The persisted preference key differs between NI topic mode and CN.
    expect(localStorage.getItem("showme.cn-news-limit")).not.toBeNull();
  });
});
