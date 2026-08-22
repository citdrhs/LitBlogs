import { describe, expect, it } from "vitest";

import { localPasswordRegistrationEnabledFor } from "./registrationConfig";

describe("local password registration configuration", () => {
  it.each(["development", "test"])("requires an explicit opt-in in %s", (mode) => {
    expect(localPasswordRegistrationEnabledFor({
      MODE: mode,
      PROD: false,
      VITE_LOCAL_PASSWORD_REGISTRATION_ENABLED: "true",
    })).toBe(true);
    expect(localPasswordRegistrationEnabledFor({ MODE: mode, PROD: false })).toBe(false);
  });

  it("fails closed in production even when a build variable requests it", () => {
    expect(localPasswordRegistrationEnabledFor({
      MODE: "production",
      PROD: true,
      VITE_LOCAL_PASSWORD_REGISTRATION_ENABLED: "true",
    })).toBe(false);
  });

  it.each(["1", "yes", "TRUE ", "enabled"])("rejects ambiguous opt-in value %s", (value) => {
    expect(localPasswordRegistrationEnabledFor({
      MODE: "development",
      PROD: false,
      VITE_LOCAL_PASSWORD_REGISTRATION_ENABLED: value,
    })).toBe(false);
  });
});
