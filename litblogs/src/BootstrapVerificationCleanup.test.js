import { beforeEach, expect, it, vi } from "vitest";

const doubles = vi.hoisted(() => ({
  captureReset: vi.fn(),
  captureVerification: vi.fn(),
  clearVerification: vi.fn(),
}));

vi.mock("./utils/resetToken", () => ({
  capturePasswordResetTokenAtBootstrap: doubles.captureReset,
}));

vi.mock("./utils/verificationToken", () => ({
  captureEmailVerificationTokenAtBootstrap: doubles.captureVerification,
  clearBootstrappedEmailVerificationToken: doubles.clearVerification,
}));

vi.mock("./main.jsx", () => {
  throw new Error("synthetic main chunk failure");
});

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
});

it("clears a captured verification secret if the main application chunk fails", async () => {
  await import("./bootstrap.js");

  expect(doubles.captureVerification).toHaveBeenCalledOnce();
  await vi.waitFor(() => expect(doubles.clearVerification).toHaveBeenCalledOnce());
});
