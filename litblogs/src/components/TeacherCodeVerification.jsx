import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";

import { clearPendingVerification, getPendingVerification } from "../utils/pendingVerification";

const TeacherCodeVerification = ({ onVerified }) => {
  const [open, setOpen] = useState(false);
  const [pending] = useState(() => getPendingVerification());
  const [expired, setExpired] = useState(!pending?.challenge);
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef(null);
  const errorRef = useRef(null);
  const signInRef = useRef(null);
  const requestRef = useRef(false);
  const controllerRef = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    controllerRef.current = controller;
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!pending?.expiresAt) return undefined;
    const expire = () => {
      setExpired(true);
      setCode("");
      clearPendingVerification();
    };
    const timer = window.setTimeout(expire, Math.max(0, pending.expiresAt - Date.now()));
    return () => window.clearTimeout(timer);
  }, [pending]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  useEffect(() => {
    if (open && expired) signInRef.current?.focus();
  }, [open, expired]);

  const submit = async (event) => {
    event.preventDefault();
    if (requestRef.current || expired || !pending?.challenge) return;
    if (!/^[0-9]{6}$/.test(code)) {
      setError("Enter the six-digit code your teacher gave you.");
      return;
    }
    const { signal } = controllerRef.current;
    requestRef.current = true;
    setSubmitting(true);
    setError("");
    try {
      const response = await axios.post("/auth/verify-student-code", {
        verification_challenge: pending.challenge,
        code,
      }, { signal });
      if (response?.status !== 200) throw new Error("Unexpected verification response");
      if (!signal.aborted) {
        clearPendingVerification();
        setCode("");
        onVerified();
      }
    } catch {
      if (!signal.aborted) {
        setCode("");
        setError("That code is incorrect or has expired. Check with your teacher, or sign in again and try a new code.");
      }
    } finally {
      requestRef.current = false;
      if (!signal.aborted) setSubmitting(false);
    }
  };

  return (
    <section className="mt-7 border-t border-slate-200 pt-6 dark:border-slate-700" aria-labelledby="teacher-code-heading">
      <h2 id="teacher-code-heading" className="text-lg font-semibold text-slate-900 dark:text-white">
        Still waiting for your email?
      </h2>
      <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
        Your teacher can tell you a code in class. This option verifies your account without another email.
      </p>
      <button
        type="button"
        aria-expanded={open}
        aria-controls="teacher-code-panel"
        onClick={() => setOpen(!open)}
        className="mt-4 inline-flex min-h-11 w-full items-center justify-center rounded-xl border border-blue-700 px-4 py-2.5 font-semibold text-blue-700 hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 dark:border-cyan-400 dark:text-cyan-300 dark:hover:bg-slate-800 dark:focus:ring-offset-slate-900"
      >
        {open ? "Close teacher code" : "Enter a teacher code"}
      </button>
      {open && (
        <div id="teacher-code-panel" className="mt-5 rounded-xl bg-slate-50 p-4 dark:bg-slate-800">
          {pending?.teacherCodeAllowed === false ? (
            <p className="text-sm leading-6 text-slate-700 dark:text-slate-200">
              Teacher codes are for student accounts. Ask an administrator for help with your account.
            </p>
          ) : expired ? (
            <>
              <p role="status" className="text-sm leading-6 text-slate-700 dark:text-slate-200">
                {pending?.challenge ? "Your verification session has expired. " : ""}
                Sign in with your email and password first. Then return here to enter your teacher’s code.
                For your privacy, refreshing this page also requires you to sign in again.
              </p>
              <Link ref={signInRef} to="/sign-in" className="mt-3 inline-block font-semibold text-blue-700 underline underline-offset-4 dark:text-cyan-300">
                Sign in to enter a code
              </Link>
            </>
          ) : (
            <form onSubmit={submit} aria-busy={submitting}>
              <p className="mb-4 break-words text-sm text-slate-700 dark:text-slate-200">
                Verifying <strong>{pending.email}</strong>
              </p>
              <label htmlFor="teacher-verification-code" className="mb-2 block text-sm font-semibold text-slate-800 dark:text-slate-100">
                Six-digit teacher code
              </label>
              <input
                ref={inputRef}
                id="teacher-verification-code"
                name="code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                required
                value={code}
                onChange={(event) => setCode(event.target.value.replace(/[^0-9]/g, "").slice(0, 6))}
                disabled={submitting}
                aria-describedby="teacher-code-help"
                className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-center font-mono text-2xl tracking-[0.3em] text-slate-950 outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-200 disabled:opacity-60 dark:border-slate-600 dark:bg-slate-900 dark:text-white"
              />
              <p id="teacher-code-help" className="mt-3 text-xs leading-5 text-slate-600 dark:text-slate-300">
                Each code works once and expires after 15 minutes. After five incorrect attempts, ask your teacher for a new code.
              </p>
              <button type="submit" disabled={submitting || code.length !== 6} className="mt-4 min-h-12 w-full rounded-xl bg-blue-700 px-4 py-3 font-semibold text-white hover:bg-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-cyan-600 dark:hover:bg-cyan-500 dark:focus:ring-offset-slate-900">
                {submitting ? "Verifying…" : "Verify my account"}
              </button>
              {error && <p ref={errorRef} tabIndex="-1" role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900 outline-none dark:border-red-800 dark:bg-red-950 dark:text-red-100">{error}</p>}
            </form>
          )}
        </div>
      )}
    </section>
  );
};

export default TeacherCodeVerification;
