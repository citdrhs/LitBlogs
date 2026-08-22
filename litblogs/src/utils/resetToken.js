const RESET_TOKEN_MAX_LENGTH = 128;
let bootstrappedPasswordResetToken = null;

export const consumePasswordResetToken = (browserWindow = window) => {
  const fragment = browserWindow.location.hash.startsWith("#")
    ? browserWindow.location.hash.slice(1)
    : browserWindow.location.hash;
  const fragmentParams = new URLSearchParams(fragment);
  const candidate = fragmentParams.get("token");

  // Never accept a query-string token. Remove any legacy token and the fragment
  // before React stores the secret in component state.
  const safeQuery = new URLSearchParams(browserWindow.location.search);
  safeQuery.delete("token");
  const query = safeQuery.toString();
  const safeUrl = `${browserWindow.location.pathname}${query ? `?${query}` : ""}`;
  browserWindow.history.replaceState(browserWindow.history.state, "", safeUrl);

  if (!candidate || candidate.length > RESET_TOKEN_MAX_LENGTH) {
    return null;
  }
  return candidate;
};

export const capturePasswordResetTokenAtBootstrap = (browserWindow = window) => {
  if (!browserWindow.location.pathname.endsWith("/reset-password")) {
    return null;
  }
  bootstrappedPasswordResetToken = consumePasswordResetToken(browserWindow);
  return bootstrappedPasswordResetToken;
};

export const getBootstrappedPasswordResetToken = () => bootstrappedPasswordResetToken;

export const clearBootstrappedPasswordResetToken = () => {
  bootstrappedPasswordResetToken = null;
};
