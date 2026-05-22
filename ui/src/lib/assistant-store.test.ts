import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAssistantStore } from "./assistant-store";

vi.mock("./sidecar", () => ({ sidecarFetch: vi.fn() }));
import { sidecarFetch } from "./sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

beforeEach(() => {
  useAssistantStore.setState({
    text: "", result: null, explanation: null, loading: false, error: null,
  });
  mock.mockReset();
});

describe("assistant-store", () => {
  it("setText updates text", () => {
    useAssistantStore.getState().setText("RSI strategy");
    expect(useAssistantStore.getState().text).toBe("RSI strategy");
  });

  it("generate POSTs and stores result", async () => {
    mock.mockResolvedValueOnce({
      spec: { name: "X" }, notes: ["ok"], saved_id: null,
    });
    useAssistantStore.getState().setText("RSI 30 altında");
    const r = await useAssistantStore.getState().generate(false);
    expect(r?.spec).not.toBeNull();
    expect(useAssistantStore.getState().result?.notes).toEqual(["ok"]);
    const body = JSON.parse(String((mock.mock.calls[0][1] as RequestInit).body));
    expect(body.text).toBe("RSI 30 altında");
    expect(body.save).toBe(false);
  });

  it("generate passes save=true through", async () => {
    mock.mockResolvedValueOnce({ spec: { name: "X" }, notes: [], saved_id: "abc" });
    useAssistantStore.getState().setText("MACD");
    await useAssistantStore.getState().generate(true);
    const body = JSON.parse(String((mock.mock.calls[0][1] as RequestInit).body));
    expect(body.save).toBe(true);
  });

  it("explainStrategy POSTs and stores explanation", async () => {
    mock.mockResolvedValueOnce({ explanation: "TR summary text" });
    const r = await useAssistantStore.getState().explainStrategy("sid");
    expect(r).toBe("TR summary text");
    expect(useAssistantStore.getState().explanation).toBe("TR summary text");
  });

  it("generate surfaces errors", async () => {
    mock.mockRejectedValueOnce(new Error("503"));
    await useAssistantStore.getState().generate();
    expect(useAssistantStore.getState().error).toContain("503");
  });
});
