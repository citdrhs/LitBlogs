const APP_BASE_PATH = import.meta.env.BASE_URL || "/";
const NORMALIZED_APP_BASE_PATH =
  APP_BASE_PATH === "/"
    ? ""
    : APP_BASE_PATH.endsWith("/")
      ? APP_BASE_PATH.slice(0, -1)
      : APP_BASE_PATH;

export const API_BASE_PATH = `${NORMALIZED_APP_BASE_PATH}/api`;

export const apiPath = (path = "") => {
  if (!path) {
    return API_BASE_PATH;
  }

  if (/^(https?:)?\/\//i.test(path)) {
    return path;
  }

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE_PATH}${normalizedPath}`;
};

export const mediaPath = (path = "") => {
  if (!path || /^(https?:)?\/\//i.test(path)) {
    return path;
  }

  return path.startsWith("/") ? path : `/${path}`;
};
