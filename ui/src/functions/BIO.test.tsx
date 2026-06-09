/**
 * BIO pane — a11y + display + honesty contract.
 *
 * BIO is the biometric-unlock STATUS pane. After the bridge fix it is honest in
 * browser/test contexts: there is no LocalAuthentication, so capabilities report
 * unavailable and a Verify click resolves DENIED via "Kullanılamıyor" — these
 * tests pin that truthfulness alongside the a11y upgrades:
 *
 *  - A1: StatusCards carry an aria-label stating label + state (not colour-only);
 *  - A2: the Verify button reports aria-busy while a verify is in flight;
 *  - A3: the load skeleton lives in a scoped role=status region (gone once cards
 *        render — the steady-state grid is NOT wrapped);
 *  - D1: biometry kind + verify `via` render as human labels (Touch ID, not the
 *        raw enum; an unavailable via → "Kullanılamıyor");
 *  - D2: last-verify freshness uses a relative label, with an honest "henüz yok"
 *        sentinel when nothing has been verified yet.
 *
 * `@/lib/biometric` is mocked via mutable shared state so each test drives the
 * pane into a branch without the real Tauri bridge.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type {
  BiometricCapabilities,
  BiometricResult,
} from "@/lib/biometric";
import { BIOPane } from "./BIO";

/* ── @/lib/biometric mock ──────────────────────────────────────────────── */

interface MockBioState {
  caps: BiometricCapabilities;
  result: BiometricResult;
  /** Hold the next capabilities() resolution open so we can assert the load UI. */
  pendingCaps: boolean;
  /** Hold requestBiometric() open so we can assert the verify busy state. */
  pendingVerify: boolean;
}

const UNAVAILABLE_CAPS: BiometricCapabilities = {
  biometry_available: false,
  passcode_available: false,
  biometry_kind: "none",
};

const mockBio: MockBioState = {
  caps: UNAVAILABLE_CAPS,
  result: {
    allowed: false,
    reason: "test",
    via: "unavailable",
    capabilities: UNAVAILABLE_CAPS,
  },
  pendingCaps: false,
  pendingVerify: false,
};

let releaseCaps: (() => void) | null = null;
let releaseVerify: (() => void) | null = null;

vi.mock("@/lib/biometric", () => ({
  capabilities: () =>
    mockBio.pendingCaps
      ? new Promise<BiometricCapabilities>((resolve) => {
          releaseCaps = () => resolve(mockBio.caps);
        })
      : Promise.resolve(mockBio.caps),
  requestBiometric: () =>
    mockBio.pendingVerify
      ? new Promise<BiometricResult>((resolve) => {
          releaseVerify = () => resolve(mockBio.result);
        })
      : Promise.resolve(mockBio.result),
}));

beforeEach(() => {
  mockBio.caps = UNAVAILABLE_CAPS;
  mockBio.result = {
    allowed: false,
    reason: "test",
    via: "unavailable",
    capabilities: UNAVAILABLE_CAPS,
  };
  mockBio.pendingCaps = false;
  mockBio.pendingVerify = false;
  releaseCaps = null;
  releaseVerify = null;
});
afterEach(() => {
  cleanup();
});

/* ── A3 — scoped load region ───────────────────────────────────────────── */

describe("BIO pane — load state (A3)", () => {
  it("announces the load skeleton in a role=status region, gone once cards render", async () => {
    mockBio.pendingCaps = true;
    const { container } = render(<BIOPane code="BIO" />);
    // While capabilities() is in flight the skeleton sits in an aria-busy status.
    const busy = container.querySelector('[role="status"][aria-busy="true"]');
    expect(busy).not.toBeNull();

    // Resolve capabilities → cards mount, the load region disappears.
    await act(async () => {
      releaseCaps?.();
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(
        container.querySelector('[role="status"][aria-busy="true"]'),
      ).toBeNull();
    });
  });
});

/* ── A1 — card aria-labels + A2 verify button + D1 display ──────────────── */

describe("BIO pane — a11y + display (loaded)", () => {
  it("labels the biometry + last-verify cards with their state (A1)", async () => {
    mockBio.caps = {
      biometry_available: true,
      passcode_available: true,
      biometry_kind: "touch_id",
    };
    render(<BIOPane code="BIO" />);
    // The biometry card name carries the kind + availability (not colour-only).
    expect(
      await screen.findByLabelText(/Biometry: Touch ID/i),
    ).toBeInTheDocument();
    // Last-verify card carries its state in the accessible name.
    expect(screen.getByLabelText(/Last verify:/i)).toBeInTheDocument();
  });

  it("renders biometry kind as a human label, not the raw enum (D1)", async () => {
    mockBio.caps = {
      biometry_available: true,
      passcode_available: true,
      biometry_kind: "touch_id",
    };
    render(<BIOPane code="BIO" />);
    expect(await screen.findByText("Touch ID")).toBeInTheDocument();
    expect(screen.queryByText("TOUCH ID")).toBeNull();
  });

  it("shows no fabricated time before any verify; a relative label after (D2)", async () => {
    render(<BIOPane code="BIO" />);
    // Before any verify: honest prompt copy, never a fabricated English "ago".
    const before = await screen.findByLabelText(/Last verify: NOT RUN/i);
    expect(before.textContent ?? "").toMatch(/click verify to open OS prompt/i);
    expect(before.textContent ?? "").not.toMatch(/ago/i);

    // After a verify, the freshness is a shared relative label ("az önce"),
    // not the old hand-rolled "Ns ago" / "never".
    const btn = screen.getByRole("button", {
      name: /Biyometrik doğrulama iste/i,
    });
    fireEvent.click(btn);
    const after = await screen.findByLabelText(/Last verify: DENIED/i);
    expect(after.textContent ?? "").toMatch(/az önce/i);
    expect(after.textContent ?? "").not.toMatch(/ago/i);
    expect(after.textContent ?? "").not.toMatch(/never/i);
  });

  it("Verify reports aria-busy while a verify is in flight (A2)", async () => {
    mockBio.caps = {
      biometry_available: true,
      passcode_available: true,
      biometry_kind: "touch_id",
    };
    // Hold requestBiometric open so we can observe the busy state.
    mockBio.pendingVerify = true;

    render(<BIOPane code="BIO" />);
    const btn = await screen.findByRole("button", {
      name: /Biyometrik doğrulama iste/i,
    });
    expect(btn).toHaveAttribute("aria-busy", "false");

    fireEvent.click(btn);
    await waitFor(() => expect(btn).toHaveAttribute("aria-busy", "true"));

    await act(async () => {
      releaseVerify?.();
      await Promise.resolve();
    });
    await waitFor(() => expect(btn).toHaveAttribute("aria-busy", "false"));
  });

  it("renders an unavailable verify `via` as 'Kullanılamıyor' (D1, honesty)", async () => {
    // Browser/test mode: clicking Verify honestly resolves DENIED via unavailable.
    mockBio.result = {
      allowed: false,
      reason: "test",
      via: "unavailable",
      capabilities: UNAVAILABLE_CAPS,
    };
    render(<BIOPane code="BIO" />);
    const btn = await screen.findByRole("button", {
      name: /Biyometrik doğrulama iste/i,
    });
    fireEvent.click(btn);
    const lastCard = await screen.findByLabelText(/Last verify: DENIED/i);
    expect(lastCard.textContent ?? "").toMatch(/Kullanılamıyor/i);
  });
});
