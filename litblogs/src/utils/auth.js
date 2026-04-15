export const clearStoredAuth = () => {
  localStorage.removeItem("token");
  localStorage.removeItem("user_info");
  localStorage.removeItem("class_info");
};

const decodeJwtPayload = (token) => {
  if (!token || typeof token !== "string") {
    return null;
  }

  const parts = token.split(".");
  if (parts.length !== 3) {
    return null;
  }

  try {
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
    const json = atob(padded);
    return JSON.parse(json);
  } catch {
    return null;
  }
};

export const isTokenExpired = (token, bufferSeconds = 30) => {
  const payload = decodeJwtPayload(token);
  const exp = Number(payload?.exp);

  if (!exp) {
    return true;
  }

  const nowInSeconds = Math.floor(Date.now() / 1000);
  return exp <= nowInSeconds + bufferSeconds;
};

export const hasValidStoredSession = () => {
  const token = localStorage.getItem("token");
  return Boolean(token) && !isTokenExpired(token);
};

export const purgeExpiredSession = () => {
  const token = localStorage.getItem("token");
  if (!token) {
    return false;
  }

  if (!isTokenExpired(token)) {
    return false;
  }

  clearStoredAuth();
  return true;
};
