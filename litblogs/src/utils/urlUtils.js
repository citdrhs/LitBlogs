import { normalizeRuntimeBasePath } from "./basePath.js";

const ABSOLUTE_URL_PATTERN = /^(https?:)?\/\//i;
const trimString = (value) => typeof value === "string" ? value.trim() : value;

export const APP_BASE_PATH = normalizeRuntimeBasePath(import.meta.env.BASE_URL || "/");
export const ROUTER_BASENAME = APP_BASE_PATH || undefined;
export const FRONTEND_URL = typeof window === "undefined"
  ? (APP_BASE_PATH || "/")
  : `${window.location.origin}${APP_BASE_PATH}`;

export const API_BASE_PATH = `${APP_BASE_PATH}/api`;

export const apiPath = (path = "") => {
  const normalizedInput = trimString(path);
  if (!normalizedInput) {
    return API_BASE_PATH;
  }

  if (ABSOLUTE_URL_PATTERN.test(normalizedInput)) {
    return normalizedInput;
  }

  const normalizedPath = normalizedInput.startsWith("/") ? normalizedInput : `/${normalizedInput}`;
  return `${API_BASE_PATH}${normalizedPath}`;
};

export const assetPath = (path = "") => {
  if (!path) {
    return APP_BASE_PATH || "/";
  }

  if (ABSOLUTE_URL_PATTERN.test(path)) {
    return path;
  }

  const normalizedPath = path.startsWith("/") ? path.slice(1) : path;
  return APP_BASE_PATH ? `${APP_BASE_PATH}/${normalizedPath}` : `/${normalizedPath}`;
};

export const resolveAppAsset = (path = "") => {
  if (!path || ABSOLUTE_URL_PATTERN.test(path)) {
    return path;
  }

  const normalizedPath = path
    .replace(/^\.?\//, "")
    .replace(/^dren\//, "");

  return assetPath(normalizedPath);
};

export const mediaPath = (path = "") => {
  const normalizedInput = trimString(path);
  if (!normalizedInput || ABSOLUTE_URL_PATTERN.test(normalizedInput)) {
    return normalizedInput;
  }

  const normalizedPath = normalizedInput.startsWith("/") ? normalizedInput : `/${normalizedInput}`;

  // Route uploaded media through the API namespace so it works behind
  // production proxies that only forward /api to the backend.
  if (normalizedPath.startsWith("/uploads/")) {
    const relativePath = normalizedPath.slice("/uploads/".length);
    return `${API_BASE_PATH}/uploads/${relativePath}`;
  }

  if (normalizedPath.startsWith("/api/uploads/")) {
    const relativePath = normalizedPath.slice("/api/uploads/".length);
    return `${API_BASE_PATH}/uploads/${relativePath}`;
  }

  return normalizedPath;
};

const PROFILE_COVER_PRESET = /^\/Classroom[1-4]\.jpeg$/;

export const profileCoverPath = (path = "") => {
  const normalizedInput = trimString(path);
  if (typeof normalizedInput === "string" && PROFILE_COVER_PRESET.test(normalizedInput)) {
    return assetPath(normalizedInput);
  }
  return mediaPath(normalizedInput);
};
