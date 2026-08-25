import { LogLevel } from "@azure/msal-browser";
import { FRONTEND_URL } from "../utils/urlUtils";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const GOOGLE_CLIENT_ID_PATTERN =
  /^[A-Za-z0-9][A-Za-z0-9._-]*\.apps\.googleusercontent\.com$/;

const normalized = (value) => (typeof value === "string" ? value.trim() : "");

export const buildOAuthProviderConfig = (env = {}) => {
  const googleClientId = normalized(env.VITE_GOOGLE_CLIENT_ID);
  const microsoftClientId = normalized(env.VITE_MICROSOFT_CLIENT_ID);
  const microsoftTenantId = normalized(env.VITE_MICROSOFT_TENANT_ID);
  const googleEnabled = GOOGLE_CLIENT_ID_PATTERN.test(googleClientId);
  const microsoftEnabled =
    UUID_PATTERN.test(microsoftClientId) && UUID_PATTERN.test(microsoftTenantId);

  return {
    google: {
      clientId: googleEnabled ? googleClientId : "",
      enabled: googleEnabled,
    },
    microsoft: {
      clientId: microsoftEnabled ? microsoftClientId : "",
      tenantId: microsoftEnabled ? microsoftTenantId.toLowerCase() : "",
      enabled: microsoftEnabled,
    },
  };
};

export const buildMsalConfig = (microsoft, redirectUri = FRONTEND_URL) => ({
  auth: {
    clientId: microsoft?.clientId || "",
    authority: microsoft?.tenantId
      ? `https://login.microsoftonline.com/${microsoft.tenantId}`
      : "",
    redirectUri,
    postLogoutRedirectUri: redirectUri,
    navigateToLoginRequestUrl: true,
  },
  cache: {
    cacheLocation: "memoryStorage",
    storeAuthStateInCookie: false,
  },
  system: {
    loggerOptions: {
      loggerCallback: () => {},
      logLevel: LogLevel.Error,
    },
  },
});

export const oauthProviderConfig = buildOAuthProviderConfig(import.meta.env);
export const msalConfig = buildMsalConfig(oauthProviderConfig.microsoft);

export const loginRequest = {
  scopes: ["openid", "profile", "email"],
  prompt: "select_account",
};
