import { apiPath } from "../utils/urlUtils.js";

const CONFIGURATION_ERROR = "Browser configuration is unavailable";
const COOKIE_NAME_PATTERN = /^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,80}$/;
const PUBLIC_STRING_FIELDS = [
  "csrf_cookie_name",
  "google_client_id",
  "microsoft_client_id",
  "microsoft_tenant_id",
];
const PUBLIC_BOOLEAN_FIELDS = ["local_password_registration_enabled"];
const PUBLIC_FIELDS = new Set([...PUBLIC_STRING_FIELDS, ...PUBLIC_BOOLEAN_FIELDS]);

const invalidConfiguration = () => new Error(CONFIGURATION_ERROR);

const parsePublicRuntimeConfig = (payload) => {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw invalidConfiguration();
  }
  const payloadFields = Object.keys(payload);
  if (
    payloadFields.length !== PUBLIC_FIELDS.size
    || payloadFields.some((field) => !PUBLIC_FIELDS.has(field))
  ) {
    throw invalidConfiguration();
  }
  if (PUBLIC_STRING_FIELDS.some((field) => typeof payload[field] !== "string")) {
    throw invalidConfiguration();
  }
  if (PUBLIC_BOOLEAN_FIELDS.some((field) => typeof payload[field] !== "boolean")) {
    throw invalidConfiguration();
  }

  const csrfCookieName = payload.csrf_cookie_name.trim();
  if (!COOKIE_NAME_PATTERN.test(csrfCookieName)) {
    throw invalidConfiguration();
  }

  return Object.freeze({
    csrfCookieName,
    googleClientId: payload.google_client_id.trim(),
    microsoftClientId: payload.microsoft_client_id.trim(),
    microsoftTenantId: payload.microsoft_tenant_id.trim(),
    localPasswordRegistrationEnabled: payload.local_password_registration_enabled,
  });
};

export const loadPublicRuntimeConfig = async (fetchImpl = window.fetch.bind(window)) => {
  try {
    const response = await fetchImpl(apiPath("/runtime-config"), {
      cache: "no-store",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!response?.ok) {
      throw invalidConfiguration();
    }
    return parsePublicRuntimeConfig(await response.json());
  } catch {
    throw invalidConfiguration();
  }
};
