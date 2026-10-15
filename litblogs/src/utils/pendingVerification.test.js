import { beforeEach, describe, expect, it } from "vitest";
import { clearPendingVerification, getPendingVerification, rememberPendingVerification } from "./pendingVerification";

const NOW = Date.parse("2026-10-15T12:00:00Z");
const detail = {
  code: "email_verification_required",
  email: "student@example.com",
  verification_challenge: "synthetic-pending-challenge",
  expires_at: "2026-10-15T12:15:00Z",
  teacher_code_allowed: true,
};

beforeEach(clearPendingVerification);

describe("pending verification memory", () => {
  it("retains a bounded challenge in memory without using browser storage", () => {
    expect(rememberPendingVerification(detail, NOW)).toBe(true);
    expect(getPendingVerification(NOW)?.challenge).toBe(detail.verification_challenge);
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain(detail.verification_challenge);
    clearPendingVerification();
    expect(getPendingVerification(NOW)).toBeNull();
  });

  it("drops an expired challenge and never revives it by moving the clock back", () => {
    rememberPendingVerification(detail, NOW);
    expect(getPendingVerification(NOW + 900_000)?.challenge).toBeNull();
    expect(getPendingVerification(NOW)?.challenge).toBeNull();
  });

  it.each(["", "x".repeat(4097), null])("does not retain invalid challenge %s", (challenge) => {
    rememberPendingVerification({ ...detail, verification_challenge: challenge }, NOW);
    expect(getPendingVerification(NOW)?.challenge).toBeNull();
  });

  it("clears an old challenge if the new login response is unrelated", () => {
    rememberPendingVerification(detail, NOW);
    expect(rememberPendingVerification({ code: "unrelated" }, NOW)).toBe(false);
    expect(getPendingVerification(NOW)).toBeNull();
  });
});
