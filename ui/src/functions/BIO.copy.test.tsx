/**
 * BIO pane — unavailable-biometry copy (p2a-g11).
 *
 * Biometry is macOS-only, so when it is absent the card must name that real
 * limit rather than claim it is "only available in the desktop app" (which is
 * misleading on Windows, where the desktop app is running).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type {
  BiometricCapabilities,
  BiometricResult,
} from "@/lib/biometric";
import { BIOPane } from "./BIO";

const UNAVAILABLE_CAPS: BiometricCapabilities = {
  biometry_available: false,
  passcode_available: false,
  biometry_kind: "none",
};

const UNAVAILABLE_RESULT: BiometricResult = {
  allowed: false,
  reason: "test",
  via: "unavailable",
  capabilities: UNAVAILABLE_CAPS,
};

vi.mock("@/lib/biometric", () => ({
  capabilities: () => Promise.resolve(UNAVAILABLE_CAPS),
  requestBiometric: () => Promise.resolve(UNAVAILABLE_RESULT),
}));

afterEach(() => {
  cleanup();
});

describe("BIO pane — unavailable biometry copy (p2a-g11)", () => {
  it("names the real limit (macOS builds) instead of the desktop app", async () => {
    render(<BIOPane code="BIO" />);
    expect(
      await screen.findByText("Touch ID / Face ID is available in macOS builds only"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/only available in the desktop app/i)).toBeNull();
  });
});
