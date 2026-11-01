import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Event, EventCallback, UnlistenFn } from "@tauri-apps/api/event";
import { Window as TauriWindow } from "@tauri-apps/api/window";
import { invoke } from "./tauri";
import { useWorkspace } from "./workspace";
import { startWorkspaceAutosave } from "./workspace-persist";

vi.mock("./tauri", () => ({
  isInTauri: () => true,
  invoke: vi.fn(),
}));

const nativeCloseEvent: Event<unknown> = {
  event: "tauri://close-requested",
  id: 1,
  payload: null,
};

describe("workspace autosave on native close", () => {
  let dispose: (() => void) | undefined;
  let closeListener: EventCallback<unknown> | undefined;
  let unlisten: ReturnType<typeof vi.fn>;
  let originalInternals: PropertyDescriptor | undefined;

  beforeEach(() => {
    localStorage.clear();
    useWorkspace.getState().resetTo("HOME");
    vi.mocked(invoke).mockReset().mockResolvedValue(undefined);
    originalInternals = Object.getOwnPropertyDescriptor(window, "__TAURI_INTERNALS__");
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      configurable: true,
      value: { metadata: { currentWindow: { label: "main" } } },
    });
    unlisten = vi.fn();
    closeListener = undefined;
    // Exercise the installed Tauri onCloseRequested implementation, including
    // its awaited handler and destroy call; stub only the native IPC boundary.
    vi.spyOn(TauriWindow.prototype, "listen").mockImplementation(
      async (_event, handler) => {
        closeListener = handler as EventCallback<unknown>;
        return unlisten;
      },
    );
    vi.spyOn(TauriWindow.prototype, "destroy").mockResolvedValue(undefined);
  });

  afterEach(() => {
    dispose?.();
    dispose = undefined;
    vi.restoreAllMocks();
    if (originalInternals) {
      Object.defineProperty(window, "__TAURI_INTERNALS__", originalInternals);
    } else {
      Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
    }
  });

  it("waits for the last workspace save before destroying the native window", async () => {
    let finishSave!: () => void;
    vi.mocked(invoke).mockReturnValue(
      new Promise<void>((resolve) => {
        finishSave = resolve;
      }),
    );
    dispose = startWorkspaceAutosave();
    useWorkspace.getState().splitFocused("h", { code: "GP", symbol: "MSFT" });
    await vi.dynamicImportSettled();
    expect(closeListener).toBeDefined();

    const closing = closeListener!(nativeCloseEvent);
    await vi.dynamicImportSettled();
    expect(invoke).toHaveBeenCalledWith("save_workspace", {
      content: expect.objectContaining({
        tree: expect.objectContaining({ kind: "split" }),
      }),
      label: "main",
    });
    expect(TauriWindow.prototype.destroy).not.toHaveBeenCalled();

    finishSave();
    await closing;
    expect(TauriWindow.prototype.destroy).toHaveBeenCalledOnce();
  });

  it("still closes when both the native save and browser fallback fail", async () => {
    const nativeError = new Error("native save failed");
    const fallbackError = new Error("storage unavailable");
    vi.mocked(invoke).mockRejectedValue(nativeError);
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw fallbackError;
    });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    dispose = startWorkspaceAutosave();
    await vi.dynamicImportSettled();

    await closeListener!(nativeCloseEvent);

    expect(TauriWindow.prototype.destroy).toHaveBeenCalledOnce();
    expect(warn).toHaveBeenCalledWith("workspace flush failed during close", fallbackError);
  });

  it("removes the native listener and pending debounce when disposed", async () => {
    vi.useFakeTimers();
    try {
      dispose = startWorkspaceAutosave();
      await vi.dynamicImportSettled();
      useWorkspace.getState().splitFocused("h", { code: "GP", symbol: "MSFT" });

      dispose();
      dispose();
      useWorkspace.getState().resetTo("HOME");
      window.dispatchEvent(new window.Event("beforeunload"));
      await vi.advanceTimersByTimeAsync(500);

      expect(unlisten).toHaveBeenCalledOnce();
      expect(invoke).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("skips listener registration if disposed before the dynamic import resolves", async () => {
    dispose = startWorkspaceAutosave();
    dispose();
    await vi.dynamicImportSettled();

    expect(TauriWindow.prototype.listen).not.toHaveBeenCalled();
  });

  it("detaches a native listener whose registration resolves after disposal", async () => {
    let finishRegistration!: (value: UnlistenFn) => void;
    vi.mocked(TauriWindow.prototype.listen).mockImplementation(
      () =>
        new Promise<UnlistenFn>((resolve) => {
          finishRegistration = resolve;
        }),
    );
    dispose = startWorkspaceAutosave();
    await vi.dynamicImportSettled();
    expect(TauriWindow.prototype.listen).toHaveBeenCalledOnce();

    dispose();
    finishRegistration(unlisten);
    await vi.waitFor(() => expect(unlisten).toHaveBeenCalledOnce());
  });
});
