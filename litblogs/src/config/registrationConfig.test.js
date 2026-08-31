import { describe, expect, it } from "vitest";

import {
  applyPublicRegistrationConfig,
  localPasswordRegistrationEnabledFor,
} from "./registrationConfig";

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

  it("requires both the trusted runtime flag and an eligible development build", () => {
    expect(applyPublicRegistrationConfig(
      { localPasswordRegistrationEnabled: true },
      {
        MODE: "test",
        PROD: false,
        VITE_LOCAL_PASSWORD_REGISTRATION_ENABLED: "true",
      },
    )).toBe(true);
    expect(applyPublicRegistrationConfig(
      { localPasswordRegistrationEnabled: false },
      {
        MODE: "test",
        PROD: false,
        VITE_LOCAL_PASSWORD_REGISTRATION_ENABLED: "true",
      },
    )).toBe(false);
  });

  it("trusts exact runtime true in a production build", () => {
    expect(applyPublicRegistrationConfig(
      { localPasswordRegistrationEnabled: true },
      {
        MODE: "production",
        PROD: true,
      },
    )).toBe(true);
  });

  it.each([undefined, false, "true", 1])(
    "does not let the production build variable enable runtime value %s",
    (runtimeValue) => {
      expect(applyPublicRegistrationConfig(
        { localPasswordRegistrationEnabled: runtimeValue },
        {
          MODE: "production",
          PROD: true,
          VITE_LOCAL_PASSWORD_REGISTRATION_ENABLED: "true",
        },
      )).toBe(false);
    },
  );
});
