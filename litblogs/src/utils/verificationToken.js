const VERIFICATION_TOKEN_MAX_LENGTH = 128;
const VERIFICATION_UNAVAILABLE_MESSAGE = "Email verification is unavailable";
const VERIFY_EMAIL_PATH_PATTERN = /(?:^|\/)verify-email\/?$/;

let bootstrappedVerificationToken = null;
let verificationCaptureAttempted = false;
let verificationConsumed = false;
let inFlightVerification = null;

const unavailable = () => Promise.reject(new Error(VERIFICATION_UNAVAILABLE_MESSAGE));

export const captureEmailVerificationTokenAtBootstrap = (browserWindow = window) => {
  if (!VERIFY_EMAIL_PATH_PATTERN.test(browserWindow.location.pathname)) {
    return false;
  }

  const fragment = browserWindow.location.hash.startsWith("#")
    ? browserWindow.location.hash.slice(1)
    : browserWindow.location.hash;
  const fragmentParams = new URLSearchParams(fragment);
  const candidates = fragmentParams.getAll("token");
  const candidate = candidates.length === 1 ? candidates[0] : "";

  const safeQuery = new URLSearchParams(browserWindow.location.search);
  safeQuery.delete("token");
  const query = safeQuery.toString();
  const safeUrl = `${browserWindow.location.pathname}${query ? `?${query}` : ""}`;
  browserWindow.history.replaceState(browserWindow.history.state, "", safeUrl);

  if (verificationCaptureAttempted) {
    return Boolean(bootstrappedVerificationToken || inFlightVerification);
  }

  verificationCaptureAttempted = true;
  bootstrappedVerificationToken = (
    candidate && candidate.length <= VERIFICATION_TOKEN_MAX_LENGTH
      ? candidate
      : null
  );
  verificationConsumed = false;
  return bootstrappedVerificationToken !== null;
};

export const hasBootstrappedEmailVerificationToken = () => (
  Boolean(inFlightVerification)
  || (Boolean(bootstrappedVerificationToken) && !verificationConsumed)
);

export const clearBootstrappedEmailVerificationToken = () => {
  bootstrappedVerificationToken = null;
  verificationConsumed = true;
};

export const submitBootstrappedEmailVerification = (submit) => {
  if (inFlightVerification) {
    return inFlightVerification;
  }
  if (
    verificationConsumed
    || !bootstrappedVerificationToken
    || typeof submit !== "function"
  ) {
    return unavailable();
  }

  const token = bootstrappedVerificationToken;
  verificationConsumed = true;

  let resolveShared;
  let rejectShared;
  const sharedRequest = new Promise((resolve, reject) => {
    resolveShared = resolve;
    rejectShared = reject;
  });
  inFlightVerification = sharedRequest;

  const clearTerminalReferences = () => {
    bootstrappedVerificationToken = null;
    if (inFlightVerification === sharedRequest) {
      inFlightVerification = null;
    }
  };

  try {
    Promise.resolve(submit(token)).then(
      (value) => {
        clearTerminalReferences();
        resolveShared(value);
      },
      (error) => {
        clearTerminalReferences();
        rejectShared(error);
      },
    );
  } catch (error) {
    clearTerminalReferences();
    rejectShared(error);
  }

  return sharedRequest;
};
