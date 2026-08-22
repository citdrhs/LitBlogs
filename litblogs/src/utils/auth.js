import axios from "axios";
import { requestPrivateDraftMemoryClear } from "./privateDraftMemory.js";

const USER_INFO_KEY = "user_info";
const CLASS_INFO_KEY = "class_info";
const LEGACY_AUTH_KEYS = ["token", USER_INFO_KEY, CLASS_INFO_KEY];
const DRAFT_PREFIXES = ["assignmentDraft:", "postDraft:"];
const UNSAFE_METHODS = new Set(["post", "put", "patch", "delete"]);

const storageKeys = (storage) => Array.from(
  { length: storage.length },
  (_unused, index) => storage.key(index),
).filter(Boolean);

const clearDraftKeys = (storage) => {
  for (const key of storageKeys(storage)) {
    if (DRAFT_PREFIXES.some((prefix) => key.startsWith(prefix))) {
      storage.removeItem(key);
    }
  }
};

const clearStorageKeys = (storage) => {
  for (const key of LEGACY_AUTH_KEYS) {
    storage.removeItem(key);
  }
  clearDraftKeys(storage);
};

export const purgeLegacyPrivateDrafts = () => {
  requestPrivateDraftMemoryClear();
  clearDraftKeys(localStorage);
  clearDraftKeys(sessionStorage);
};

export const clearStoredAuth = () => {
  requestPrivateDraftMemoryClear();
  clearStorageKeys(localStorage);
  clearStorageKeys(sessionStorage);
};

export const purgeLegacyPersistentAuth = () => {
  clearStorageKeys(localStorage);
  clearDraftKeys(sessionStorage);
  sessionStorage.removeItem("token");
};

export const getStoredSessionMetadata = () => {
  const raw = sessionStorage.getItem(USER_INFO_KEY);
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    sessionStorage.removeItem(USER_INFO_KEY);
    return null;
  }
};

export const persistSessionMetadata = (payload = {}) => {
  const metadata = {
    userId: payload.user_id ?? payload.userId ?? payload.id,
    username: payload.username ?? "",
    firstName: payload.first_name ?? payload.firstName ?? "",
    first_name: payload.first_name ?? payload.firstName ?? "",
    lastName: payload.last_name ?? payload.lastName ?? "",
    last_name: payload.last_name ?? payload.lastName ?? "",
    role: payload.role ?? "",
    is_admin: Boolean(payload.is_admin),
  };

  sessionStorage.setItem(USER_INFO_KEY, JSON.stringify(metadata));
  localStorage.removeItem("token");
  localStorage.removeItem(USER_INFO_KEY);
  localStorage.removeItem(CLASS_INFO_KEY);
  sessionStorage.removeItem("token");
  return metadata;
};

export const hasValidStoredSession = () => Boolean(getStoredSessionMetadata());

export const purgeExpiredSession = () => {
  purgeLegacyPersistentAuth();
  return false;
};

const cookieValue = (name) => {
  if (!name || typeof document === "undefined") return null;

  for (const part of document.cookie.split(";")) {
    const [rawName, ...rawValueParts] = part.trim().split("=");
    if (rawName === name) {
      try {
        return decodeURIComponent(rawValueParts.join("="));
      } catch {
        return null;
      }
    }
  }
  return null;
};

const normalizedApiPath = (apiBasePath) => {
  const path = new URL(apiBasePath || "/api", window.location.origin).pathname;
  return path === "/" ? path : path.replace(/\/+$/, "");
};

const resolvedRequestUrl = (config, apiBasePath) => {
  const rawUrl = String(config.url || "");
  if (/^(?:[a-z][a-z\d+.-]*:)?\/\//i.test(rawUrl)) {
    return new URL(rawUrl, window.location.origin);
  }

  const apiPath = normalizedApiPath(apiBasePath);
  if (rawUrl === apiPath || rawUrl.startsWith(`${apiPath}/`)) {
    return new URL(rawUrl, window.location.origin);
  }

  const baseUrl = config.baseURL || apiBasePath || "/api";
  const normalizedBase = new URL(
    `${String(baseUrl).replace(/\/+$/, "")}/`,
    window.location.origin,
  );
  return new URL(rawUrl.replace(/^\/+/, ""), normalizedBase);
};

const isSameOriginApiRequest = (config, apiBasePath) => {
  const url = resolvedRequestUrl(config, apiBasePath);
  const apiPath = normalizedApiPath(apiBasePath);
  return (
    url.origin === window.location.origin &&
    (url.pathname === apiPath || url.pathname.startsWith(`${apiPath}/`))
  );
};

const isUnsafeSameOriginApiRequest = (config, apiBasePath) => {
  const method = String(config.method || "get").toLowerCase();
  return UNSAFE_METHODS.has(method) && isSameOriginApiRequest(config, apiBasePath);
};

const deleteHeader = (headers, name) => {
  if (typeof headers?.delete === "function") {
    headers.delete(name);
    return;
  }
  if (headers) {
    delete headers[name];
    delete headers[name.toLowerCase()];
  }
};

export const configureAuthHttpClient = (
  httpClient = axios,
  {
    apiBasePath = "/api",
    csrfCookieName,
  } = {},
) => {
  if (!csrfCookieName) {
    throw new Error("Browser configuration is unavailable");
  }
  httpClient.defaults.baseURL = httpClient.defaults.baseURL || apiBasePath;
  httpClient.defaults.withCredentials = false;
  httpClient.interceptors.request.use((config) => {
    config.withCredentials = isSameOriginApiRequest(config, apiBasePath);
    deleteHeader(config.headers, "Authorization");

    if (isUnsafeSameOriginApiRequest(config, apiBasePath)) {
      const csrfToken = cookieValue(csrfCookieName);
      if (csrfToken && typeof config.headers?.set === "function") {
        config.headers.set("X-CSRF-Token", csrfToken);
      } else if (csrfToken) {
        config.headers = { ...config.headers, "X-CSRF-Token": csrfToken };
      }
    }
    return config;
  });
  httpClient.interceptors.response.use(
    (response) => response,
    (error) => {
      deleteHeader(error?.config?.headers, "X-CSRF-Token");
      deleteHeader(error?.config?.headers, "Authorization");
      if (error?.config) {
        delete error.config.auth;
        delete error.config.data;
        delete error.config.params;
      }
      return Promise.reject(error);
    },
  );
  return httpClient;
};

export const fetchBrowserSession = async (httpClient = axios) => {
  const response = await httpClient.get("/auth/session");
  return persistSessionMetadata(response.data);
};

export const logoutBrowserSession = async (httpClient = axios) => {
  purgeLegacyPrivateDrafts();
  const response = await httpClient.post("/auth/logout");
  if (response.status !== 204) {
    throw new Error("Logout was not confirmed by the server");
  }
  clearStoredAuth();
  return response;
};
