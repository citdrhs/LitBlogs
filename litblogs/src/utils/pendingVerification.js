// A pending verification challenge proves a password check, not a signed-in session.
// Keep it in memory only; refresh requires the student to sign in again.
let pendingVerification = null;

export const clearPendingVerification = () => {
  pendingVerification = null;
};

export const rememberPendingVerification = (detail, now = Date.now()) => {
  clearPendingVerification();
  if (detail?.code !== "email_verification_required") return false;
  const email = typeof detail.email === "string" ? detail.email.trim() : "";
  if (!email || email.length > 100) return false;
  const expiresAt = Date.parse(detail.expires_at);
  const challenge = typeof detail.verification_challenge === "string"
    && detail.verification_challenge.length <= 4096
    && detail.verification_challenge.length > 0
    && Number.isFinite(expiresAt) && expiresAt > now
    ? detail.verification_challenge
    : null;
  pendingVerification = {
    email,
    teacherCodeAllowed: detail.teacher_code_allowed === true,
    challenge,
    expiresAt: challenge ? expiresAt : null,
  };
  return true;
};

export const getPendingVerification = (now = Date.now()) => {
  if (!pendingVerification) return null;
  if (pendingVerification.expiresAt !== null && pendingVerification.expiresAt <= now) {
    pendingVerification = { ...pendingVerification, challenge: null, expiresAt: null };
  }
  return { ...pendingVerification };
};
