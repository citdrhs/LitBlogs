import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { clearStoredAuth, fetchBrowserSession } from "../utils/auth";

const ProtectedRoute = ({ allowedRoles = [], children }) => {
  const location = useLocation();
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
      .catch(() => {
        if (active) {
          clearStoredAuth();
          setSessionState({
            locationKey,
            metadata: null,
            status: "unauthenticated",
          });
        }
      });
    return () => {
      active = false;
    };
  }, [location.key]);

  const sessionStatus = sessionState.locationKey === location.key
    ? sessionState.status
    : "loading";

  if (sessionStatus === "loading") {
    return null;
  }

  if (sessionStatus === "unauthenticated") {
    return <Navigate to="/sign-in" replace state={{ from: location }} />;
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
