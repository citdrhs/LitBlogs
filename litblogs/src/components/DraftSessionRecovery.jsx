import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { clearStoredAuth, persistSessionMetadata } from "../utils/auth.js";

const failureMessage = (status, checkingSession) => {
  if (status === 401 && !checkingSession) {
    return "Check your school email and password, then try again.";
  }
  if (status === 401 || status === 403) {
    return "We could not restore your session. Contact your teacher or try again.";
  }
  if (status === 429) {
    return "Too many sign-in attempts. Wait a few minutes and try again.";
  }
  return "Sign-in is temporarily unavailable. Keep this tab open and try again.";
};

const sameAccount = (userId, ownerId) => (
  (typeof userId === "number" || typeof userId === "string")
  && /^[1-9]\d*$/.test(String(userId))
  && String(userId) === String(ownerId)
);

const DraftSessionRecovery = ({ ownerId, onRecovered, onDiscardStart, onDiscard }) => {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const emailRef = useRef(null);
  const errorRef = useRef(null);
  const requestRef = useRef(null);
  const pendingRef = useRef(false);
  const discardingRef = useRef(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    emailRef.current?.focus();
    return () => {
      mountedRef.current = false;
      requestRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  const discard = async () => {
    if (discardingRef.current) return;
    discardingRef.current = true;
    requestRef.current?.abort();
    setPassword("");
    setPending(true);
    setError("");
    onDiscardStart?.();
    clearStoredAuth();
    try {
      await axios.post("/auth/logout", {}, {
        draftReauthentication: true, timeout: 10_000,
      });
    } catch {
      // Private memory is already cleared even when the server is unavailable.
    } finally {
      if (mountedRef.current) onDiscard();
    }
  };

  const reauthenticate = async (event) => {
    event.preventDefault();
    if (pendingRef.current || discardingRef.current || !email.trim() || !password) return;
    pendingRef.current = true;
    const controller = new AbortController();
    requestRef.current = controller;
    const config = { draftReauthentication: true, signal: controller.signal };
    const isCurrent = () => mountedRef.current && !controller.signal.aborted
      && requestRef.current === controller && !discardingRef.current;
    setPending(true);
    setError("");
    let checkingSession = false;
    try {
      const request = axios.post("/auth/login", { email: email.trim(), password }, config);
      setPassword("");
      const response = await request;
      if (!isCurrent()) return;
      if (response.status !== 200) throw new Error("Sign-in was not confirmed");
      if (!sameAccount(response.data?.user_id, ownerId)) {
        await discard();
        return;
      }
      checkingSession = true;
      const verified = await axios.get("/auth/session", config);
      if (!isCurrent()) return;
      if (verified.status !== 200) throw new Error("Session was not confirmed");
      if (!sameAccount(verified.data?.user_id, ownerId)) {
        await discard();
        return;
      }
      const metadata = persistSessionMetadata(verified.data);
      onRecovered(metadata);
    } catch (requestError) {
      if (isCurrent()) setError(failureMessage(requestError?.response?.status, checkingSession));
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        pendingRef.current = false;
      }
      if (mountedRef.current) {
        setPassword("");
        if (!discardingRef.current) setPending(false);
      }
    }
  };

  const fieldClass = "mt-2 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 disabled:bg-gray-100";

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12 text-slate-900">
      <section aria-labelledby="draft-recovery-title" className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-lg">
        <h1 id="draft-recovery-title" className="text-2xl font-semibold">Sign in to recover your draft</h1>
        <p className="mt-3 text-sm leading-6 text-slate-600">
          Your session has expired. Your draft is kept only in this tab. Keep this tab open and sign in with the same school account to return to your work.
        </p>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Signing in will not publish your post. You can review it before publishing.
        </p>
        <form onSubmit={reauthenticate} className="mt-6 space-y-4" aria-busy={pending}>
          <label className="block text-sm font-medium">
            School email
            <input ref={emailRef} type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} required disabled={pending} className={fieldClass} />
          </label>
          <label className="block text-sm font-medium">
            Password
            <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required disabled={pending} className={fieldClass} />
          </label>
          {error && <p ref={errorRef} role="alert" tabIndex={-1} className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}
          <button type="submit" disabled={pending} className="w-full rounded-lg bg-blue-700 px-4 py-2.5 font-medium text-white hover:bg-blue-800 disabled:cursor-wait disabled:opacity-60">
            {pending ? "Signing in…" : "Sign in and return to draft"}
          </button>
        </form>
        <button type="button" onClick={discard} disabled={discardingRef.current} className="mt-4 w-full rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60">
          Discard draft and sign out
        </button>
      </section>
    </main>
  );
};

export default DraftSessionRecovery;
