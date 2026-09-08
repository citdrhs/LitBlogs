import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { loadPublicRuntimeConfig } from "./runtimeConfig.js";

const VALID_PAYLOAD = {
  csrf_cookie_name: "__Host-litblogs-csrf",
  google_oauth_enabled: true,
  google_client_id: "987654321.apps.googleusercontent.com",
  microsoft_oauth_enabled: true,
  microsoft_client_id: "2f1c67a1-91e2-46a3-941f-b88e31763e51",
  microsoft_tenant_id: "871bd3e0-2dc0-4a40-9b07-9d03068c2364",
  local_password_registration_enabled: false,
};

describe("public runtime configuration", () => {
  it("loads same-origin backend-derived browser settings without persistence", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(VALID_PAYLOAD),
    });

    await expect(loadPublicRuntimeConfig(fetchImpl)).resolves.toEqual({
      csrfCookieName: VALID_PAYLOAD.csrf_cookie_name,
      googleOauthEnabled: true,
      googleClientId: VALID_PAYLOAD.google_client_id,
      microsoftOauthEnabled: true,
      microsoftClientId: VALID_PAYLOAD.microsoft_client_id,
      microsoftTenantId: VALID_PAYLOAD.microsoft_tenant_id,
      localPasswordRegistrationEnabled: false,
    });
    expect(fetchImpl).toHaveBeenCalledWith("/api/runtime-config", {
      cache: "no-store",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it.each([
    [{ ...VALID_PAYLOAD, csrf_cookie_name: "" }],
    [{ ...VALID_PAYLOAD, csrf_cookie_name: "unsafe;cookie" }],
    [{ ...VALID_PAYLOAD, google_oauth_enabled: "true" }],
    [{ ...VALID_PAYLOAD, google_client_id: null }],
    [{ ...VALID_PAYLOAD, microsoft_oauth_enabled: 1 }],
    [{ ...VALID_PAYLOAD, local_password_registration_enabled: "false" }],
    [{ ...VALID_PAYLOAD, unexpected_secret: "must-not-be-accepted" }],
  ])("fails closed for an invalid backend payload", async (payload) => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(payload),
    });

    await expect(loadPublicRuntimeConfig(fetchImpl)).rejects.toThrow(
      "Browser configuration is unavailable",
    );
  });

  it("fails closed without reflecting backend or network details", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(
      new Error("https://private.example/?token=must-not-leak"),
    );

    await expect(loadPublicRuntimeConfig(fetchImpl)).rejects.toThrow(
      "Browser configuration is unavailable",
    );
  });

  it("keeps the accepted canonical payload aligned with the backend response model", async () => {
    const backendSource = readFileSync(resolve("main.py"), "utf8");
    const responseModel = backendSource.match(
      /class PublicRuntimeConfigResponse\(BaseModel\):\r?\n([\s\S]*?)\r?\n\r?\nclass /,
    )?.[1];
    const backendFields = Array.from(
      responseModel?.matchAll(/^\s{4}([a-z_]+):\s+(?:str|bool)$/gm) || [],
      (match) => match[1],
    );
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(VALID_PAYLOAD),
    });

    expect(backendFields.sort()).toEqual(Object.keys(VALID_PAYLOAD).sort());
    await expect(loadPublicRuntimeConfig(fetchImpl)).resolves.toMatchObject({
      googleOauthEnabled: true,
      microsoftOauthEnabled: true,
    });
  });

  it("wires the runtime cookie and provider settings into startup", () => {
    const mainSource = readFileSync(resolve("src/main.jsx"), "utf8");
    const authSource = readFileSync(resolve("src/utils/auth.js"), "utf8");

    expect(mainSource).toContain("await loadPublicRuntimeConfig()");
    expect(mainSource).toContain("applyPublicOAuthConfig(runtimeConfig)");
    expect(mainSource).toContain("applyPublicRegistrationConfig(runtimeConfig)");
    expect(mainSource).toContain("csrfCookieName: runtimeConfig.csrfCookieName");
    expect(authSource).not.toContain("VITE_CSRF_COOKIE_NAME");
  });
});
