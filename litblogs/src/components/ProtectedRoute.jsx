import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { clearStoredAuth, fetchBrowserSession } from "../utils/auth";

const ProtectedRoute = ({ allowedRoles = [], children }) => {
  const location = useLocation();
  const [retryAttempt, setRetryAttempt] = useState(0);
  const [sessionState, setSessionState] = useState({
    locationKey: null,
    metadata: null,
    status: "loading",
  });

  useEffect(() => {
    let active = true;
    const locationKey = location.key;
    fetchBrowserSession()
      .then((metadata) => {
        if (active) {
          setSessionState({
            locationKey,
            metadata,
            status: "authenticated",
          });
        }
      })
      .catch((error) => {
        if (active) {
          const unauthenticated = error?.response?.status === 401;
          if (unauthenticated) clearStoredAuth();
          setSessionState({
            locationKey,
            metadata: null,
            status: unauthenticated ? "unauthenticated" : "unavailable",
          });
        }
      });
    return () => {
      active = false;
    };
  }, [location.key, retryAttempt]);

  const sessionStatus = sessionState.locationKey === location.key
    ? sessionState.status
    : "loading";

  if (sessionStatus === "loading") {
    return null;
  }

  if (sessionStatus === "unauthenticated") {
    return <Navigate to="/sign-in" replace state={{ from: location }} />;
  }

  if (sessionStatus === "unavailable") {
    return (
      <main className="flex min-h-screen items-center justify-center px-4">
        <div className="max-w-md rounded-lg border border-amber-300 bg-amber-50 p-6 text-amber-900">
          <p role="alert">We couldn't check your sign-in. Check your connection and try again. Your work in this tab has not been discarded.</p>
          <button
            type="button"
            className="mt-4 rounded-lg bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800"
            onClick={() => {
              setSessionState({ locationKey: location.key, metadata: null, status: "loading" });
              setRetryAttempt((attempt) => attempt + 1);
            }}
          >
            Try again
          </button>
        </div>
      </main>
    );
  }

  const normalizedRole = String(sessionState.metadata?.role || "").toUpperCase();
  const normalizedAllowedRoles = allowedRoles.map((role) => String(role).toUpperCase());
  if (normalizedAllowedRoles.length > 0 && !normalizedAllowedRoles.includes(normalizedRole)) {
    return (
      <main className="flex min-h-screen items-center justify-center px-4">
        <p role="alert" className="rounded-lg border border-amber-300 bg-amber-50 p-6 text-amber-900">
          You do not have access to this page.
        </p>
      </main>
    );
  }

  return children;
};

export default ProtectedRoute;
