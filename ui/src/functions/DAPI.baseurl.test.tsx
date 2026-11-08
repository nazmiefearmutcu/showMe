/**
 * DAPI pane — base URL comes from the sidecar connection (p2a-g11).
 *
 * The engine returns summary.base_url as null (it does not know the bound
 * port). The pane must use the sidecar address it is connected to, never the
 * literal "<sidecar-port>" template, in both the Base URL detail and cURL copy.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DAPIPane } from "./DAPI";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/lib/sidecar", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/sidecar")>()),
  sidecarBaseUrl: () => "http://127.0.0.1:9911",
}));

function payloadWithNullBaseUrl() {
  return {
    data: {
      sources: ["showme_fastapi_routes_curated"],
      elapsed_ms: 2,
      data: {
        rows: [
          {
            method: "GET",
            path: "/api/health",
            purpose: "Sidecar and engine health check.",
            request_body: "-",
            response_shape: "{ ok }",
            mutates_state: "no",
            example: "/api/health",
          },
        ],
        summary: {
          base_url: null,
          endpoints: 1,
          total_routes: 1,
          state_changing: 0,
          source_mode: "curated_manifest",
        },
        methodology: "test",
      },
    },
  };
}

afterEach(() => {
  cleanup();
  Reflect.deleteProperty(navigator, "clipboard");
});

describe("DAPI pane — base URL from the sidecar connection (p2a-g11)", () => {
  it("shows the connected sidecar address, never the placeholder", () => {
    mockFn.state = "ok";
    mockFn.data = payloadWithNullBaseUrl().data;
    mockFn.error = null;
    const { container } = render(<DAPIPane code="DAPI" />);
    fireEvent.click(screen.getByText("/api/health"));
    expect(screen.getByText("Base URL").nextElementSibling?.textContent).toBe(
      "http://127.0.0.1:9911",
    );
    expect(container.textContent).not.toContain("<sidecar-port>");
  });

  it("copies a runnable cURL against the connected sidecar address", () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    mockFn.state = "ok";
    mockFn.data = payloadWithNullBaseUrl().data;
    mockFn.error = null;
    render(<DAPIPane code="DAPI" />);
    fireEvent.click(screen.getByText("/api/health"));
    fireEvent.click(screen.getByLabelText("Copy GET /api/health as cURL"));
    expect(writeText).toHaveBeenCalledTimes(1);
    const curl = writeText.mock.calls[0][0] as string;
    expect(curl).toContain('"http://127.0.0.1:9911/api/health"');
    expect(curl).not.toContain("<sidecar-port>");
  });
});
