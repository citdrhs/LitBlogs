const ABSOLUTE_URL_PATTERN = /^(https?:)?\/\//i;

const normalizeBasePath = (value = "/") => {
  if (!value || value === "/") {
    return "";
  }

  const withoutTrailingSlash = value.endsWith("/")
    ? value.slice(0, -1)
    : value;

  return withoutTrailingSlash.startsWith("/")
    ? withoutTrailingSlash
    : `/${withoutTrailingSlash}`;
};

export const APP_BASE_PATH = normalizeBasePath(import.meta.env.BASE_URL || "/");
export const ROUTER_BASENAME = APP_BASE_PATH || undefined;
export const FRONTEND_URL = typeof window === "undefined"
  ? (APP_BASE_PATH || "/")
  : `${window.location.origin}${APP_BASE_PATH}`;

export const API_BASE_PATH = `${APP_BASE_PATH}/api`;

export const apiPath = (path = "") => {
  if (!path) {
    return API_BASE_PATH;
  }

  if (ABSOLUTE_URL_PATTERN.test(path)) {
    return path;
  }

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
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
  if (!path || ABSOLUTE_URL_PATTERN.test(path)) {
    return path;
  }

  const inferLegacyUploadPath = (value) => {
    const normalizedValue = (value || "").trim();
    if (!normalizedValue || normalizedValue.includes("/")) {
      return "";
    }

    const hasFileExtension = /\.[a-z0-9]{2,6}$/i.test(normalizedValue);
    if (!hasFileExtension) {
      return "";
    }

    const extension = normalizedValue.split(".").pop()?.toLowerCase() || "";
    const videoExtensions = new Set(["mp4", "webm", "ogg", "mov", "m4v", "avi", "mkv"]);
    const imageExtensions = new Set(["jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "heic"]);

    if (normalizedValue.startsWith("profile_") || normalizedValue.startsWith("cover_")) {
      return `/uploads/profile_images/${normalizedValue}`;
    }

    if (videoExtensions.has(extension)) {
      return `/uploads/videos/${normalizedValue}`;
    }

    if (imageExtensions.has(extension)) {
      return `/uploads/images/${normalizedValue}`;
    }

    return `/uploads/files/${normalizedValue}`;
  };

  const inferredLegacyUploadPath = inferLegacyUploadPath(path);
  const normalizedInputPath = inferredLegacyUploadPath || path;

  const normalizedPath = normalizedInputPath.startsWith("/") ? normalizedInputPath : `/${normalizedInputPath}`;

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
