import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Link, useSearchParams } from "react-router-dom";
import axios from "axios";

import Footer from "./components/Footer";
import { resolveAppAsset } from "./utils/urlUtils";
import { getLocalUserSettings } from "./utils/userSettings";
import {
  hasBootstrappedEmailVerificationToken,
  submitBootstrappedEmailVerification,
} from "./utils/verificationToken";

const GENERIC_INVALID_MESSAGE = "Invalid or expired verification link";
const GENERIC_RESEND_MESSAGE =
  "If the account can be verified, verification instructions will be sent.";
const RESEND_ERROR_MESSAGE = "We couldn't submit that request. Please try again.";

const StatusIcon = ({ status }) => {
  if (status === "verifying") {
    return (
      <svg
        aria-hidden="true"
        className="h-12 w-12 animate-spin text-blue-600 dark:text-cyan-300"
        viewBox="0 0 24 24"
        fill="none"
      >
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" opacity="0.22" />
        <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
    );
  }

  if (status === "success") {
    return (
      <svg
        aria-hidden="true"
        className="h-12 w-12 text-emerald-600 dark:text-emerald-300"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
      >
        <circle cx="12" cy="12" r="9" />
        <path d="m8 12.25 2.45 2.45L16.5 8.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }

  if (status === "resend") {
    return (
      <svg
        aria-hidden="true"
        className="h-12 w-12 text-blue-700 dark:text-cyan-300"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
      >
        <rect x="3" y="5" width="18" height="14" rx="2" />
        <path d="m4.5 7 7.5 5.5L19.5 7" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }

  return (
    <svg
      aria-hidden="true"
      className="h-12 w-12 text-amber-600 dark:text-amber-300"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
    >
      <path d="M12 3.25 21 19H3L12 3.25Z" strokeLinejoin="round" />
      <path d="M12 8.25v5.25M12 16.75h.01" strokeLinecap="round" />
    </svg>
  );
};

const VerifyEmail = () => {
  const [searchParams] = useSearchParams();
  const resendOnly = (
    searchParams.get("resend") === "1"
    && !hasBootstrappedEmailVerificationToken()
  );
  const [status, setStatus] = useState(resendOnly ? "resend" : "verifying");
  const [email, setEmail] = useState("");
  const [isResending, setIsResending] = useState(false);
  const [resendResult, setResendResult] = useState(null);
  const headingRef = useRef(null);
  const resendResultRef = useRef(null);
  const [darkMode] = useState(() => getLocalUserSettings().darkMode);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", darkMode);
  }, [darkMode]);

  useEffect(() => {
    if (resendOnly) return undefined;

    let active = true;
    submitBootstrappedEmailVerification((token) => (
      axios.post("/auth/verify-email", { token })
    )).then(
      () => {
        if (active) setStatus("success");
      },
      () => {
        if (active) setStatus("error");
      },
    );

    return () => {
      active = false;
    };
  }, [resendOnly]);

  useEffect(() => {
    if (status !== "verifying") {
      headingRef.current?.focus();
    }
  }, [status]);

  useEffect(() => {
    if (resendResult) {
      resendResultRef.current?.focus();
    }
  }, [resendResult]);

  const handleResend = async (event) => {
    event.preventDefault();
    setIsResending(true);
    setResendResult(null);

    try {
      const response = await axios.post("/auth/resend-verification", {
        email: email.trim(),
      });
      if (response?.status !== 202) {
        throw new Error("Unexpected verification response");
      }
      setEmail("");
      setResendResult({ type: "success", message: GENERIC_RESEND_MESSAGE });
    } catch {
      setResendResult({ type: "error", message: RESEND_ERROR_MESSAGE });
    } finally {
      setIsResending(false);
    }
  };

  const stateCopy = {
    verifying: {
      title: "Verifying your school email",
      description: "Please keep this page open for a moment.",
    },
    success: {
      title: "Email verified",
      description: "Your school email is confirmed. You can now sign in to LitBlogs.",
    },
    error: {
      title: "We couldn't verify this link",
      description: GENERIC_INVALID_MESSAGE,
    },
    resend: {
      title: "Request another verification email",
      description: "Enter your school email. For privacy, the response is the same for every address.",
    },
  }[status];

  const showResend = status === "error" || status === "resend";
  const resendAccepted = resendResult?.type === "success";

  return (
    <div className={`min-h-screen flex flex-col transition-colors duration-300 ${
      darkMode
        ? "bg-slate-950 text-slate-100"
        : "bg-gradient-to-br from-sky-50 via-white to-blue-100 text-slate-900"
    }`}>
      <nav className="mx-auto mt-3 flex w-fit items-center gap-6 rounded-xl border border-slate-200/70 bg-white/85 px-6 py-2 shadow-sm backdrop-blur dark:border-slate-700 dark:bg-slate-900/85">
        <Link to="/" aria-label="LitBlogs home">
          <img src={resolveAppAsset("logo.png")} alt="" className="h-8 w-auto" />
        </Link>
        <Link className="text-sm font-medium text-slate-700 hover:text-blue-700 dark:text-slate-200 dark:hover:text-cyan-300" to="/">
          Home
        </Link>
        <Link className="text-sm font-medium text-slate-700 hover:text-blue-700 dark:text-slate-200 dark:hover:text-cyan-300" to="/sign-in">
          Sign In
        </Link>
      </nav>

      <main className="flex flex-1 items-center justify-center px-4 py-12 sm:px-6">
        <motion.section
          aria-labelledby="verification-title"
          aria-busy={status === "verifying"}
          className="w-full max-w-xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_24px_70px_-36px_rgba(15,23,42,0.45)] dark:border-slate-700 dark:bg-slate-900"
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: "easeOut" }}
        >
          <div className="h-1.5 bg-gradient-to-r from-blue-700 via-cyan-500 to-sky-300" aria-hidden="true" />
          <div className="p-7 sm:p-10">
            <p className="mb-5 text-xs font-bold uppercase tracking-[0.2em] text-blue-700 dark:text-cyan-300">
              LitBlogs account
            </p>
            <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-blue-50 dark:bg-slate-800">
              <StatusIcon status={status} />
            </div>
            <h1
              id="verification-title"
              ref={headingRef}
              tabIndex="-1"
              className="text-3xl font-semibold tracking-tight text-slate-950 outline-none dark:text-white sm:text-4xl"
            >
              {stateCopy.title}
            </h1>
            <p
              className={`mt-4 leading-7 ${
                status === "error"
                  ? "text-amber-800 dark:text-amber-200"
                  : "text-slate-600 dark:text-slate-300"
              }`}
              role={status === "error" ? "alert" : "status"}
              aria-live={status === "verifying" ? "polite" : undefined}
            >
              {stateCopy.description}
            </p>

            {status === "success" && (
              <Link
                to="/sign-in"
                className="mt-8 inline-flex min-h-12 w-full items-center justify-center rounded-xl bg-blue-700 px-5 py-3 font-semibold text-white shadow-sm transition-colors hover:bg-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 dark:bg-cyan-600 dark:hover:bg-cyan-500 dark:focus:ring-offset-slate-900"
              >
                Sign In
              </Link>
            )}

            {showResend && (
              <form
                className="mt-8 border-t border-slate-200 pt-7 dark:border-slate-700"
                onSubmit={handleResend}
                aria-busy={isResending}
              >
                {status === "error" && (
                  <h2 className="mb-2 text-lg font-semibold text-slate-900 dark:text-white">
                    Request a new link
                  </h2>
                )}
                <p className="mb-5 text-sm leading-6 text-slate-600 dark:text-slate-300">
                  We use the same confirmation message whether or not the address can receive a link.
                  Delivery may take a few minutes. Check your spam folder, and wait at least five
                  minutes before requesting another email.
                </p>
                <label htmlFor="verification-email" className="mb-2 block text-sm font-semibold text-slate-800 dark:text-slate-100">
                  School email address
                </label>
                <input
                  id="verification-email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  spellCheck="false"
                  maxLength="100"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  disabled={isResending || resendAccepted}
                  className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-slate-950 shadow-sm outline-none transition focus:border-blue-600 focus:ring-2 focus:ring-blue-200 disabled:cursor-wait disabled:opacity-70 dark:border-slate-600 dark:bg-slate-800 dark:text-white dark:focus:border-cyan-400 dark:focus:ring-cyan-900"
                />
                <button
                  type="submit"
                  disabled={isResending || resendAccepted}
                  className="mt-4 inline-flex min-h-12 w-full items-center justify-center rounded-xl bg-blue-700 px-5 py-3 font-semibold text-white shadow-sm transition-colors hover:bg-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-wait disabled:opacity-70 dark:bg-cyan-600 dark:hover:bg-cyan-500 dark:focus:ring-offset-slate-900"
                >
                  {isResending
                    ? "Sending…"
                    : resendAccepted
                      ? "Request received"
                      : "Send verification email"}
                </button>
                {resendResult && (
                  <p
                    ref={resendResultRef}
                    tabIndex="-1"
                    role={resendResult.type === "success" ? "status" : "alert"}
                    className={`mt-4 rounded-lg border px-4 py-3 text-sm outline-none ${
                      resendResult.type === "success"
                        ? "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-100"
                        : "border-red-200 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100"
                    }`}
                  >
                    {resendResult.message}
                  </p>
                )}
              </form>
            )}
          </div>
        </motion.section>
      </main>

      <Footer darkMode={darkMode} />
    </div>
  );
};

export default VerifyEmail;
