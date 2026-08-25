import { describe, expect, it } from "vitest";

import * as oauthConfiguration from "./msalConfig.js";

describe("Microsoft browser token cache", () => {
  it("keeps provider credentials in memory instead of browser storage", () => {
    expect(oauthConfiguration.msalConfig.cache.cacheLocation).toBe("memoryStorage");
    expect(oauthConfiguration.msalConfig.cache.storeAuthStateInCookie).toBe(false);
  });
});

describe("public OAuth environment configuration", () => {
  it("exports a testable fail-closed configuration builder", () => {
    expect(typeof oauthConfiguration.buildOAuthProviderConfig).toBe("function");
    if (typeof oauthConfiguration.buildOAuthProviderConfig !== "function") return;

    expect(oauthConfiguration.buildOAuthProviderConfig({})).toEqual({
      google: { clientId: "", enabled: false },
      microsoft: { clientId: "", tenantId: "", enabled: false },
    });
  });

  it("accepts only public Vite IDs and builds a tenant-specific authority", () => {
    expect(typeof oauthConfiguration.buildOAuthProviderConfig).toBe("function");
    expect(typeof oauthConfiguration.buildMsalConfig).toBe("function");
    if (
      typeof oauthConfiguration.buildOAuthProviderConfig !== "function" ||
      typeof oauthConfiguration.buildMsalConfig !== "function"
    ) return;

    const env = {
      VITE_GOOGLE_CLIENT_ID: "987654321.apps.googleusercontent.com",
      VITE_MICROSOFT_CLIENT_ID: "2f1c67a1-91e2-46a3-941f-b88e31763e51",
      VITE_MICROSOFT_TENANT_ID: "871bd3e0-2dc0-4a40-9b07-9d03068c2364",
      VITE_MICROSOFT_CLIENT_SECRET: "must-never-be-consumed-by-vite",
    };
    const providers = oauthConfiguration.buildOAuthProviderConfig(env);
    const selectedMsalConfig = oauthConfiguration.buildMsalConfig(
      providers.microsoft,
      "https://litblogs.school.example",
    );

    expect(providers.google).toEqual({
      clientId: env.VITE_GOOGLE_CLIENT_ID,
      enabled: true,
    });
    expect(providers.microsoft).toEqual({
      clientId: env.VITE_MICROSOFT_CLIENT_ID,
      tenantId: env.VITE_MICROSOFT_TENANT_ID,
      enabled: true,
    });
    expect(selectedMsalConfig.auth).toMatchObject({
      clientId: env.VITE_MICROSOFT_CLIENT_ID,
      authority: `https://login.microsoftonline.com/${env.VITE_MICROSOFT_TENANT_ID}`,
      redirectUri: "https://litblogs.school.example",
    });
    expect(JSON.stringify({ providers, selectedMsalConfig })).not.toContain(
      env.VITE_MICROSOFT_CLIENT_SECRET,
    );
  });

  it.each(["common", "organizations", "consumers", "not-a-guid"])(
    "disables Microsoft for an untrusted tenant value: %s",
    (tenantId) => {
      expect(typeof oauthConfiguration.buildOAuthProviderConfig).toBe("function");
      if (typeof oauthConfiguration.buildOAuthProviderConfig !== "function") return;

      const providers = oauthConfiguration.buildOAuthProviderConfig({
        VITE_MICROSOFT_CLIENT_ID: "2f1c67a1-91e2-46a3-941f-b88e31763e51",
        VITE_MICROSOFT_TENANT_ID: tenantId,
      });

      expect(providers.microsoft.enabled).toBe(false);
    },
  );

  it("keeps the shipped-style public placeholders disabled", () => {
    const providers = oauthConfiguration.buildOAuthProviderConfig({
      VITE_GOOGLE_CLIENT_ID: "replace-with-google-client-id",
      VITE_MICROSOFT_CLIENT_ID: "replace-with-microsoft-client-id",
      VITE_MICROSOFT_TENANT_ID: "replace-with-microsoft-tenant-id",
    });

    expect(providers.google.enabled).toBe(false);
    expect(providers.microsoft.enabled).toBe(false);
  });
});
