export const DRAFT_SESSION_EXPIRED_EVENT = "litblogs:draft-session-expired";

export const handleUnauthorizedResponse = (error, {
  clearAuth,
  redirect,
  signInPath,
  currentPath,
  eventTarget = typeof window === "undefined" ? undefined : window,
}) => {
  if (error?.response?.status !== 401 || error?.config?.draftReauthentication === true) {
    return Promise.reject(error);
  }

  // Use the target browser's Event constructor so injected windows and DOM
  // targets accept it without crossing the Node/jsdom event realm boundary.
  const EventConstructor = eventTarget?.Event
    || eventTarget?.ownerDocument?.defaultView?.Event
    || (typeof window === "undefined" ? Event : window.Event);
  const event = new EventConstructor(DRAFT_SESSION_EXPIRED_EVENT, { cancelable: true });
  const preserveDraftSession = eventTarget?.dispatchEvent(event) === false;

  if (!preserveDraftSession) {
    clearAuth();
    if (currentPath !== signInPath) redirect(signInPath);
  }

  // A protected editor may preserve its draft, but the original request still
  // fails. Reauthentication must never replay a publish or autosave implicitly.
  return Promise.reject(error);
};
